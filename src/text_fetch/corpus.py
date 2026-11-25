"""Convert local Markdown and plain-text documents to the JATS used by LitKit."""

from __future__ import annotations

import io
import re
import tarfile
from collections.abc import Iterator, Sequence
from pathlib import Path
from stat import S_ISREG
from tempfile import TemporaryDirectory

import yaml
from lxml import etree
from markdown_it import MarkdownIt
from markdown_it.token import Token

_SUFFIXES = {".md", ".markdown", ".txt"}
_HEADER_KEYS = ("title", "abstract", "summary", "description")
_HEADER_FIELD = re.compile(r"^(?:" + "|".join(_HEADER_KEYS) + r")[ \t]*:", re.MULTILINE)
_FRONT_MATTER = re.compile(
    r"\A---[ \t]*\n(.*?)^(?:---|\.\.\.)[ \t]*(?:\n|$)", re.MULTILINE | re.DOTALL
)
_MARKDOWN = MarkdownIt("commonmark", {"html": False})


def _read_header(text: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return {}, text
    # BaseLoader keeps scalar values as written (including dates and numbers).
    try:
        fields = yaml.load(match[1], Loader=yaml.BaseLoader)
    except yaml.YAMLError as exc:
        # Two thematic breaks can surround ordinary Markdown or plain text.
        if _HEADER_FIELD.search(match[1]):
            raise ValueError(f"Invalid YAML front matter: {exc}") from exc
        return {}, text
    if not isinstance(fields, dict) or not any(key in fields for key in _HEADER_KEYS):
        return {}, text
    header = {}
    for key in _HEADER_KEYS:
        if key in fields:
            if not isinstance(fields[key], str):
                raise ValueError(f"Expected text for {key!r} in YAML front matter")
            header[key] = fields[key].strip()
    return header, text[match.end() :]


def _inline_text(tokens: Sequence[Token]) -> str:
    parts = []
    for token in tokens:
        if token.children:
            parts.append(_inline_text(token.children))
        elif token.type in {"softbreak", "hardbreak"}:
            parts.append("\n")
        else:
            parts.append(token.content)
    return "".join(parts)


def _markdown_blocks(text: str) -> Iterator[tuple[int, str]]:
    """Yield heading levels and body paragraphs in source order (level zero is body)."""
    level = 0
    for token in _MARKDOWN.parse(text):
        if token.type == "heading_open" and token.level == 0:
            level = int(token.tag[1:])
        elif token.type == "inline":
            yield level, _inline_text(token.children or [])
            level = 0
        elif token.type in {"fence", "code_block"}:
            yield 0, token.content.rstrip("\n")


def document_to_jats(text: str, source: Path) -> bytes:
    """Convert one document. The corpus-relative source path identifies it in JATS."""
    suffix = source.suffix.lower()
    if suffix not in _SUFFIXES:
        raise ValueError("Expected a .md, .markdown, or .txt document")
    if "\x00" in text:
        raise ValueError("Expected UTF-8 text without NUL characters")
    text = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    header, text = _read_header(text)
    if suffix == ".txt":
        blocks = [(0, p.strip()) for p in re.split(r"\n\s*\n", text)]
    else:
        blocks = list(_markdown_blocks(text))

    paragraphs = [value for level, value in blocks if not level and value.strip()]
    if not paragraphs:
        raise ValueError("Document has no body text")
    first_heading = next(
        (value for level, value in blocks if level and value.strip()), ""
    )
    title = header.get("title") or first_heading or source.stem
    summary = (
        header.get("abstract") or header.get("summary") or header.get("description")
    )

    article = etree.Element("article")
    meta = etree.SubElement(etree.SubElement(article, "front"), "article-meta")
    etree.SubElement(
        meta, "article-id", {"pub-id-type": "publisher-id"}
    ).text = source.as_posix()
    titles = etree.SubElement(meta, "title-group")
    etree.SubElement(titles, "article-title").text = title
    abstract = etree.SubElement(meta, "abstract")
    if not summary:
        sentences = re.split(r"(?<=[.!?])\s+", " ".join(paragraphs), maxsplit=3)
        summary = " ".join(" ".join(sentences[:3]).split()[:100])
        abstract.set("abstract-type", "excerpt")
    etree.SubElement(abstract, "p").text = summary

    body = etree.SubElement(article, "body")
    sections = [(0, body)]
    for index, (level, value) in enumerate(blocks):
        if not value.strip():
            continue
        if level:
            if index == 0 and value == title:
                continue
            while sections[-1][0] >= level:
                sections.pop()
            section = etree.SubElement(sections[-1][1], "sec")
            etree.SubElement(section, "title").text = value
            sections.append((level, section))
        else:
            etree.SubElement(sections[-1][1], "p").text = value

    return etree.tostring(
        article, encoding="UTF-8", xml_declaration=True, pretty_print=True
    )


def _read_jats(path: Path, relative: Path) -> bytes:
    try:
        return document_to_jats(path.read_text(encoding="utf-8"), relative)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc


def _source_files(root: Path) -> Iterator[Path]:
    def report_error(error: OSError) -> None:
        raise error

    for directory, _, names in root.walk(on_error=report_error):
        for name in names:
            path = directory / name
            if path.suffix.lower() in _SUFFIXES and S_ISREG(path.stat().st_mode):
                yield path


def import_corpus(source: Path, output: Path) -> int:
    """Write a JATS archive or a single XML file and return the document count."""
    single_xml = output.suffix.lower() == ".xml"
    if not single_xml and not output.name.lower().endswith((".tar.gz", ".tgz")):
        raise ValueError("Use .tar.gz for a corpus, or .xml for a single document")
    if source.is_dir():
        if single_xml:
            raise ValueError("XML output requires a single input file")
        files = sorted(_source_files(source))
        if not files:
            raise ValueError(f"No Markdown or TXT documents found in {source}")
        root = source
    else:
        if source.suffix.lower() not in _SUFFIXES:
            raise ValueError(f"Expected a .md, .markdown, or .txt document: {source}")
        files = [source]
        root = source.parent

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        staged = Path(staging) / output.name
        if single_xml:
            staged.write_bytes(_read_jats(source, Path(source.name)))
        else:
            with tarfile.open(staged, "w:gz") as archive:
                for path in files:
                    relative = path.relative_to(root)
                    data = _read_jats(path, relative)
                    member = tarfile.TarInfo(relative.as_posix() + ".xml")
                    member.size = len(data)
                    # The tar header stores seconds. LitKit also compares the fraction.
                    mtime = path.stat().st_mtime
                    member.mtime = int(mtime)
                    member.pax_headers = {"mtime": str(mtime)}
                    archive.addfile(member, io.BytesIO(data))
        staged.replace(output)
    return len(files)
