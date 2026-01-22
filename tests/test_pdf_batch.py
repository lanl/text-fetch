"""Tests for PDF batch processing."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from text_fetch.pdf import (
    PDFProcessingResult,
    _parse_tei_metadata,
    find_pdfs,
    process_pdf_batch,
)
from text_fetch.pmc import ValidationStatus

if TYPE_CHECKING:
    pass


class TestFindPdfs:
    """Tests for find_pdfs function."""

    def test_finds_pdfs_recursively(self, tmp_path: Path) -> None:
        """Finds PDFs in nested directories."""
        (tmp_path / "a.pdf").touch()
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.pdf").touch()

        pdfs = find_pdfs(tmp_path)

        assert len(pdfs) == 2
        assert any(p.name == "a.pdf" for p in pdfs)
        assert any(p.name == "b.pdf" for p in pdfs)

    def test_ignores_non_pdf(self, tmp_path: Path) -> None:
        """Ignores non-PDF files."""
        (tmp_path / "doc.txt").touch()
        (tmp_path / "image.png").touch()
        (tmp_path / "real.pdf").touch()

        pdfs = find_pdfs(tmp_path)

        assert len(pdfs) == 1
        assert pdfs[0].name == "real.pdf"

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Returns empty list for empty directory."""
        pdfs = find_pdfs(tmp_path)
        assert pdfs == []

    def test_deeply_nested(self, tmp_path: Path) -> None:
        """Finds PDFs in deeply nested directories."""
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "deep.pdf").touch()

        pdfs = find_pdfs(tmp_path)

        assert len(pdfs) == 1
        assert pdfs[0].name == "deep.pdf"


class TestParseTeiMetadata:
    """Tests for TEI metadata parsing."""

    def test_extracts_basic_fields(self) -> None:
        """Extracts DOI, title, author from TEI."""
        tei = """<?xml version="1.0"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0">
          <teiHeader>
            <fileDesc>
              <titleStmt>
                <title>Test Paper Title</title>
              </titleStmt>
            </fileDesc>
            <sourceDesc>
              <biblStruct>
                <analytic>
                  <author>
                    <persName><surname>Smith</surname></persName>
                  </author>
                  <idno type="DOI">10.1234/test</idno>
                </analytic>
                <monogr>
                  <imprint><date when="2024"/></imprint>
                </monogr>
              </biblStruct>
            </sourceDesc>
          </teiHeader>
        </TEI>"""

        metadata = _parse_tei_metadata(tei)

        assert metadata["DOI"] == "10.1234/test"
        assert metadata["first_author"] == "Smith"
        assert metadata["year"] == "2024"

    def test_handles_missing_fields(self) -> None:
        """Returns empty dict for minimal TEI."""
        tei = """<?xml version="1.0"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0"/>"""

        metadata = _parse_tei_metadata(tei)

        assert metadata == {}

    def test_handles_invalid_xml(self) -> None:
        """Returns empty dict for invalid XML."""
        metadata = _parse_tei_metadata("not xml")

        assert metadata == {}

    def test_extracts_pmid_pmcid(self) -> None:
        """Extracts PMID and PMCID when present."""
        tei = """<?xml version="1.0"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0">
          <teiHeader>
            <sourceDesc>
              <biblStruct>
                <analytic>
                  <idno type="PMID">12345678</idno>
                  <idno type="PMCID">PMC9876543</idno>
                </analytic>
              </biblStruct>
            </sourceDesc>
          </teiHeader>
        </TEI>"""

        metadata = _parse_tei_metadata(tei)

        assert metadata["PMID"] == "12345678"
        assert metadata["PMCID"] == "PMC9876543"

    def test_extracts_journal(self) -> None:
        """Extracts journal title."""
        tei = """<?xml version="1.0"?>
        <TEI xmlns="http://www.tei-c.org/ns/1.0">
          <teiHeader>
            <sourceDesc>
              <biblStruct>
                <monogr>
                  <title level="j">Nature Methods</title>
                </monogr>
              </biblStruct>
            </sourceDesc>
          </teiHeader>
        </TEI>"""

        metadata = _parse_tei_metadata(tei)

        assert metadata["journal"] == "Nature Methods"


class TestPDFProcessingResult:
    """Tests for PDFProcessingResult dataclass."""

    def test_to_dict(self) -> None:
        """Converts to dictionary."""
        result = PDFProcessingResult(
            pdf_path="/path/to/paper.pdf",
            sha1="abc123",
            source="grobid-fulltext",
            validation=ValidationStatus.VALID,
            metadata={"DOI": "10.1234/test"},
            notes=["test_note"],
        )

        d = result.to_dict()

        assert d["pdf_path"] == "/path/to/paper.pdf"
        assert d["sha1"] == "abc123"
        assert d["source"] == "grobid-fulltext"
        assert d["validation"] == "valid"
        assert d["metadata"]["DOI"] == "10.1234/test"
        assert "test_note" in d["notes"]

    def test_default_values(self) -> None:
        """Default values are set correctly."""
        result = PDFProcessingResult(
            pdf_path="/test.pdf",
            sha1="xyz",
        )

        assert result.source == "unknown"
        assert result.validation == ValidationStatus.INCOMPLETE
        assert result.metadata == {}
        assert result.notes == []


class TestProcessPdfBatch:
    """Tests for process_pdf_batch function."""

    def test_creates_output_structure(self, tmp_path: Path) -> None:
        """Creates valid/ and incomplete/ directories."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        (pdf_dir / "test.pdf").write_bytes(b"%PDF-1.4 test content")

        out_dir = tmp_path / "output"

        with patch("text_fetch.pdf.GROBIDClient") as mock_grobid:
            mock_grobid.return_value.process_pdf.return_value = None

            result = process_pdf_batch(
                pdf_dir=pdf_dir,
                output_dir=out_dir,
                grobid_url="http://localhost:8070",
            )

        assert (out_dir / "valid").is_dir()
        assert (out_dir / "incomplete").is_dir()
        assert result["total"] == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Returns zero counts for empty directory."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()

        out_dir = tmp_path / "output"

        result = process_pdf_batch(
            pdf_dir=pdf_dir,
            output_dir=out_dir,
        )

        assert result["total"] == 0
        assert result["valid"] == 0
        assert result["errors"] == 0

    def test_progress_callback(self, tmp_path: Path) -> None:
        """Progress callback is called."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        (pdf_dir / "test.pdf").write_bytes(b"%PDF-1.4")

        out_dir = tmp_path / "output"
        calls: list[tuple[str, int, int]] = []

        def callback(name: str, current: int, total: int) -> None:
            calls.append((name, current, total))

        with patch("text_fetch.pdf.GROBIDClient") as mock_grobid:
            mock_grobid.return_value.process_pdf.return_value = None

            process_pdf_batch(
                pdf_dir=pdf_dir,
                output_dir=out_dir,
                progress_callback=callback,
            )

        assert len(calls) == 1
        assert calls[0][0] == "test.pdf"
        assert calls[0][1] == 1
        assert calls[0][2] == 1

    @patch("text_fetch.pdf.GROBIDClient")
    def test_tei_caching(self, mock_grobid_class: MagicMock, tmp_path: Path) -> None:
        """TEI files are cached when save_tei=True."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        (pdf_dir / "test.pdf").write_bytes(b"%PDF-1.4")

        out_dir = tmp_path / "output"

        mock_grobid = MagicMock()
        mock_grobid_class.return_value = mock_grobid
        mock_grobid.process_pdf.return_value = (
            '<?xml version="1.0"?>' '<TEI xmlns="http://www.tei-c.org/ns/1.0"/>'
        )
        mock_grobid.tei_to_jats.return_value = (
            '<?xml version="1.0"?>' "<article><front><title/></front></article>"
        )

        process_pdf_batch(
            pdf_dir=pdf_dir,
            output_dir=out_dir,
            save_tei=True,
        )

        assert (out_dir / "tei_cache").is_dir()

    @patch("text_fetch.pdf.GROBIDClient")
    def test_handles_grobid_failure(
        self, mock_grobid_class: MagicMock, tmp_path: Path
    ) -> None:
        """Handles GROBID processing failure."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        (pdf_dir / "test.pdf").write_bytes(b"%PDF-1.4")

        out_dir = tmp_path / "output"

        mock_grobid = MagicMock()
        mock_grobid_class.return_value = mock_grobid
        mock_grobid.process_pdf.return_value = None

        result = process_pdf_batch(
            pdf_dir=pdf_dir,
            output_dir=out_dir,
        )

        assert result["errors"] == 1
        assert result["valid"] == 0


class TestCliPdfBatch:
    """Tests for text-fetch pdf batch CLI command."""

    def test_pdf_batch_help(self) -> None:
        """pdf batch shows help."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["pdf", "batch", "--help"])

        assert result.exit_code == 0
        assert "--dir" in result.output
        assert "--out" in result.output
        assert "--grobid-url" in result.output

    def test_pdf_batch_requires_dir(self) -> None:
        """pdf batch requires --dir option."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["pdf", "batch", "--out", "/tmp/out"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_pdf_batch_requires_out(self) -> None:
        """pdf batch requires --out option."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["pdf", "batch", "--dir", "."])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_pdf_batch_no_pdfs_found(self, tmp_path: Path) -> None:
        """pdf batch handles empty directory."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        pdf_dir = tmp_path / "empty"
        pdf_dir.mkdir()
        out_dir = tmp_path / "output"

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["pdf", "batch", "--dir", str(pdf_dir), "--out", str(out_dir)],
        )

        assert result.exit_code == 0
        assert "No PDF files found" in result.output
