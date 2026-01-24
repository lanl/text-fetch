"""Workspace management commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ..config import get_grobid_url, get_ncbi_api_key, get_ncbi_email


@click.group()
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
    from ..workspace import Workspace, WorkspaceError

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
    from ..workspace import Workspace, WorkspaceError

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
        text-fetch workspace build ./my-corpus --out ./final \\
            --include-incomplete
    """
    from ..common import build_provenance, embed_provenance
    from ..workspace import Workspace, WorkspaceError

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
    from ..workspace import Workspace, WorkspaceError

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


@workspace.command(name="update")
@click.argument("path", type=click.Path(exists=True))
@click.option(
    "--source",
    type=click.Choice(["europepmc", "biorxiv", "medrxiv", "arxiv", "chemrxiv", "pmc"]),
    help="Only update specific source (default: all sources)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be fetched without downloading",
)
@click.option("--grobid-url", help="GROBID service URL (for arxiv, chemrxiv)")
@click.option(
    "--email",
    envvar="NCBI_EMAIL",
    help="NCBI email (required for pmc)",
)
@click.option(
    "--api-key",
    envvar="NCBI_API_KEY",
    help="NCBI API key",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def workspace_update_cmd(
    ctx: click.Context,
    path: str,
    source: str | None,
    dry_run: bool,
    grobid_url: str | None,
    email: str | None,
    api_key: str | None,
    verbose: bool,
) -> None:
    """Re-run workspace searches to fetch new papers.

    Fetches only papers published since the last fetch for each source.

    \b
    Examples:
        # Update all sources
        text-fetch workspace update ./my-corpus

        # Update specific source
        text-fetch workspace update ./my-corpus --source europepmc

        # Show what would be fetched
        text-fetch workspace update ./my-corpus --dry-run
    """
    import contextlib
    import logging

    from ..workspace import Workspace, WorkspaceError

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    try:
        ws = Workspace.load(path)
    except WorkspaceError as e:
        raise click.ClickException(str(e)) from e

    config = ctx.obj["config"]

    # Resolve settings
    resolved_grobid = get_grobid_url(cli_value=grobid_url, config=config)

    resolved_email = None
    with contextlib.suppress(ValueError):
        resolved_email = get_ncbi_email(cli_value=email, config=config)

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=config)

    click.echo(f"Workspace: {ws.manifest.name}")
    click.echo(f"Path: {ws.path}")

    # Get source records
    source_records = ws.manifest.source_records

    if not source_records:
        click.echo("\nNo previous fetches recorded. Nothing to update.")
        click.echo("Run a fetch command with --workspace first.")
        return

    # Filter by source if specified
    sources_to_update = [source] if source else list(source_records.keys())

    click.echo(f"\nSources to update: {', '.join(sources_to_update)}")

    if dry_run:
        click.echo("\n[DRY RUN] Would check for updates from:")
        for src in sources_to_update:
            record = source_records.get(src)
            if record:
                last = record.last_fetch[:10] if record.last_fetch else "never"
                click.echo(f"  {src}: papers since {last}")
            else:
                click.echo(f"  {src}: no previous fetch (full fetch)")
        click.echo("\nRun without --dry-run to fetch updates.")
        return

    # Actually perform updates - per-source tracking
    update_results: dict[str, dict[str, Any]] = {}
    total_new = 0

    for src in sources_to_update:
        record = source_records.get(src)
        if not record:
            click.echo(f"\n{src}: No previous fetch recorded, skipping")
            update_results[src] = {"status": "skipped", "reason": "no previous fetch"}
            continue

        last_str = record.last_fetch[:10] if record.last_fetch else "unknown"
        click.echo(f"\n{src}: Checking for papers since {last_str}...")

        # Get the most recent search config for this source
        searches = ws.get_searches()
        search_config = None
        for search in searches:
            if search.config.get("source") == src:
                search_config = search.config
                break

        if not search_config:
            click.echo("  No previous search config found, skipping")
            update_results[src] = {"status": "skipped", "reason": "no search config"}
            continue

        try:
            stats = _run_source_update(
                src=src,
                search_config=search_config,
                workspace=ws,
                grobid_url=resolved_grobid,
                email=resolved_email,
                api_key=resolved_api_key,
                verbose=verbose,
            )

            new_papers = stats.get("fetched", 0) + stats.get("converted", 0)
            total_new += new_papers
            update_results[src] = {
                "status": "success",
                "fetched": new_papers,
                "valid": stats.get("valid", 0),
                "incomplete": stats.get("incomplete", 0),
                "errors": stats.get("errors", 0),
            }
            click.echo(f"  Fetched {new_papers} new papers")

        except Exception as e:
            click.echo(f"  Error: {e}")
            update_results[src] = {"status": "error", "error": str(e)}

    # Summary
    click.echo(f"\n{'=' * 50}")
    click.echo("Update complete!")
    click.echo()
    click.echo("Per-source results:")
    for src, result in update_results.items():
        if result.get("status") == "success":
            fetched = result.get("fetched", 0)
            valid = result.get("valid", 0)
            click.echo(f"  {src}: {fetched} new ({valid} valid)")
        elif result.get("status") == "skipped":
            click.echo(f"  {src}: skipped - {result.get('reason')}")
        else:
            click.echo(f"  {src}: error - {result.get('error')}")
    click.echo()
    click.echo(f"Total new papers: {total_new}")


def _run_source_update(
    src: str,
    search_config: dict[str, Any],
    workspace: Any,
    grobid_url: str | None,
    email: str | None,
    api_key: str | None,
    verbose: bool,
) -> dict[str, Any]:
    """Run update for a specific source."""
    if src == "europepmc":
        from ..europepmc import fetch_europepmc

        return fetch_europepmc(
            query=search_config.get("query"),
            author=search_config.get("author"),
            keywords=search_config.get("keywords"),
            output_dir=str(workspace.path),
            workspace=workspace,
            max_results=search_config.get("max_results", 100),
            open_access_only=search_config.get("open_access_only", True),
            verbose=verbose,
            update=True,
        )

    elif src == "biorxiv":
        from ..biorxiv import fetch_biorxiv

        return fetch_biorxiv(
            start_date=search_config.get("start_date"),
            end_date=search_config.get("end_date"),
            days=search_config.get("days"),
            category=search_config.get("category"),
            dois=search_config.get("dois"),
            output_dir=str(workspace.path),
            workspace=workspace,
            grobid_url=grobid_url,
            max_results=search_config.get("max_results", 100),
            verbose=verbose,
            update=True,
        )

    elif src == "medrxiv":
        from ..biorxiv import fetch_medrxiv

        return fetch_medrxiv(
            start_date=search_config.get("start_date"),
            end_date=search_config.get("end_date"),
            days=search_config.get("days"),
            category=search_config.get("category"),
            dois=search_config.get("dois"),
            output_dir=str(workspace.path),
            workspace=workspace,
            grobid_url=grobid_url,
            max_results=search_config.get("max_results", 100),
            verbose=verbose,
            update=True,
        )

    elif src == "arxiv":
        from ..arxiv import fetch_arxiv

        if not grobid_url:
            raise ValueError("GROBID URL required for arXiv update")

        return fetch_arxiv(
            query=search_config.get("query"),
            output_dir=str(workspace.path),
            workspace=workspace,
            grobid_url=grobid_url,
            max_results=search_config.get("max_results", 100),
            verbose=verbose,
            update=True,
        )

    elif src == "chemrxiv":
        from ..chemrxiv import fetch_chemrxiv

        if not grobid_url:
            raise ValueError("GROBID URL required for ChemRxiv update")

        return fetch_chemrxiv(
            term=search_config.get("term"),
            category_ids=search_config.get("category_ids"),
            date_from=search_config.get("date_from"),
            date_to=search_config.get("date_to"),
            output_dir=str(workspace.path),
            workspace=workspace,
            grobid_url=grobid_url,
            max_results=search_config.get("max_results", 100),
            verbose=verbose,
            update=True,
        )

    elif src == "pmc":
        from ..pmc import fetch_pmc

        if not email:
            raise ValueError("NCBI email required for PMC update")

        return fetch_pmc(
            query=search_config.get("query"),
            email=email,
            api_key=api_key,
            output_dir=str(workspace.path),
            workspace=workspace,
            verbose=verbose,
            update=True,
        )

    else:
        raise ValueError(f"Unknown source: {src}")


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
    from ..workspace import Workspace, WorkspaceError

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
            msg = "\nThis will clear ALL contents including search history."
            click.echo(msg)

        if not click.confirm("Proceed?"):
            click.echo("Aborted.")
            return

    ws.clear(keep_history=keep_history)

    click.echo(f"Cleared workspace: {ws.path}")
    if keep_history:
        click.echo("  Search history preserved.")
    else:
        click.echo("  All contents removed.")
