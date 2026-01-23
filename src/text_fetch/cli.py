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
    """Process PDF files in a directory via GROBID."""
    import csv
    from pathlib import Path

    from text_fetch.grobid import get_default_xslt_path
    from text_fetch.pdf import find_pdfs, process_pdf_batch

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

    # Count PDFs
    pdfs = find_pdfs(pdf_dir)
    if not pdfs:
        click.echo("No PDF files found.")
        return

    click.echo(f"Found {len(pdfs)} PDF files in {pdf_dir}")
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

    # Summary
    click.echo("\nProcessing complete:")
    click.echo(f"  Total: {result['total']}")
    click.echo(f"  Valid: {result['valid']}")
    click.echo(f"  Incomplete: {result['incomplete']}")
    click.echo(f"  Errors: {result['errors']}")

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

    # Create tarball if requested
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
    """
    import logging

    from .pmc import fetch_pmc
    from .query import SearchConfig, SearchConfigError

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
            verbose=verbose,
            progress_callback=progress_callback,
        )

    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Print summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  PMIDs found: {stats['pmids_found']:,}")
    click.echo(f"  PMC full-text available: {stats['pmcids_available']:,}")
    click.echo(f"  Downloaded: {stats['fetched']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Skipped (duplicates): {stats['skipped']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")
    click.echo(f"Manifest: {out}/manifest.json")

    # Create tarball if requested
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


@pmc.command(name="sync")
@click.option(
    "--storage",
    required=True,
    type=click.Path(),
    help="Storage directory for PMC OA corpus",
)
@click.option(
    "--update",
    is_flag=True,
    help="Only download new/updated files (incremental update)",
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
    update: bool,
    subset: tuple[str, ...],
    max_files: int | None,
    yes: bool,
    verbose: bool,
) -> None:
    """Sync PMC Open Access corpus to local storage.

    Downloads tar.gz files from the PMC Open Access subset.
    Use --update for incremental updates after initial sync.

    \b
    Examples:
        # Initial sync (downloads entire corpus ~400GB)
        text-fetch pmc sync --storage /Volumes/External/pmc-oa

        # Incremental update
        text-fetch pmc sync --storage /Volumes/External/pmc-oa --update

        # Sync only commercial-use subset
        text-fetch pmc sync --storage ./pmc-oa --subset oa_comm
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
    click.echo(f"Mode: {'incremental update' if update else 'full sync'}")

    # Check existing manifest
    manifest = read_sync_manifest(storage)
    if manifest.entries:
        click.echo(f"Existing manifest: {len(manifest.entries)} files")
        if manifest.last_sync:
            click.echo(f"Last sync: {manifest.last_sync}")

    with PMCOAClient(storage, subsets=subsets) as client:
        # Fetch file lists to show stats
        click.echo("\nFetching file lists...")
        all_entries = client.get_all_entries()

        if not all_entries:
            click.echo("Error: Could not fetch file lists from PMC")
            ctx.exit(1)

        # Calculate what needs to be downloaded
        if update and manifest.entries:
            to_download = client.get_updates(manifest, all_entries)
        else:
            to_download = all_entries

        if max_files:
            to_download = to_download[:max_files]

        # Calculate estimated size (rough estimate: ~5MB average per file)
        estimated_size_mb = len(to_download) * 5

        click.echo(f"\nRemote files: {len(all_entries):,}")
        click.echo(f"Files to download: {len(to_download):,}")
        click.echo(f"Estimated size: ~{estimated_size_mb:,} MB")

        if not to_download:
            click.echo("\nNothing to download. Already up to date.")
            return

        # Confirmation prompt
        if not yes:
            if len(to_download) > 1000:
                click.echo(
                    f"\nWarning: This will download {len(to_download):,} files "
                    f"(~{estimated_size_mb / 1024:.1f} GB)."
                )
            if not click.confirm("\nProceed with download?"):
                click.echo("Aborted.")
                ctx.exit(0)

        # Progress bar
        with click.progressbar(
            length=len(to_download),
            label="Downloading",
            show_pos=True,
            show_percent=True,
        ) as bar:

            def progress_callback(accession_id: str, current: int, total: int) -> None:
                bar.update(1)

            stats = client.sync(
                update_only=update,
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
    """
    import logging

    from .arxiv import fetch_arxiv
    from .query import SearchConfig, SearchConfigError

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

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  PDFs downloaded: {stats['pdfs_downloaded']:,}")
    click.echo(f"  Converted: {stats['converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
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
    """
    import logging

    from .biorxiv import fetch_biorxiv

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL (fallback): {resolved_grobid}")

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
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Direct JATS: {stats['jats_direct']:,}")
    click.echo(f"  Via GROBID: {stats['pdf_converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
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
    """
    import logging

    from .biorxiv import fetch_medrxiv

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL (fallback): {resolved_grobid}")

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
            grobid_url=resolved_grobid,
            max_results=max_results,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Direct JATS: {stats['jats_direct']:,}")
    click.echo(f"  Via GROBID: {stats['pdf_converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
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
    """
    import logging

    from .chemrxiv import fetch_chemrxiv, get_category_ids

    config = ctx.obj["config"]
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        logging.basicConfig(level=logging.DEBUG)
        click.echo(f"GROBID URL: {resolved_grobid}")

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

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  PDFs downloaded: {stats['pdfs_downloaded']:,}")
    click.echo(f"  Converted: {stats['converted']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
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
    """
    import logging

    from .europepmc import fetch_europepmc

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

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
            max_results=max_results,
            open_access_only=not include_non_oa,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Summary
    click.echo("\n" + "=" * 50)
    click.echo("Fetch complete!")
    click.echo(f"  Articles found: {stats['articles_found']:,}")
    click.echo(f"  Full-text available: {stats['full_text_available']:,}")
    click.echo(f"  Downloaded: {stats['fetched']:,}")
    click.echo(f"    Valid: {stats['valid']:,}")
    click.echo(f"    Incomplete: {stats['incomplete']:,}")
    click.echo(f"  Errors: {stats['errors']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
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


@cli.command(name="fetch")
@click.option(
    "--config-file",
    type=click.Path(exists=True),
    required=True,
    help="JSON search configuration file",
)
@click.option("--out", required=True, help="Output directory")
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
    config_file: str,
    out: str,
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
    """
    import logging

    from .fetch import unified_fetch
    from .query import SearchConfig, SearchConfigError

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

    # Load search config
    try:
        search_config = SearchConfig.from_json(config_file)
    except SearchConfigError as e:
        raise click.UsageError(f"Invalid config: {e}") from e

    # Override sources if specified
    if sources:
        search_config.sources = sources.split(",")

    # Override deduplication
    if no_dedupe:
        search_config.deduplicate_by_doi = False

    # Validate email if pmc source is used
    effective_sources = search_config.sources or ["pmc"]
    if "pmc" in effective_sources and not resolved_email:
        raise click.UsageError(
            "NCBI email required for PMC source. "
            "Set via --email, NCBI_EMAIL env var, or config file."
        )

    # Show config summary
    click.echo(f"Config: {config_file}")
    click.echo(f"Sources: {', '.join(effective_sources)}")
    click.echo(f"Max per source: {search_config.max_results_per_source}")
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
            email=resolved_email,
            api_key=resolved_api_key,
            grobid_url=resolved_grobid,
            verbose=verbose,
            progress_callback=progress_callback,
        )
    finally:
        if progress_bar[0] is not None:
            progress_bar[0].__exit__(None, None, None)

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
    click.echo(f"Duplicates removed: {stats['duplicates_removed']:,}")
    click.echo(f"\nOutput: {out}/")

    # Create tarball if requested
    cmd = f"text-fetch fetch --config-file {config_file} --out {out}"
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
