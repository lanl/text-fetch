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
    expand_references: bool = False,
    expand_citations: bool = False,
    expansion_depth: int = 1,
    max_expansion: int | None = None,
    dry_run: bool = False,
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
        expand_references: Expand by following references (europepmc only).
        expand_citations: Expand by following citations (europepmc only).
        expansion_depth: Number of expansion hops (default: 1).
        max_expansion: Cap on total expanded papers (None = unlimited).
        dry_run: If True, return expansion preview without fetching.

    Returns:
        Statistics dict with per-source stats and deduplication info.
        If dry_run=True, returns {"dry_run": True, "expansion_result": ...}.
    """
    # When workspace is used, deduplication is automatic via DOI index
    if workspace:
        output_path = workspace.path
    else:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

    sources = config.sources or ["pmc"]  # Default to PMC

    # Check for expansion on non-europepmc sources
    has_expansion = expand_references or expand_citations
    if has_expansion:
        non_epmc = [s for s in sources if s != "europepmc"]
        if non_epmc:
            logger.warning(
                "Citation expansion only supported for europepmc. "
                "Expansion skipped for: %s",
                ", ".join(non_epmc),
            )
        if "europepmc" not in sources:
            logger.warning("No europepmc source - expansion options will be ignored.")

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
        "expansion": None,  # Will be set if expansion is used
    }

    # Handle europepmc expansion (dry-run or full expansion)
    if has_expansion and "europepmc" in sources:
        expansion_result = _handle_europepmc_expansion(
            config=config,
            output_dir=output_path,
            workspace=workspace,
            email=email,
            api_key=api_key,
            expand_references=expand_references,
            expand_citations=expand_citations,
            expansion_depth=expansion_depth,
            max_expansion=max_expansion,
            dry_run=dry_run,
            verbose=verbose,
            progress_callback=progress_callback,
        )

        # In dry-run mode, return early with expansion preview
        if dry_run:
            return {
                "dry_run": True,
                "expansion_result": expansion_result,
                "seed_stats": expansion_result.get("seed_stats", {}),
            }

        # Store expansion stats
        stats["expansion"] = {
            "expand_references": expand_references,
            "expand_citations": expand_citations,
            "expansion_depth": expansion_depth,
            "seeds_fetched": expansion_result.get("seeds_fetched", 0),
            "expanded_fetched": expansion_result.get("expanded_fetched", 0),
            "total_unique": expansion_result.get("total_unique", 0),
        }

        # Add expansion stats to totals
        stats["total_fetched"] += expansion_result.get("expanded_fetched", 0)
        stats["total_valid"] += expansion_result.get("expanded_valid", 0)

        return stats

    # Non-expansion path: fetch from each source normally
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


def _handle_europepmc_expansion(
    config: SearchConfig,
    output_dir: Path,
    workspace: Workspace | None,
    email: str | None,
    api_key: str | None,
    expand_references: bool,
    expand_citations: bool,
    expansion_depth: int,
    max_expansion: int | None,
    dry_run: bool,
    verbose: bool,
    progress_callback: Callable[[str, str, int, int], None] | None,
) -> dict[str, Any]:
    """Handle Europe PMC fetch with citation/reference expansion.

    This implements a two-phase fetch:
    1. Fetch seed papers from the search query
    2. Expand via citations/references to discover related papers

    Args:
        config: Search configuration.
        output_dir: Output directory.
        workspace: Optional workspace.
        email: NCBI email for PMC downloads.
        api_key: NCBI API key.
        expand_references: Expand by following references.
        expand_citations: Expand by following citations.
        expansion_depth: Number of hops.
        max_expansion: Cap on expanded papers.
        dry_run: If True, return preview without fetching.
        verbose: Verbose logging.
        progress_callback: Progress callback.

    Returns:
        Dictionary with expansion statistics.
    """
    from .europepmc import (
        EuropePMCArticle,
        EuropePMCClient,
        expand_papers,
        fetch_europepmc,
    )

    client = EuropePMCClient()
    query = config.to_europepmc_query()

    # Get source-specific max_results
    opts = config.source_options.get("europepmc")
    max_results = (
        opts.max_results if opts and opts.max_results else config.max_results_per_source
    )

    # Phase 1: Search for seed papers (metadata only, don't download yet)
    if verbose:
        logger.info("Searching for seed papers: %s", query)

    # Collect seeds - iter_search handles pagination and total discovery
    # Show progress callback when we have results
    seeds: list[EuropePMCArticle] = []
    for i, article in enumerate(client.iter_search(query, max_results=max_results)):
        seeds.append(article)
        # Update progress every 25 articles (Europe PMC page size)
        if progress_callback and (i % 25 == 0 or i == 0):
            # Estimate expected - use max_results if set, otherwise show growing count
            total_est = max_results if max_results else (i + 1) * 2
            progress_callback("europepmc", f"search:{i}", i + 1, total_est)

    # Filter to papers with PMCIDs (downloadable)
    seeds_with_pmcid = [s for s in seeds if s.pmcid]

    seed_stats = {
        "query": query,
        "articles_found": len(seeds),
        "with_pmcid": len(seeds_with_pmcid),
    }

    if verbose:
        logger.info(
            "Found %d seeds, %d with PMCIDs",
            len(seeds),
            len(seeds_with_pmcid),
        )

    # Phase 2: Expand via citations/references
    if verbose:
        logger.info(
            "Expanding: refs=%s, cites=%s, depth=%d",
            expand_references,
            expand_citations,
            expansion_depth,
        )

    # Wrap progress callback for expansion
    def expansion_progress(stage: str, current: int, total: int) -> None:
        if progress_callback:
            progress_callback("europepmc", f"expand:{stage}", current, total)

    expansion_result = expand_papers(
        client=client,
        seeds=seeds_with_pmcid,
        expand_references=expand_references,
        expand_citations=expand_citations,
        depth=expansion_depth,
        max_expansion=max_expansion,
        progress_callback=expansion_progress,
    )

    # Build dry-run result
    if dry_run:
        return {
            "seed_stats": seed_stats,
            "expansion_config": {
                "expand_references": expand_references,
                "expand_citations": expand_citations,
                "depth": expansion_depth,
                "max_expansion": max_expansion,
            },
            "seed_coverage": expansion_result.seed_coverage,
            "expansion_stats": expansion_result.expansion_stats,
            "layers": expansion_result.layers,
        }

    # Phase 3: Fetch seed papers
    if verbose:
        logger.info("Fetching %d seed papers...", len(seeds_with_pmcid))

    seed_pmcids = [s.pmcid for s in seeds_with_pmcid if s.pmcid]

    seed_fetch_stats = fetch_europepmc(
        pmcids=seed_pmcids,
        output_dir=output_dir,
        workspace=workspace,
        verbose=verbose,
        progress_callback=_wrap_callback(progress_callback, "europepmc"),
        email=email,
        api_key=api_key,
    )

    # Phase 4: Fetch expanded papers
    expanded_pmcids: list[str] = []
    for papers in expansion_result.expanded_papers.values():
        for paper in papers:
            pmcid = paper.get("pmcid")
            if pmcid:
                # Normalize PMCID
                if not str(pmcid).upper().startswith("PMC"):
                    pmcid = f"PMC{pmcid}"
                expanded_pmcids.append(pmcid)

    # Remove duplicates while preserving order
    seen: set[str] = set(seed_pmcids)
    unique_expanded: list[str] = []
    for pmcid in expanded_pmcids:
        if pmcid not in seen:
            seen.add(pmcid)
            unique_expanded.append(pmcid)

    if verbose:
        logger.info("Fetching %d expanded papers...", len(unique_expanded))

    expanded_fetch_stats: dict[str, Any] = {"fetched": 0, "valid": 0}
    if unique_expanded:
        expanded_fetch_stats = fetch_europepmc(
            pmcids=unique_expanded,
            output_dir=output_dir,
            workspace=workspace,
            verbose=verbose,
            progress_callback=_wrap_callback(progress_callback, "europepmc"),
            email=email,
            api_key=api_key,
        )

    return {
        "seed_stats": seed_stats,
        "seeds_fetched": seed_fetch_stats.get("fetched", 0),
        "seeds_valid": seed_fetch_stats.get("valid", 0),
        "expanded_fetched": expanded_fetch_stats.get("fetched", 0),
        "expanded_valid": expanded_fetch_stats.get("valid", 0),
        "total_unique": len(seed_pmcids) + len(unique_expanded),
        "expansion_stats": expansion_result.expansion_stats,
        "seed_coverage": expansion_result.seed_coverage,
    }


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
