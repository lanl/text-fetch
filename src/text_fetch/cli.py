#!/usr/bin/env python3
"""text-fetch CLI entry point.

This module is a thin dispatcher. Business logic lives in text_fetch/*.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from . import __version__
from .common import build_provenance, create_jats_tarball, embed_provenance
from .config import (
    get_grobid_url,
    get_ncbi_api_key,
    get_ncbi_email,
    load_config,
)


def _handle_tarball_creation(
    output_dir: str,
    tarball: bool,
    tarball_name: str | None,
    stats: dict[str, Any],
    search_config_dict: dict[str, Any] | None,
    command: str,
    source: str,
    verbose: bool = False,
) -> None:
    """Handle tarball creation after a fetch completes.

    Args:
        output_dir: Output directory path.
        tarball: Whether to create tarball.
        tarball_name: Custom tarball name or None for default.
        stats: Fetch statistics dict.
        search_config_dict: Search config as dict (for embedding).
        command: Original command line.
        source: Source name (pmc, europepmc, etc).
        verbose: Whether to show verbose output.
    """
    if not tarball:
        return

    out_path = Path(output_dir)
    default_name = f"{source}_corpus.tar.gz" if source else "corpus.tar.gz"
    tarball_path = out_path / (tarball_name or default_name)

    if verbose:
        click.echo(f"Creating tarball: {tarball_path}")

    try:
        tarball_stats = create_jats_tarball(out_path, tarball_path)

        # Build and embed provenance
        provenance = build_provenance(
            stats=tarball_stats,
            command=command,
            sources_queried=[source] if source else None,
        )
        embed_provenance(tarball_path, search_config_dict, provenance)

        click.echo(f"Created tarball: {tarball_path}")
        click.echo(f"  Files included: {tarball_stats['files_included']}")
        click.echo(f"  Size: {tarball_stats['bytes']:,} bytes")
    except Exception as e:
        click.echo(f"Warning: Failed to create tarball: {e}", err=True)


@click.group()
@click.version_option(version=__version__, prog_name="text-fetch")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Acquire scientific literature for RAG pipelines."""
    # Load config once and store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@cli.group()
@click.pass_context
def pdf(ctx: click.Context) -> None:
    """Process local PDF files via GROBID."""
    pass


@pdf.command("batch")
@click.option(
    "--dir",
    "-d",
    "pdf_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Directory containing PDF files (scanned recursively)",
)
@click.option(
    "--out",
    "-o",
    "output_dir",
    required=True,
    type=click.Path(),
    help="Output directory for JATS files",
)
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option(
    "--grobid-url",
    default=None,
    help="GROBID service URL (default: from config or localhost:8070)",
)
@click.option(
    "--xslt-path",
    default=None,
    type=click.Path(exists=True),
    help="Path to TEI→JATS XSLT stylesheet (default: bundled)",
)
@click.option(
    "--prefer-fulltext/--header-only",
    default=True,
    help="Use fulltext processing (default) vs header-only",
)
@click.option(
    "--save-tei/--no-tei",
    default=True,
    help="Cache TEI XML files",
)
@click.option(
    "--resolve-ncbi",
    is_flag=True,
    help="Resolve DOIs to PMID/PMCID via NCBI",
)
@click.option(
    "--email",
    default=None,
    help="Email for NCBI API (required with --resolve-ncbi)",
)
@click.option(
    "--api-key",
    default=None,
    help="NCBI API key for faster rate limits",
)
@click.option(
    "--csv",
    "csv_path",
    default=None,
    type=click.Path(),
    help="Output CSV metadata file",
)
@click.option(
    "--normalize-unicode",
    is_flag=True,
    help="Convert Unicode characters to ASCII",
)
@click.option(
    "--ocr",
    is_flag=True,
    help="Enable OCR for scanned PDFs (requires GROBID with Tesseract)",
)
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pdf_batch(
    ctx: click.Context,
    pdf_dir: str,
    output_dir: str,
    workspace: str | None,
    grobid_url: str | None,
    xslt_path: str | None,
    prefer_fulltext: bool,
    save_tei: bool,
    resolve_ncbi: bool,
    email: str | None,
    api_key: str | None,
    csv_path: str | None,
    normalize_unicode: bool,
    ocr: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Process PDF files in a directory via GROBID.

    \b
    Examples:
        # Basic batch processing
        text-fetch pdf batch --dir ./PDFs --out ./output

        # Add to workspace for deduplication
        text-fetch pdf batch --dir ./PDFs --workspace ./my-corpus --out ./output
    """
    import csv
    import sys
    from pathlib import Path

    from text_fetch.grobid import get_default_xslt_path
    from text_fetch.pdf import find_pdfs, process_pdf_batch
    from text_fetch.workspace import Workspace

    # Resolve XSLT path
    resolved_xslt = Path(xslt_path) if xslt_path else get_default_xslt_path()

    config = ctx.obj["config"]

    # Resolve settings from config
    grobid = grobid_url or get_grobid_url(config=config)

    if resolve_ncbi:
        email = email or get_ncbi_email(config=config)
        api_key = api_key or get_ncbi_api_key(config=config)
        if not email:
            click.echo(
                "Error: --email or config email required with --resolve-ncbi",
                err=True,
            )
            raise SystemExit(1)

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Count PDFs
    pdfs = find_pdfs(pdf_dir)
    if not pdfs:
        click.echo("No PDF files found.")
        return

    click.echo(f"Found {len(pdfs)} PDF files in {pdf_dir}")
    if ws:
        click.echo(f"Workspace: {ws.path}")
    else:
        click.echo(f"Output directory: {output_dir}")
    click.echo(f"GROBID URL: {grobid}")
    if ocr:
        click.echo("OCR: enabled")

    def progress_callback(name: str, current: int, total: int) -> None:
        if verbose:
            click.echo(f"[{current}/{total}] Processing {name}")

    result = process_pdf_batch(
        pdf_dir=Path(pdf_dir),
        output_dir=Path(output_dir),
        workspace=ws,
        grobid_url=grobid,
        xslt_path=resolved_xslt,
        prefer_fulltext=prefer_fulltext,
        save_tei=save_tei,
        resolve_ncbi=resolve_ncbi,
        email=email,
        api_key=api_key,
        normalize_unicode=normalize_unicode,
        ocr=ocr,
        progress_callback=progress_callback,
    )

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        search_config = {
            "source": "pdf",
            "pdf_dir": pdf_dir,
        }
        ws.record_search(config=search_config, command=cmd, stats=result)

    # Summary
    click.echo("\nProcessing complete:")
    click.echo(f"  Total: {result['total']}")
    click.echo(f"  Valid: {result['valid']}")
    click.echo(f"  Incomplete: {result['incomplete']}")
    if result.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {result['duplicates_skipped']}")
    click.echo(f"  Errors: {result['errors']}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")

    # CSV output
    if csv_path:
        fieldnames = [
            "first_author",
            "year",
            "title",
            "journal",
            "DOI",
            "PMID",
            "PMCID",
            "pdf_path",
            "tei_path",
            "jats_path",
            "source",
            "notes",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in result["results"]:
                row = {**r.get("metadata", {})}
                row["pdf_path"] = r["pdf_path"]
                row["tei_path"] = r.get("tei_path", "")
                row["jats_path"] = r.get("jats_path", "")
                row["source"] = r["source"]
                row["notes"] = ";".join(r.get("notes", []))
                writer.writerow(row)
        click.echo(f"Wrote metadata to {csv_path}")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch pdf batch --dir {pdf_dir} --out {output_dir}"
        _handle_tarball_creation(
            output_dir=output_dir,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=result,
            search_config_dict=None,
            command=cmd,
            source="pdf",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.group()
@click.pass_context
def pmc(ctx: click.Context) -> None:
    """PubMed Central commands."""
    pass


@pmc.command(name="fetch")
@click.option("--config-file", type=click.Path(exists=True), help="JSON search config")
@click.option("--query", help="Raw PubMed query string")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option(
    "--email",
    default=None,
    envvar="NCBI_EMAIL",
    help="Email for NCBI requests",
)
@click.option(
    "--api-key",
    default=None,
    envvar="NCBI_API_KEY",
    help="NCBI API key (optional, for higher rate limits)",
)
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc_fetch(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    out: str,
    workspace: str | None,
    email: str | None,
    api_key: str | None,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from PubMed Central via E-utilities.

    \b
    Examples:
        # Fetch by author
        text-fetch pmc fetch --query "hlavacek ws[au]" --out ./output

        # Fetch using JSON config
        text-fetch pmc fetch --config-file input/ebola.json --out ./output

        # Add to workspace for deduplication
        text-fetch pmc fetch --query "hlavacek ws[au]" --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from .pmc import fetch_pmc
    from .query import SearchConfig, SearchConfigError
    from .workspace import Workspace

    if not config_file and not query:
        raise click.UsageError("Either --config-file or --query is required")

    config = ctx.obj["config"]

    # Resolve settings with priority: CLI > env > config file
    try:
        resolved_email = get_ncbi_email(cli_value=email, config=config)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=config)

    # Set up logging
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"Using NCBI email: {resolved_email}")
        if resolved_api_key:
            click.echo("Using NCBI API key: [configured]")
        else:
            click.echo("No NCBI API key configured (using lower rate limit)")
        if config.config_path:
            click.echo(f"Config loaded from: {config.config_path}")

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Load search config if provided
    search_config = None
    if config_file:
        try:
            search_config = SearchConfig.from_json(config_file)
            if verbose:
                click.echo(f"Loaded search config: {search_config}")
        except SearchConfigError as e:
            raise click.UsageError(f"Invalid search config: {e}") from e

    # Show query that will be used
    pubmed_query: str = (
        search_config.to_pubmed_query() if search_config else (query or "")
    )
    click.echo(f"Query: {pubmed_query}")

    # Progress callback for click progress bar
    progress_bar = None
    total_articles = 0

    def progress_callback(pmcid: str, current: int, total: int) -> None:
        nonlocal progress_bar, total_articles
        if progress_bar is None:
            total_articles = total
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        # Run the fetch
        stats = fetch_pmc(
            config=search_config,
            query=query,
            email=resolved_email,
            api_key=resolved_api_key,
            output_dir=out,
            workspace=ws,
            verbose=verbose,
            progress_callback=progress_callback,
        )

    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        ws_search_config = {
            "source": "pmc",
            "query": query,
            "config_file": config_file,
        }
        ws.record_search(config=ws_search_config, command=cmd, stats=stats)

    # Print summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  PMIDs found: {stats['pmids_found']:,}")
    click.echo(f"  PMC full-text available: {stats['pmcids_available']:,}")
    click.echo(f"  Downloaded: {stats['fetched']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Skipped (duplicates): {stats['skipped']:,}")
    if stats.get("duplicates_skipped"):
        click.echo(f"  DOI duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")
        click.echo(f"Manifest: {out}/manifest.json")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        search_config_dict = search_config.to_dict() if search_config else None
        cmd = f"text-fetch pmc fetch --query '{query or pubmed_query}' --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=search_config_dict,
            command=cmd,
            source="pmc",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@pmc.command(name="sync")
@click.option(
    "--storage",
    required=True,
    type=click.Path(),
    help="Storage directory for PMC OA corpus",
)
@click.option(
    "--download",
    is_flag=True,
    help="Actually download files (default is dry-run)",
)
@click.option(
    "--subset",
    multiple=True,
    type=click.Choice(["oa_comm", "oa_noncomm", "oa_other"]),
    help="Subset(s) to sync (default: all)",
)
@click.option(
    "--max-files",
    type=int,
    default=None,
    help="Maximum files to download (for testing)",
)
@click.option(
    "--verify",
    is_flag=True,
    help="Verify existing files match expected sizes",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompts",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc_sync(
    ctx: click.Context,
    storage: str,
    download: bool,
    subset: tuple[str, ...],
    max_files: int | None,
    verify: bool,
    yes: bool,
    verbose: bool,
) -> None:
    """Check for PMC OA updates (dry-run by default).

    Shows what files would be downloaded. Use --download to fetch.

    \b
    Examples:
        # Check for updates (dry-run)
        text-fetch pmc sync --storage /Volumes/External/pmc-oa

        # Download updates
        text-fetch pmc sync --storage /Volumes/External/pmc-oa --download

        # Sync only commercial-use subset
        text-fetch pmc sync --storage ./pmc-oa --subset oa_comm --download

        # Verify existing files
        text-fetch pmc sync --storage ./pmc-oa --verify
    """
    import logging

    from .pmc_oa import PMCOAClient, read_sync_manifest

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Determine subsets
    subsets = list(subset) if subset else ["oa_comm", "oa_noncomm", "oa_other"]

    click.echo(f"Storage directory: {storage}")
    click.echo(f"Subsets: {', '.join(subsets)}")

    # Check existing manifest
    manifest = read_sync_manifest(storage)
    if manifest.entries:
        click.echo(f"Local files: {len(manifest.entries):,}")
        if manifest.last_sync:
            click.echo(f"Last sync: {manifest.last_sync}")
    else:
        click.echo("Local files: 0 (no manifest)")

    with PMCOAClient(storage, subsets=subsets) as client:
        # Handle verification mode
        if verify:
            if not manifest.entries:
                click.echo("\nNo files to verify. Run import first.")
                return

            click.echo("\nVerifying local files...")
            with click.progressbar(
                length=len(manifest.entries),
                label="Verifying",
                show_pos=True,
                show_percent=True,
            ) as bar:

                def verify_callback(
                    accession_id: str, current: int, total: int
                ) -> None:
                    bar.update(1)

                results = client.verify_files(
                    manifest=manifest,
                    progress_callback=verify_callback,
                )

            click.echo("\n" + "=" * 50)
            click.echo("Verification complete!")
            click.echo(f"  Total: {results['total']:,}")
            click.echo(f"  Verified: {results['verified']:,}")
            click.echo(f"  Missing: {results['missing']:,}")
            click.echo(f"  Size mismatch: {results['size_mismatch']:,}")

            if results["missing_files"] and verbose:
                click.echo("\nMissing files:")
                for f in results["missing_files"][:10]:
                    click.echo(f"  {f}")
                if len(results["missing_files"]) > 10:
                    click.echo(f"  ... and {len(results['missing_files']) - 10} more")
            return

        # Fetch file lists to show stats
        click.echo("\nFetching remote file lists...")
        all_entries = client.get_all_entries()

        if not all_entries:
            click.echo("Error: Could not fetch file lists from PMC")
            ctx.exit(1)

        # Calculate what needs to be downloaded (always incremental if we have files)
        if manifest.entries:
            to_download = client.get_updates(manifest, all_entries)
        else:
            to_download = all_entries

        if max_files:
            to_download = to_download[:max_files]

        # Calculate estimated size (rough estimate: ~5MB average per file)
        estimated_size_mb = len(to_download) * 5
        estimated_size_gb = estimated_size_mb / 1024

        # Show status summary
        click.echo("\n" + "=" * 50)
        click.echo("PMC OA Status:")
        click.echo(f"  Remote files: {len(all_entries):,}")
        click.echo(f"  Local files:  {len(manifest.entries):,}")
        click.echo(f"  New/updated:  {len(to_download):,}", nl=False)
        if to_download:
            if estimated_size_gb >= 1:
                click.echo(f" (~{estimated_size_gb:.1f} GB)")
            else:
                click.echo(f" (~{estimated_size_mb:,} MB)")
        else:
            click.echo()

        if not to_download:
            click.echo("\nAlready up to date!")
            return

        # If not downloading, show dry-run message
        if not download:
            click.echo("\nRun with --download to fetch updates.")
            return

        # Confirmation prompt for large downloads
        if not yes and len(to_download) > 1000:
            click.echo(
                f"\nWarning: This will download {len(to_download):,} files "
                f"(~{estimated_size_gb:.1f} GB)."
            )
            if not click.confirm("Proceed with download?"):
                click.echo("Aborted.")
                ctx.exit(0)

        # Progress bar for download
        click.echo()
        with click.progressbar(
            length=len(to_download),
            label="Downloading",
            show_pos=True,
            show_percent=True,
        ) as bar:

            def progress_callback(accession_id: str, current: int, total: int) -> None:
                bar.update(1)

            stats = client.sync(
                update_only=bool(manifest.entries),
                progress_callback=progress_callback,
                max_files=max_files,
            )

        # Summary
        click.echo("\n" + "=" * 50)
        click.echo("Sync complete!")
        click.echo(f"  Downloaded: {stats['downloaded']:,}")
        click.echo(f"  Failed: {stats['failed']:,}")
        click.echo(f"  Total bytes: {stats['bytes_downloaded']:,}")
        click.echo(f"  Manifest: {storage}/sync_manifest.json")


@pmc.command(name="status")
@click.option(
    "--storage",
    required=True,
    type=click.Path(),
    help="Storage directory for PMC OA corpus",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc_status(
    ctx: click.Context,
    storage: str,
    verbose: bool,
) -> None:
    """Show status of local PMC OA mirror.

    \b
    Examples:
        text-fetch pmc status --storage /Volumes/External/pmc-oa
    """
    from .pmc_oa import PMCOAClient

    with PMCOAClient(storage) as client:
        status = client.get_status()

    click.echo("PMC OA Local Mirror")
    click.echo("=" * 40)
    click.echo(f"Storage: {status['storage_dir']}")

    if not status["manifest_exists"]:
        click.echo("\nNo manifest found. Run 'pmc import' or 'pmc sync' first.")
        return

    if status["last_sync"]:
        last_sync = status["last_sync"][:19].replace("T", " ")
        click.echo(f"Last sync: {last_sync}")

    click.echo()
    click.echo("Subsets:")
    for subset in status.get("subsets", []):
        count = status["subset_counts"].get(subset, 0)
        size_bytes = status["subset_bytes"].get(subset, 0)
        size_gb = size_bytes / (1024 * 1024 * 1024)
        click.echo(f"  {subset}: {count:,} files ({size_gb:.1f} GB)")

    total_gb = status["total_bytes"] / (1024 * 1024 * 1024)
    click.echo()
    click.echo(f"Total: {status['total_files']:,} files ({total_gb:.1f} GB)")


@pmc.command(name="import")
@click.option(
    "--storage",
    required=True,
    type=click.Path(exists=True),
    help="Storage directory containing existing .tar.gz files",
)
@click.option(
    "--subset",
    multiple=True,
    type=click.Choice(["oa_comm", "oa_noncomm", "oa_other"]),
    help="Subset(s) to import (default: all)",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc_import(
    ctx: click.Context,
    storage: str,
    subset: tuple[str, ...],
    verbose: bool,
) -> None:
    """Import existing .tar.gz files into sync manifest.

    Scans the storage directory for existing PMC .tar.gz files and
    cross-references them with PMC file lists to create manifest entries.
    This allows incremental updates after manually downloading the corpus.

    \b
    Examples:
        # Import existing collection
        text-fetch pmc import --storage /Volumes/External/pmc-oa

        # Import only commercial-use subset
        text-fetch pmc import --storage ./pmc-oa --subset oa_comm
    """
    import logging

    from .pmc_oa import import_existing

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    # Determine subsets
    subsets = list(subset) if subset else None

    click.echo(f"Scanning {storage} for .tar.gz files...")
    click.echo("(This may take a while for large collections)")
    click.echo()

    # Progress tracking
    progress_bar = None

    def progress_callback(accession_id: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None and total > 0:
            progress_bar = click.progressbar(
                length=total,
                label="Matching files",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        if progress_bar is not None:
            progress_bar.update(1)

    try:
        results = import_existing(
            storage_dir=storage,
            subsets=subsets,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    click.echo("\n" + "=" * 50)
    click.echo("Import complete!")
    click.echo(f"  Files scanned: {results['scanned']:,}")
    click.echo(f"  Matched: {results['matched']:,}")
    click.echo(f"  Unmatched: {results['unmatched']:,}")
    click.echo(f"  Manifest: {storage}/sync_manifest.json")

    if results["unmatched_files"] and verbose:
        click.echo("\nUnmatched files (not in current PMC lists):")
        for f in results["unmatched_files"][:10]:
            click.echo(f"  {f}")
        if len(results["unmatched_files"]) > 10:
            more = len(results["unmatched_files"]) - 10
            click.echo(f"  ... and {more} more")


@cli.group()
@click.pass_context
def arxiv(ctx: click.Context) -> None:
    """arXiv preprint commands."""
    pass


@arxiv.command(name="fetch")
@click.option(
    "--config-file",
    type=click.Path(exists=True),
    help="JSON search config",
)
@click.option("--query", help="Raw arXiv query string")
@click.option(
    "--categories",
    multiple=True,
    help="arXiv categories (e.g., q-bio.MN, cs.AI)",
)
@click.option("--max-results", default=100, help="Maximum results")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option("--grobid-url", help="GROBID service URL")
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def arxiv_fetch(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    categories: tuple[str, ...],
    max_results: int,
    out: str,
    workspace: str | None,
    grobid_url: str | None,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch preprints from arXiv.

    Downloads PDFs and converts to JATS via GROBID.

    \b
    Examples:
        # Search by author
        text-fetch arxiv fetch --query 'au:"hlavacek ws"' --out ./output

        # Search by category
        text-fetch arxiv fetch --categories q-bio.MN --out ./output

        # Using JSON config
        text-fetch arxiv fetch --config-file input/search.json --out ./output

        # Add to workspace for deduplication
        text-fetch arxiv fetch --categories q-bio.MN --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from .arxiv import fetch_arxiv
    from .query import SearchConfig, SearchConfigError
    from .workspace import Workspace

    if not config_file and not query and not categories:
        raise click.UsageError(
            "Either --config-file, --query, or --categories required"
        )

    config = ctx.obj["config"]

    # Resolve GROBID URL
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL: {resolved_grobid}")

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Build search config
    search_config = None
    if config_file:
        try:
            search_config = SearchConfig.from_json(config_file)
        except SearchConfigError as e:
            raise click.UsageError(f"Invalid config: {e}") from e
    elif categories:
        search_config = SearchConfig(arxiv_categories=list(categories))

    # Show query
    arxiv_query: str | None = search_config.to_arxiv_query() if search_config else query
    click.echo(f"Query: {arxiv_query}")

    # Progress bar
    progress_bar = None

    def progress_callback(arxiv_id: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        stats = fetch_arxiv(
            config=search_config,
            query=query,
            output_dir=out,
            workspace=ws,
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        ws_search_config = {
            "source": "arxiv",
            "query": query,
            "categories": list(categories) if categories else None,
            "max_results": max_results,
        }
        ws.record_search(config=ws_search_config, command=cmd, stats=stats)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  PDFs downloaded: {stats['pdfs_downloaded']:,}")
    click.echo(f"  Converted: {stats['converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    if stats.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        search_config_dict = search_config.to_dict() if search_config else None
        cmd = f"text-fetch arxiv fetch --query '{query or arxiv_query}' --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=search_config_dict,
            command=cmd,
            source="arxiv",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.group()
@click.pass_context
def biorxiv(ctx: click.Context) -> None:
    """bioRxiv preprint commands."""
    pass


@biorxiv.command(name="fetch")
@click.option("--start-date", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option("--days", type=int, help="Recent N days (alternative to date range)")
@click.option("--category", help="bioRxiv category filter (use underscore for spaces)")
@click.option("--doi", multiple=True, help="Specific DOIs to fetch")
@click.option("--max-results", default=100, help="Maximum results")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option("--grobid-url", help="GROBID service URL (for PDF fallback)")
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def biorxiv_fetch(
    ctx: click.Context,
    start_date: str | None,
    end_date: str | None,
    days: int | None,
    category: str | None,
    doi: tuple[str, ...],
    max_results: int,
    out: str,
    workspace: str | None,
    grobid_url: str | None,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch preprints from bioRxiv.

    Downloads JATS XML directly when available, falls back to PDF→GROBID.

    \b
    Examples:
        # Recent 30 days of systems biology
        text-fetch biorxiv fetch --days 30 --category systems_biology --out ./output

        # Date range
        text-fetch biorxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

        # Specific DOIs
        text-fetch biorxiv fetch --doi 10.1101/2024.01.15.123456 --out ./output

        # Add to workspace for deduplication
        text-fetch biorxiv fetch --days 30 --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from .biorxiv import fetch_biorxiv
    from .workspace import Workspace

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL (fallback): {resolved_grobid}")

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Progress bar
    progress_bar = None

    def progress_callback(doi_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        stats = fetch_biorxiv(
            start_date=start_date,
            end_date=end_date,
            category=category,
            days=days,
            dois=list(doi) if doi else None,
            output_dir=out,
            workspace=ws,
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        search_config = {
            "source": "biorxiv",
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "category": category,
            "dois": list(doi) if doi else None,
            "max_results": max_results,
        }
        ws.record_search(config=search_config, command=cmd, stats=stats)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Direct JATS: {stats['jats_direct']:,}")
    click.echo(f"  Via GROBID: {stats['pdf_converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    if stats.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch biorxiv fetch --days {days or ''} --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=None,
            command=cmd,
            source="biorxiv",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.group()
@click.pass_context
def medrxiv(ctx: click.Context) -> None:
    """medRxiv preprint commands."""
    pass


@medrxiv.command(name="fetch")
@click.option("--start-date", help="Start date (YYYY-MM-DD)")
@click.option("--end-date", help="End date (YYYY-MM-DD)")
@click.option("--days", type=int, help="Recent N days (alternative to date range)")
@click.option("--category", help="medRxiv category filter (use underscore for spaces)")
@click.option("--doi", multiple=True, help="Specific DOIs to fetch")
@click.option("--max-results", default=100, help="Maximum results")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option("--grobid-url", help="GROBID service URL (for PDF fallback)")
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def medrxiv_fetch(
    ctx: click.Context,
    start_date: str | None,
    end_date: str | None,
    days: int | None,
    category: str | None,
    doi: tuple[str, ...],
    max_results: int,
    out: str,
    workspace: str | None,
    grobid_url: str | None,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch preprints from medRxiv.

    Downloads JATS XML directly when available, falls back to PDF→GROBID.

    \b
    Examples:
        # Recent epidemiology preprints
        text-fetch medrxiv fetch --days 30 --category epidemiology --out ./output

        # Date range
        text-fetch medrxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

        # Add to workspace for deduplication
        text-fetch medrxiv fetch --days 30 --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from .biorxiv import fetch_medrxiv
    from .workspace import Workspace

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL (fallback): {resolved_grobid}")

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Progress bar
    progress_bar = None

    def progress_callback(doi_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        stats = fetch_medrxiv(
            start_date=start_date,
            end_date=end_date,
            category=category,
            days=days,
            dois=list(doi) if doi else None,
            output_dir=out,
            workspace=ws,
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        search_config = {
            "source": "medrxiv",
            "start_date": start_date,
            "end_date": end_date,
            "days": days,
            "category": category,
            "dois": list(doi) if doi else None,
            "max_results": max_results,
        }
        ws.record_search(config=search_config, command=cmd, stats=stats)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Direct JATS: {stats['jats_direct']:,}")
    click.echo(f"  Via GROBID: {stats['pdf_converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    if stats.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch medrxiv fetch --days {days or ''} --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=None,
            command=cmd,
            source="medrxiv",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.group()
@click.pass_context
def chemrxiv(ctx: click.Context) -> None:
    """ChemRxiv preprint commands."""
    pass


@chemrxiv.command(name="fetch")
@click.option("--term", help="Search query (title, abstract, authors)")
@click.option(
    "--category",
    multiple=True,
    help="Category filter (e.g., organic_chemistry)",
)
@click.option("--date-from", help="Start date (YYYY-MM-DD)")
@click.option("--date-to", help="End date (YYYY-MM-DD)")
@click.option("--item-id", multiple=True, help="Specific item IDs to fetch")
@click.option("--max-results", default=100, help="Maximum results")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option("--grobid-url", help="GROBID service URL (required)")
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def chemrxiv_fetch(
    ctx: click.Context,
    term: str | None,
    category: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    item_id: tuple[str, ...],
    max_results: int,
    out: str,
    workspace: str | None,
    grobid_url: str | None,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch preprints from ChemRxiv.

    Requires GROBID for PDF→JATS conversion (no native JATS available).

    \b
    Examples:
        # Search by term
        text-fetch chemrxiv fetch --term "catalysis" --out ./output

        # Filter by category
        text-fetch chemrxiv fetch --category organic_chemistry --out ./output

        # Date range
        text-fetch chemrxiv fetch --date-from 2024-01-01 --out ./output

        # Specific item IDs
        text-fetch chemrxiv fetch --item-id item_2024-abc123 --out ./output

        # Add to workspace for deduplication
        text-fetch chemrxiv fetch --term "catalysis" --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from .chemrxiv import fetch_chemrxiv, get_category_ids
    from .workspace import Workspace

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL: {resolved_grobid}")

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Convert category names to IDs
    category_ids = get_category_ids(list(category)) if category else None

    # Progress bar
    progress_bar = None

    def progress_callback(item_id_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        stats = fetch_chemrxiv(
            term=term,
            category_ids=category_ids,
            date_from=date_from,
            date_to=date_to,
            item_ids=list(item_id) if item_id else None,
            output_dir=out,
            workspace=ws,
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        search_config = {
            "source": "chemrxiv",
            "term": term,
            "category_ids": category_ids,
            "date_from": date_from,
            "date_to": date_to,
            "item_ids": list(item_id) if item_id else None,
            "max_results": max_results,
        }
        ws.record_search(config=search_config, command=cmd, stats=stats)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  PDFs downloaded: {stats['pdfs_downloaded']:,}")
    click.echo(f"  Converted: {stats['converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    if stats.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch chemrxiv fetch --term '{term or ''}' --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=None,
            command=cmd,
            source="chemrxiv",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.group()
@click.pass_context
def europepmc(ctx: click.Context) -> None:
    """Europe PMC commands."""
    pass


@europepmc.command(name="fetch")
@click.option("--query", help="Raw Lucene query string")
@click.option("--author", help="Author name")
@click.option("--keyword", multiple=True, help="Keywords to search")
@click.option("--date-from", help="Start date (YYYY-MM-DD)")
@click.option("--date-to", help="End date (YYYY-MM-DD)")
@click.option("--pmcid", multiple=True, help="Specific PMC IDs to fetch")
@click.option("--max-results", default=100, help="Maximum results")
@click.option("--include-non-oa", is_flag=True, help="Include non-open-access")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from checkpoint if interrupted",
)
@click.option(
    "--update",
    is_flag=True,
    help="Only fetch papers since last fetch (requires workspace)",
)
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def europepmc_fetch(
    ctx: click.Context,
    query: str | None,
    author: str | None,
    keyword: tuple[str, ...],
    date_from: str | None,
    date_to: str | None,
    pmcid: tuple[str, ...],
    max_results: int,
    include_non_oa: bool,
    out: str,
    workspace: str | None,
    resume: bool,
    update: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from Europe PMC.

    Downloads native JATS XML (no GROBID required).

    \b
    Examples:
        # Search by author
        text-fetch europepmc fetch --author "hlavacek ws" --out ./output

        # Search with keywords
        text-fetch europepmc fetch --keyword "systems biology" --out ./output

        # Date range
        text-fetch europepmc fetch --author "perelson" --date-from 2020-01-01 --out ./output

        # Raw Lucene query
        text-fetch europepmc fetch --query 'AUTH:"hlavacek" AND TITLE:modeling' --out ./output

        # Specific PMC IDs
        text-fetch europepmc fetch --pmcid PMC123456 --pmcid PMC789012 --out ./output

        # Add to workspace for deduplication
        text-fetch europepmc fetch --author "hlavacek ws" --workspace ./my-corpus --out ./output

        # Resume interrupted fetch
        text-fetch europepmc fetch --author "hlavacek ws" --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch europepmc fetch --author "hlavacek ws" --workspace ./my-corpus --update
    """
    import logging
    import sys

    from .europepmc import fetch_europepmc
    from .workspace import Workspace

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Progress bar
    progress_bar = None

    def progress_callback(pmcid_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        stats = fetch_europepmc(
            query=query,
            author=author,
            keywords=list(keyword) if keyword else None,
            date_from=date_from,
            date_to=date_to,
            pmcids=list(pmcid) if pmcid else None,
            output_dir=out,
            workspace=ws,
            max_results=max_results,
            open_access_only=not include_non_oa,
            verbose=verbose,
            progress_callback=progress_callback,
            resume=resume,
            update=update,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Record search in workspace
    if ws:
        # Build command string
        cmd = " ".join(sys.argv)
        # Build config dict for recording
        search_config = {
            "source": "europepmc",
            "query": query,
            "author": author,
            "keywords": list(keyword) if keyword else None,
            "date_from": date_from,
            "date_to": date_to,
            "pmcids": list(pmcid) if pmcid else None,
            "max_results": max_results,
            "open_access_only": not include_non_oa,
        }
        ws.record_search(
            config=search_config,
            command=cmd,
            stats=stats,
        )

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Full-text available: {stats['full_text_available']:,}")
    click.echo(f"  Downloaded: {stats['fetched']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    if stats.get("resumed_from"):
        click.echo(f"  Resumed from: {stats['resumed_from']:,} completed")
    if stats.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch europepmc fetch --author '{author or ''}' --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=None,
            command=cmd,
            source="europepmc",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.command(name="fetch")
@click.option(
    "--config-file",
    type=click.Path(exists=True),
    help="JSON search configuration file",
)
@click.option(
    "--from-tarball",
    type=click.Path(exists=True),
    help="Re-run fetch using config from existing tarball",
)
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option("--email", envvar="NCBI_EMAIL", help="Email for NCBI requests")
@click.option("--api-key", envvar="NCBI_API_KEY", help="NCBI API key")
@click.option("--grobid-url", help="GROBID service URL")
@click.option(
    "--sources",
    help="Comma-separated sources to use (overrides config)",
)
@click.option("--no-dedupe", is_flag=True, help="Disable DOI deduplication")
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def unified_fetch_cmd(
    ctx: click.Context,
    config_file: str | None,
    from_tarball: str | None,
    out: str,
    workspace: str | None,
    email: str | None,
    api_key: str | None,
    grobid_url: str | None,
    sources: str | None,
    no_dedupe: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from multiple sources using unified config.

    \b
    Examples:
        # Fetch from all sources in config
        text-fetch fetch --config-file input/hlavacek.json --out ./output

        # Override sources
        text-fetch fetch --config-file input/search.json \\
            --sources pmc,europepmc --out ./output

        # Disable deduplication
        text-fetch fetch --config-file input/search.json --no-dedupe --out ./output

        # Add to workspace for deduplication
        text-fetch fetch --config-file input/search.json \\
            --workspace ./my-corpus --out ./output

        # Re-run fetch from existing tarball (reproducibility)
        text-fetch fetch --from-tarball corpus.tar.gz --out ./updated --tarball
    """
    import logging
    import sys

    from .common import extract_search_config_from_tarball
    from .fetch import unified_fetch
    from .query import SearchConfig, SearchConfigError
    from .workspace import Workspace

    # Validate options
    if not config_file and not from_tarball:
        raise click.UsageError("Either --config-file or --from-tarball is required")
    if config_file and from_tarball:
        raise click.UsageError("Cannot use both --config-file and --from-tarball")

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    app_config = ctx.obj["config"]

    # Resolve settings
    resolved_email = None
    import contextlib

    with contextlib.suppress(ValueError):
        # Email only required if pmc source is used
        resolved_email = get_ncbi_email(cli_value=email, config=app_config)

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=app_config)
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=app_config)

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Load search config from file or tarball
    config_source = config_file  # For display purposes
    if from_tarball:
        config_source = f"tarball:{from_tarball}"
        config_data = extract_search_config_from_tarball(Path(from_tarball))
        if not config_data:
            raise click.ClickException(
                f"No search config found in tarball: {from_tarball}"
            )
        try:
            search_config = SearchConfig.from_dict(config_data)
        except SearchConfigError as e:
            raise click.ClickException(f"Invalid config in tarball: {e}") from e
        if verbose:
            click.echo(f"Loaded config from tarball: {from_tarball}")
    else:
        # config_file is not None here (validated above)
        assert config_file is not None
        try:
            search_config = SearchConfig.from_json(config_file)
        except SearchConfigError as e:
            raise click.UsageError(f"Invalid config: {e}") from e

    # Override sources if specified
    if sources:
        search_config.sources = [s.strip() for s in sources.split(",")]

    # Override deduplication (when using workspace, deduplication is automatic)
    if no_dedupe and not ws:
        search_config.deduplicate_by_doi = False

    # Validate email if pmc source is used
    effective_sources = search_config.sources or ["pmc"]
    if "pmc" in effective_sources and not resolved_email:
        raise click.UsageError(
            "NCBI email required for PMC source. "
            "Set via --email, NCBI_EMAIL env var, or config file."
        )

    # Show config summary
    click.echo(f"Config: {config_source}")
    click.echo(f"Sources: {', '.join(effective_sources)}")
    click.echo(f"Max per source: {search_config.max_results_per_source}")
    if ws:
        click.echo(f"Workspace: {ws.path} (auto-deduplication)")
    else:
        click.echo(f"Deduplicate: {search_config.deduplicate_by_doi}")
    click.echo()

    # Progress tracking
    current_source: list[str | None] = [None]
    progress_bar: list[click.progressbar | None] = [None]

    def progress_callback(
        source: str, article_id: str, current: int, total: int
    ) -> None:
        if source != current_source[0]:
            if progress_bar[0] is not None:
                progress_bar[0].__exit__(None, None, None)
            current_source[0] = source
            progress_bar[0] = click.progressbar(
                length=total,
                label=f"Fetching {source}",
                show_pos=True,
                show_percent=True,
            )
            progress_bar[0].__enter__()
        if progress_bar[0] is not None:
            progress_bar[0].update(1)

    try:
        stats = unified_fetch(
            config=search_config,
            output_dir=out,
            workspace=ws,
            email=resolved_email,
            api_key=resolved_api_key,
            grobid_url=resolved_grobid,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar[0] is not None:
            progress_bar[0].__exit__(None, None, None)

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        ws_search_config = {
            "source": "unified",
            "config_file": config_file,
            "sources": search_config.sources,
        }
        ws.record_search(config=ws_search_config, command=cmd, stats=stats)

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("Unified fetch complete!")
    click.echo()
    click.echo("Per-source statistics:")
    for source, source_stats in stats["per_source"].items():
        if "error" in source_stats:
            click.echo(f"  {source}: ERROR - {source_stats['error']}")
        else:
            click.echo(
                f"  {source}: {source_stats.get('fetched', 0)} fetched, "
                f"{source_stats.get('valid', 0)} valid"
            )
    click.echo()
    click.echo(f"Total fetched: {stats['total_fetched']:,}")
    click.echo(f"Total valid: {stats['total_valid']:,}")
    click.echo(f"Total incomplete: {stats['total_incomplete']:,}")
    if ws:
        click.echo(f"Duplicates skipped: {stats.get('duplicates_skipped', 0):,}")
    else:
        click.echo(f"Duplicates removed: {stats['duplicates_removed']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch fetch --config-file {config_source} --out {out}"
        _handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict=search_config.to_dict(),
            command=cmd,
            source="unified",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


@cli.command(name="config")
@click.option("--show", is_flag=True, help="Show resolved configuration")
@click.pass_context
def config_cmd(ctx: click.Context, show: bool) -> None:
    """Show or manage configuration."""
    config = ctx.obj["config"]

    if True:  # Default behavior is to show
        click.echo("Configuration:")
        path = config.config_path or "Not found"
        click.echo(f"  Config file: {path}")
        click.echo("")
        click.echo("  [ncbi]")
        click.echo(f"    email: {config.ncbi.email or '(not set)'}")
        api_status = "[configured]" if config.ncbi.api_key else "(not set)"
        click.echo(f"    api_key: {api_status}")
        click.echo("")
        click.echo("  [grobid]")
        click.echo(f"    url: {config.grobid.url}")
        click.echo("")
        click.echo("Search paths:")
        click.echo("  1. ./text-fetch.toml")
        click.echo("  2. ~/.config/text-fetch/config.toml")


# =============================================================================
# Workspace Commands
# =============================================================================


@cli.group()
@click.pass_context
def workspace(ctx: click.Context) -> None:
    """Manage corpus workspaces for cross-search deduplication."""
    pass


@workspace.command(name="init")
@click.argument("path", type=click.Path())
@click.option("--name", help="Workspace name (defaults to directory name)")
def workspace_init(path: str, name: str | None) -> None:
    """Initialize a new workspace directory.

    Creates a workspace with the following structure:
    - .text-fetch/ (metadata directory)
    - valid/ (complete JATS files)
    - incomplete/ (incomplete JATS files)

    \b
    Examples:
        text-fetch workspace init ./my-corpus
        text-fetch workspace init ./my-corpus --name "Systems Biology"
    """
    from .workspace import Workspace, WorkspaceError

    try:
        ws = Workspace.init(path, name=name)
        click.echo(f"Initialized workspace: {ws.path}")
        click.echo(f"  Name: {ws.manifest.name}")
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e


@workspace.command(name="status")
@click.argument("path", type=click.Path(exists=True))
def workspace_status(path: str) -> None:
    """Show workspace statistics and status.

    \b
    Examples:
        text-fetch workspace status ./my-corpus
    """
    from .workspace import Workspace, WorkspaceError

    try:
        ws = Workspace.load(path)
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e

    stats = ws.get_statistics()

    click.echo(f"Workspace: {stats['name']}")
    click.echo(f"Path: {stats['path']}")
    if stats["created"]:
        click.echo(f"Created: {stats['created'][:19].replace('T', ' ')}")
    if stats["updated"]:
        click.echo(f"Updated: {stats['updated'][:19].replace('T', ' ')}")
    click.echo()
    click.echo("Statistics:")
    click.echo(f"  Searches: {stats['total_searches']}")
    click.echo(f"  Valid articles: {stats['total_valid']}")
    click.echo(f"  Incomplete articles: {stats['total_incomplete']}")
    click.echo(f"  Unique DOIs: {stats['unique_dois']}")
    click.echo(f"  Duplicates skipped: {stats['duplicates_skipped']}")

    # Show recent searches
    searches = ws.get_searches()
    if searches:
        click.echo()
        click.echo("Recent searches:")
        for search in searches[:5]:
            timestamp = search.timestamp[:19].replace("T", " ")
            fetched = search.statistics.get("fetched", "?")
            cmd = search.command
            if len(cmd) > 50:
                cmd = cmd[:47] + "..."
            click.echo(f"  {search.id} ({timestamp}): {fetched} articles")
            click.echo(f"    {cmd}")


@workspace.command(name="build")
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--tarball",
    "tarball_name",
    default=None,
    help="Output tarball filename (default: workspace_corpus.tar.gz)",
)
@click.option(
    "--out",
    type=click.Path(),
    help="Output directory for tarball (default: workspace directory)",
)
@click.option(
    "--include-incomplete",
    is_flag=True,
    help="Include incomplete files in tarball",
)
@click.option(
    "--compression",
    type=click.Choice(["gz", "bz2", "none"]),
    default="gz",
    help="Compression type (default: gz)",
)
def workspace_build(
    path: str,
    tarball_name: str | None,
    out: str | None,
    include_incomplete: bool,
    compression: str,
) -> None:
    """Build tarball from workspace contents.

    Creates a tarball containing all JATS XML files from the workspace,
    with provenance metadata embedded.

    \b
    Examples:
        text-fetch workspace build ./my-corpus
        text-fetch workspace build ./my-corpus --tarball corpus.tar.gz
        text-fetch workspace build ./my-corpus --out ./final --include-incomplete
    """
    from .workspace import Workspace, WorkspaceError

    try:
        ws = Workspace.load(path)
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e

    # Determine output path
    output_dir = Path(out) if out else ws.path
    default_name = f"{ws.manifest.name}_corpus.tar.gz"
    tarball_path = output_dir / (tarball_name or default_name)

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    click.echo(f"Building tarball from workspace: {ws.path}")

    stats = ws.build_tarball(
        output_path=tarball_path,
        include_incomplete=include_incomplete,
        compression=compression,
    )

    # Embed provenance
    from .common import build_provenance, embed_provenance

    workspace_stats = ws.get_statistics()
    provenance = build_provenance(
        stats=workspace_stats,
        command=f"text-fetch workspace build {path}",
        sources_queried=None,
    )

    # Build config summary from all searches
    search_records = ws.get_searches()
    search_config = {
        "workspace": ws.manifest.name,
        "searches": len(search_records),
        "search_ids": [s.id for s in search_records],
    }

    embed_provenance(tarball_path, search_config, provenance)

    click.echo(f"Created tarball: {tarball_path}")
    click.echo(f"  Files included: {stats['files_included']}")
    click.echo(f"  Valid: {stats['valid_count']}")
    click.echo(f"  Incomplete: {stats['incomplete_count']}")
    click.echo(f"  Size: {stats['bytes']:,} bytes")


@workspace.command(name="list-searches")
@click.argument("path", type=click.Path(exists=True))
def workspace_list_searches(path: str) -> None:
    """List all searches recorded in workspace.

    \b
    Examples:
        text-fetch workspace list-searches ./my-corpus
    """
    from .workspace import Workspace, WorkspaceError

    try:
        ws = Workspace.load(path)
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e

    searches = ws.get_searches()

    if not searches:
        click.echo("No searches recorded in this workspace.")
        return

    # Header
    click.echo(f"{'ID':<12} {'Timestamp':<20} {'Articles':>10}  Command")
    click.echo("-" * 80)

    for search in searches:
        timestamp = search.timestamp[:19].replace("T", " ")
        fetched = search.statistics.get("fetched", 0)
        valid = search.statistics.get("valid", 0)
        cmd = search.command
        if len(cmd) > 40:
            cmd = cmd[:37] + "..."
        click.echo(f"{search.id:<12} {timestamp:<20} {fetched:>5}/{valid:<4} {cmd}")


@workspace.command(name="clear")
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--keep-history",
    is_flag=True,
    help="Keep search history but clear files",
)
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Skip confirmation prompt",
)
def workspace_clear(path: str, keep_history: bool, force: bool) -> None:
    """Clear workspace contents.

    Removes all JATS files and resets the DOI index.
    Optionally keeps search history with --keep-history.

    \b
    Examples:
        text-fetch workspace clear ./my-corpus --keep-history
        text-fetch workspace clear ./my-corpus --force
    """
    from .workspace import Workspace, WorkspaceError

    try:
        ws = Workspace.load(path)
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e

    stats = ws.get_statistics()

    if not force:
        click.echo(f"Workspace: {stats['name']}")
        click.echo(f"  Valid articles: {stats['total_valid']}")
        click.echo(f"  Incomplete articles: {stats['total_incomplete']}")
        click.echo(f"  Searches: {stats['total_searches']}")
        if keep_history:
            click.echo("\nThis will clear all files but keep search history.")
        else:
            click.echo("\nThis will clear ALL contents including search history.")

        if not click.confirm("Proceed?"):
            click.echo("Aborted.")
            return

    ws.clear(keep_history=keep_history)

    click.echo(f"Cleared workspace: {ws.path}")
    if keep_history:
        click.echo("  Search history preserved.")
    else:
        click.echo("  All contents removed.")


if __name__ == "__main__":
    cli()
