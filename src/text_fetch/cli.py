#!/usr/bin/env python3
"""text-fetch CLI entry point.

This module is a thin dispatcher. Business logic lives in text_fetch/*.
"""

from __future__ import annotations

import click

from . import __version__
from .config import (
    get_grobid_url,
    get_ncbi_api_key,
    get_ncbi_email,
    load_config,
)


@click.group()
@click.version_option(version=__version__, prog_name="text-fetch")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Acquire scientific literature for RAG pipelines."""
    # Load config once and store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@cli.command()
@click.argument("pdf_root", type=click.Path(exists=True))
@click.option("--out", required=True, help="Output CSV path")
@click.option("--grobid-url", default=None, help="GROBID service URL")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pdf(
    ctx: click.Context,
    pdf_root: str,
    out: str,
    grobid_url: str | None,
    verbose: bool,
) -> None:
    """Process PDFs via GROBID and emit CSV index."""
    config = ctx.obj["config"]
    resolved_grobid_url = get_grobid_url(cli_value=grobid_url, config=config)

    if verbose:
        click.echo(f"Using GROBID at: {resolved_grobid_url}")

    click.echo(f"PDF processing not yet implemented. Root: {pdf_root}")


@cli.command()
@click.option("--config-file", type=click.Path(exists=True), help="JSON search config")
@click.option("--query", help="Raw PubMed query string")
@click.option("--out", required=True, help="Output directory")
@click.option(
    "--email",
    default=None,
    envvar="NCBI_EMAIL",
    help="Email for NCBI requests",
)
@click.option(
    "--api-key",
    default=None,
    envvar="NCBI_API_KEY",
    help="NCBI API key (optional, for higher rate limits)",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pmc(
    ctx: click.Context,
    config_file: str | None,
    query: str | None,
    out: str,
    email: str | None,
    api_key: str | None,
    verbose: bool,
) -> None:
    """Fetch articles from PubMed Central."""
    if not config_file and not query:
        raise click.UsageError("Either --config-file or --query is required")

    config = ctx.obj["config"]

    # Resolve settings with priority: CLI > env > config file
    try:
        resolved_email = get_ncbi_email(cli_value=email, config=config)
    except ValueError as e:
        raise click.UsageError(str(e)) from e

    resolved_api_key = get_ncbi_api_key(cli_value=api_key, config=config)

    if verbose:
        click.echo(f"Using NCBI email: {resolved_email}")
        if resolved_api_key:
            click.echo("Using NCBI API key: [configured]")
        else:
            click.echo("No NCBI API key configured (using lower rate limit)")
        if config.config_path:
            click.echo(f"Config loaded from: {config.config_path}")

    click.echo("PMC fetching not yet implemented.")


@cli.command(name="config")
@click.option("--show", is_flag=True, help="Show resolved configuration")
@click.pass_context
def config_cmd(ctx: click.Context, show: bool) -> None:
    """Show or manage configuration."""
    config = ctx.obj["config"]

    if True:  # Default behavior is to show
        click.echo("Configuration:")
        click.echo(f"  Config file: {config.config_path or 'Not found'}")
        click.echo("")
        click.echo("  [ncbi]")
        click.echo(f"    email: {config.ncbi.email or '(not set)'}")
        click.echo(
            f"    api_key: {'[configured]' if config.ncbi.api_key else '(not set)'}"
        )
        click.echo("")
        click.echo("  [grobid]")
        click.echo(f"    url: {config.grobid.url}")
        click.echo("")
        click.echo("Search paths:")
        click.echo("  1. ./text-fetch.toml")
        click.echo("  2. ~/.config/text-fetch/config.toml")


if __name__ == "__main__":
    cli()
