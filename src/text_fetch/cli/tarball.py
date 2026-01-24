"""Tarball creation commands."""

from __future__ import annotations

from pathlib import Path

import click


@click.group()
@click.pass_context
def tarball(ctx: click.Context) -> None:
    """Create and manage JATS tarballs."""
    pass


@tarball.command(name="create")
@click.option(
    "--xml-dir",
    "-d",
    "xml_dirs",
    multiple=True,
    required=True,
    type=click.Path(exists=True),
    help="Directory containing JATS/XML files (repeatable)",
)
@click.option(
    "--out",
    "-o",
    required=True,
    type=click.Path(),
    help="Output tarball path (.tar.gz)",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(exists=True),
    help="Include metadata CSV in tarball",
)
@click.option(
    "--include-incomplete",
    is_flag=True,
    help="Include files from incomplete/ directories",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Validate JATS files before inclusion (default: validate)",
)
@click.option(
    "--recursive",
    "-r",
    is_flag=True,
    help="Recursively search directories for XML files",
)
@click.option(
    "--compression",
    type=click.Choice(["gz", "bz2", "none"]),
    default="gz",
    help="Compression type (default: gz)",
)
@click.option(
    "--pattern",
    default="*.xml",
    help="Glob pattern for XML files (default: *.xml)",
)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def tarball_create(
    xml_dirs: tuple[str, ...],
    out: str,
    csv_path: str | None,
    include_incomplete: bool,
    validate: bool,
    recursive: bool,
    compression: str,
    pattern: str,
    verbose: bool,
) -> None:
    """Create a tarball from existing JATS XML files.

    This command allows you to create a tarball from previously processed
    JATS files without re-running a fetch. Useful for:

    - Creating tarballs after forgetting to use --tarball flag
    - Combining files from multiple sources into a single tarball
    - Packaging manually curated collections with provenance metadata
    - Creating tarballs with only valid files (excluding incomplete)

    \b
    Examples:
        # Create tarball from single directory
        text-fetch tarball create --xml-dir ./output/valid --out corpus.tar.gz

        # Combine multiple directories
        text-fetch tarball create \\
            --xml-dir ./pmc/valid \\
            --xml-dir ./europepmc/valid \\
            --out combined.tar.gz

        # Include metadata CSV
        text-fetch tarball create \\
            --xml-dir ./output/valid \\
            --csv ./output/metadata.csv \\
            --out corpus.tar.gz

        # Recursive search with custom pattern
        text-fetch tarball create \\
            --xml-dir ./output \\
            --recursive \\
            --pattern "*.jats.xml" \\
            --out corpus.tar.gz

        # Skip validation (faster, no filtering)
        text-fetch tarball create \\
            --xml-dir ./output \\
            --recursive \\
            --no-validate \\
            --out all_files.tar.gz

        # Include incomplete files
        text-fetch tarball create \\
            --xml-dir ./output/valid \\
            --xml-dir ./output/incomplete \\
            --include-incomplete \\
            --out full_corpus.tar.gz
    """
    from ..common import (
        build_provenance,
        create_tarball_from_files,
        embed_provenance,
        embed_validation_summary,
        find_jats_files,
        validate_and_collect_stats,
    )

    # Convert to paths
    directories = [Path(d) for d in xml_dirs]
    output_path = Path(out)
    csv_file = Path(csv_path) if csv_path else None

    # Ensure output has proper extension
    out_str = str(output_path)
    if not out_str.endswith((".tar.gz", ".tar.bz2", ".tar")):
        if compression == "gz":
            output_path = Path(out_str + ".tar.gz")
        elif compression == "bz2":
            output_path = Path(out_str + ".tar.bz2")
        else:
            output_path = Path(out_str + ".tar")

    # Find files
    dir_count = len(xml_dirs)
    dir_word = "directory" if dir_count == 1 else "directories"
    click.echo(f"Scanning {dir_count} {dir_word}...")

    files = find_jats_files(
        directories=directories,
        pattern=pattern,
        recursive=recursive,
        include_incomplete=include_incomplete,
    )

    if not files:
        click.echo("No XML files found matching criteria.")
        return

    click.echo(f"Found {len(files)} XML files")

    # Validate
    if validate:
        click.echo("Validating files...")

    stats = validate_and_collect_stats(
        files=files,
        validate=validate,
        verbose=verbose,
    )

    if validate:
        click.echo(f"  Valid: {stats['valid_count']}")
        click.echo(f"  Invalid: {stats['invalid_count']}")

    if not stats["valid_files"]:
        click.echo("No valid files to include in tarball.")
        return

    # Create tarball
    click.echo(f"Creating tarball: {output_path}")
    tarball_stats = create_tarball_from_files(
        files=stats["valid_files"],
        output_path=output_path,
        csv_path=csv_file,
        compression=compression,
    )

    # Build and embed provenance
    dir_list = " ".join(f"--xml-dir {d}" for d in xml_dirs)
    cmd = f"text-fetch tarball create {dir_list} --out {out}"
    provenance = build_provenance(
        stats=tarball_stats,
        command=cmd,
        sources_queried=None,
    )
    embed_provenance(output_path, None, provenance)

    # Create and embed validation summary
    validation_summary = {
        "source_directories": [str(d) for d in directories],
        "total_files_scanned": stats["total_files"],
        "files_included": stats["valid_count"],
        "files_excluded": stats["invalid_count"],
        "validation_enabled": validate,
        "pattern_used": pattern,
        "recursive": recursive,
        "include_incomplete": include_incomplete,
        # Excluded files (capped at 20 for readability)
        "excluded_files": [f.name for f in stats.get("invalid_files", [])][:20],
    }
    embed_validation_summary(output_path, validation_summary)

    # Summary
    click.echo("\nTarball created successfully!")
    click.echo(f"  Files included: {tarball_stats['files_included']}")
    click.echo(f"  Size: {tarball_stats['bytes']:,} bytes")
    if csv_file:
        click.echo(f"  Metadata: {csv_file.name}")
    click.echo(f"  Output: {output_path}")
