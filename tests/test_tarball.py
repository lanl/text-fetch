"""Tests for tarball utility functions."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path
from typing import Any

import pytest
from text_fetch.common import (
    build_provenance,
    create_jats_tarball,
    embed_provenance,
    read_tarball_provenance,
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
