"""PubMed Central commands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import click

from ..config import get_ncbi_api_key, get_ncbi_email
from ._common import handle_tarball_creation

if TYPE_CHECKING:
    pass


@click.group()
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
def pmc_fetch(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    out: str,
    workspace: str | None,
    email: str | None,
    api_key: str | None,
    resume: bool,
    update: bool,
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
        text-fetch pmc fetch --query "hlavacek ws[au]" \\
            --workspace ./my-corpus --out ./output

        # Resume interrupted fetch
        text-fetch pmc fetch --query "hlavacek ws[au]" --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch pmc fetch --query "hlavacek ws[au]" \\
            --workspace ./my-corpus --update
    """
    import logging
    import sys

    from ..pmc import fetch_pmc
    from ..query import SearchConfig, SearchConfigError
    from ..workspace import Workspace

    if not config_file and not query:
        raise click.UsageError("Either --config-file or --query is required")

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

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
            resume=resume,
            update=update,
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
    if stats.get("resumed_from"):
        click.echo(f"  Resumed from: {stats['resumed_from']:,} completed")
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
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
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

    from ..pmc_oa import PMCOAClient, read_sync_manifest

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
                    remaining = len(results["missing_files"]) - 10
                    click.echo(f"  ... and {remaining} more")
            return

        # Fetch file lists to show stats
        click.echo("\nFetching remote file lists...")
        all_entries = client.get_all_entries()

        if not all_entries:
            click.echo("Error: Could not fetch file lists from PMC")
            ctx.exit(1)

        # Calculate what needs to be downloaded (always incremental if we have
        # files)
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
    from ..pmc_oa import PMCOAClient

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
    for subset_name in status.get("subsets", []):
        count = status["subset_counts"].get(subset_name, 0)
        size_bytes = status["subset_bytes"].get(subset_name, 0)
        size_gb = size_bytes / (1024 * 1024 * 1024)
        click.echo(f"  {subset_name}: {count:,} files ({size_gb:.1f} GB)")

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

    from ..pmc_oa import import_existing

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
