"""Europe PMC commands."""

from __future__ import annotations

from pathlib import Path

import click

from ._common import handle_tarball_creation


@click.group()
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
        text-fetch europepmc fetch --author "perelson" \\
            --date-from 2020-01-01 --out ./output

        # Raw Lucene query
        text-fetch europepmc fetch \\
            --query 'AUTH:"hlavacek" AND TITLE:modeling' --out ./output

        # Specific PMC IDs
        text-fetch europepmc fetch --pmcid PMC123456 --pmcid PMC789012 \\
            --out ./output

        # Add to workspace for deduplication
        text-fetch europepmc fetch --author "hlavacek ws" \\
            --workspace ./my-corpus --out ./output

        # Resume interrupted fetch
        text-fetch europepmc fetch --author "hlavacek ws" \\
            --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch europepmc fetch --author "hlavacek ws" \\
            --workspace ./my-corpus --update
    """
    import logging
    import sys

    from ..europepmc import fetch_europepmc
    from ..workspace import Workspace

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
        auth = author or ""
        cmd = f"text-fetch europepmc fetch --author '{auth}' --out {out}"
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
