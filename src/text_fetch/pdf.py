"""Local PDF processing via GROBID.

Provides batch processing of PDF directories with TEI caching
and JATS conversion.
"""

from __future__ import annotations

__all__ = [
    "PDFProcessingResult",
    "find_pdfs",
    "process_pdf",
    "process_pdf_batch",
]

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from lxml import etree as ET

from text_fetch.common import clean, sha1_of_file
from text_fetch.grobid import GROBIDClient
from text_fetch.pmc import JATSValidator, ValidationStatus

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class PDFProcessingResult:
    """Result of processing a single PDF."""

    pdf_path: str
    sha1: str
    tei_path: str | None = None
    jats_path: str | None = None
    source: str = "unknown"  # grobid-fulltext, grobid-header, cache
    validation: ValidationStatus = ValidationStatus.INCOMPLETE
    metadata: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for manifest."""
        return {
            "pdf_path": self.pdf_path,
            "sha1": self.sha1,
            "tei_path": self.tei_path,
            "jats_path": self.jats_path,
            "source": self.source,
            "validation": self.validation.value,
            "metadata": self.metadata,
            "notes": self.notes,
        }


def find_pdfs(root_dir: str | Path) -> list[Path]:
    """Recursively find all PDF files in a directory.

    Args:
        root_dir: Directory to scan.

    Returns:
        Sorted list of PDF file paths.
    """
    root = Path(root_dir)
    pdfs = sorted(root.rglob("*.pdf"))
    return pdfs


def _get_cache_paths(
    pdf_path: Path,
    sha1: str,
    tei_cache_dir: Path | None,
    jats_output_dir: Path | None,
) -> tuple[Path | None, Path | None]:
    """Generate cache paths based on PDF name and SHA1."""
    base_name = pdf_path.stem
    tei_path = None
    jats_path = None

    if tei_cache_dir:
        tei_path = tei_cache_dir / f"{base_name}.{sha1[:8]}.tei.xml"
    if jats_output_dir:
        jats_path = jats_output_dir / f"{base_name}.{sha1[:8]}.jats.xml"

    return tei_path, jats_path


def _parse_tei_metadata(
    tei_xml: str, normalize_unicode: bool = False
) -> dict[str, str]:
    """Extract metadata from TEI XML.

    Returns dict with: first_author, year, title, journal, DOI, PMID, PMCID
    """
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    try:
        root = ET.fromstring(tei_xml.encode("utf-8"))
    except ET.XMLSyntaxError:
        return {}

    def tei_text(xpath: str) -> str:
        nodes = root.xpath(xpath, namespaces=ns)
        if not nodes:
            return ""
        if isinstance(nodes[0], str):
            return clean(nodes[0], normalize_unicode)
        txt = "".join(nodes[0].itertext())
        return clean(txt, normalize_unicode)

    def first_match(xpaths: list[str]) -> str:
        for xp in xpaths:
            v = tei_text(xp)
            if v:
                return v
        return ""

    metadata: dict[str, str] = {}

    # DOI
    metadata["DOI"] = first_match(
        [
            "//tei:teiHeader//tei:idno[@type='DOI']/text()",
            "//tei:teiHeader//tei:ptr[@type='DOI']/@target",
        ]
    )

    # PMID/PMCID
    metadata["PMID"] = first_match(["//tei:teiHeader//tei:idno[@type='PMID']/text()"])
    metadata["PMCID"] = first_match(
        [
            "//tei:teiHeader//tei:idno[@type='PMCID']/text()",
            "//tei:teiHeader//tei:idno[@type='PMC']/text()",
        ]
    )

    # Title
    metadata["title"] = first_match(
        [
            "//tei:teiHeader//tei:biblStruct/tei:analytic/"
            "tei:title[not(@type) or @type='main']/text()",
            "//tei:teiHeader//tei:biblStruct/tei:monogr/"
            "tei:title[not(@type) or @type='main']/text()",
            "//tei:teiHeader//tei:titleStmt/tei:title/text()",
        ]
    )

    # Journal
    metadata["journal"] = first_match(
        [
            "//tei:teiHeader//tei:biblStruct/tei:monogr/"
            "tei:title[@level='j']/text()",
        ]
    )

    # Year
    yraw = first_match(
        [
            "//tei:teiHeader//tei:biblStruct/tei:monogr/" "tei:imprint/tei:date/@when",
            "//tei:teiHeader//tei:biblStruct/tei:monogr/" "tei:imprint/tei:date/text()",
        ]
    )
    if yraw:
        m = re.search(r"(19|20|21)\d{2}", yraw)
        if m:
            metadata["year"] = m.group(0)

    # First author
    metadata["first_author"] = first_match(
        [
            "//tei:teiHeader//tei:biblStruct/tei:analytic/"
            "tei:author[1]/tei:persName/tei:surname/text()",
            "//tei:teiHeader//tei:biblStruct/tei:monogr/"
            "tei:author[1]/tei:persName/tei:surname/text()",
            "(//tei:teiHeader//tei:surname/text())[1]",
        ]
    )

    return {k: v for k, v in metadata.items() if v}


ProgressCallback = Callable[[str, int, int], None]


def process_pdf(
    pdf_path: Path,
    grobid_client: GROBIDClient,
    xslt_path: Path,
    tei_cache_dir: Path | None = None,
    jats_output_dir: Path | None = None,
    prefer_fulltext: bool = True,
    normalize_unicode: bool = False,
    ocr: bool = False,
) -> PDFProcessingResult:
    """Process a single PDF through GROBID pipeline.

    Args:
        pdf_path: Path to PDF file.
        grobid_client: GROBID client instance.
        xslt_path: Path to tei2jats.xsl stylesheet.
        tei_cache_dir: Directory for TEI cache (optional).
        jats_output_dir: Directory for JATS output (optional).
        prefer_fulltext: If True, use processFulltextDocument first.
        normalize_unicode: If True, convert Unicode to ASCII.
        ocr: If True, enable OCR for scanned PDFs.

    Returns:
        PDFProcessingResult with processing details.
    """
    sha1 = sha1_of_file(str(pdf_path))
    result = PDFProcessingResult(
        pdf_path=str(pdf_path),
        sha1=sha1,
    )

    tei_cache_path, _ = _get_cache_paths(pdf_path, sha1, tei_cache_dir, jats_output_dir)

    # Check TEI cache
    tei_xml: str | None = None
    if tei_cache_path and tei_cache_path.exists():
        try:
            tei_xml = tei_cache_path.read_text(encoding="utf-8")
            result.source = "cache"
            result.tei_path = str(tei_cache_path)
            logger.debug("Loaded TEI from cache: %s", tei_cache_path)
        except Exception as e:
            result.notes.append(f"tei_cache_read_error:{e}")

    # Process with GROBID if not cached
    if tei_xml is None:
        pdf_bytes = pdf_path.read_bytes()
        tei_xml = grobid_client.process_pdf(
            pdf_bytes,
            full_text=prefer_fulltext,
            ocr=ocr,
        )
        if tei_xml:
            result.source = "grobid-fulltext" if prefer_fulltext else "grobid-header"

            # Save to cache
            if tei_cache_path:
                try:
                    tei_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    tei_cache_path.write_text(tei_xml, encoding="utf-8")
                    result.tei_path = str(tei_cache_path)
                except Exception as e:
                    result.notes.append(f"tei_save_error:{e}")
        else:
            result.notes.append("grobid_processing_failed")
            return result

    # Parse TEI metadata
    metadata = _parse_tei_metadata(tei_xml, normalize_unicode)
    result.metadata = metadata

    return result


def process_pdf_batch(
    pdf_dir: Path,
    output_dir: Path,
    grobid_url: str = "http://localhost:8070",
    xslt_path: Path | str = "tei2jats.xsl",
    prefer_fulltext: bool = True,
    save_tei: bool = True,
    resolve_ncbi: bool = False,
    email: str | None = None,
    api_key: str | None = None,
    normalize_unicode: bool = False,
    ocr: bool = False,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Process all PDFs in a directory.

    Args:
        pdf_dir: Directory containing PDFs.
        output_dir: Output directory for JATS files.
        grobid_url: GROBID service URL.
        xslt_path: Path to TEI→JATS stylesheet.
        prefer_fulltext: Use fulltext mode in GROBID.
        save_tei: Cache TEI XML files.
        resolve_ncbi: Resolve DOIs to PMID/PMCID.
        email: Email for NCBI API (required if resolve_ncbi).
        api_key: NCBI API key (optional).
        normalize_unicode: Convert Unicode to ASCII.
        ocr: Enable OCR for scanned PDFs.
        progress_callback: Optional callback(pdf_name, current, total).

    Returns:
        Dictionary with processing statistics and results.
    """
    pdfs = find_pdfs(pdf_dir)
    total = len(pdfs)

    if total == 0:
        return {
            "total": 0,
            "valid": 0,
            "incomplete": 0,
            "errors": 0,
            "results": [],
        }

    # Set up directories
    output_path = Path(output_dir)
    valid_dir = output_path / "valid"
    incomplete_dir = output_path / "incomplete"
    tei_cache_dir = output_path / "tei_cache" if save_tei else None

    valid_dir.mkdir(parents=True, exist_ok=True)
    incomplete_dir.mkdir(parents=True, exist_ok=True)
    if tei_cache_dir:
        tei_cache_dir.mkdir(parents=True, exist_ok=True)

    # Initialize clients
    grobid = GROBIDClient(grobid_url)

    # Optional NCBI client for ID resolution
    ncbi = None
    if resolve_ncbi and email:
        from text_fetch.ncbi import NCBIClient

        ncbi = NCBIClient(email=email, api_key=api_key)

    xslt = Path(xslt_path)

    results: list[PDFProcessingResult] = []
    valid_count = 0
    incomplete_count = 0
    error_count = 0

    validator = JATSValidator()

    for i, pdf_path in enumerate(pdfs, 1):
        if progress_callback:
            progress_callback(pdf_path.name, i, total)

        try:
            # Process PDF to get TEI
            result = process_pdf(
                pdf_path,
                grobid,
                xslt,
                tei_cache_dir=tei_cache_dir,
                jats_output_dir=None,  # We handle JATS saving manually
                prefer_fulltext=prefer_fulltext,
                normalize_unicode=normalize_unicode,
                ocr=ocr,
            )

            # NCBI ID resolution
            if ncbi and result.metadata.get("DOI"):
                try:
                    mapping = ncbi.convert_ids([result.metadata["DOI"]], id_type="doi")
                    pmcid = mapping.get(result.metadata["DOI"])
                    if pmcid:
                        result.metadata["PMCID"] = pmcid
                except Exception as e:
                    result.notes.append(f"ncbi_error:{e}")

            # Convert TEI to JATS
            tei_content: str | None = None
            if result.tei_path:
                tei_content = Path(result.tei_path).read_text(encoding="utf-8")
            elif result.source.startswith("grobid"):
                # Re-process to get TEI content (shouldn't happen often)
                tei_content = grobid.process_pdf(
                    pdf_path.read_bytes(),
                    full_text=prefer_fulltext,
                )

            if tei_content:
                # Note: TEI already has OCR results, no need to re-process
                jats_xml = grobid.tei_to_jats(tei_content, xslt)

                if jats_xml:
                    # Validate
                    validation = validator.validate(jats_xml)
                    result.validation = validation.status

                    # Choose directory
                    if validation.status == ValidationStatus.VALID:
                        dest_dir = valid_dir
                        valid_count += 1
                    else:
                        dest_dir = incomplete_dir
                        incomplete_count += 1

                    # Save JATS
                    jats_filename = f"{pdf_path.stem}.{result.sha1[:8]}.jats.xml"
                    jats_path = dest_dir / jats_filename
                    jats_path.write_text(jats_xml, encoding="utf-8")
                    result.jats_path = str(jats_path)
                else:
                    result.notes.append("jats_conversion_failed")
                    error_count += 1
            else:
                error_count += 1

            results.append(result)

        except Exception as e:
            logger.error("Failed to process %s: %s", pdf_path, e)
            error_count += 1
            results.append(
                PDFProcessingResult(
                    pdf_path=str(pdf_path),
                    sha1="",
                    notes=[f"processing_error:{e}"],
                )
            )

    # Clean up
    if ncbi:
        ncbi.close()

    return {
        "total": total,
        "valid": valid_count,
        "incomplete": incomplete_count,
        "errors": error_count,
        "results": [r.to_dict() for r in results],
    }
