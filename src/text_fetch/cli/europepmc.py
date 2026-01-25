"""Europe PMC commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import click

from ._common import handle_tarball_creation

if TYPE_CHECKING:
    from ..europepmc import ExpansionResult


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
@click.option(
    "--max-results", default=None, type=int, help="Maximum results (default: unlimited)"
)
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
# Expansion options
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
    help="Expand both directions (shorthand for --expand-references --expand-citations)",
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
    expand_references: bool,
    expand_citations: bool,
    expand: bool,
    expansion_depth: int,
    max_expansion: int,
    dry_run: bool,
    yes: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from Europe PMC with optional citation expansion.

    Downloads native JATS XML (no GROBID required).

    \b
    Examples:
        # Search by author
        text-fetch europepmc fetch --author "hlavacek ws" --out ./output

        # Search with keywords
        text-fetch europepmc fetch --keyword "systems biology" --out ./output

        # Expand by following references (papers seeds cite)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand-references --out ./output

        # Expand by following citations (papers citing seeds)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand-citations --out ./output

        # Both directions
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --out ./output

        # Preview expansion (dry-run)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --dry-run --out ./output

        # Custom expansion options
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --expansion-depth 2 --max-expansion 10000 --out ./output

        # Add to workspace for deduplication
        text-fetch europepmc fetch --author "hlavacek ws" \\
            --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from ..europepmc import (
        EuropePMCClient,
        expand_papers,
        fetch_europepmc,
    )
    from ..workspace import Workspace

    # Validate update flag
    if update and not workspace:
        raise click.UsageError("--update requires --workspace")

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    # Resolve expansion flags
    do_expand_refs = expand_references or expand
    do_expand_cites = expand_citations or expand

    # Resolve max_expansion (0 means unlimited)
    effective_max_expansion = max_expansion if max_expansion > 0 else None

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Progress bar for seed fetch
    progress_bar = None

    def progress_callback(pmcid_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Fetching seed articles",
                show_pos=True,
                show_percent=True,
            )
            progress_bar.__enter__()
        progress_bar.update(1)

    try:
        # First, fetch seed papers
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

    # If expansion requested and we have seeds, expand
    expansion_result = None
    if (do_expand_refs or do_expand_cites) and stats["full_text_available"] > 0:
        click.echo("\n" + "=" * 50)
        click.echo("Citation Expansion")
        click.echo("=" * 50)

        client = EuropePMCClient()

        # Get seed articles for expansion
        # FIX: If --pmcid was provided, use those directly as seeds
        if pmcid:
            # Direct PMCID lookup for seeds
            click.echo(f"Using {len(pmcid)} provided PMCIDs as expansion seeds...")
            seeds = []
            for pmcid_val in pmcid:
                article = client.get_by_pmcid(pmcid_val)
                if article and article.pmcid and article.has_full_text:
                    seeds.append(article)
        else:
            # Build query to get seed articles
            if query:
                seed_query = query
            else:
                seed_query = EuropePMCClient.build_query(
                    author=author,
                    keywords=list(keyword) if keyword else None,
                    date_from=date_from,
                    date_to=date_to,
                    open_access_only=not include_non_oa,
                    has_full_text=True,
                )

            seeds = list(client.iter_search(seed_query, max_results=max_results))
            seeds = [s for s in seeds if s.pmcid and s.has_full_text]

        if not seeds:
            click.echo("No seed papers with PMCID available for expansion.")
        else:
            click.echo(f"Expanding from {len(seeds)} seed papers...")
            click.echo(
                f"  Directions: "
                f"{'references ' if do_expand_refs else ''}"
                f"{'citations' if do_expand_cites else ''}"
            )
            click.echo(f"  Depth: {expansion_depth}")
            if effective_max_expansion:
                click.echo(f"  Max expansion: {effective_max_expansion:,}")

            # Dry-run mode: preview and prompt
            if dry_run:
                click.echo("\nDry-run mode: gathering expansion statistics...")

                # Expansion progress callback
                def expansion_progress(stage: str, current: int, total: int) -> None:
                    if stage == "expanding":
                        click.echo(f"  Checking seed {current}/{total}...", nl=False)
                        click.echo("\r", nl=False)

                expansion_result = expand_papers(
                    client=client,
                    seeds=seeds,
                    expand_references=do_expand_refs,
                    expand_citations=do_expand_cites,
                    depth=expansion_depth,
                    max_expansion=effective_max_expansion,
                    progress_callback=expansion_progress,
                )

                # Display dry-run report
                _display_expansion_report(expansion_result)

                # Prompt for confirmation
                if not yes and not click.confirm("\nContinue with expansion?"):
                    click.echo("Expansion cancelled.")
                    expansion_result = None
                # If confirmed, expansion_result already has the data

            else:
                # Normal mode: expand directly
                click.echo("\nExpanding...")

                def expansion_progress(stage: str, current: int, total: int) -> None:
                    click.echo(
                        f"\r  Processing seed {current}/{total}...",
                        nl=False,
                    )

                expansion_result = expand_papers(
                    client=client,
                    seeds=seeds,
                    expand_references=do_expand_refs,
                    expand_citations=do_expand_cites,
                    depth=expansion_depth,
                    max_expansion=effective_max_expansion,
                    progress_callback=expansion_progress,
                )
                click.echo()  # newline after progress

            # Save expansion manifest if we have results
            if expansion_result and expansion_result.total_expanded > 0:
                output_path = Path(out)
                manifest_path = output_path / "expansion_manifest.json"
                manifest_data = {
                    "expansion_config": expansion_result.config,
                    "seed_coverage": expansion_result.seed_coverage,
                    "expansion_stats": expansion_result.expansion_stats,
                    "id_issues": {
                        "no_id_count": len(expansion_result.id_issues.get("no_id", [])),
                        "lookup_failed_count": len(
                            expansion_result.id_issues.get("lookup_failed", [])
                        ),
                    },
                    "layers": expansion_result.layers,
                }
                manifest_path.write_text(json.dumps(manifest_data, indent=2))
                click.echo(f"\nExpansion manifest saved: {manifest_path}")

                # FIX: Actually fetch the expanded papers!
                # Extract PMCIDs from expanded papers
                expanded_pmcids: list[str] = []
                for papers in expansion_result.expanded_papers.values():
                    for paper in papers:
                        raw_pmcid = paper.get("pmcid")
                        if raw_pmcid is None:
                            continue
                        # Normalize PMCID
                        pmcid_norm = str(raw_pmcid).upper()
                        if not pmcid_norm.startswith("PMC"):
                            pmcid_norm = f"PMC{pmcid_norm}"
                        expanded_pmcids.append(pmcid_norm)

                if expanded_pmcids:
                    click.echo(f"\nFetching {len(expanded_pmcids)} expanded papers...")

                    # Progress bar for expanded fetch
                    exp_progress_bar = None

                    def exp_progress_cb(
                        pmcid_str: str, current: int, total: int
                    ) -> None:
                        nonlocal exp_progress_bar
                        if exp_progress_bar is None:
                            exp_progress_bar = click.progressbar(
                                length=total,
                                label="Fetching expanded articles",
                                show_pos=True,
                                show_percent=True,
                            )
                            exp_progress_bar.__enter__()
                        exp_progress_bar.update(1)

                    try:
                        exp_stats = fetch_europepmc(
                            pmcids=expanded_pmcids,
                            output_dir=out,
                            workspace=ws,
                            open_access_only=not include_non_oa,
                            verbose=verbose,
                            progress_callback=exp_progress_cb,
                        )
                    finally:
                        if exp_progress_bar is not None:
                            exp_progress_bar.__exit__(None, None, None)

                    # Update main stats with expansion stats
                    stats["expanded_fetched"] = exp_stats["fetched"]
                    stats["expanded_valid"] = exp_stats["valid"]
                    stats["expanded_errors"] = exp_stats["errors"]
                    stats["expanded_duplicates"] = exp_stats.get(
                        "duplicates_skipped", 0
                    )

                    click.echo("\nExpanded papers downloaded:")
                    click.echo(f"  Fetched: {exp_stats['fetched']:,}")
                    click.echo(f"  Valid: {exp_stats['valid']:,}")
                    click.echo(f"  Errors: {exp_stats['errors']:,}")
                    if exp_stats.get("duplicates_skipped"):
                        click.echo(
                            f"  Duplicates skipped: "
                            f"{exp_stats['duplicates_skipped']:,}"
                        )

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
            "expand_references": do_expand_refs,
            "expand_citations": do_expand_cites,
            "expansion_depth": expansion_depth,
            "max_expansion": max_expansion,
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

    # Expansion summary
    if expansion_result:
        click.echo("\nExpansion:")
        click.echo(f"  Total expanded: {expansion_result.total_expanded:,}")
        click.echo(
            f"  References found: "
            f"{expansion_result.expansion_stats.get('references_found', 0):,}"
        )
        click.echo(
            f"  Citations found: "
            f"{expansion_result.expansion_stats.get('citations_found', 0):,}"
        )
        click.echo(
            f"  Duplicates skipped: "
            f"{expansion_result.expansion_stats.get('duplicates_skipped', 0):,}"
        )

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
            "Note: Use 'text-fetch workspace build' to create tarball from workspace"
        )


def _display_expansion_report(result: ExpansionResult) -> None:
    """Display dry-run expansion report."""

    click.echo("\n" + "=" * 60)
    click.echo("EXPANSION DRY-RUN REPORT")
    click.echo("=" * 60)

    # Seed coverage
    sc = result.seed_coverage
    click.echo("\nSEED COVERAGE:")
    click.echo(f"  Total seeds found:        {sc.get('total_seeds', 0):>6}")
    click.echo(
        f"  Seeds with citations:     {sc.get('seeds_with_citations', 0):>6} "
        f"({sc.get('citation_coverage_pct', 0):.0f}%)"
    )
    click.echo(
        f"  Seeds with references:    {sc.get('seeds_with_references', 0):>6} "
        f"({sc.get('reference_coverage_pct', 0):.0f}%)"
    )
    click.echo(f"  Seeds with both:          {sc.get('seeds_with_both', 0):>6}")
    click.echo(
        f"  Seeds with neither:       {sc.get('seeds_with_neither', 0):>6} "
        "← may be too new or non-PMC"
    )

    # Expansion stats
    es = result.expansion_stats
    click.echo("\nEXPANSION RESULTS:")
    click.echo(f"  References found:         {es.get('references_found', 0):>6}")
    click.echo(f"  Citations found:          {es.get('citations_found', 0):>6}")
    click.echo(f"  Total unique expanded:    {es.get('total_unique', 0):>6}")
    click.echo(f"  Duplicates skipped:       {es.get('duplicates_skipped', 0):>6}")

    # ID issues
    no_id_count = len(result.id_issues.get("no_id", []))
    lookup_failed = len(result.id_issues.get("lookup_failed", []))
    if no_id_count > 0 or lookup_failed > 0:
        click.echo("\nID ISSUES:")
        if no_id_count > 0:
            click.echo(f"  ⚠ {no_id_count} papers missing usable ID")
        if lookup_failed > 0:
            click.echo(f"  ⚠ {lookup_failed} API lookups failed")

    # Layers
    click.echo("\nLAYERS:")
    for layer in result.layers:
        depth = layer.get("depth", 0)
        ltype = layer.get("type", "")
        count = layer.get("count", 0)
        click.echo(f"  Depth {depth} ({ltype}): {count:,} papers")

    click.echo("=" * 60)
