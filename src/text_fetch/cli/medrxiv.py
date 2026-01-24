"""medRxiv preprint commands."""

from __future__ import annotations

from pathlib import Path

import click

from ..config import get_grobid_url
from ._common import handle_tarball_creation


@click.group()
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
    resume: bool,
    update: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch preprints from medRxiv.

    Downloads JATS XML directly when available, falls back to PDF→GROBID.

    \b
    Examples:
        # Recent epidemiology preprints
        text-fetch medrxiv fetch --days 30 --category epidemiology \\
            --out ./output

        # Date range
        text-fetch medrxiv fetch --start-date 2024-01-01 \\
            --end-date 2024-01-31 --out ./output

        # Add to workspace for deduplication
        text-fetch medrxiv fetch --days 30 --workspace ./my-corpus \\
            --out ./output

        # Resume interrupted fetch
        text-fetch medrxiv fetch --days 30 --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch medrxiv fetch --days 30 --workspace ./my-corpus --update
    """
    import logging
    import sys

    from ..biorxiv import fetch_medrxiv
    from ..workspace import Workspace

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

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
            resume=resume,
            update=update,
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
        cmd = f"text-fetch medrxiv fetch --days {days or ''} --out {out}"
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
