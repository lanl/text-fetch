"""Shared utilities for CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from ..common import build_provenance, create_jats_tarball, embed_provenance


def handle_tarball_creation(
    output_dir: str,
    tarball: bool,
    tarball_name: str | None,
    stats: dict[str, Any],
    search_config_dict: dict[str, Any] | None,
    command: str,
    source: str,
    verbose: bool = False,
) -> None:
    """Handle tarball creation after a fetch completes.

    Args:
        output_dir: Output directory path.
        tarball: Whether to create tarball.
        tarball_name: Custom tarball name or None for default.
        stats: Fetch statistics dict.
        search_config_dict: Search config as dict (for embedding).
        command: Original command line.
        source: Source name (pmc, europepmc, etc).
        verbose: Whether to show verbose output.
    """
    if not tarball:
        return

    out_path = Path(output_dir)
    default_name = f"{source}_corpus.tar.gz" if source else "corpus.tar.gz"
    tarball_path = out_path / (tarball_name or default_name)

    if verbose:
        click.echo(f"Creating tarball: {tarball_path}")

    try:
        tarball_stats = create_jats_tarball(out_path, tarball_path)

        # Build and embed provenance
        provenance = build_provenance(
            stats=tarball_stats,
            command=command,
            sources_queried=[source] if source else None,
        )
        embed_provenance(tarball_path, search_config_dict, provenance)

        click.echo(f"Created tarball: {tarball_path}")
        click.echo(f"  Files included: {tarball_stats['files_included']}")
        click.echo(f"  Size: {tarball_stats['bytes']:,} bytes")
    except Exception as e:
        click.echo(f"Warning: Failed to create tarball: {e}", err=True)
