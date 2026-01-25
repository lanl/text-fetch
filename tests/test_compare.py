"""Tests for corpus comparison."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from click.testing import CliRunner
from text_fetch.cli import cli
from text_fetch.compare import (
    ComparisonResult,
    compare_corpora,
    detect_id_type,
    extract_ids_from_tarball,
    load_corpus_ids,
    normalize_id,
    parse_id_list,
)


class TestDetectIdType:
    """Tests for detect_id_type function."""

    def test_pmcid_uppercase(self) -> None:
        """Test detection of uppercase PMCID."""
        assert detect_id_type("PMC123456") == "pmcid"

    def test_pmcid_lowercase(self) -> None:
        """Test detection of lowercase PMCID."""
        assert detect_id_type("pmc123456") == "pmcid"

    def test_pmcid_mixed_case(self) -> None:
        """Test detection of mixed case PMCID."""
        assert detect_id_type("Pmc123456") == "pmcid"

    def test_doi_simple(self) -> None:
        """Test detection of DOI."""
        assert detect_id_type("10.1016/j.cell.2020.01.001") == "doi"

    def test_doi_with_prefix(self) -> None:
        """Test detection of DOI with prefix."""
        assert detect_id_type("10.1234/example") == "doi"

    def test_pmid_8_digits(self) -> None:
        """Test detection of 8-digit PMID."""
        assert detect_id_type("32847729") == "pmid"

    def test_pmid_7_digits(self) -> None:
        """Test detection of 7-digit PMID."""
        assert detect_id_type("1234567") == "pmid"

    def test_unknown_short(self) -> None:
        """Test unknown for short strings."""
        assert detect_id_type("abc") == "unknown"

    def test_unknown_short_number(self) -> None:
        """Test unknown for short numbers."""
        assert detect_id_type("12345") == "unknown"

    def test_strips_whitespace(self) -> None:
        """Test that whitespace is stripped."""
        assert detect_id_type("  PMC123456  ") == "pmcid"


class TestNormalizeId:
    """Tests for normalize_id function."""

    def test_pmcid_already_normalized(self) -> None:
        """Test PMCID that is already normalized."""
        assert normalize_id("PMC123456") == "PMC123456"

    def test_pmcid_lowercase(self) -> None:
        """Test lowercase PMCID normalization."""
        assert normalize_id("pmc123456") == "PMC123456"

    def test_pmcid_mixed_case(self) -> None:
        """Test mixed case PMCID normalization."""
        assert normalize_id("Pmc789012") == "PMC789012"

    def test_doi_uppercase(self) -> None:
        """Test DOI normalization to lowercase."""
        assert normalize_id("10.1016/J.CELL.2020") == "10.1016/j.cell.2020"

    def test_doi_already_lowercase(self) -> None:
        """Test DOI that is already lowercase."""
        assert normalize_id("10.1234/example") == "10.1234/example"

    def test_pmid_unchanged(self) -> None:
        """Test PMID is unchanged."""
        assert normalize_id("32847729") == "32847729"

    def test_unknown_unchanged(self) -> None:
        """Test unknown IDs are unchanged."""
        assert normalize_id("abc123") == "abc123"


class TestParseIdList:
    """Tests for parse_id_list function."""

    def test_simple_list(self, tmp_path: Path) -> None:
        """Test parsing a simple ID list."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("PMC123456\nPMC789012\n")

        ids, types = parse_id_list(id_file)

        assert ids == {"PMC123456", "PMC789012"}
        assert types["pmcid"] == 2
        assert types["doi"] == 0
        assert types["pmid"] == 0
        assert types["unknown"] == 0

    def test_mixed_types(self, tmp_path: Path) -> None:
        """Test parsing mixed ID types."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("PMC123456\n10.1234/example\n32847729\n")

        ids, types = parse_id_list(id_file)

        assert len(ids) == 3
        assert types["pmcid"] == 1
        assert types["doi"] == 1
        assert types["pmid"] == 1

    def test_comments_ignored(self, tmp_path: Path) -> None:
        """Test that comments are ignored."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("# This is a comment\nPMC123456\n")

        ids, types = parse_id_list(id_file)

        assert ids == {"PMC123456"}
        assert types["pmcid"] == 1

    def test_blank_lines_ignored(self, tmp_path: Path) -> None:
        """Test that blank lines are ignored."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("PMC123456\n\n\nPMC789012\n")

        ids, types = parse_id_list(id_file)

        assert len(ids) == 2

    def test_comments_and_blanks(self, tmp_path: Path) -> None:
        """Test comments and blanks together."""
        content = "# Comment\nPMC123456\n\n# Another comment\nPMC789012\n"
        id_file = tmp_path / "ids.txt"
        id_file.write_text(content)

        ids, types = parse_id_list(id_file)

        assert len(ids) == 2

    def test_normalizes_ids(self, tmp_path: Path) -> None:
        """Test that IDs are normalized."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("pmc123456\n10.1234/EXAMPLE\n")

        ids, types = parse_id_list(id_file)

        assert "PMC123456" in ids
        assert "10.1234/example" in ids

    def test_deduplicates_ids(self, tmp_path: Path) -> None:
        """Test that duplicate IDs are deduplicated."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("PMC123456\nPMC123456\npmc123456\n")

        ids, types = parse_id_list(id_file)

        assert len(ids) == 1
        assert "PMC123456" in ids
        # All three lines were counted
        assert types["pmcid"] == 3


class TestExtractIdsFromTarball:
    """Tests for extract_ids_from_tarball function."""

    def _create_tarball(
        self,
        tmp_path: Path,
        manifest: dict | None = None,
        xml_files: list | None = None,
    ) -> Path:
        """Helper to create a tarball for testing."""
        tarball_path = tmp_path / "corpus.tar.gz"

        with tarfile.open(tarball_path, "w:gz") as tar:
            if manifest is not None:
                manifest_bytes = json.dumps(manifest).encode("utf-8")
                manifest_file = io.BytesIO(manifest_bytes)
                tarinfo = tarfile.TarInfo(name="manifest.json")
                tarinfo.size = len(manifest_bytes)
                tar.addfile(tarinfo, manifest_file)

            if xml_files:
                for filename in xml_files:
                    xml_bytes = b"<article/>"
                    xml_file = io.BytesIO(xml_bytes)
                    tarinfo = tarfile.TarInfo(name=filename)
                    tarinfo.size = len(xml_bytes)
                    tar.addfile(tarinfo, xml_file)

        return tarball_path

    def test_tarball_with_manifest_pmcid(self, tmp_path: Path) -> None:
        """Test extracting PMCIDs from manifest."""
        manifest = {
            "files": [
                {"path": "valid/PMC123456.xml", "pmcid": "PMC123456"},
                {"path": "valid/PMC789012.xml", "pmcid": "PMC789012"},
            ]
        }
        tarball_path = self._create_tarball(tmp_path, manifest=manifest)

        ids, types = extract_ids_from_tarball(tarball_path)

        assert ids == {"PMC123456", "PMC789012"}
        assert types["pmcid"] == 2

    def test_tarball_with_manifest_doi(self, tmp_path: Path) -> None:
        """Test extracting DOIs from manifest."""
        manifest = {
            "files": [
                {"path": "valid/article1.xml", "doi": "10.1234/example1"},
                {"path": "valid/article2.xml", "doi": "10.1234/example2"},
            ]
        }
        tarball_path = self._create_tarball(tmp_path, manifest=manifest)

        ids, types = extract_ids_from_tarball(tarball_path)

        assert len(ids) == 2
        assert types["doi"] == 2

    def test_tarball_with_manifest_priority(self, tmp_path: Path) -> None:
        """Test that PMCID takes priority over DOI."""
        manifest = {
            "files": [
                {
                    "path": "valid/PMC123456.xml",
                    "pmcid": "PMC123456",
                    "doi": "10.1234/example",
                },
            ]
        }
        tarball_path = self._create_tarball(tmp_path, manifest=manifest)

        ids, types = extract_ids_from_tarball(tarball_path)

        assert ids == {"PMC123456"}
        assert types["pmcid"] == 1
        assert types["doi"] == 0

    def test_tarball_fallback_filename(self, tmp_path: Path) -> None:
        """Test falling back to filename when no PMCID/DOI."""
        manifest = {
            "files": [
                {"path": "valid/PMC123456.xml"},
            ]
        }
        tarball_path = self._create_tarball(tmp_path, manifest=manifest)

        ids, types = extract_ids_from_tarball(tarball_path)

        assert ids == {"PMC123456"}
        assert types["pmcid"] == 1

    def test_tarball_no_manifest(self, tmp_path: Path) -> None:
        """Test extracting IDs from XML filenames when no manifest."""
        tarball_path = self._create_tarball(
            tmp_path,
            manifest=None,
            xml_files=["valid/PMC123456.xml", "valid/PMC789012.xml"],
        )

        ids, types = extract_ids_from_tarball(tarball_path)

        assert ids == {"PMC123456", "PMC789012"}
        assert types["pmcid"] == 2


class TestLoadCorpusIds:
    """Tests for load_corpus_ids function."""

    def test_loads_txt_file(self, tmp_path: Path) -> None:
        """Test loading from .txt file."""
        id_file = tmp_path / "ids.txt"
        id_file.write_text("PMC123456\nPMC789012\n")

        ids, types = load_corpus_ids(id_file)

        assert len(ids) == 2
        assert types["pmcid"] == 2

    def test_loads_tar_gz_file(self, tmp_path: Path) -> None:
        """Test loading from .tar.gz file."""
        tarball_path = tmp_path / "corpus.tar.gz"
        manifest = {
            "files": [
                {"path": "valid/PMC123456.xml", "pmcid": "PMC123456"},
            ]
        }
        with tarfile.open(tarball_path, "w:gz") as tar:
            manifest_bytes = json.dumps(manifest).encode("utf-8")
            manifest_file = io.BytesIO(manifest_bytes)
            tarinfo = tarfile.TarInfo(name="manifest.json")
            tarinfo.size = len(manifest_bytes)
            tar.addfile(tarinfo, manifest_file)

        ids, types = load_corpus_ids(tarball_path)

        assert ids == {"PMC123456"}


class TestCompareCorpora:
    """Tests for compare_corpora function."""

    def test_identical_corpora(self, tmp_path: Path) -> None:
        """Test comparing identical corpora."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC123456\nPMC789012\n")
        cand.write_text("PMC123456\nPMC789012\n")

        result = compare_corpora(ref, cand)

        assert result.jaccard == 1.0
        assert result.recall == 1.0
        assert result.precision == 1.0
        assert len(result.overlap) == 2
        assert len(result.reference_only) == 0
        assert len(result.candidate_only) == 0

    def test_no_overlap(self, tmp_path: Path) -> None:
        """Test comparing corpora with no overlap."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC111111\nPMC222222\n")
        cand.write_text("PMC333333\nPMC444444\n")

        result = compare_corpora(ref, cand)

        assert result.jaccard == 0.0
        assert result.recall == 0.0
        assert result.precision == 0.0
        assert len(result.overlap) == 0
        assert len(result.reference_only) == 2
        assert len(result.candidate_only) == 2

    def test_partial_overlap(self, tmp_path: Path) -> None:
        """Test comparing corpora with partial overlap."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC111111\nPMC222222\nPMC333333\n")
        cand.write_text("PMC222222\nPMC333333\nPMC444444\nPMC555555\n")

        result = compare_corpora(ref, cand)

        # Overlap: PMC222222, PMC333333 (2 papers)
        # Union: 5 papers
        assert len(result.overlap) == 2
        assert result.jaccard == pytest.approx(0.4)  # 2/5
        assert result.recall == pytest.approx(2 / 3)  # 2/3 of reference
        assert result.precision == pytest.approx(0.5)  # 2/4 of candidate
        assert result.reference_only == {"PMC111111"}
        assert result.candidate_only == {"PMC444444", "PMC555555"}

    def test_candidate_subset_of_reference(self, tmp_path: Path) -> None:
        """Test when candidate is a subset of reference."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC111111\nPMC222222\nPMC333333\n")
        cand.write_text("PMC111111\nPMC222222\n")

        result = compare_corpora(ref, cand)

        assert result.recall == pytest.approx(2 / 3)
        assert result.precision == 1.0

    def test_reference_subset_of_candidate(self, tmp_path: Path) -> None:
        """Test when reference is a subset of candidate."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC111111\nPMC222222\n")
        cand.write_text("PMC111111\nPMC222222\nPMC333333\n")

        result = compare_corpora(ref, cand)

        assert result.recall == 1.0
        assert result.precision == pytest.approx(2 / 3)

    def test_custom_labels(self, tmp_path: Path) -> None:
        """Test custom labels are used."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC123456\n")
        cand.write_text("PMC123456\n")

        result = compare_corpora(
            ref, cand, reference_label="Expert", candidate_label="Auto"
        )

        assert result.reference_label == "Expert"
        assert result.candidate_label == "Auto"

    def test_default_labels_use_filename(self, tmp_path: Path) -> None:
        """Test default labels use filename."""
        ref = tmp_path / "expert_corpus.txt"
        cand = tmp_path / "auto_corpus.txt"
        ref.write_text("PMC123456\n")
        cand.write_text("PMC123456\n")

        result = compare_corpora(ref, cand)

        assert result.reference_label == "expert_corpus.txt"
        assert result.candidate_label == "auto_corpus.txt"


class TestComparisonResult:
    """Tests for ComparisonResult dataclass."""

    def test_jaccard_empty_corpora(self) -> None:
        """Test Jaccard with empty corpora."""
        result = ComparisonResult(
            reference_label="ref",
            reference_source="ref.txt",
            reference_ids=set(),
            reference_id_types={"pmcid": 0, "doi": 0, "pmid": 0, "unknown": 0},
            candidate_label="cand",
            candidate_source="cand.txt",
            candidate_ids=set(),
            candidate_id_types={"pmcid": 0, "doi": 0, "pmid": 0, "unknown": 0},
            overlap=set(),
            reference_only=set(),
            candidate_only=set(),
        )

        assert result.jaccard == 0.0
        assert result.recall == 0.0
        assert result.precision == 0.0

    def test_to_dict(self, tmp_path: Path) -> None:
        """Test to_dict serialization."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC123456\nPMC789012\n")
        cand.write_text("PMC123456\n")

        result = compare_corpora(ref, cand)
        d = result.to_dict()

        assert d["metadata"]["text_fetch_version"]
        assert d["metadata"]["timestamp"]
        assert d["metadata"]["normalized"] is False
        assert d["reference"]["count"] == 2
        assert d["candidate"]["count"] == 1
        assert d["overlap"]["count"] == 1
        assert d["overlap"]["jaccard"] == pytest.approx(0.5, abs=0.01)
        assert d["overlap"]["recall"] == 0.5
        assert d["overlap"]["precision"] == 1.0
        assert "PMC789012" in d["reference_only"]
        assert len(d["candidate_only"]) == 0


class TestCompareCLI:
    """Tests for compare CLI command."""

    def test_compare_help(self) -> None:
        """Test compare --help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "--help"])

        assert result.exit_code == 0
        assert "Compare two corpora" in result.output
        assert "--reference" in result.output
        assert "--candidate" in result.output

    def test_compare_pretty_print(self, tmp_path: Path) -> None:
        """Test compare command with pretty print output."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC123456\nPMC789012\n")
        cand.write_text("PMC123456\n")

        runner = CliRunner()
        result = runner.invoke(cli, ["compare", "-r", str(ref), "-c", str(cand)])

        assert result.exit_code == 0
        assert "CORPUS COMPARISON" in result.output
        assert "REFERENCE:" in result.output
        assert "CANDIDATE:" in result.output
        assert "OVERLAP METRICS:" in result.output
        assert "Jaccard:" in result.output
        assert "Recall:" in result.output
        assert "Precision:" in result.output

    def test_compare_json_output(self, tmp_path: Path) -> None:
        """Test compare command with JSON output."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        out = tmp_path / "result.json"
        ref.write_text("PMC123456\nPMC789012\n")
        cand.write_text("PMC123456\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["compare", "-r", str(ref), "-c", str(cand), "-o", str(out)]
        )

        assert result.exit_code == 0
        assert out.exists()

        data = json.loads(out.read_text())
        assert data["metadata"]["text_fetch_version"]
        assert data["reference"]["count"] == 2
        assert data["candidate"]["count"] == 1
        assert data["overlap"]["count"] == 1

    def test_compare_with_labels(self, tmp_path: Path) -> None:
        """Test compare command with custom labels."""
        ref = tmp_path / "ref.txt"
        cand = tmp_path / "cand.txt"
        ref.write_text("PMC123456\n")
        cand.write_text("PMC123456\n")

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "compare",
                "-r",
                str(ref),
                "-c",
                str(cand),
                "--ref-label",
                "Expert",
                "--cand-label",
                "Auto",
            ],
        )

        assert result.exit_code == 0
        assert "REFERENCE: Expert" in result.output
        assert "CANDIDATE: Auto" in result.output

    def test_compare_missing_reference(self, tmp_path: Path) -> None:
        """Test compare command with missing reference file."""
        cand = tmp_path / "cand.txt"
        cand.write_text("PMC123456\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["compare", "-r", "nonexistent.txt", "-c", str(cand)]
        )

        assert result.exit_code != 0

    def test_compare_missing_candidate(self, tmp_path: Path) -> None:
        """Test compare command with missing candidate file."""
        ref = tmp_path / "ref.txt"
        ref.write_text("PMC123456\n")

        runner = CliRunner()
        result = runner.invoke(
            cli, ["compare", "-r", str(ref), "-c", "nonexistent.txt"]
        )

        assert result.exit_code != 0
