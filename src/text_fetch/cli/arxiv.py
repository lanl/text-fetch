"""arXiv preprint commands."""

from __future__ import annotations

from pathlib import Path

import click

from ..config import get_grobid_url
from ._common import handle_tarball_creation


@click.group()
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
def arxiv_fetch(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    categories: tuple[str, ...],
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
        text-fetch arxiv fetch --categories q-bio.MN \\
            --workspace ./my-corpus --out ./output

        # Resume interrupted fetch
        text-fetch arxiv fetch --categories q-bio.MN --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch arxiv fetch --categories q-bio.MN \\
            --workspace ./my-corpus --update
    """
    import logging
    import sys

    from ..arxiv import fetch_arxiv
    from ..query import SearchConfig, SearchConfigError
    from ..workspace import Workspace

    if not config_file and not query and not categories:
        raise click.UsageError(
            "Either --config-file, --query, or --categories required"
        )

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

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
        search_config_dict = search_config.to_dict() if search_config else None
        q = query or arxiv_query
        cmd = f"text-fetch arxiv fetch --query '{q}' --out {out}"
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
