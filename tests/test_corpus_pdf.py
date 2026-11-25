"""Exercise the installed corpus import path with real text and raster PDFs."""

import shutil
import tarfile
from pathlib import Path
from xml.etree import ElementTree as ET

from click.testing import CliRunner
from text_fetch.cli import cli
from text_fetch.corpus_pdf import summary_for_pdf
from text_fetch.pmc import JATSValidator, ValidationStatus

PDFS = Path(__file__).parent / "fixtures" / "corpus"


def test_pdf_title_abstract_and_two_column_reading_order(tmp_path: Path) -> None:
    output = tmp_path / "study.xml"
    result = CliRunner().invoke(
        cli, ["corpus", "import", str(PDFS / "two-column.pdf"), "--out", str(output)]
    )
    assert result.exit_code == 0, result.output
    assert JATSValidator().validate_file(output).status == ValidationStatus.VALID
    root = ET.parse(output)
    assert root.findtext(".//article-title") == "Cedar grove – gauge study"
    assert root.findtext(".//abstract/p") == (
        "Rain measurements were compared at two fixed stations. "
        "Both instruments were checked before each observation."
    )
    assert root.find(".//abstract[@abstract-type='excerpt']") is None
    pages = root.findall("./body/sec[@sec-type='page']")
    assert [p.findtext("label") for p in pages] == ["1", "2"]
    assert (
        pages[0].findtext("p[last()]")
        == "A copper gauge was placed beside the cedar grove."
    )
    # The PDF draws alternating columns. Reading down each column preserves meaning.
    assert [p.text for p in pages[1].findall("p")] == [
        "Western station readings.",
        "The western gauge collected seventeen millimeters.",
        "Level it.",
        "Eastern station readings.",
        "The eastern gauge collected twelve millimeters.",
        "Log the time.",
    ]


def test_mixed_archive_excerpts_prose_and_preserves_physical_pages(
    tmp_path: Path,
) -> None:
    notes = tmp_path / "notes"
    (notes / "guides").mkdir(parents=True)
    shutil.copyfile(PDFS / "field-guide.pdf", notes / "guides" / "manual.PDF")
    (notes / "setup.md").write_text("# Setup\n\nBring the notebook.", encoding="utf-8")
    (notes / "count.txt").write_text("Three stations.", encoding="utf-8")
    output = tmp_path / "survey.tgz"
    result = CliRunner().invoke(
        cli, ["corpus", "import", str(notes), "--out", str(output)]
    )
    assert result.exit_code == 0, result.output
    with tarfile.open(output) as archive:
        assert set(archive.getnames()) == {
            "guides/manual.PDF.xml",
            "setup.md.xml",
            "count.txt.xml",
        }
        member = archive.extractfile("guides/manual.PDF.xml")
        assert member is not None
        root = ET.fromstring(member.read())
    assert root.findtext(".//article-id") == "guides/manual.PDF"
    assert root.findtext(".//article-title") == "manual"
    assert root.findtext(".//abstract[@abstract-type='excerpt']/p") == (
        "Field crews measured overnight rainfall at the cedar grove."
    )
    pages = root.findall("./body/sec")
    assert [s.get("id") for s in pages] == ["page-1", "page-2", "page-3", "page-4"]
    assert pages[1].findtext("p") == "Table of Contents"
    assert not pages[2].findall("p")
    assert pages[3].findtext("p[last()]") == "Stop."


def test_form_text_and_xmp_title(tmp_path: Path) -> None:
    output = tmp_path / "river.xml"
    result = CliRunner().invoke(
        cli, ["corpus", "import", str(PDFS / "form-text.pdf"), "--out", str(output)]
    )
    assert result.exit_code == 0, result.output
    root = ET.parse(output)
    assert root.findtext(".//article-title") == "River log"
    assert (
        root.findtext(".//abstract/p")
        == "Several separate records document the river level."
    )
    assert (
        root.findtext("./body/sec/p[last()]") == "This is the body of the field note."
    )


def test_image_only_pdf_reports_ocr_and_preserves_archive(tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("Existing note.")
    output = tmp_path / "notes.tar.gz"
    args = ["corpus", "import", str(tmp_path), "--out", str(output)]
    runner = CliRunner()
    assert runner.invoke(cli, args).exit_code == 0
    original = output.read_bytes()
    scan = tmp_path / "scan.pdf"
    shutil.copyfile(PDFS / "scan.pdf", scan)
    result = runner.invoke(cli, args)
    assert result.exit_code != 0
    assert str(scan) in result.output
    assert "OCR is needed" in result.output
    assert output.read_bytes() == original


def test_invalid_pdf_reports_a_read_error(tmp_path: Path) -> None:
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    output = tmp_path / "broken.xml"
    result = CliRunner().invoke(
        cli, ["corpus", "import", str(broken), "--out", str(output)]
    )
    assert result.exit_code != 0
    assert "broken.pdf" in result.output
    assert "Cannot read PDF" in result.output
    assert not output.exists()


def test_abstract_continues_across_pages_and_stops_at_next_heading() -> None:
    pages = [
        ["Abstract  The gauge was calibrated in the field.", "1"],
        [
            "Two instruments confirmed the reading.",
            "Field Procedures",
            "Bring a notebook.",
        ],
    ]
    abstract, _ = summary_for_pdf("Gauge calibration", pages)
    assert (
        abstract
        == "The gauge was calibrated in the field. Two instruments confirmed the reading."
    )


def test_excerpt_survives_continued_contents_and_short_notes() -> None:
    pages = [
        ["Contents", "Calibration . . . . . 3"],
        ["2.1 Getting started", "2.2 Which sensors are installed?", "3"],
        [
            "Abstract Data Types",
            "This manual describes the types supported by the reader.",
        ],
    ]
    assert summary_for_pdf("Manual", pages) == (
        None,
        ["This manual describes the types supported by the reader."],
    )
    assert summary_for_pdf("Checklist", [["Stop."]]) == (None, ["Stop."])
