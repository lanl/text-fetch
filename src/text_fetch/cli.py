#!/usr/bin/env python3
"""text-fetch CLI entry point.

This module is a thin dispatcher. Business logic lives in text_fetch/*.
"""

from __future__ import annotations

import click

from . import __version__
from .config import (
    get_grobid_url,
    get_ncbi_api_key,
    get_ncbi_email,
    load_config,
)


@click.group()
@click.version_option(version=__version__, prog_name="text-fetch")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Acquire scientific literature for RAG pipelines."""
    # Load config once and store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@cli.command()
@click.argument("pdf_root", type=click.Path(exists=True))
@click.option("--out", required=True, help="Output CSV path")
@click.option("--grobid-url", default=None, help="GROBID service URL")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pdf(
    ctx: click.Context,
    pdf_root: str,
    out: str,
    grobid_url: str | None,
    verbose: bool,
) -> None:
    """Process PDFs via GROBID and emit CSV index."""
    config = ctx.obj["config"]
    resolved_grobid_url = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        click.echo(f"Using GROBID at: {resolved_grobid_url}")

    click.echo(f"PDF processing not yet implemented. Root: {pdf_root}")


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
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc_fetch(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    out: str,
    email: str | None,
    api_key: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from PubMed Central via E-utilities."""
    if not config_file and not query:
        raise click.UsageError("Either --config-file or --query is required")

    config = ctx.obj["config"]

    # Resolve settings with priority: CLI > env > config file
    try:
        resolved_email = get_ncbi_email(cli_value=email, config=config)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=config)

    if verbose:
        click.echo(f"Using NCBI email: {resolved_email}")
        if resolved_api_key:
            click.echo("Using NCBI API key: [configured]")
        else:
            click.echo("No NCBI API key configured (using lower rate limit)")
        if config.config_path:
            click.echo(f"Config loaded from: {config.config_path}")

    click.echo("PMC fetching not yet implemented.")


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


if __name__ == "__main__":
    cli()
