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
# NCBI options (required for PMC-source articles)
@click.option(
    "--email",
    type=str,
    default=None,
    envvar="NCBI_EMAIL",
    help="Email for NCBI API (required for PMC-source articles). "
    "Can also be set via NCBI_EMAIL env var.",
)
@click.option(
    "--api-key",
    type=str,
    default=None,
    envvar="NCBI_API_KEY",
    help="NCBI API key for higher rate limits (optional). "
    "Can also be set via NCBI_API_KEY env var.",
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
    email: str | None,
    api_key: str | None,
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

    NOTE: PMC-source articles (SRC:PMC) require --email because Europe PMC
    doesn't host their full-text XML. For these articles, text-fetch
    downloads from NCBI instead.

    \b
    Examples:
        # Search by author (non-PMC sources work without email)
        text-fetch europepmc fetch --author "hlavacek ws" --out ./output

        # Search PMC-source articles (requires email)
        text-fetch europepmc fetch --query "ebolavirus AND SRC:PMC" \\
            --email your@email.com --out ./output

        # Expand by following references (papers seeds cite)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand-references --email your@email.com --out ./output

        # Expand by following citations (papers citing seeds)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand-citations --email your@email.com --out ./output

        # Both directions
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --email your@email.com --out ./output

        # Preview expansion (dry-run)
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --dry-run --out ./output

        # Custom expansion options
        text-fetch europepmc fetch --keyword "ebolavirus vaccine" \\
            --expand --expansion-depth 2 --max-expansion 10000 \\
            --email your@email.com --out ./output

        # Add to workspace for deduplication
        text-fetch europepmc fetch --author "hlavacek ws" \\
            --workspace ./my-corpus --out ./output
    """
    import logging
    import sys

    from ..config import get_ncbi_api_key, get_setting, load_config
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

    # Load config from text-fetch.toml and resolve email/api_key
    config = load_config()
    # get_ncbi_email() raises if no email, but we only want to raise if PMC articles
    # are found. So use get_setting directly for optional resolution.
    resolved_email = get_setting("ncbi.email", cli_value=email, config=config)
    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=config)

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

    # ==========================================================================
    # SEED PAPERS SECTION
    # ==========================================================================
    click.echo("=" * 50)
    click.echo("SEED PAPERS")
    click.echo("=" * 50)

    # Progress bar for seed fetch
    progress_bar = None

    def progress_callback(pmcid_str: str, current: int, total: int) -> None:
        nonlocal progress_bar
        if progress_bar is None:
            progress_bar = click.progressbar(
                length=total,
                label="Downloading seeds",
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
            email=resolved_email,
            api_key=resolved_api_key,
        )
    finally:
        if progress_bar is not None:
            progress_bar.__exit__(None, None, None)

    # Show seed papers summary with clear breakdown
    articles_found = stats["articles_found"]
    with_pmcid = stats["full_text_available"]
    without_pmcid = articles_found - with_pmcid

    click.echo(f"\nQuery matched: {articles_found} articles")
    click.echo(f"  With PMCIDs (downloadable): {with_pmcid}")
    if without_pmcid > 0:
        click.echo(f"  Without PMCIDs (skipped):   {without_pmcid}")

    click.echo(f"\nDownloaded: {stats['fetched']}")
    click.echo(f"  Valid:      {stats['valid']}")
    click.echo(f"  Incomplete: {stats['incomplete']}")
    if stats.get("errors", 0) > 0:
        click.echo(f"  Errors:     {stats['errors']}")
    if stats.get("duplicates_skipped", 0) > 0:
        click.echo(f"  Duplicates: {stats['duplicates_skipped']}")

    # ==========================================================================
    # CITATION EXPANSION SECTION
    # ==========================================================================
    expansion_result = None
    expanded_refs_downloaded = 0
    expanded_cites_downloaded = 0
    expanded_refs_discovered = 0
    expanded_cites_discovered = 0

    if (do_expand_refs or do_expand_cites) and stats["full_text_available"] > 0:
        click.echo("\n" + "=" * 50)
        click.echo("CITATION EXPANSION")
        click.echo("=" * 50)

        client = EuropePMCClient()

        # Get seed articles for expansion
        if pmcid:
            # Direct PMCID lookup for seeds
            seeds = []
            for pmcid_val in pmcid:
                article = client.get_by_pmcid(pmcid_val)
                if article and article.pmcid:
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
                    has_full_text=False,
                )

            seeds = list(client.iter_search(seed_query, max_results=max_results))
            seeds = [s for s in seeds if s.pmcid]

        if not seeds:
            click.echo("No seed papers with PMCID available for expansion.")
        else:
            directions = []
            if do_expand_refs:
                directions.append("references")
            if do_expand_cites:
                directions.append("citations")

            click.echo(f"\nExpanding from {len(seeds)} seed papers...")
            click.echo(f"  Directions: {' + '.join(directions)}")
            click.echo(f"  Depth: {expansion_depth}")
            if effective_max_expansion:
                click.echo(f"  Max expansion: {effective_max_expansion:,}")

            # Dry-run mode: preview and prompt
            if dry_run:
                click.echo("\nDry-run mode: gathering expansion statistics...")

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

                _display_expansion_report(expansion_result)

                if not yes and not click.confirm("\nContinue with expansion?"):
                    click.echo("Expansion cancelled.")
                    expansion_result = None
            else:
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
                click.echo()

            # Process expansion results
            if expansion_result and expansion_result.total_expanded > 0:
                # Save expansion manifest
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

                # Get discovered counts by type
                expanded_refs_discovered = expansion_result.expansion_stats.get(
                    "references_found", 0
                )
                expanded_cites_discovered = expansion_result.expansion_stats.get(
                    "citations_found", 0
                )
                total_unique = expansion_result.expansion_stats.get("total_unique", 0)
                duplicates = expansion_result.expansion_stats.get(
                    "duplicates_skipped", 0
                )

                # Show discovered summary
                click.echo("\nDiscovered in citation graph:")
                if do_expand_refs:
                    click.echo(
                        f"  References (papers seeds cite):   {expanded_refs_discovered:,}"
                    )
                if do_expand_cites:
                    click.echo(
                        f"  Citations (papers citing seeds):  {expanded_cites_discovered:,}"
                    )
                if duplicates > 0:
                    click.echo(f"  Duplicates removed:               {duplicates:,}")
                click.echo(f"  Unique papers to look up:         {total_unique:,}")

                # Look up PMCIDs with tracking by type
                click.echo("\nLooking up PMCIDs...")
                ref_pmcids: list[str] = []
                cite_pmcids: list[str] = []
                refs_no_pmcid = 0
                cites_no_pmcid = 0

                for papers in expansion_result.expanded_papers.values():
                    for paper in papers:
                        exp_type = paper.get("_expansion_type", "")
                        pmcid_found = None

                        # First check if PMCID already present
                        raw_pmcid = paper.get("pmcid")
                        if raw_pmcid:
                            pmcid_norm = str(raw_pmcid).upper()
                            if not pmcid_norm.startswith("PMC"):
                                pmcid_norm = f"PMC{pmcid_norm}"
                            pmcid_found = pmcid_norm
                        else:
                            # Need to look up the paper to find PMCID
                            source = paper.get("source", "")
                            paper_id = paper.get("id")
                            if source == "MED" and paper_id:
                                article = client.get_by_pmid(str(paper_id))
                                if article and article.pmcid:
                                    pmcid_found = article.pmcid
                            elif source == "PMC" and paper_id:
                                pmcid_norm = str(paper_id).upper()
                                if not pmcid_norm.startswith("PMC"):
                                    pmcid_norm = f"PMC{pmcid_norm}"
                                pmcid_found = pmcid_norm

                        # Track by type
                        if pmcid_found:
                            if exp_type == "references":
                                ref_pmcids.append(pmcid_found)
                            elif exp_type == "citations":
                                cite_pmcids.append(pmcid_found)
                            else:
                                ref_pmcids.append(pmcid_found)  # default
                        else:
                            if exp_type == "references":
                                refs_no_pmcid += 1
                            elif exp_type == "citations":
                                cites_no_pmcid += 1
                            else:
                                refs_no_pmcid += 1

                # Show PMCID lookup results
                click.echo("\nPMCID lookup results:")
                if do_expand_refs:
                    click.echo(
                        f"  References: {len(ref_pmcids):,} downloadable, "
                        f"{refs_no_pmcid:,} without full-text"
                    )
                if do_expand_cites:
                    click.echo(
                        f"  Citations:  {len(cite_pmcids):,} downloadable, "
                        f"{cites_no_pmcid:,} without full-text"
                    )

                # Combine and download
                all_expanded_pmcids = ref_pmcids + cite_pmcids

                if all_expanded_pmcids:
                    click.echo(
                        f"\nFetching {len(all_expanded_pmcids):,} expanded papers..."
                    )

                    exp_progress_bar = None

                    def exp_progress_cb(
                        pmcid_str: str, current: int, total: int
                    ) -> None:
                        nonlocal exp_progress_bar
                        if exp_progress_bar is None:
                            exp_progress_bar = click.progressbar(
                                length=total,
                                label="Downloading expanded",
                                show_pos=True,
                                show_percent=True,
                            )
                            exp_progress_bar.__enter__()
                        exp_progress_bar.update(1)

                    try:
                        exp_stats = fetch_europepmc(
                            pmcids=all_expanded_pmcids,
                            output_dir=out,
                            workspace=ws,
                            open_access_only=not include_non_oa,
                            verbose=verbose,
                            progress_callback=exp_progress_cb,
                            email=resolved_email,
                            api_key=resolved_api_key,
                        )
                    finally:
                        if exp_progress_bar is not None:
                            exp_progress_bar.__exit__(None, None, None)

                    stats["expanded_fetched"] = exp_stats["fetched"]
                    stats["expanded_valid"] = exp_stats["valid"]
                    stats["expanded_errors"] = exp_stats["errors"]
                    stats["expanded_duplicates"] = exp_stats.get(
                        "duplicates_skipped", 0
                    )

                    # Track counts for summary
                    expanded_refs_downloaded = len(ref_pmcids)
                    expanded_cites_downloaded = len(cite_pmcids)

                    click.echo(f"\nDownloaded: {exp_stats['fetched']:,}")
                    click.echo(f"  Valid:      {exp_stats['valid']:,}")
                    if exp_stats.get("errors", 0) > 0:
                        click.echo(f"  Errors:     {exp_stats['errors']:,}")
                    if exp_stats.get("duplicates_skipped"):
                        click.echo(f"  Duplicates: {exp_stats['duplicates_skipped']:,}")

    # ==========================================================================
    # RECORD SEARCH IN WORKSPACE
    # ==========================================================================
    if ws:
        cmd = " ".join(sys.argv)
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

    # ==========================================================================
    # FINAL SUMMARY
    # ==========================================================================
    click.echo("\n" + "=" * 50)
    click.echo("CORPUS SUMMARY")
    click.echo("=" * 50)

    seed_valid = stats["valid"]
    total_corpus = seed_valid

    click.echo(f"\nSeeds:      {seed_valid:,} papers")

    if expansion_result and expansion_result.total_expanded > 0:
        exp_valid = stats.get("expanded_valid", 0)
        total_corpus += exp_valid

        if do_expand_refs and expanded_refs_discovered > 0:
            click.echo(
                f"References: {expanded_refs_downloaded:,} papers "
                f"(from {expanded_refs_discovered:,} discovered)"
            )
        if do_expand_cites and expanded_cites_discovered > 0:
            click.echo(
                f"Citations:  {expanded_cites_downloaded:,} papers "
                f"(from {expanded_cites_discovered:,} discovered)"
            )

    click.echo("-" * 30)
    click.echo(f"TOTAL:      {total_corpus:,} papers")

    if ws:
        click.echo(f"\nWorkspace: {ws.path}")
    else:
        click.echo(f"\nOutput: {out}/valid/")

    # Create tarball if requested
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
