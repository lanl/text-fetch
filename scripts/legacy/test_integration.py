"""Integration tests for the PDF → JATS pipeline.

These tests require GROBID to be running at localhost:8070.
Run with: pytest tests/test_integration.py -v
Skip with: pytest -m "not slow"
"""

import os
import subprocess
import tempfile

import pytest
import requests

from pdf_to_jats import (
    find_pdfs,
    grobid_process,
    parse_tei_fields,
    tei_to_jats,
)


def grobid_is_running(url: str = "http://localhost:8070") -> bool:
    """Check if GROBID service is available."""
    try:
        r = requests.get(f"{url}/api/isalive", timeout=5)
        return r.status_code == 200
    except Exception:
        return False


@pytest.fixture
def real_pdf_path():
    """Find a real PDF in Manuscripts/ for testing."""
    if not os.path.isdir("Manuscripts"):
        pytest.skip("Manuscripts/ directory not found")

    pdfs = find_pdfs("Manuscripts")
    if not pdfs:
        pytest.skip("No PDFs found in Manuscripts/")

    return pdfs[0]


@pytest.fixture
def grobid_url():
    """GROBID service URL."""
    return "http://localhost:8070"


class TestGrobidIntegration:
    """Tests requiring GROBID to be running."""

    @pytest.mark.slow
    def test_grobid_is_reachable(self, grobid_url):
        """Verify GROBID is running before other tests."""
        if not grobid_is_running(grobid_url):
            pytest.skip("GROBID not running at localhost:8070")

        r = requests.get(f"{grobid_url}/api/isalive", timeout=5)
        assert r.status_code == 200

    @pytest.mark.slow
    def test_process_pdf_to_tei(self, real_pdf_path, grobid_url):
        """Test processing a real PDF through GROBID."""
        if not grobid_is_running(grobid_url):
            pytest.skip("GROBID not running at localhost:8070")

        tei_xml, source = grobid_process(
            real_pdf_path,
            grobid_url,
            prefer_fulltext=True,
            ocr=False,
            timeout=120,
        )

        assert tei_xml is not None, f"GROBID returned no TEI for {real_pdf_path}"
        assert source in ("grobid-fulltext", "grobid-header")
        assert tei_xml.strip().startswith("<?xml") or tei_xml.strip().startswith("<TEI")

    @pytest.mark.slow
    def test_parse_grobid_tei(self, real_pdf_path, grobid_url):
        """Test parsing TEI from GROBID output."""
        if not grobid_is_running(grobid_url):
            pytest.skip("GROBID not running at localhost:8070")

        tei_xml, _ = grobid_process(
            real_pdf_path,
            grobid_url,
            prefer_fulltext=False,
            ocr=False,
            timeout=120,
        )

        if tei_xml is None:
            pytest.skip("GROBID couldn't process PDF")

        fields = parse_tei_fields(tei_xml)

        # Should have at least some fields populated
        assert isinstance(fields, dict)
        assert "first_author" in fields
        assert "title" in fields
        assert "year" in fields

    @pytest.mark.slow
    def test_full_pipeline_pdf_to_jats(self, real_pdf_path, grobid_url):
        """Test complete pipeline: PDF → TEI → JATS."""
        if not grobid_is_running(grobid_url):
            pytest.skip("GROBID not running at localhost:8070")

        if not os.path.exists("tei2jats.xsl"):
            pytest.skip("tei2jats.xsl not found")

        # Step 1: PDF → TEI via GROBID
        tei_xml, source = grobid_process(
            real_pdf_path,
            grobid_url,
            prefer_fulltext=True,
            ocr=False,
            timeout=120,
        )

        if tei_xml is None:
            pytest.skip("GROBID couldn't process PDF")

        # Step 2: Parse TEI metadata
        fields = parse_tei_fields(tei_xml)
        assert isinstance(fields, dict)

        # Step 3: TEI → JATS
        jats_xml = tei_to_jats(tei_xml, "tei2jats.xsl")

        assert jats_xml is not None
        assert "<?xml" in jats_xml or "<article" in jats_xml.lower()

        # Verify it's valid XML by parsing
        from lxml import etree

        doc = etree.fromstring(jats_xml.encode("utf-8"))
        assert doc is not None


class TestScriptIntegration:
    """Test the pdf_to_jats.py script as a whole."""

    @pytest.mark.slow
    def test_script_produces_csv(self, grobid_url):
        """Test that the script produces valid CSV output."""
        if not grobid_is_running(grobid_url):
            pytest.skip("GROBID not running at localhost:8070")

        if not os.path.isdir("Manuscripts"):
            pytest.skip("Manuscripts/ directory not found")

        pdfs = find_pdfs("Manuscripts")
        if not pdfs:
            pytest.skip("No PDFs found in Manuscripts/")

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "output.csv")
            tei_dir = os.path.join(tmpdir, "tei_cache")
            jats_dir = os.path.join(tmpdir, "jats_cache")

            # Process just one PDF to keep test fast
            result = subprocess.run(
                [
                    "python",
                    "pdf_to_jats.py",
                    "Manuscripts",
                    "--out",
                    csv_path,
                    "--grobid-url",
                    grobid_url,
                    "--save-tei",
                    "--tei-out",
                    tei_dir,
                    "--save-jats",
                    "--jats-out",
                    jats_dir,
                    "--only",
                    os.path.basename(pdfs[0]),
                    "--verbose",
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )

            assert result.returncode == 0, f"Script failed: {result.stderr}"
            assert os.path.exists(csv_path), "CSV not created"

            # Verify CSV has content
            with open(csv_path) as f:
                lines = f.readlines()
            assert len(lines) >= 2, "CSV should have header + at least 1 row"

            # Verify header columns
            header = lines[0].strip()
            assert "first_author" in header
            assert "DOI" in header
            assert "jats_path" in header
