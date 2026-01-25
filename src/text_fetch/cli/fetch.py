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
    "--max-results",
    default=None,
    help="Max results per source (number or 'all' for unlimited)",
)
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
@click.option(
    "--expand-references",
    is_flag=True,
    help="Expand by following references (papers seeds cite)",
)
@click.option(
    "--expand-citations",
    is_flag=True,
    help="Expand by following citations (papers citing seeds)",
)
@click.option(
    "--expand",
    is_flag=True,
    help="Expand both directions (--expand-references + --expand-citations)",
)
@click.option(
    "--expansion-depth",
    type=int,
    default=1,
    help="Expansion depth / hops (default: 1)",
)
@click.option(
    "--max-expansion",
    type=int,
    default=0,
    help="Max expanded papers (0=unlimited, default: 0)",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview expansion stats, prompt before proceeding",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Auto-confirm dry-run prompt",
)
@click.option(
    "--from-plan",
    type=click.Path(exists=True),
    help="Resume from saved expansion plan (skip expansion analysis)",
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
    max_results: str | None,
    resume: bool,
    update: bool,
    expand_references: bool,
    expand_citations: bool,
    expand: bool,
    expansion_depth: int,
    max_expansion: int,
    dry_run: bool,
    yes: bool,
    from_plan: str | None,
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

        # Preview expansion (dry-run)
        text-fetch fetch --config-file ebola.json --sources europepmc \\
            --expand --dry-run --out ./output

        # Fetch with citation expansion (europepmc only)
        text-fetch fetch --config-file ebola.json --sources europepmc \\
            --expand --out ./output

        # Expand references only with depth 2
        text-fetch fetch --config-file search.json --sources europepmc \\
            --expand-references --expansion-depth 2 --out ./output
    """
    import contextlib
    import logging
    import sys

    from ..common import extract_search_config_from_tarball
    from ..fetch import unified_fetch
    from ..query import SearchConfig, SearchConfigError
    from ..workspace import Workspace

    # Handle --from-plan mode (different validation)
    if from_plan:
        # Load plan and run fetch directly
        _handle_from_plan(
            from_plan=from_plan,
            out=out,
            workspace=workspace,
            email=email,
            api_key=api_key,
            max_expansion=max_expansion,
            tarball=tarball,
            tarball_name=tarball_name,
            verbose=verbose,
            yes=yes,
            ctx=ctx,
        )
        return

    # Validate options for normal mode
    if not config_file and not from_tarball:
        raise click.UsageError(
            "Either --config-file, --from-tarball, or --from-plan is required"
        )
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

    # Override max_results if specified
    if max_results is not None:
        if max_results.lower() == "all":
            # None means unlimited in the fetch functions
            search_config.max_results_per_source = 0  # 0 = unlimited
        else:
            try:
                search_config.max_results_per_source = int(max_results)
            except ValueError:
                raise click.UsageError(
                    f"Invalid --max-results value: {max_results}. "
                    "Use a number or 'all' for unlimited."
                ) from None

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

    # Resolve expansion flags
    do_expand_refs = expand_references or expand
    do_expand_cites = expand_citations or expand
    has_expansion = do_expand_refs or do_expand_cites
    effective_max_expansion = max_expansion if max_expansion > 0 else None

    # Show config summary
    click.echo(f"Config: {config_source}")
    click.echo(f"Sources: {', '.join(effective_sources)}")
    max_display = search_config.max_results_per_source or "unlimited"
    click.echo(f"Max per source: {max_display}")
    if ws:
        click.echo(f"Workspace: {ws.path} (auto-deduplication)")
    else:
        click.echo(f"Deduplicate: {search_config.deduplicate_by_doi}")

    # Show expansion settings if enabled
    if has_expansion:
        exp_dirs = []
        if do_expand_refs:
            exp_dirs.append("references")
        if do_expand_cites:
            exp_dirs.append("citations")
        click.echo(f"Expansion: {' + '.join(exp_dirs)} (depth {expansion_depth})")
        if effective_max_expansion:
            click.echo(f"Max expansion: {effective_max_expansion}")
        if dry_run:
            click.echo("Mode: DRY-RUN (preview only)")
    click.echo()

    # Progress tracking
    current_source: list[str | None] = [None]
    progress_bar: list[click.progressbar | None] = [None]

    # Track current phase for label changes
    current_phase: list[str] = [""]
    last_search_count: list[int] = [0]

    def progress_callback(
        source: str, article_id: str, current: int, total: int
    ) -> None:
        # Determine current phase from article_id prefix
        if article_id.startswith("search:"):
            phase = "search"
        elif article_id.startswith("expand:"):
            phase = "expand"
        else:
            phase = "fetch"

        # For search phase, use simple text output with clear labeling
        if phase == "search":
            # Only update if count changed
            if current != last_search_count[0]:
                last_search_count[0] = current
                # Overwrite the same line with \r
                click.echo(
                    f"\rRetrieving {source} metadata: {current:,} / {total:,}",
                    nl=False,
                )
            return

        # Create new progress bar if source or phase changed
        phase_key = f"{source}:{phase}"
        if phase_key != current_phase[0]:
            # End search line if we were searching
            if current_phase[0].endswith(":search"):
                click.echo()  # newline after search status
            if progress_bar[0] is not None:
                progress_bar[0].__exit__(None, None, None)
            current_phase[0] = phase_key
            current_source[0] = source

            # Set appropriate label
            if phase == "expand":
                label = f"Expanding {source} (ETA shown)"
            else:
                label = f"Fetching {source} (ETA shown)"

            progress_bar[0] = click.progressbar(
                length=total,
                label=label,
                show_pos=True,
                show_percent=True,
            )
            progress_bar[0].__enter__()

        if progress_bar[0] is not None:
            # Update length if total changed
            if hasattr(progress_bar[0], "length") and progress_bar[0].length < total:
                progress_bar[0].length = total
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
            expand_references=do_expand_refs,
            expand_citations=do_expand_cites,
            expansion_depth=expansion_depth,
            max_expansion=effective_max_expansion,
            dry_run=dry_run,
        )
    finally:
        if progress_bar[0] is not None:
            progress_bar[0].__exit__(None, None, None)

    # Handle dry-run output
    if stats.get("dry_run"):
        _display_dry_run_report(
            stats,
            output_dir=out,
            email_configured=bool(resolved_email),
            api_key_configured=bool(resolved_api_key),
        )
        if not yes and not click.confirm("\nContinue with fetch?"):
            click.echo("Fetch cancelled.")
            return
        # Re-run without dry_run
        click.echo("\nProceeding with fetch...")
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
                expand_references=do_expand_refs,
                expand_citations=do_expand_cites,
                expansion_depth=expansion_depth,
                max_expansion=effective_max_expansion,
                dry_run=False,
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


def _display_dry_run_report(
    stats: dict,
    output_dir: str,
    email_configured: bool,
    api_key_configured: bool,
) -> None:
    """Display dry-run expansion report."""
    click.echo("\n" + "=" * 60)
    click.echo("EXPANSION DRY-RUN PREVIEW")
    click.echo("=" * 60)

    # Output configuration
    click.echo("\nOUTPUT")
    click.echo(f"  Directory: {output_dir}")
    email_status = "configured ✓" if email_configured else "NOT SET ✗"
    api_status = "configured ✓" if api_key_configured else "not set"
    click.echo(f"  NCBI Email: {email_status}")
    click.echo(f"  NCBI API Key: {api_status}")

    expansion = stats.get("expansion_result", {})
    seed_stats = expansion.get("seed_stats", {})
    seed_coverage = expansion.get("seed_coverage", {})
    exp_stats = expansion.get("expansion_stats", {})
    exp_config = expansion.get("expansion_config", {})

    # Seed paper summary
    click.echo("\nSEED PAPERS")
    click.echo(f"  Query matched: {seed_stats.get('articles_found', 0):,}")
    click.echo(f"  With PMCIDs (downloadable): {seed_stats.get('with_pmcid', 0):,}")

    # Expansion configuration
    click.echo("\nEXPANSION CONFIG")
    if exp_config.get("expand_references"):
        click.echo("  References: YES")
    if exp_config.get("expand_citations"):
        click.echo("  Citations: YES")
    click.echo(f"  Depth: {exp_config.get('depth', 1)}")
    max_exp = exp_config.get("max_expansion")
    click.echo(f"  Max expansion: {max_exp if max_exp else 'unlimited'}")

    # Seed coverage stats
    click.echo("\nSEED COVERAGE")
    total = seed_coverage.get("total_seeds", 0)
    with_refs = seed_coverage.get("seeds_with_references", 0)
    with_cites = seed_coverage.get("seeds_with_citations", 0)
    ref_pct = seed_coverage.get("reference_coverage_pct", 0)
    cite_pct = seed_coverage.get("citation_coverage_pct", 0)

    click.echo(f"  Seeds with references: {with_refs}/{total} ({ref_pct}%)")
    click.echo(f"  Seeds with citations: {with_cites}/{total} ({cite_pct}%)")

    # Expansion results
    click.echo("\nEXPANSION RESULTS")
    refs_found = exp_stats.get("references_found", 0)
    cites_found = exp_stats.get("citations_found", 0)
    total_unique = exp_stats.get("total_unique", 0)
    dupes = exp_stats.get("duplicates_skipped", 0)

    total_raw = refs_found + cites_found
    # Papers without usable IDs or cross-overlaps
    unaccounted = total_raw - total_unique - dupes
    if unaccounted < 0:
        unaccounted = 0

    click.echo(f"  References discovered: {refs_found:,}")
    click.echo(f"  Citations discovered: {cites_found:,}")
    click.echo(f"  Total discovered: {total_raw:,}")
    click.echo(f"  - Duplicates (same paper): {dupes:,}")
    if unaccounted > 0:
        click.echo(f"  - No usable ID: ~{unaccounted:,}")
    click.echo(f"  = Unique expanded: {total_unique:,}")

    # Layer breakdown
    layers = expansion.get("layers", [])
    if layers:
        click.echo("\nLAYERS")
        for layer in layers:
            depth = layer.get("depth", 0)
            ltype = layer.get("type", "unknown")
            count = layer.get("count", 0)
            if depth == 0:
                click.echo(f"  Depth {depth} (seeds): {count:,}")
            else:
                click.echo(f"  Depth {depth} ({ltype}): {count:,}")

    # Show plan save info
    plan_path = expansion.get("plan_saved")
    if plan_path:
        click.echo("\nEXPANSION PLAN SAVED")
        click.echo(f"  Location: {plan_path}")
        click.echo("  To resume later without re-running expansion:")
        click.echo(f"    text-fetch fetch --from-plan {plan_path} --out <dir>")

    click.echo("\n" + "=" * 60)


def _handle_from_plan(
    from_plan: str,
    out: str,
    workspace: str | None,
    email: str | None,
    api_key: str | None,
    max_expansion: int,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
    yes: bool,
    ctx: click.Context,
) -> None:
    """Handle fetch from saved expansion plan."""
    import contextlib
    import logging

    from ..config import get_ncbi_api_key, get_ncbi_email
    from ..fetch import ExpansionPlan, unified_fetch
    from ..workspace import Workspace

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    app_config = ctx.obj["config"]

    # Load expansion plan
    plan_path = Path(from_plan)
    plan = ExpansionPlan.from_json(plan_path)

    # Display plan summary
    click.echo("=" * 60)
    click.echo("LOADING EXPANSION PLAN")
    click.echo("=" * 60)
    click.echo(f"\nPlan file: {from_plan}")
    click.echo(f"Created: {plan.created_at}")
    click.echo(f"text-fetch version: {plan.text_fetch_version}")
    click.echo(f"Config file: {plan.config_file}")
    click.echo(f"Query: {plan.query}")
    click.echo()
    click.echo(f"Seed papers: {len(plan.seed_pmcids):,}")
    click.echo(f"Expanded papers: {len(plan.expanded_pmcids):,}")
    click.echo(f"Total unique: {plan.total_papers:,}")

    # Show expansion config
    exp_cfg = plan.expansion_config
    click.echo("\nOriginal expansion config:")
    if exp_cfg.get("expand_references"):
        click.echo("  References: YES")
    if exp_cfg.get("expand_citations"):
        click.echo("  Citations: YES")
    click.echo(f"  Depth: {exp_cfg.get('depth', 1)}")
    orig_max = exp_cfg.get("max_expansion")
    click.echo(f"  Max expansion: {orig_max if orig_max else 'unlimited'}")

    # Show override if specified
    effective_max = max_expansion if max_expansion > 0 else None
    if effective_max and effective_max < len(plan.expanded_pmcids):
        click.echo()
        click.echo(
            f"Note: --max-expansion {effective_max} will limit "
            f"expanded papers from {len(plan.expanded_pmcids):,} "
            f"to {effective_max:,}"
        )

    click.echo()
    click.echo(f"Output directory: {out}")

    # Confirm unless --yes
    if not yes and not click.confirm("Proceed with fetch?"):
        click.echo("Cancelled.")
        return

    # Resolve settings
    resolved_email = None
    with contextlib.suppress(ValueError):
        resolved_email = get_ncbi_email(cli_value=email, config=app_config)

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=app_config)

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Progress tracking
    progress_bar: list[click.progressbar | None] = [None]
    current_phase: list[str] = [""]

    def progress_callback(
        source: str, article_id: str, current: int, total: int
    ) -> None:
        phase = "fetch"
        phase_key = f"{source}:{phase}"

        if phase_key != current_phase[0]:
            if progress_bar[0] is not None:
                progress_bar[0].__exit__(None, None, None)
            current_phase[0] = phase_key

            progress_bar[0] = click.progressbar(
                length=total,
                label=f"Fetching {source} (ETA shown)",
                show_pos=True,
                show_percent=True,
            )
            progress_bar[0].__enter__()

        if progress_bar[0] is not None:
            if hasattr(progress_bar[0], "length") and progress_bar[0].length < total:
                progress_bar[0].length = total
            progress_bar[0].update(1)

    click.echo()
    try:
        stats = unified_fetch(
            output_dir=out,
            workspace=ws,
            email=resolved_email,
            api_key=resolved_api_key,
            verbose=verbose,
            progress_callback=progress_callback,
            max_expansion=effective_max,
            expansion_plan=plan,
        )
    finally:
        if progress_bar[0] is not None:
            progress_bar[0].__exit__(None, None, None)

    # Summary
    click.echo("\n" + "=" * 60)
    click.echo("Fetch from plan complete!")
    click.echo()
    click.echo(f"Total fetched: {stats['total_fetched']:,}")
    click.echo(f"Total valid: {stats['total_valid']:,}")
    click.echo(f"Total incomplete: {stats.get('total_incomplete', 0):,}")
    click.echo(f"Total errors: {stats.get('total_errors', 0):,}")
    if ws:
        click.echo(f"Duplicates skipped: {stats.get('duplicates_skipped', 0):,}")
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/")

    # Create tarball if requested (only if not using workspace)
    if not ws and tarball:
        handle_tarball_creation(
            output_dir=out,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=stats,
            search_config_dict={"from_plan": from_plan},
            command=f"text-fetch fetch --from-plan {from_plan} --out {out}",
            source="europepmc",
            verbose=verbose,
        )
    elif ws and tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
