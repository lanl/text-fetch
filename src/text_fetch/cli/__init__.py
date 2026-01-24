#!/usr/bin/env python3
"""text-fetch CLI entry point.

This module is the main entry point for the CLI.
Command groups are organized in submodules for maintainability.
"""

from __future__ import annotations

import click

from .. import __version__
from ..config import load_config


@click.group()
@click.version_option(version=__version__, prog_name="text-fetch")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Acquire scientific literature for RAG pipelines."""
    # Load config once and store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config()


@cli.command(name="config")
@click.option("--show", is_flag=True, help="Show resolved configuration")
@click.pass_context
def config_cmd(ctx: click.Context, show: bool) -> None:
    """Show or manage configuration."""
    config = ctx.obj["config"]

    if True:  # Default behavior is to show
        click.echo("Configuration:")
        path = config.config_path or "Not found"
        click.echo(f"  Config file: {path}")
        click.echo("")
        click.echo("  [ncbi]")
        click.echo(f"    email: {config.ncbi.email or '(not set)'}")
        api_status = "[configured]" if config.ncbi.api_key else "(not set)"
        click.echo(f"    api_key: {api_status}")
        click.echo("")
        click.echo("  [grobid]")
        click.echo(f"    url: {config.grobid.url}")
        click.echo("")
        click.echo("Search paths:")
        click.echo("  1. ./text-fetch.toml")
        click.echo("  2. ~/.config/text-fetch/config.toml")


def _register_commands() -> None:
    """Register all command groups."""
    from . import (
        arxiv,
        biorxiv,
        chemrxiv,
        europepmc,
        fetch,
        medrxiv,
        pdf,
        pmc,
        tarball,
        workspace,
    )

    cli.add_command(pdf.pdf)
    cli.add_command(pmc.pmc)
    cli.add_command(arxiv.arxiv)
    cli.add_command(biorxiv.biorxiv)
    cli.add_command(medrxiv.medrxiv)
    cli.add_command(chemrxiv.chemrxiv)
    cli.add_command(europepmc.europepmc)
    cli.add_command(fetch.unified_fetch_cmd, name="fetch")
    cli.add_command(workspace.workspace)
    cli.add_command(tarball.tarball)


_register_commands()


if __name__ == "__main__":
    cli()
