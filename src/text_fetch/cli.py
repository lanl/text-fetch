#!/usr/bin/env python3
"""text-fetch CLI entry point.

This module is a thin dispatcher. Business logic lives in text_fetch/*.
"""

from typing import Optional

import click

from . import __version__


@click.group()
@click.version_option(version=__version__, prog_name="text-fetch")
def cli() -> None:
    """Acquire scientific literature for RAG pipelines."""
    pass


@cli.command()
@click.argument("pdf_root", type=click.Path(exists=True))
@click.option("--out", required=True, help="Output CSV path")
@click.option(
    "--grobid-url", default="http://localhost:8070", help="GROBID service URL"
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def pdf(pdf_root: str, out: str, grobid_url: str, verbose: bool) -> None:
    """Process PDFs via GROBID and emit CSV index."""
    click.echo(f"PDF processing not yet implemented. Root: {pdf_root}")


@cli.command()
@click.option("--config", type=click.Path(exists=True), help="JSON search config")
@click.option("--query", help="Raw PubMed query string")
@click.option("--out", required=True, help="Output directory")
@click.option("--email", required=True, help="Email for NCBI requests")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def pmc(
    config: Optional[str],
    query: Optional[str],
    out: str,
    email: str,
    verbose: bool,
) -> None:
    """Fetch articles from PubMed Central."""
    if not config and not query:
        raise click.UsageError("Either --config or --query is required")
    click.echo("PMC fetching not yet implemented.")


if __name__ == "__main__":
    cli()
