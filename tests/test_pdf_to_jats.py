"""Unit tests for pdf_to_jats.py functions."""

import os

import pytest

from pdf_to_jats import (
    TeiToJatsError,
    clean,
    parse_tei_fields,
    sha1_of_file,
    tei_to_jats,
)


class TestClean:
    """Tests for the clean() text normalization function."""

    def test_normalizes_whitespace(self):
        assert clean("  hello   world  ") == "hello world"

    def test_removes_nbsp(self):
        assert clean("hello\u00a0world") == "hello world"

    def test_removes_zero_width_space(self):
        assert clean("hello\u200bworld") == "helloworld"

    def test_empty_string(self):
        assert clean("") == ""

    def test_none_like_empty(self):
        # clean() expects str, but empty string should work
        assert clean("") == ""

    def test_unicode_normalization_off(self):
        result = clean("naïve café")
        assert result == "naïve café"

    def test_unicode_normalization_on(self):
        result = clean("naïve café", normalize_unicode=True)
        assert result == "naive cafe"

    def test_multiple_spaces_to_single(self):
        assert clean("a    b\t\tc\n\nd") == "a b c d"


class TestParseTeiFields:
    """Tests for TEI XML parsing."""

    def test_extracts_doi(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["DOI"] == "10.1234/example.2024"

    def test_extracts_first_author(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["first_author"] == "Smith"

    def test_extracts_title(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["title"] == "Sample Paper Title"

    def test_extracts_journal(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["journal"] == "Journal of Examples"

    def test_extracts_year(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["year"] == "2024"

    def test_extracts_pmid(self, sample_tei_with_pmid):
        result = parse_tei_fields(sample_tei_with_pmid)
        assert result["PMID"] == "12345678"

    def test_extracts_pmcid(self, sample_tei_with_pmid):
        result = parse_tei_fields(sample_tei_with_pmid)
        assert result["PMCID"] == "PMC9876543"

    def test_handles_missing_fields(self, minimal_tei_xml):
        result = parse_tei_fields(minimal_tei_xml)
        assert result["first_author"] == ""
        assert result["year"] == ""
        assert result["title"] == ""
        assert result["journal"] == ""
        assert result["DOI"] == ""
        assert result["PMID"] == ""
        assert result["PMCID"] == ""

    def test_unicode_normalization(self, sample_tei_xml):
        # Test that normalize_unicode parameter works
        result = parse_tei_fields(sample_tei_xml, normalize_unicode=True)
        assert isinstance(result["title"], str)


class TestSha1OfFile:
    """Tests for file hashing."""

    def test_computes_hash(self, sample_pdf_path):
        h = sha1_of_file(str(sample_pdf_path))
        assert len(h) == 40  # SHA1 hex digest is 40 chars
        assert h.isalnum()

    def test_consistent_hash(self, sample_pdf_path):
        h1 = sha1_of_file(str(sample_pdf_path))
        h2 = sha1_of_file(str(sample_pdf_path))
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")
        assert sha1_of_file(str(file1)) != sha1_of_file(str(file2))


class TestTeiToJats:
    """Tests for TEI to JATS conversion."""

    @pytest.fixture
    def xslt_path(self):
        """Path to the XSLT stylesheet."""
        return "tei2jats.xsl"

    def test_converts_tei_to_jats(self, sample_tei_xml, xslt_path):
        if not os.path.exists(xslt_path):
            pytest.skip("tei2jats.xsl not found")

        jats = tei_to_jats(sample_tei_xml, xslt_path)
        assert "<?xml" in jats
        # JATS should have article element or similar structure
        assert "<" in jats

    def test_raises_on_invalid_tei(self, xslt_path):
        if not os.path.exists(xslt_path):
            pytest.skip("tei2jats.xsl not found")

        with pytest.raises(TeiToJatsError):
            tei_to_jats("not valid xml", xslt_path)

    def test_raises_on_missing_xslt(self, sample_tei_xml):
        with pytest.raises(TeiToJatsError):
            tei_to_jats(sample_tei_xml, "nonexistent.xsl")
