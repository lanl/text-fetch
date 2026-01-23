"""Unified multi-source fetch orchestrator."""

from __future__ import annotations

__all__ = [
    "unified_fetch",
    "deduplicate_by_doi",
]

import logging
from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .query import SearchConfig

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


def unified_fetch(
    config: SearchConfig,
    output_dir: str | Path,
    workspace: Workspace | None = None,
    email: str | None = None,
    api_key: str | None = None,
    grobid_url: str | None = None,
    verbose: bool = False,
    progress_callback: Callable[[str, str, int, int], None] | None = None,
    resume: bool = False,
    update: bool = False,
) -> dict[str, Any]:
    """Fetch articles from multiple sources using unified config.

    Args:
        config: SearchConfig with sources and query parameters.
        output_dir: Base output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        email: NCBI email (required for pmc source).
        api_key: NCBI API key (optional).
        grobid_url: GROBID URL (required for arxiv, chemrxiv).
        verbose: Enable verbose logging.
        progress_callback: Optional callback(source, id, current, total).
        resume: Resume from checkpoints for interrupted fetches.
        update: Only fetch papers since last fetch (requires workspace).

    Returns:
        Statistics dict with per-source stats and deduplication info.
    """
    # When workspace is used, deduplication is automatic via DOI index
    if workspace:
        output_path = workspace.path
    else:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

    sources = config.sources or ["pmc"]  # Default to PMC

    # Overall stats
    stats: dict[str, Any] = {
        "sources": sources,
        "per_source": {},
        "total_fetched": 0,
        "total_valid": 0,
        "total_incomplete": 0,
        "total_errors": 0,
        "duplicates_removed": 0,
        "duplicates_skipped": 0,
        "unique_dois": [],
    }

    # Fetch from each source
    for source in sources:
        # When using workspace, all files go to workspace dirs
        # When not using workspace, create source subdirs
        source_dir = output_path if workspace else (output_path / source)

        try:
            source_stats = _fetch_from_source(
                source=source,
                config=config,
                output_dir=source_dir,
                workspace=workspace,
                email=email,
                api_key=api_key,
                grobid_url=grobid_url,
                verbose=verbose,
                progress_callback=progress_callback,
                resume=resume,
                update=update,
            )
            stats["per_source"][source] = source_stats
            stats["total_fetched"] += source_stats.get("fetched", 0)
            stats["total_valid"] += source_stats.get("valid", 0)
            stats["total_incomplete"] += source_stats.get("incomplete", 0)
            stats["total_errors"] += source_stats.get("errors", 0)
            stats["duplicates_skipped"] += source_stats.get("duplicates_skipped", 0)
        except Exception as e:
            logger.error("Error fetching from %s: %s", source, e)
            stats["per_source"][source] = {"error": str(e)}
            stats["total_errors"] += 1

    # Deduplicate by DOI if requested (only if not using workspace)
    # Workspace handles deduplication via DOI index automatically
    if not workspace and config.deduplicate_by_doi:
        dedup_stats = deduplicate_by_doi(output_path)
        stats["duplicates_removed"] = dedup_stats["removed"]
        stats["unique_dois"] = dedup_stats["unique_dois"]

    # Write unified manifest (only if not using workspace)
    if not workspace:
        _write_unified_manifest(output_path, stats, config)

    return stats


def _fetch_from_source(
    source: str,
    config: SearchConfig,
    output_dir: Path,
    workspace: Workspace | None,
    email: str | None,
    api_key: str | None,
    grobid_url: str | None,
    verbose: bool,
    progress_callback: Callable[[str, str, int, int], None] | None,
    resume: bool = False,
    update: bool = False,
) -> dict[str, Any]:
    """Fetch from a single source."""
    # Get source-specific options
    opts = config.source_options.get(source)
    max_results = (
        opts.max_results if opts and opts.max_results else config.max_results_per_source
    )

    if source == "pmc":
        from .pmc import fetch_pmc

        return fetch_pmc(
            config=config,
            email=email or "",
            api_key=api_key,
            output_dir=output_dir,
            workspace=workspace,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, source),
            resume=resume,
            update=update,
        )

    elif source == "europepmc":
        from .europepmc import fetch_europepmc

        return fetch_europepmc(
            query=config.to_europepmc_query(),
            output_dir=output_dir,
            workspace=workspace,
            max_results=max_results,
            open_access_only=config.open_access_only,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, source),
            resume=resume,
            update=update,
        )

    elif source == "arxiv":
        from .arxiv import fetch_arxiv

        if not grobid_url:
            raise ValueError("GROBID URL required for arXiv")

        return fetch_arxiv(
            config=config,
            output_dir=output_dir,
            workspace=workspace,
            grobid_url=grobid_url,
            max_results=max_results,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, source),
            resume=resume,
            update=update,
        )

    elif source in ("biorxiv", "medrxiv"):
        from .biorxiv import fetch_biorxiv, fetch_medrxiv

        params = config.to_biorxiv_params(source)
        fetch_fn = fetch_biorxiv if source == "biorxiv" else fetch_medrxiv

        return fetch_fn(
            output_dir=output_dir,
            workspace=workspace,
            grobid_url=grobid_url,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, source),
            resume=resume,
            update=update,
            **params,
        )

    elif source == "chemrxiv":
        from .chemrxiv import fetch_chemrxiv

        if not grobid_url:
            raise ValueError("GROBID URL required for ChemRxiv")

        params = config.to_chemrxiv_params()
        return fetch_chemrxiv(
            output_dir=output_dir,
            workspace=workspace,
            grobid_url=grobid_url,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, source),
            resume=resume,
            update=update,
            **params,
        )

    else:
        raise ValueError(f"Unknown source: {source}")


def _wrap_callback(
    callback: Callable[[str, str, int, int], None] | None,
    source: str,
) -> Callable[[str, int, int], None] | None:
    """Wrap progress callback to add source parameter."""
    if callback is None:
        return None

    def wrapped(article_id: str, current: int, total: int) -> None:
        callback(source, article_id, current, total)

    return wrapped


def deduplicate_by_doi(output_dir: Path) -> dict[str, Any]:
    """Remove duplicate articles by DOI across sources.

    Keeps the first occurrence (usually from "better" sources like PMC).

    Args:
        output_dir: Directory with source subdirectories.

    Returns:
        Stats dict with removed count and unique DOIs.
    """
    import json
    from xml.etree import ElementTree as ET

    seen_dois: dict[str, str] = {}  # DOI -> first source/path
    duplicates: list[tuple[str, str]] = []  # (path, duplicate_of)

    # Priority order: native JATS sources first
    source_priority = ["pmc", "europepmc", "biorxiv", "medrxiv", "arxiv", "chemrxiv"]

    for source in source_priority:
        source_dir = output_dir / source
        if not source_dir.exists():
            continue

        for xml_file in source_dir.rglob("*.xml"):
            try:
                tree = ET.parse(xml_file)
                root = tree.getroot()

                # Extract DOI
                doi = None
                for article_id in root.iter("article-id"):
                    if article_id.get("pub-id-type") == "doi":
                        doi = article_id.text
                        break

                if doi:
                    doi = doi.strip().lower()
                    if doi in seen_dois:
                        duplicates.append((str(xml_file), seen_dois[doi]))
                    else:
                        seen_dois[doi] = str(xml_file)

            except ET.ParseError:
                continue

    # Remove duplicates (move to duplicates folder)
    duplicates_dir = output_dir / "_duplicates"
    removed_count = 0

    for dup_path, _original_path in duplicates:
        try:
            dup_file = Path(dup_path)
            duplicates_dir.mkdir(parents=True, exist_ok=True)
            # Prefix with source and subdir to avoid filename collisions
            rel_parts = dup_file.relative_to(output_dir).parts
            source = rel_parts[0] if rel_parts else "unknown"
            subdir = rel_parts[1] if len(rel_parts) > 1 else "unknown"
            dest_name = f"{source}_{subdir}_{dup_file.name}"
            dup_file.rename(duplicates_dir / dest_name)
            removed_count += 1
        except OSError:
            pass

    # Write deduplication log
    if duplicates:
        log_path = output_dir / "duplicates.json"
        log_data = {
            "removed": removed_count,
            "duplicates": [{"removed": dup, "kept": orig} for dup, orig in duplicates],
        }
        log_path.write_text(json.dumps(log_data, indent=2))

    return {
        "removed": removed_count,
        "unique_dois": list(seen_dois.keys()),
    }


def _write_unified_manifest(
    output_dir: Path,
    stats: dict[str, Any],
    config: SearchConfig,
) -> None:
    """Write unified manifest.json."""
    import json
    from datetime import datetime

    manifest = {
        "version": "1.0",
        "created_at": datetime.now(UTC).isoformat(),
        "config": config.to_dict(),
        "statistics": {
            "sources": stats["sources"],
            "total_fetched": stats["total_fetched"],
            "total_valid": stats["total_valid"],
            "total_incomplete": stats["total_incomplete"],
            "total_errors": stats["total_errors"],
            "duplicates_removed": stats["duplicates_removed"],
        },
        "per_source": stats["per_source"],
    }

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))
