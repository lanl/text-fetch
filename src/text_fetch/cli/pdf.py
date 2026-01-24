"""PDF processing commands."""

from __future__ import annotations

import click

from ..config import get_grobid_url, get_ncbi_api_key, get_ncbi_email
from ._common import handle_tarball_creation


@click.group()
@click.pass_context
def pdf(ctx: click.Context) -> None:
    """Process local PDF files via GROBID."""
    pass


@pdf.command("batch")
@click.option(
    "--dir",
    "-d",
    "pdf_dir",
    required=True,
    type=click.Path(exists=True, file_okay=False),
    help="Directory containing PDF files (scanned recursively)",
)
@click.option(
    "--out",
    "-o",
    "output_dir",
    required=True,
    type=click.Path(),
    help="Output directory for JATS files",
)
@click.option(
    "--workspace",
    type=click.Path(),
    help="Add results to workspace (enables cross-search deduplication)",
)
@click.option(
    "--grobid-url",
    default=None,
    help="GROBID service URL (default: from config or localhost:8070)",
)
@click.option(
    "--xslt-path",
    default=None,
    type=click.Path(exists=True),
    help="Path to TEI→JATS XSLT stylesheet (default: bundled)",
)
@click.option(
    "--prefer-fulltext/--header-only",
    default=True,
    help="Use fulltext processing (default) vs header-only",
)
@click.option(
    "--save-tei/--no-tei",
    default=True,
    help="Cache TEI XML files",
)
@click.option(
    "--resolve-ncbi",
    is_flag=True,
    help="Resolve DOIs to PMID/PMCID via NCBI",
)
@click.option(
    "--email",
    default=None,
    help="Email for NCBI API (required with --resolve-ncbi)",
)
@click.option(
    "--api-key",
    default=None,
    help="NCBI API key for faster rate limits",
)
@click.option(
    "--csv",
    "csv_path",
    default=None,
    type=click.Path(),
    help="Output CSV metadata file",
)
@click.option(
    "--normalize-unicode",
    is_flag=True,
    help="Convert Unicode characters to ASCII",
)
@click.option(
    "--ocr",
    is_flag=True,
    help="Enable OCR for scanned PDFs (requires GROBID with Tesseract)",
)
@click.option("--tarball", is_flag=True, help="Create tarball of results")
@click.option("--tarball-name", default=None, help="Custom tarball filename")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
@click.pass_context
def pdf_batch(
    ctx: click.Context,
    pdf_dir: str,
    output_dir: str,
    workspace: str | None,
    grobid_url: str | None,
    xslt_path: str | None,
    prefer_fulltext: bool,
    save_tei: bool,
    resolve_ncbi: bool,
    email: str | None,
    api_key: str | None,
    csv_path: str | None,
    normalize_unicode: bool,
    ocr: bool,
    tarball: bool,
    tarball_name: str | None,
    verbose: bool,
) -> None:
    """Process PDF files in a directory via GROBID.

    \b
    Examples:
        # Basic batch processing
        text-fetch pdf batch --dir ./PDFs --out ./output

        # Add to workspace for deduplication
        text-fetch pdf batch --dir ./PDFs --workspace ./my-corpus --out ./output
    """
    import csv
    import sys
    from pathlib import Path

    from text_fetch.grobid import get_default_xslt_path
    from text_fetch.pdf import find_pdfs, process_pdf_batch
    from text_fetch.workspace import Workspace

    # Resolve XSLT path
    resolved_xslt = Path(xslt_path) if xslt_path else get_default_xslt_path()

    config = ctx.obj["config"]

    # Resolve settings from config
    grobid = grobid_url or get_grobid_url(config=config)

    if resolve_ncbi:
        email_val = email or get_ncbi_email(config=config)
        api_key_val = api_key or get_ncbi_api_key(config=config)
        if not email_val:
            click.echo(
                "Error: --email or config email required " "with --resolve-ncbi",
                err=True,
            )
            raise SystemExit(1)
        email = email_val
        api_key = api_key_val

    # Load or create workspace if specified
    ws = None
    if workspace:
        ws_path = Path(workspace)
        ws = Workspace.load_or_init(ws_path)
        if verbose:
            click.echo(f"Using workspace: {ws_path}")

    # Count PDFs
    pdfs = find_pdfs(pdf_dir)
    if not pdfs:
        click.echo("No PDF files found.")
        return

    click.echo(f"Found {len(pdfs)} PDF files in {pdf_dir}")
    if ws:
        click.echo(f"Workspace: {ws.path}")
    else:
        click.echo(f"Output directory: {output_dir}")
    click.echo(f"GROBID URL: {grobid}")
    if ocr:
        click.echo("OCR: enabled")

    def progress_callback(name: str, current: int, total: int) -> None:
        if verbose:
            click.echo(f"[{current}/{total}] Processing {name}")

    result = process_pdf_batch(
        pdf_dir=Path(pdf_dir),
        output_dir=Path(output_dir),
        workspace=ws,
        grobid_url=grobid,
        xslt_path=resolved_xslt,
        prefer_fulltext=prefer_fulltext,
        save_tei=save_tei,
        resolve_ncbi=resolve_ncbi,
        email=email,
        api_key=api_key,
        normalize_unicode=normalize_unicode,
        ocr=ocr,
        progress_callback=progress_callback,
    )

    # Record search in workspace
    if ws:
        cmd = " ".join(sys.argv)
        search_config = {
            "source": "pdf",
            "pdf_dir": pdf_dir,
        }
        ws.record_search(config=search_config, command=cmd, stats=result)

    # Summary
    click.echo("\nProcessing complete:")
    click.echo(f"  Total: {result['total']}")
    click.echo(f"  Valid: {result['valid']}")
    click.echo(f"  Incomplete: {result['incomplete']}")
    if result.get("duplicates_skipped"):
        click.echo(f"  Duplicates skipped: {result['duplicates_skipped']}")
    click.echo(f"  Errors: {result['errors']}")
    if ws:
        click.echo(f"\nWorkspace: {ws.path}")

    # CSV output
    if csv_path:
        fieldnames = [
            "first_author",
            "year",
            "title",
            "journal",
            "DOI",
            "PMID",
            "PMCID",
            "pdf_path",
            "tei_path",
            "jats_path",
            "source",
            "notes",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in result["results"]:
                row = {**r.get("metadata", {})}
                row["pdf_path"] = r["pdf_path"]
                row["tei_path"] = r.get("tei_path", "")
                row["jats_path"] = r.get("jats_path", "")
                row["source"] = r["source"]
                row["notes"] = ";".join(r.get("notes", []))
                writer.writerow(row)
        click.echo(f"Wrote metadata to {csv_path}")

    # Create tarball if requested (only if not using workspace)
    if not ws:
        cmd = f"text-fetch pdf batch --dir {pdf_dir} --out {output_dir}"
        handle_tarball_creation(
            output_dir=output_dir,
            tarball=tarball,
            tarball_name=tarball_name,
            stats=result,
            search_config_dict=None,
            command=cmd,
            source="pdf",
            verbose=verbose,
        )
    elif tarball:
        click.echo(
            "Note: Use 'text-fetch workspace build' to create tarball " "from workspace"
        )
