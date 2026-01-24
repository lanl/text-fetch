"""Unified fetch command."""

from __future__ import annotations

from pathlib import Path

import click

from ..config import get_grobid_url, get_ncbi_api_key, get_ncbi_email
from ._common import handle_tarball_creation


@click.command(name="fetch")
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
@click.option(
    "--resume",
    is_flag=True,
    help="Resume from checkpoints if interrupted",
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
    resume: bool,
    update: bool,
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
        text-fetch fetch --config-file input/search.json \\
            --no-dedupe --out ./output

        # Add to workspace for deduplication
        text-fetch fetch --config-file input/search.json \\
            --workspace ./my-corpus --out ./output

        # Re-run fetch from existing tarball (reproducibility)
        text-fetch fetch --from-tarball corpus.tar.gz --out ./updated --tarball

        # Resume interrupted fetch
        text-fetch fetch --config-file search.json --out ./output --resume

        # Update mode: fetch only new papers since last fetch
        text-fetch fetch --config-file search.json --workspace ./corpus --update
    """
    import contextlib
    import logging
    import sys

    from ..common import extract_search_config_from_tarball
    from ..fetch import unified_fetch
    from ..query import SearchConfig, SearchConfigError
    from ..workspace import Workspace

    # Validate options
    if not config_file and not from_tarball:
        raise click.UsageError("Either --config-file or --from-tarball is required")
    if config_file and from_tarball:
        raise click.UsageError("Cannot use both --config-file and --from-tarball")
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    app_config = ctx.obj["config"]

    # Resolve settings
    resolved_email = None
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
    needs_email = "pmc" in effective_sources and not resolved_email
    if needs_email:
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
            resume=resume,
            update=update,
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
        dupe_cnt = stats.get("duplicates_skipped", 0)
        click.echo(f"Duplicates skipped: {dupe_cnt:,}")
    else:
        click.echo(f"Duplicates removed: {stats['duplicates_removed']:,}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch fetch --config-file {config_source} --out {out}"
        handle_tarball_creation(
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
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
