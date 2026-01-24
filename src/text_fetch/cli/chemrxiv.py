"""ChemRxiv preprint commands."""

from __future__ import annotations

from pathlib import Path

import click

from ..config import get_grobid_url
from ._common import handle_tarball_creation


@click.group()
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
    resume: bool,
    update: bool,
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
        text-fetch chemrxiv fetch --term "catalysis" \\
            --workspace ./my-corpus --out ./output

        # Resume interrupted fetch
        text-fetch chemrxiv fetch --term "catalysis" --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch chemrxiv fetch --term "catalysis" \\
            --workspace ./my-corpus --update
    """
    import logging
    import sys

    from ..chemrxiv import fetch_chemrxiv, get_category_ids
    from ..workspace import Workspace

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

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
            resume=resume,
            update=update,
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
        cmd = f"text-fetch chemrxiv fetch --term '{term or ''}' --out {out}"
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
