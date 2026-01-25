"""CLI command for corpus comparison."""

from __future__ import annotations

import json
from pathlib import Path

import click

from text_fetch.compare import ComparisonResult, compare_corpora


@click.command(name="compare")
@click.option(
    "--reference",
    "-r",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to reference corpus (tarball or ID list)",
)
@click.option(
    "--candidate",
    "-c",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to candidate corpus (tarball or ID list)",
)
@click.option(
    "--out",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output JSON path (default: pretty-print to stdout)",
)
@click.option(
    "--ref-label",
    type=str,
    default=None,
    help="Label for reference corpus",
)
@click.option(
    "--cand-label",
    type=str,
    default=None,
    help="Label for candidate corpus",
)
@click.option(
    "--normalize",
    is_flag=True,
    help="Normalize IDs via Europe PMC lookup (DOI/PMID→PMCID)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Verbose output (shows normalization progress)",
)
def compare_cmd(
    reference: Path,
    candidate: Path,
    out: Path | None,
    ref_label: str | None,
    cand_label: str | None,
    normalize: bool,
    verbose: bool,
) -> None:
    """Compare two corpora and compute overlap metrics.

    Compares a reference corpus against a candidate corpus to measure
    coverage and identify missing or additional papers.

    \b
    Examples:
        # Compare auto-generated corpus against expert curation
        text-fetch compare -r expert.txt -c auto_corpus.tar.gz -o result.json

        # Pretty-print comparison to stdout
        text-fetch compare -r corpus_a.tar.gz -c corpus_b.tar.gz

        # With custom labels
        text-fetch compare -r old.tar.gz -c new.tar.gz \\
            --ref-label "Depth 1" --cand-label "Depth 2"

        # With ID normalization (slower but more accurate for mixed IDs)
        text-fetch compare -r expert.txt -c auto_corpus.tar.gz --normalize
    """
    import logging

    if verbose:
        logging.basicConfig(level=logging.INFO)

    if normalize:
        click.echo("Normalizing IDs via Europe PMC (this may take a while)...")

    result = compare_corpora(
        reference_path=reference,
        candidate_path=candidate,
        reference_label=ref_label,
        candidate_label=cand_label,
        normalize=normalize,
    )

    if out:
        # Write JSON output
        out.write_text(json.dumps(result.to_dict(), indent=2))
        click.echo(f"Comparison saved to: {out}")
    else:
        # Pretty-print to stdout
        _print_comparison(result)


def _print_comparison(result: ComparisonResult) -> None:
    """Pretty-print comparison results."""
    click.echo("═" * 67)
    click.echo("CORPUS COMPARISON")
    click.echo("═" * 67)
    click.echo()

    click.echo(f"REFERENCE: {result.reference_label}")
    click.echo(f"  Source: {result.reference_source}")
    click.echo(f"  Papers: {len(result.reference_ids):,}")
    click.echo()

    click.echo(f"CANDIDATE: {result.candidate_label}")
    click.echo(f"  Source: {result.candidate_source}")
    click.echo(f"  Papers: {len(result.candidate_ids):,}")
    click.echo()

    click.echo("OVERLAP METRICS:")
    click.echo(f"  Common papers:  {len(result.overlap):,}")
    click.echo(f"  Jaccard:        {result.jaccard:.2f}  (similarity)")
    recall_pct = result.recall * 100
    click.echo(
        f"  Recall:         {result.recall:.2f}  "
        f"(candidate found {recall_pct:.0f}% of reference)"
    )
    precision_pct = result.precision * 100
    click.echo(
        f"  Precision:      {result.precision:.2f}  "
        f"({precision_pct:.0f}% of candidate is in reference)"
    )
    click.echo()

    # Reference only
    ref_only_count = len(result.reference_only)
    if ref_only_count > 0:
        click.echo(f"REFERENCE ONLY ({ref_only_count} papers not in candidate):")
        preview = sorted(result.reference_only)[:5]
        click.echo(f"  {', '.join(preview)}")
        if ref_only_count > 5:
            click.echo(f"  ... and {ref_only_count - 5} more")
    else:
        click.echo("REFERENCE ONLY: (none)")
    click.echo()

    # Candidate only
    cand_only_count = len(result.candidate_only)
    if cand_only_count > 0:
        click.echo(f"CANDIDATE ONLY ({cand_only_count} papers not in reference):")
        preview = sorted(result.candidate_only)[:5]
        click.echo(f"  {', '.join(preview)}")
        if cand_only_count > 5:
            click.echo(f"  ... and {cand_only_count - 5} more")
    else:
        click.echo("CANDIDATE ONLY: (none)")
