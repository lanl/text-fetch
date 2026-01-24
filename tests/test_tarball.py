"""Tests for tarball utility functions."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner
from text_fetch.cli import cli
from text_fetch.common import (
    build_provenance,
    create_jats_tarball,
    create_tarball_from_files,
    embed_provenance,
    embed_validation_summary,
    find_jats_files,
    read_tarball_provenance,
    validate_and_collect_stats,
)


@pytest.fixture
def sample_output_dir(tmp_path: Path) -> Path:
    """Create a sample output directory structure."""
    # Create valid/ directory with XML files
    valid_dir = tmp_path / "valid"
    valid_dir.mkdir()
    (valid_dir / "PMC123456.xml").write_text("<article>Content 1</article>")
    (valid_dir / "PMC789012.xml").write_text("<article>Content 2</article>")

    # Create incomplete/ directory with XML files
    incomplete_dir = tmp_path / "incomplete"
    incomplete_dir.mkdir()
    (incomplete_dir / "PMC999999.xml").write_text("<article>Incomplete</article>")

    # Create manifest.json
    manifest: dict[str, Any] = {
        "papers": [
            {"pmcid": "PMC123456", "title": "Paper 1"},
            {"pmcid": "PMC789012", "title": "Paper 2"},
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    return tmp_path


@pytest.fixture
def unified_output_dir(tmp_path: Path) -> Path:
    """Create a unified fetch output directory structure."""
    # Create pmc/valid/ directory
    pmc_valid = tmp_path / "pmc" / "valid"
    pmc_valid.mkdir(parents=True)
    (pmc_valid / "PMC111111.xml").write_text("<article>PMC 1</article>")
    (pmc_valid / "PMC222222.xml").write_text("<article>PMC 2</article>")

    # Create europepmc/valid/ directory
    epmc_valid = tmp_path / "europepmc" / "valid"
    epmc_valid.mkdir(parents=True)
    (epmc_valid / "PMC333333.xml").write_text("<article>EPMC 1</article>")

    # Create pmc/incomplete/ directory
    pmc_incomplete = tmp_path / "pmc" / "incomplete"
    pmc_incomplete.mkdir(parents=True)
    (pmc_incomplete / "PMC444444.xml").write_text("<article>Incomplete</article>")

    # Create _duplicates/ directory (should be excluded)
    duplicates = tmp_path / "_duplicates"
    duplicates.mkdir()
    (duplicates / "duplicate.xml").write_text("<article>Dup</article>")

    # Create manifest.json
    manifest: dict[str, list[Any]] = {"papers": []}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    return tmp_path


class TestCreateJatsTarball:
    """Tests for create_jats_tarball function."""

    def test_basic_tarball_creation(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test basic tarball creation from valid/ directory."""
        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(sample_output_dir, tarball_path)

        assert tarball_path.exists()
        assert stats["files_included"] == 2
        assert stats["valid_count"] == 2
        assert stats["incomplete_count"] == 0
        assert stats["bytes"] > 0
        assert "root" in stats["sources"]

    def test_excludes_incomplete_by_default(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test that incomplete/ files are excluded by default."""
        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(sample_output_dir, tarball_path)

        # Check tarball contents
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert "valid/PMC123456.xml" in names
            assert "valid/PMC789012.xml" in names
            assert "incomplete/PMC999999.xml" not in names

        assert stats["incomplete_count"] == 0

    def test_includes_incomplete_when_requested(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test that incomplete/ files are included when requested."""
        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(
            sample_output_dir, tarball_path, include_incomplete=True
        )

        # Check tarball contents
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert "incomplete/PMC999999.xml" in names

        assert stats["incomplete_count"] == 1
        assert stats["files_included"] == 3

    def test_includes_manifest(self, sample_output_dir: Path, tmp_path: Path) -> None:
        """Test that manifest.json is included."""
        tarball_path = tmp_path / "corpus.tar.gz"

        create_jats_tarball(sample_output_dir, tarball_path)

        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert "manifest.json" in names

            # Verify manifest content
            manifest_file = tar.extractfile("manifest.json")
            assert manifest_file is not None
            manifest = json.load(manifest_file)
            assert "papers" in manifest

    def test_unified_fetch_structure(
        self, unified_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test tarball creation from unified fetch structure."""
        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(unified_output_dir, tarball_path)

        # Check tarball contents
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert "pmc/valid/PMC111111.xml" in names
            assert "pmc/valid/PMC222222.xml" in names
            assert "europepmc/valid/PMC333333.xml" in names
            # _duplicates should be excluded
            assert "_duplicates/duplicate.xml" not in names
            # incomplete should be excluded by default
            assert "pmc/incomplete/PMC444444.xml" not in names

        assert stats["files_included"] == 3
        assert stats["valid_count"] == 3
        assert "pmc" in stats["sources"]
        assert "europepmc" in stats["sources"]

    def test_compression_gz(self, sample_output_dir: Path, tmp_path: Path) -> None:
        """Test gzip compression."""
        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(sample_output_dir, tarball_path, compression="gz")

        assert tarball_path.exists()
        # Verify it's valid gzip
        with tarfile.open(tarball_path, "r:gz") as tar:
            assert len(tar.getnames()) > 0
        assert stats["bytes"] > 0

    def test_compression_bz2(self, sample_output_dir: Path, tmp_path: Path) -> None:
        """Test bzip2 compression."""
        tarball_path = tmp_path / "corpus.tar.bz2"

        stats = create_jats_tarball(sample_output_dir, tarball_path, compression="bz2")

        assert tarball_path.exists()
        # Verify it's valid bzip2
        with tarfile.open(tarball_path, "r:bz2") as tar:
            assert len(tar.getnames()) > 0
        assert stats["bytes"] > 0

    def test_compression_none(self, sample_output_dir: Path, tmp_path: Path) -> None:
        """Test no compression."""
        tarball_path = tmp_path / "corpus.tar"

        stats = create_jats_tarball(sample_output_dir, tarball_path, compression="none")

        assert tarball_path.exists()
        # Verify it's valid uncompressed tar
        with tarfile.open(tarball_path, "r") as tar:
            assert len(tar.getnames()) > 0
        assert stats["bytes"] > 0

    def test_empty_valid_directory(self, tmp_path: Path) -> None:
        """Test with empty valid/ directory."""
        valid_dir = tmp_path / "output" / "valid"
        valid_dir.mkdir(parents=True)

        tarball_path = tmp_path / "corpus.tar.gz"

        stats = create_jats_tarball(tmp_path / "output", tarball_path)

        assert tarball_path.exists()
        assert stats["files_included"] == 0
        assert stats["valid_count"] == 0


class TestEmbedProvenance:
    """Tests for embed_provenance function."""

    def test_embed_provenance_basic(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test basic provenance embedding."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        provenance = {
            "text_fetch_version": "0.1.9",
            "fetch_timestamp": "2025-01-22T10:30:00Z",
            "command": "text-fetch pmc fetch --query test",
        }

        embed_provenance(tarball_path, None, provenance)

        # Verify embedded content
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert ".text-fetch/provenance.json" in names

            prov_file = tar.extractfile(".text-fetch/provenance.json")
            assert prov_file is not None
            embedded = json.load(prov_file)
            assert embedded["text_fetch_version"] == "0.1.9"

    def test_embed_provenance_with_search_config(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test provenance embedding with search config."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        search_config = {
            "query": "hlavacek ws[au]",
            "sources": ["pmc", "europepmc"],
        }
        provenance = {"text_fetch_version": "0.1.9"}

        embed_provenance(tarball_path, search_config, provenance)

        # Verify embedded content
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert ".text-fetch/provenance.json" in names
            assert ".text-fetch/search_config.json" in names

            cfg_file = tar.extractfile(".text-fetch/search_config.json")
            assert cfg_file is not None
            embedded_config = json.load(cfg_file)
            assert embedded_config["query"] == "hlavacek ws[au]"

    def test_embed_provenance_with_fetch_log(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test provenance embedding with fetch log."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        provenance = {"text_fetch_version": "0.1.9"}
        fetch_log = [
            "Fetching PMC123456...",
            "Fetching PMC789012...",
            "Complete: 2 papers fetched",
        ]

        embed_provenance(tarball_path, None, provenance, fetch_log=fetch_log)

        # Verify embedded content
        with tarfile.open(tarball_path, "r:gz") as tar:
            names = tar.getnames()
            assert ".text-fetch/fetch_log.txt" in names

            log_file = tar.extractfile(".text-fetch/fetch_log.txt")
            assert log_file is not None
            log_content = log_file.read().decode("utf-8")
            assert "Fetching PMC123456..." in log_content
            assert "Complete: 2 papers fetched" in log_content

    def test_embed_preserves_original_content(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test that embedding provenance preserves original tarball content."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        # Get original names
        with tarfile.open(tarball_path, "r:gz") as tar:
            original_names = set(tar.getnames())

        provenance = {"text_fetch_version": "0.1.9"}
        embed_provenance(tarball_path, None, provenance)

        # Verify original content is preserved
        with tarfile.open(tarball_path, "r:gz") as tar:
            new_names = set(tar.getnames())
            # Original names should still be present
            for name in original_names:
                assert name in new_names
            # Plus new provenance files
            assert ".text-fetch/provenance.json" in new_names


class TestReadTarballProvenance:
    """Tests for read_tarball_provenance function."""

    def test_read_provenance(self, sample_output_dir: Path, tmp_path: Path) -> None:
        """Test reading embedded provenance."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        original_provenance = {
            "text_fetch_version": "0.1.9",
            "fetch_timestamp": "2025-01-22T10:30:00Z",
        }
        original_config = {"query": "test query"}
        embed_provenance(tarball_path, original_config, original_provenance)

        # Read it back
        config, provenance = read_tarball_provenance(tarball_path)

        assert config is not None
        assert provenance is not None
        assert config["query"] == "test query"
        assert provenance["text_fetch_version"] == "0.1.9"

    def test_read_provenance_no_config(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test reading provenance when no config was embedded."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        provenance = {"text_fetch_version": "0.1.9"}
        embed_provenance(tarball_path, None, provenance)

        config, prov = read_tarball_provenance(tarball_path)

        assert config is None
        assert prov is not None
        assert prov["text_fetch_version"] == "0.1.9"

    def test_read_provenance_tarball_without_provenance(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test reading from tarball without embedded provenance."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        config, provenance = read_tarball_provenance(tarball_path)

        assert config is None
        assert provenance is None

    def test_roundtrip_provenance(
        self, sample_output_dir: Path, tmp_path: Path
    ) -> None:
        """Test full roundtrip of embedding and reading provenance."""
        tarball_path = tmp_path / "corpus.tar.gz"
        create_jats_tarball(sample_output_dir, tarball_path)

        original_config = {
            "query": "test query",
            "sources": ["pmc", "europepmc"],
            "max_results": 100,
        }
        original_provenance = {
            "text_fetch_version": "0.1.9",
            "fetch_timestamp": "2025-01-22T10:30:00Z",
            "statistics": {"total_fetched": 50, "valid": 45},
        }

        embed_provenance(tarball_path, original_config, original_provenance)
        config, provenance = read_tarball_provenance(tarball_path)

        assert config == original_config
        assert provenance == original_provenance


class TestBuildProvenance:
    """Tests for build_provenance function."""

    def test_basic_provenance(self) -> None:
        """Test basic provenance building."""
        stats = {
            "files_included": 10,
            "bytes": 12345,
            "sources": ["pmc", "europepmc"],
        }

        provenance = build_provenance(stats)

        assert "text_fetch_version" in provenance
        assert "fetch_timestamp" in provenance
        assert provenance["statistics"] == stats
        assert provenance["sources_queried"] == ["pmc", "europepmc"]

    def test_provenance_with_command(self) -> None:
        """Test provenance building with command."""
        stats = {"files_included": 5}
        command = "text-fetch pmc fetch --query test"

        provenance = build_provenance(stats, command=command)

        assert provenance["command"] == command

    def test_provenance_with_sources_override(self) -> None:
        """Test provenance building with explicit sources."""
        stats = {"files_included": 5, "sources": ["pmc"]}

        provenance = build_provenance(
            stats, sources_queried=["pmc", "europepmc", "biorxiv"]
        )

        # Explicit sources_queried should override stats["sources"]
        assert provenance["sources_queried"] == ["pmc", "europepmc", "biorxiv"]

    def test_provenance_timestamp_format(self) -> None:
        """Test that timestamp is in ISO format with timezone."""
        stats = {"files_included": 5}

        provenance = build_provenance(stats)

        timestamp = provenance["fetch_timestamp"]
        # Should end with +00:00 or Z for UTC
        assert "+" in timestamp or timestamp.endswith("Z")


# =============================================================================
# v0.2.5: Standalone Tarball Command Tests
# =============================================================================


VALID_JATS = (
    """<?xml version="1.0"?>
<article>
  <front>
    <article-meta>
      <title-group>
        <article-title>Test Article Title</article-title>
      </title-group>
      <abstract><p>Test abstract content that is valid.</p></abstract>
    </article-meta>
  </front>
  <body><p>Test body content that is long enough to pass validation. """
    + ("X" * 800)
    + """</p></body>
</article>"""
)

INCOMPLETE_JATS = """<?xml version="1.0"?>
<article>
  <front>
    <article-meta>
      <title-group>
        <article-title></article-title>
      </title-group>
    </article-meta>
  </front>
  <body></body>
</article>"""


class TestFindJatsFiles:
    """Tests for find_jats_files function."""

    def test_find_jats_files_single_dir(self, tmp_path: Path) -> None:
        """Test finding XML files in single directory."""
        (tmp_path / "file1.xml").write_text("<article/>")
        (tmp_path / "file2.xml").write_text("<article/>")
        (tmp_path / "file3.txt").write_text("not xml")

        files = find_jats_files([tmp_path])

        assert len(files) == 2
        assert all(f.suffix == ".xml" for f in files)

    def test_find_jats_files_multiple_dirs(self, tmp_path: Path) -> None:
        """Test combining files from multiple directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "file1.xml").write_text("<article/>")
        (dir2 / "file2.xml").write_text("<article/>")

        files = find_jats_files([dir1, dir2])

        assert len(files) == 2

    def test_find_jats_files_excludes_incomplete(self, tmp_path: Path) -> None:
        """Test that incomplete/ is excluded by default."""
        valid = tmp_path / "valid"
        incomplete = tmp_path / "incomplete"
        valid.mkdir()
        incomplete.mkdir()

        (valid / "good.xml").write_text("<article/>")
        (incomplete / "bad.xml").write_text("<article/>")

        files = find_jats_files([tmp_path], recursive=True, include_incomplete=False)

        assert len(files) == 1
        assert files[0].name == "good.xml"

    def test_find_jats_files_includes_incomplete(self, tmp_path: Path) -> None:
        """Test including incomplete/ when requested."""
        valid = tmp_path / "valid"
        incomplete = tmp_path / "incomplete"
        valid.mkdir()
        incomplete.mkdir()

        (valid / "good.xml").write_text("<article/>")
        (incomplete / "bad.xml").write_text("<article/>")

        files = find_jats_files([tmp_path], recursive=True, include_incomplete=True)

        assert len(files) == 2

    def test_find_jats_files_recursive(self, tmp_path: Path) -> None:
        """Test recursive file discovery."""
        subdir = tmp_path / "a" / "b" / "c"
        subdir.mkdir(parents=True)

        (tmp_path / "root.xml").write_text("<article/>")
        (subdir / "nested.xml").write_text("<article/>")

        # Non-recursive should only find root
        files_non_recursive = find_jats_files([tmp_path], recursive=False)
        assert len(files_non_recursive) == 1
        assert files_non_recursive[0].name == "root.xml"

        # Recursive should find both
        files_recursive = find_jats_files([tmp_path], recursive=True)
        assert len(files_recursive) == 2

    def test_find_jats_files_custom_pattern(self, tmp_path: Path) -> None:
        """Test custom glob pattern."""
        (tmp_path / "file.xml").write_text("<article/>")
        (tmp_path / "file.jats.xml").write_text("<article/>")
        (tmp_path / "file.nxml").write_text("<article/>")

        files = find_jats_files([tmp_path], pattern="*.jats.xml")

        assert len(files) == 1
        assert files[0].name == "file.jats.xml"

    def test_find_jats_files_deduplicates(self, tmp_path: Path) -> None:
        """Test that duplicate paths are deduplicated."""
        (tmp_path / "file.xml").write_text("<article/>")

        # Pass same directory twice
        files = find_jats_files([tmp_path, tmp_path])

        assert len(files) == 1

    def test_find_jats_files_nonexistent_dir(self, tmp_path: Path) -> None:
        """Test handling of non-existent directories."""
        nonexistent = tmp_path / "does_not_exist"

        files = find_jats_files([nonexistent])

        assert len(files) == 0


class TestValidateAndCollectStats:
    """Tests for validate_and_collect_stats function."""

    def test_validate_valid_files(self, tmp_path: Path) -> None:
        """Test validation of valid JATS files."""
        (tmp_path / "valid.xml").write_text(VALID_JATS)

        files = [tmp_path / "valid.xml"]
        stats = validate_and_collect_stats(files, validate=True)

        assert stats["valid_count"] == 1
        assert stats["invalid_count"] == 0
        assert len(stats["valid_files"]) == 1

    def test_validate_incomplete_files(self, tmp_path: Path) -> None:
        """Test validation of incomplete JATS files."""
        (tmp_path / "incomplete.xml").write_text(INCOMPLETE_JATS)

        files = [tmp_path / "incomplete.xml"]
        stats = validate_and_collect_stats(files, validate=True)

        assert stats["valid_count"] == 0
        assert stats["invalid_count"] == 1
        assert len(stats["invalid_files"]) == 1

    def test_skip_validation(self, tmp_path: Path) -> None:
        """Test that all files pass when validation is skipped."""
        (tmp_path / "file.xml").write_text(INCOMPLETE_JATS)

        files = [tmp_path / "file.xml"]
        stats = validate_and_collect_stats(files, validate=False)

        assert stats["valid_count"] == 1
        assert stats["invalid_count"] == 0

    def test_collects_total_bytes(self, tmp_path: Path) -> None:
        """Test that total bytes are collected."""
        content = "<article>" + "X" * 1000 + "</article>"
        (tmp_path / "file.xml").write_text(content)

        files = [tmp_path / "file.xml"]
        stats = validate_and_collect_stats(files, validate=False)

        assert stats["total_bytes"] > 1000


class TestCreateTarballFromFiles:
    """Tests for create_tarball_from_files function."""

    def test_basic_tarball(self, tmp_path: Path) -> None:
        """Test basic tarball creation."""
        xml1 = tmp_path / "file1.xml"
        xml2 = tmp_path / "file2.xml"
        xml1.write_text("<article><title>Test 1</title></article>")
        xml2.write_text("<article><title>Test 2</title></article>")

        output = tmp_path / "corpus.tar.gz"

        stats = create_tarball_from_files(
            files=[xml1, xml2],
            output_path=output,
        )

        assert stats["files_included"] == 2
        assert output.exists()

        # Verify contents
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert "file1.xml" in names
            assert "file2.xml" in names

    def test_tarball_with_csv(self, tmp_path: Path) -> None:
        """Test tarball creation with CSV metadata."""
        xml = tmp_path / "file.xml"
        csv = tmp_path / "metadata.csv"
        xml.write_text("<article/>")
        csv.write_text("title,doi\nTest,10.1234/test")

        output = tmp_path / "corpus.tar.gz"

        create_tarball_from_files(
            files=[xml],
            output_path=output,
            csv_path=csv,
        )

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert "metadata.csv" in names

    def test_flat_structure(self, tmp_path: Path) -> None:
        """Test that tarball has flat structure (no subdirectories)."""
        subdir = tmp_path / "some" / "nested" / "path"
        subdir.mkdir(parents=True)
        xml = subdir / "file.xml"
        xml.write_text("<article/>")

        output = tmp_path / "corpus.tar.gz"

        create_tarball_from_files(files=[xml], output_path=output)

        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            # Should be flat, not include the nested path
            assert "file.xml" in names
            assert "some/nested/path/file.xml" not in names


class TestEmbedValidationSummary:
    """Tests for embed_validation_summary function."""

    def test_embed_validation_summary(self, tmp_path: Path) -> None:
        """Test embedding validation summary in tarball."""
        # Create initial tarball
        xml = tmp_path / "file.xml"
        xml.write_text("<article/>")
        output = tmp_path / "corpus.tar.gz"
        create_tarball_from_files(files=[xml], output_path=output)

        summary = {
            "total_files_scanned": 10,
            "files_included": 8,
            "files_excluded": 2,
            "validation_enabled": True,
        }

        embed_validation_summary(output, summary)

        # Verify embedded content
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert ".text-fetch/validation_summary.json" in names

            summary_file = tar.extractfile(".text-fetch/validation_summary.json")
            assert summary_file is not None
            embedded = json.load(summary_file)
            assert embedded["total_files_scanned"] == 10
            assert embedded["files_included"] == 8


class TestTarballCreateCLI:
    """CLI integration tests for tarball create command."""

    @pytest.fixture
    def cli_runner(self) -> CliRunner:
        """Create a CLI runner."""
        return CliRunner()

    def test_tarball_create_basic(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Test basic tarball create command."""
        # Create valid JATS files
        xml_dir = tmp_path / "xml"
        xml_dir.mkdir()
        (xml_dir / "test.xml").write_text(VALID_JATS)

        output = tmp_path / "corpus.tar.gz"

        result = cli_runner.invoke(
            cli,
            [
                "tarball",
                "create",
                "--xml-dir",
                str(xml_dir),
                "--out",
                str(output),
            ],
        )

        assert result.exit_code == 0, result.output
        assert output.exists()
        assert "Tarball created successfully" in result.output

    def test_tarball_create_multiple_dirs(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test combining multiple directories."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()

        (dir1 / "file1.xml").write_text("<article/>")
        (dir2 / "file2.xml").write_text("<article/>")

        output = tmp_path / "combined.tar.gz"

        result = cli_runner.invoke(
            cli,
            [
                "tarball",
                "create",
                "--xml-dir",
                str(dir1),
                "--xml-dir",
                str(dir2),
                "--out",
                str(output),
                "--no-validate",
            ],
        )

        assert result.exit_code == 0, result.output

        with tarfile.open(output, "r:gz") as tar:
            names = [n for n in tar.getnames() if n.endswith(".xml")]
            assert len(names) >= 2

    def test_tarball_create_no_files(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test with empty directory."""
        xml_dir = tmp_path / "empty"
        xml_dir.mkdir()

        output = tmp_path / "corpus.tar.gz"

        result = cli_runner.invoke(
            cli,
            [
                "tarball",
                "create",
                "--xml-dir",
                str(xml_dir),
                "--out",
                str(output),
            ],
        )

        assert result.exit_code == 0
        assert "No XML files found" in result.output

    def test_tarball_create_with_validation(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test with validation enabled."""
        xml_dir = tmp_path / "xml"
        xml_dir.mkdir()

        # Create one valid and one incomplete file
        (xml_dir / "valid.xml").write_text(VALID_JATS)
        (xml_dir / "incomplete.xml").write_text(INCOMPLETE_JATS)

        output = tmp_path / "corpus.tar.gz"

        result = cli_runner.invoke(
            cli,
            [
                "tarball",
                "create",
                "--xml-dir",
                str(xml_dir),
                "--out",
                str(output),
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Valid: 1" in result.output
        assert "Invalid: 1" in result.output

    def test_tarball_create_has_provenance(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Test that created tarball has provenance embedded."""
        xml_dir = tmp_path / "xml"
        xml_dir.mkdir()
        (xml_dir / "test.xml").write_text(VALID_JATS)

        output = tmp_path / "corpus.tar.gz"

        result = cli_runner.invoke(
            cli,
            [
                "tarball",
                "create",
                "--xml-dir",
                str(xml_dir),
                "--out",
                str(output),
            ],
        )

        assert result.exit_code == 0, result.output

        # Verify provenance and validation summary are embedded
        with tarfile.open(output, "r:gz") as tar:
            names = tar.getnames()
            assert ".text-fetch/provenance.json" in names
            assert ".text-fetch/validation_summary.json" in names
