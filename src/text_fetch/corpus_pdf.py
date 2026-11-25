"""Read the text layer of a PDF for local corpus import."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from lxml import etree
from pdfminer.converter import PDFPageAggregator
from pdfminer.layout import LAParams, LTFigure, LTPage, LTTextBox
from pdfminer.pdfdocument import PDFDocument, PDFPasswordIncorrect
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.pdftypes import PDFException, PDFStream, resolve1
from pdfminer.psparser import PSException
from pdfminer.utils import decode_text

# Unmapped glyphs in otherwise readable PDFs can produce XML-forbidden characters.
_INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_DOT_LEADER = re.compile(r"(?:\.[ \t]*){4,}|…{2,}")
_PAGE_NUMBER = re.compile(r"(?:page\s+)?(?:\d+|[ivxlcdm]+)(?:\s+(?:of|/)\s+\d+)?", re.I)
_ABSTRACT = re.compile(
    r"^(?i:abstract)(?:[ \t]*[:.\-–—][ \t]*|[ \t]+(?=[A-Z][^\n]*[.!?](?:\s|$))|[ \t]*$)",
    re.M,
)
_NEXT_SECTION = re.compile(
    r"^(?:(?:\d+(?:\.\d+)*\.?|[IVX]+\.)[ \t]+[A-Z][^\n]{0,78}(?<![.!?])$"
    r"|(?i:introduction|overview|references|(?:table of )?contents)[ \t]*$"
    r"|(?i:key[ -]?words|index terms)\b)",
    re.M,
)


def _usable_title(text: str) -> str:
    title = " ".join(_INVALID_XML.sub("", text).split())
    return "" if title.casefold() in {"untitled", "untitled document"} else title


def _pdf_title(document: PDFDocument) -> str:
    for info in document.info:
        value = resolve1(info.get("Title"))
        if isinstance(value, bytes):
            text = (
                value.decode("utf-8-sig", errors="replace")
                if value.startswith(b"\xef\xbb\xbf")
                else decode_text(value)
            )
            if title := _usable_title(text):
                return title

    # Some PDF writers only set the Dublin Core title in the XMP packet.
    stream = resolve1(document.catalog.get("Metadata"))
    if isinstance(stream, PDFStream):
        try:
            xml = etree.fromstring(
                stream.get_data(),
                etree.XMLParser(resolve_entities=False, no_network=True),
            )
        except (etree.XMLSyntaxError, PSException, PDFException):
            return ""
        dc_title = xml.find(".//{http://purl.org/dc/elements/1.1/}title")
        if dc_title is not None:
            translations = dc_title.findall(
                ".//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li"
            )
            translations.sort(
                key=lambda node: node.get("{http://www.w3.org/XML/1998/namespace}lang")
                != "x-default"
            )
            for node in translations or [dc_title]:
                if title := _usable_title(node.text or ""):
                    return title
    return ""


def _text_boxes(layout: LTPage | LTFigure) -> Iterator[LTTextBox]:
    for item in layout:
        if isinstance(item, LTTextBox):
            yield item
        elif isinstance(item, LTFigure):
            yield from _text_boxes(item)


def _page_paragraphs(page: LTPage) -> list[str]:
    # Find a gutter near the center; the two columns can have different widths.
    boxes = sorted(_text_boxes(page), key=lambda box: (-box.y1, box.x0))
    center = (page.x0 + page.x1) / 2
    cuts = (page.x0 + page.width * pct / 100 for pct in range(30, 71, 2))
    split = min(
        cuts, key=lambda x: (sum(b.x0 < x < b.x1 for b in boxes), abs(x - center))
    )
    # A box spanning the gutter (often a heading) separates horizontal bands.
    # Within a band, two vertically overlapping columns with a clear gutter read
    # down the left column first. Sparse single-column notes retain vertical order.
    ordered: list[LTTextBox] = []
    band: list[LTTextBox] = []

    def flush_band() -> None:
        left = [box for box in band if box.x0 < split]
        right = [box for box in band if box.x0 >= split]
        if (
            left
            and right
            and min(b.x0 for b in right) - max(b.x1 for b in left) >= page.width * 0.025
            and min(left[0].y1, right[0].y1)
            > max(min(b.y0 for b in left), min(b.y0 for b in right))
        ):
            ordered.extend(left + right)
        else:
            ordered.extend(band)
        band.clear()

    for box in boxes:
        if box.x0 < split < box.x1:
            flush_band()
            ordered.append(box)
        else:
            band.append(box)
    flush_band()
    paragraphs = []
    for box in ordered:
        text = _INVALID_XML.sub("", box.get_text()).strip()
        if text:
            # Keep a visible hyphen attached to its word across a soft line wrap.
            paragraphs.append(
                re.sub(r"(?<=\w)-\n(?=\w)", "-", text).replace("\u00ad\n", "")
            )
    return paragraphs


def read_pdf(path: Path) -> tuple[str, list[list[str]]]:
    """Return the title and ordered text boxes for every physical page."""
    pages = []
    try:
        with path.open("rb") as stream:
            document = PDFDocument(PDFParser(stream))
            title = _pdf_title(document) or path.stem
            resources = PDFResourceManager()
            device = PDFPageAggregator(resources, laparams=LAParams(all_texts=True))
            interpreter = PDFPageInterpreter(resources, device)
            for page in PDFPage.create_pages(document):
                interpreter.process_page(page)
                pages.append(_page_paragraphs(device.get_result()))
    except PDFPasswordIncorrect as exc:
        raise ValueError("PDF requires a password") from exc
    except (PSException, PDFException) as exc:
        raise ValueError(f"Cannot read PDF: {exc}") from exc
    if not any(pages):
        raise ValueError("PDF has no extractable text. OCR is needed to import it.")
    return title, pages


def _summary_blocks(page: list[str], title: str) -> Iterator[str]:
    """Omit contents entries and page furniture from stage one only."""
    contents = False
    last_leader = max(
        (i for i, box in enumerate(page) if _DOT_LEADER.search(box)), default=-1
    )
    for i, box in enumerate(page):
        lines = []
        for line in box.splitlines():
            line = line.strip()
            if line.casefold() in {"contents", "table of contents"}:
                contents = True
            elif _DOT_LEADER.search(line):
                contents = i != last_leader
            elif line.casefold() != title.casefold() and not _PAGE_NUMBER.fullmatch(
                line
            ):
                if (
                    contents
                    and i >= last_leader
                    and line.endswith((".", "。"))
                    and _is_prose(line)
                ):
                    contents = False
                if contents:
                    continue
                lines.append(line)
        if text := "\n".join(lines).strip():
            yield text


def _is_prose(text: str) -> bool:
    # Contents listings can span multiple lines in a single layout box.
    if re.search(r"^(?:\d+\.\d+(?:\.\d+)*\b|\d+[.)]\s)", text, re.M):
        return False
    words = text.split()
    return bool(
        text
        and text[0].isalnum()
        and (
            len(words) >= 15
            or (len(words) >= 5 and re.search(r"(?<!\d)[.!?](?:\s|$)", text))
            or (len(text) >= 15 and re.search(r"[。！？]", text))
        )
    )


def _labeled_abstract(boxes: list[str]) -> str | None:
    for i, box in enumerate(boxes):
        label = _ABSTRACT.search(box)
        if label is None:
            continue
        parts = []
        for j in range(i, len(boxes)):
            paragraph = boxes[j] if j != i else box[label.end() :].strip()
            boundary = _NEXT_SECTION.search(paragraph)
            if boundary:
                parts.append(paragraph[: boundary.start()])
                break
            if (
                parts
                and 1 < len(paragraph.split()) <= 8
                and paragraph.istitle()
                and paragraph[-1].isalpha()
            ):
                break
            if paragraph:
                parts.append(paragraph)
        else:
            # Without a clear end, only the first labeled paragraph is identifiable.
            parts = parts[:1]
        if abstract := " ".join(" ".join(parts).split()):
            return abstract
    return None


def summary_for_pdf(title: str, pages: list[list[str]]) -> tuple[str | None, list[str]]:
    """Prefer a labeled abstract, otherwise excerpt the first substantive paragraph."""
    candidates = [box for page in pages for box in _summary_blocks(page, title)]
    if abstract := _labeled_abstract(candidates):
        return abstract, []
    for box in candidates:
        if _is_prose(box):
            return None, [box]
    # A document made entirely of short notes can still supply an excerpt.
    return None, candidates or [box for page in pages for box in page]
