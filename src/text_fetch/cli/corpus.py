"""Local corpus import commands."""

from pathlib import Path

import click


@click.group()
def corpus() -> None:
    """Import local documents for retrieval."""


@corpus.command("import")
@click.argument("source", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--out",
    "-o",
    required=True,
    type=click.Path(dir_okay=False, path_type=Path),
    help="JATS archive (.tar.gz or .tgz), or .xml for a single input file.",
)
def corpus_import(source: Path, out: Path) -> None:
    """Convert a Markdown, TXT, or PDF file or recursively import a directory."""
    from ..corpus import import_corpus

    try:
        count = import_corpus(source, out)
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from exc
    noun = "document" if count == 1 else "documents"
    click.echo(f"Imported {count} {noun} into {out}")
