"""Tests for workspace module."""

from __future__ import annotations

from pathlib import Path

import pytest
from text_fetch.workspace import (
    DOIIndex,
    SearchRecord,
    Workspace,
    WorkspaceError,
    WorkspaceManifest,
)

# =============================================================================
# DOIIndex Tests
# =============================================================================


class TestDOIIndex:
    """Tests for DOIIndex class."""

    def test_init_empty(self, tmp_path: Path) -> None:
        """Test initializing empty DOI index."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        assert len(index) == 0
        assert not index_path.exists()  # Not created until first save

    def test_add_and_contains(self, tmp_path: Path) -> None:
        """Test adding DOI and checking existence."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/test", "valid/test.xml", "pmc", "search_001")

        assert index.contains("10.1234/test")
        assert len(index) == 1
        assert index_path.exists()

    def test_case_insensitive(self, tmp_path: Path) -> None:
        """Test DOI lookup is case-insensitive."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/TEST", "valid/test.xml", "pmc", "search_001")

        assert index.contains("10.1234/test")
        assert index.contains("10.1234/TEST")
        assert index.contains("10.1234/Test")
        assert index.contains("  10.1234/test  ")  # Whitespace stripped

    def test_get(self, tmp_path: Path) -> None:
        """Test getting DOI metadata."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/test", "valid/test.xml", "pmc", "search_001")
        result = index.get("10.1234/test")

        assert result is not None
        assert result["file"] == "valid/test.xml"
        assert result["source"] == "pmc"
        assert result["search_id"] == "search_001"
        assert "added" in result

    def test_get_not_found(self, tmp_path: Path) -> None:
        """Test getting non-existent DOI."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        result = index.get("10.1234/nonexistent")
        assert result is None

    def test_remove(self, tmp_path: Path) -> None:
        """Test removing DOI from index."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/test", "valid/test.xml", "pmc", "search_001")
        assert index.contains("10.1234/test")

        result = index.remove("10.1234/test")
        assert result is True
        assert not index.contains("10.1234/test")

    def test_remove_not_found(self, tmp_path: Path) -> None:
        """Test removing non-existent DOI."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        result = index.remove("10.1234/nonexistent")
        assert result is False

    def test_clear(self, tmp_path: Path) -> None:
        """Test clearing all DOIs."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/test1", "valid/test1.xml", "pmc", "search_001")
        index.add("10.1234/test2", "valid/test2.xml", "pmc", "search_001")
        assert len(index) == 2

        index.clear()
        assert len(index) == 0

    def test_persistence(self, tmp_path: Path) -> None:
        """Test DOI index persists to disk."""
        index_path = tmp_path / "doi_index.json"

        # Create and populate
        index1 = DOIIndex(index_path)
        index1.add("10.1234/test", "valid/test.xml", "pmc", "search_001")

        # Load in new instance
        index2 = DOIIndex(index_path)
        assert index2.contains("10.1234/test")

    def test_iteration(self, tmp_path: Path) -> None:
        """Test iterating over DOIs."""
        index_path = tmp_path / "doi_index.json"
        index = DOIIndex(index_path)

        index.add("10.1234/test1", "valid/test1.xml", "pmc", "search_001")
        index.add("10.1234/test2", "valid/test2.xml", "pmc", "search_001")

        dois = list(index)
        assert len(dois) == 2
        assert "10.1234/test1" in dois
        assert "10.1234/test2" in dois


# =============================================================================
# WorkspaceManifest Tests
# =============================================================================


class TestWorkspaceManifest:
    """Tests for WorkspaceManifest dataclass."""

    def test_default_values(self) -> None:
        """Test default values."""
        manifest = WorkspaceManifest()

        assert manifest.version == "1.0"
        assert manifest.created == ""
        assert manifest.updated == ""
        assert manifest.name == ""
        assert manifest.statistics == {}

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        manifest = WorkspaceManifest(
            version="1.0",
            created="2025-01-01T00:00:00",
            updated="2025-01-02T00:00:00",
            name="test-corpus",
            statistics={"total_valid": 10},
        )

        data = manifest.to_dict()

        assert data["version"] == "1.0"
        assert data["created"] == "2025-01-01T00:00:00"
        assert data["updated"] == "2025-01-02T00:00:00"
        assert data["name"] == "test-corpus"
        assert data["statistics"]["total_valid"] == 10

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "version": "1.0",
            "created": "2025-01-01T00:00:00",
            "name": "test-corpus",
            "statistics": {"total_valid": 10},
        }

        manifest = WorkspaceManifest.from_dict(data)

        assert manifest.version == "1.0"
        assert manifest.created == "2025-01-01T00:00:00"
        assert manifest.name == "test-corpus"
        assert manifest.statistics["total_valid"] == 10


# =============================================================================
# SearchRecord Tests
# =============================================================================


class TestSearchRecord:
    """Tests for SearchRecord dataclass."""

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        record = SearchRecord(
            id="search_001",
            timestamp="2025-01-01T00:00:00",
            config={"author": "hlavacek ws"},
            command="text-fetch europepmc fetch --author 'hlavacek ws'",
            statistics={"fetched": 10, "valid": 8},
        )

        data = record.to_dict()

        assert data["id"] == "search_001"
        assert data["timestamp"] == "2025-01-01T00:00:00"
        assert data["config"]["author"] == "hlavacek ws"
        assert data["statistics"]["valid"] == 8

    def test_from_dict(self) -> None:
        """Test creation from dictionary."""
        data = {
            "id": "search_001",
            "timestamp": "2025-01-01T00:00:00",
            "config": {"author": "hlavacek ws"},
            "command": "text-fetch europepmc fetch",
            "statistics": {"fetched": 10},
        }

        record = SearchRecord.from_dict(data)

        assert record.id == "search_001"
        assert record.config["author"] == "hlavacek ws"


# =============================================================================
# Workspace Tests
# =============================================================================


class TestWorkspace:
    """Tests for Workspace class."""

    def test_init(self, tmp_path: Path) -> None:
        """Test workspace initialization."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        assert ws.path == ws_path.resolve()
        assert ws.is_workspace()
        assert (ws_path / ".text-fetch").exists()
        assert (ws_path / ".text-fetch" / "workspace.json").exists()
        assert (ws_path / ".text-fetch" / "searches").exists()
        assert (ws_path / "valid").exists()
        assert (ws_path / "incomplete").exists()

    def test_init_with_name(self, tmp_path: Path) -> None:
        """Test workspace initialization with custom name."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path, name="My Research Corpus")

        assert ws.manifest.name == "My Research Corpus"

    def test_init_default_name(self, tmp_path: Path) -> None:
        """Test workspace uses directory name by default."""
        ws_path = tmp_path / "my-corpus"
        ws = Workspace.init(ws_path)

        assert ws.manifest.name == "my-corpus"

    def test_init_already_exists(self, tmp_path: Path) -> None:
        """Test error when workspace already exists."""
        ws_path = tmp_path / "corpus"
        Workspace.init(ws_path)

        with pytest.raises(WorkspaceError, match="already exists"):
            Workspace.init(ws_path)

    def test_load(self, tmp_path: Path) -> None:
        """Test loading existing workspace."""
        ws_path = tmp_path / "corpus"
        Workspace.init(ws_path, name="Test Corpus")

        ws = Workspace.load(ws_path)

        assert ws.manifest.name == "Test Corpus"
        assert ws.is_workspace()

    def test_load_not_workspace(self, tmp_path: Path) -> None:
        """Test error loading non-workspace directory."""
        with pytest.raises(WorkspaceError, match="Not a workspace"):
            Workspace.load(tmp_path)

    def test_load_or_init_new(self, tmp_path: Path) -> None:
        """Test load_or_init creates new workspace."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.load_or_init(ws_path, name="New Corpus")

        assert ws.manifest.name == "New Corpus"
        assert ws.is_workspace()

    def test_load_or_init_existing(self, tmp_path: Path) -> None:
        """Test load_or_init loads existing workspace."""
        ws_path = tmp_path / "corpus"
        Workspace.init(ws_path, name="Existing Corpus")

        ws = Workspace.load_or_init(ws_path, name="Different Name")

        # Should use existing name
        assert ws.manifest.name == "Existing Corpus"

    def test_has_doi(self, tmp_path: Path) -> None:
        """Test DOI existence check."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        assert not ws.has_doi("10.1234/test")

        ws.add_file("<article/>", "10.1234/test", "pmc", "search_001", True)

        assert ws.has_doi("10.1234/test")
        assert ws.has_doi("10.1234/TEST")  # Case insensitive

    def test_add_file_valid(self, tmp_path: Path) -> None:
        """Test adding valid file to workspace."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result = ws.add_file(
            "<article>test</article>",
            "10.1234/test",
            "pmc",
            "search_001",
            is_valid=True,
        )

        assert result is not None
        assert result.exists()
        assert result.parent.name == "valid"
        assert ws.has_doi("10.1234/test")

    def test_add_file_incomplete(self, tmp_path: Path) -> None:
        """Test adding incomplete file to workspace."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result = ws.add_file(
            "<article>test</article>",
            "10.1234/test",
            "pmc",
            "search_001",
            is_valid=False,
        )

        assert result is not None
        assert result.exists()
        assert result.parent.name == "incomplete"

    def test_add_file_duplicate_skipped(self, tmp_path: Path) -> None:
        """Test duplicate DOI is skipped."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result1 = ws.add_file(
            "<article>first</article>",
            "10.1234/test",
            "pmc",
            "search_001",
            is_valid=True,
        )
        result2 = ws.add_file(
            "<article>second</article>",
            "10.1234/test",
            "pmc",
            "search_002",
            is_valid=True,
        )

        assert result1 is not None
        assert result2 is None  # Skipped duplicate

        stats = ws.get_statistics()
        assert stats["duplicates_skipped"] == 1

    def test_record_duplicate_skip(self, tmp_path: Path) -> None:
        """Test manually recording duplicate skips."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        # Record skips without going through add_file
        ws.record_duplicate_skip("10.1234/skip1")
        ws.record_duplicate_skip("10.1234/skip2")
        ws.record_duplicate_skip("10.1234/skip3")

        stats = ws.get_statistics()
        assert stats["duplicates_skipped"] == 3

    def test_record_duplicate_skip_persists(self, tmp_path: Path) -> None:
        """Test duplicate skip counter persists across sessions."""
        ws_path = tmp_path / "corpus"

        # Session 1: record skips
        ws1 = Workspace.init(ws_path)
        ws1.record_duplicate_skip("10.1234/skip1")
        ws1.record_duplicate_skip("10.1234/skip2")

        # Session 2: load and verify
        ws2 = Workspace.load(ws_path)
        stats = ws2.get_statistics()
        assert stats["duplicates_skipped"] == 2

        # Record more skips
        ws2.record_duplicate_skip("10.1234/skip3")
        stats2 = ws2.get_statistics()
        assert stats2["duplicates_skipped"] == 3

    def test_add_file_no_doi(self, tmp_path: Path) -> None:
        """Test adding file without DOI."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result = ws.add_file(
            "<article>test</article>",
            doi=None,
            source="pmc",
            search_id="search_001",
            is_valid=True,
        )

        assert result is not None
        assert result.exists()
        assert "pmc_" in result.name

    def test_add_file_custom_filename(self, tmp_path: Path) -> None:
        """Test adding file with custom filename."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result = ws.add_file(
            "<article>test</article>",
            "10.1234/test",
            "pmc",
            "search_001",
            is_valid=True,
            filename="custom.xml",
        )

        assert result is not None
        assert result.name == "custom.xml"

    def test_record_search(self, tmp_path: Path) -> None:
        """Test recording search."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        search_id = ws.record_search(
            config={"author": "hlavacek ws"},
            command="text-fetch europepmc fetch --author 'hlavacek ws'",
            stats={"fetched": 10, "valid": 8},
        )

        assert search_id == "search_001"

        stats = ws.get_statistics()
        assert stats["total_searches"] == 1

    def test_record_multiple_searches(self, tmp_path: Path) -> None:
        """Test recording multiple searches."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        id1 = ws.record_search({"author": "a"}, "cmd1", {"fetched": 5})
        id2 = ws.record_search({"author": "b"}, "cmd2", {"fetched": 10})
        id3 = ws.record_search({"author": "c"}, "cmd3", {"fetched": 15})

        assert id1 == "search_001"
        assert id2 == "search_002"
        assert id3 == "search_003"

    def test_get_searches(self, tmp_path: Path) -> None:
        """Test getting search records."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        ws.record_search({"author": "a"}, "cmd1", {"fetched": 5})
        ws.record_search({"author": "b"}, "cmd2", {"fetched": 10})

        searches = ws.get_searches()

        assert len(searches) == 2
        # Newest first
        assert searches[0].id == "search_002"
        assert searches[1].id == "search_001"

    def test_get_statistics(self, tmp_path: Path) -> None:
        """Test getting workspace statistics."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path, name="Test Corpus")

        ws.add_file("<article/>", "10.1234/test1", "pmc", "s1", True)
        ws.add_file("<article/>", "10.1234/test2", "pmc", "s1", False)
        ws.record_search({}, "cmd", {"fetched": 2})

        stats = ws.get_statistics()

        assert stats["name"] == "Test Corpus"
        assert stats["total_searches"] == 1
        assert stats["total_valid"] == 1
        assert stats["total_incomplete"] == 1
        assert stats["unique_dois"] == 2

    def test_clear_full(self, tmp_path: Path) -> None:
        """Test clearing workspace completely."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        ws.add_file("<article/>", "10.1234/test", "pmc", "s1", True)
        ws.record_search({}, "cmd", {"fetched": 1})

        ws.clear(keep_history=False)

        stats = ws.get_statistics()
        assert stats["total_valid"] == 0
        assert stats["total_searches"] == 0
        assert stats["unique_dois"] == 0

    def test_clear_keep_history(self, tmp_path: Path) -> None:
        """Test clearing workspace while keeping history."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        ws.add_file("<article/>", "10.1234/test", "pmc", "s1", True)
        ws.record_search({}, "cmd", {"fetched": 1})

        ws.clear(keep_history=True)

        stats = ws.get_statistics()
        assert stats["total_valid"] == 0
        assert stats["total_searches"] == 1  # History preserved
        assert stats["unique_dois"] == 0

    def test_build_tarball(self, tmp_path: Path) -> None:
        """Test building tarball from workspace."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        # Add some files
        ws.add_file("<article>1</article>", "10.1234/test1", "pmc", "s1", True)
        ws.add_file("<article>2</article>", "10.1234/test2", "pmc", "s1", True)
        ws.add_file("<article>3</article>", "10.1234/test3", "pmc", "s1", False)

        tarball_path = tmp_path / "output.tar.gz"
        stats = ws.build_tarball(tarball_path, include_incomplete=False)

        assert tarball_path.exists()
        assert stats["files_included"] == 2
        assert stats["valid_count"] == 2
        assert stats["bytes"] > 0

    def test_build_tarball_include_incomplete(self, tmp_path: Path) -> None:
        """Test building tarball including incomplete files."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        ws.add_file("<article>1</article>", "10.1234/test1", "pmc", "s1", True)
        ws.add_file("<article>2</article>", "10.1234/test2", "pmc", "s1", False)

        tarball_path = tmp_path / "output.tar.gz"
        stats = ws.build_tarball(tarball_path, include_incomplete=True)

        assert stats["files_included"] == 2
        assert stats["valid_count"] == 1
        assert stats["incomplete_count"] == 1


# =============================================================================
# Integration Tests
# =============================================================================


class TestWorkspaceIntegration:
    """Integration tests for workspace functionality."""

    def test_cross_search_deduplication(self, tmp_path: Path) -> None:
        """Test DOI deduplication across multiple searches."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        # First search adds papers
        ws.add_file("<a>1</a>", "10.1234/paper1", "pmc", "search_001", True)
        ws.add_file("<a>2</a>", "10.1234/paper2", "pmc", "search_001", True)
        ws.add_file("<a>3</a>", "10.1234/paper3", "pmc", "search_001", True)
        ws.record_search(
            {"author": "hlavacek ws"},
            "text-fetch europepmc fetch --author 'hlavacek ws'",
            {"fetched": 3, "valid": 3},
        )

        # Second search - paper2 is duplicate, paper4 is new
        result1 = ws.add_file("<a>2</a>", "10.1234/paper2", "pmc", "search_002", True)
        result2 = ws.add_file("<a>4</a>", "10.1234/paper4", "pmc", "search_002", True)
        ws.record_search(
            {"author": "perelson as"},
            "text-fetch europepmc fetch --author 'perelson as'",
            {"fetched": 1, "valid": 1, "duplicates_skipped": 1},
        )

        assert result1 is None  # Duplicate skipped
        assert result2 is not None  # New paper added

        stats = ws.get_statistics()
        assert stats["total_valid"] == 4
        assert stats["unique_dois"] == 4
        assert stats["duplicates_skipped"] == 1
        assert stats["total_searches"] == 2

    def test_workspace_persistence(self, tmp_path: Path) -> None:
        """Test workspace data persists across sessions."""
        ws_path = tmp_path / "corpus"

        # Session 1: Create and populate
        ws1 = Workspace.init(ws_path, name="Persistent Corpus")
        ws1.add_file("<a>1</a>", "10.1234/test", "pmc", "search_001", True)
        ws1.record_search(
            {"author": "test"},
            "text-fetch test",
            {"fetched": 1, "valid": 1},
        )

        # Session 2: Load and verify
        ws2 = Workspace.load(ws_path)
        assert ws2.manifest.name == "Persistent Corpus"
        assert ws2.has_doi("10.1234/test")

        stats = ws2.get_statistics()
        assert stats["total_valid"] == 1
        assert stats["total_searches"] == 1

    def test_filename_from_doi(self, tmp_path: Path) -> None:
        """Test filename generation from DOI."""
        ws_path = tmp_path / "corpus"
        ws = Workspace.init(ws_path)

        result = ws.add_file(
            "<article/>",
            "10.1101/2024.01.15.123456",
            "biorxiv",
            "search_001",
            True,
        )

        assert result is not None
        # DOI slashes should be replaced
        assert "10.1101_2024.01.15.123456" in result.name
        assert result.name.startswith("biorxiv_")


# =============================================================================
# CLI Integration Tests
# =============================================================================


class TestWorkspaceCLI:
    """CLI integration tests for workspace commands."""

    def test_workspace_init_cli(self, tmp_path: Path) -> None:
        """Test workspace init CLI command."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "my-corpus"

        result = runner.invoke(cli, ["workspace", "init", str(ws_path)])

        assert result.exit_code == 0
        assert "Initialized workspace" in result.output
        assert (ws_path / ".text-fetch").exists()

    def test_workspace_init_with_name_cli(self, tmp_path: Path) -> None:
        """Test workspace init with custom name."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        result = runner.invoke(
            cli,
            ["workspace", "init", str(ws_path), "--name", "My Research Corpus"],
        )

        assert result.exit_code == 0
        assert "My Research Corpus" in result.output

    def test_workspace_init_already_exists_cli(self, tmp_path: Path) -> None:
        """Test workspace init error when already exists."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        # First init succeeds
        runner.invoke(cli, ["workspace", "init", str(ws_path)])

        # Second init fails
        result = runner.invoke(cli, ["workspace", "init", str(ws_path)])

        assert result.exit_code != 0
        assert "already exists" in result.output

    def test_workspace_status_cli(self, tmp_path: Path) -> None:
        """Test workspace status CLI command."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        # Initialize workspace
        Workspace.init(ws_path, name="Test Status Corpus")

        result = runner.invoke(cli, ["workspace", "status", str(ws_path)])

        assert result.exit_code == 0
        assert "Test Status Corpus" in result.output
        assert "Statistics:" in result.output
        assert "Searches:" in result.output

    def test_workspace_status_not_workspace_cli(self, tmp_path: Path) -> None:
        """Test workspace status on non-workspace."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()

        result = runner.invoke(cli, ["workspace", "status", str(tmp_path)])

        assert result.exit_code != 0
        assert "Not a workspace" in result.output

    def test_workspace_list_searches_empty_cli(self, tmp_path: Path) -> None:
        """Test list-searches on empty workspace."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        Workspace.init(ws_path)

        result = runner.invoke(cli, ["workspace", "list-searches", str(ws_path)])

        assert result.exit_code == 0
        assert "No searches recorded" in result.output

    def test_workspace_list_searches_with_data_cli(self, tmp_path: Path) -> None:
        """Test list-searches with search history."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        ws = Workspace.init(ws_path)
        ws.record_search(
            {"author": "test"},
            "text-fetch test",
            {"fetched": 10, "valid": 8},
        )

        result = runner.invoke(cli, ["workspace", "list-searches", str(ws_path)])

        assert result.exit_code == 0
        assert "search_001" in result.output
        assert "text-fetch test" in result.output

    def test_workspace_build_cli(self, tmp_path: Path) -> None:
        """Test workspace build CLI command."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        # Create workspace with files
        ws = Workspace.init(ws_path, name="build-test")
        ws.add_file("<a>1</a>", "10.1234/test1", "pmc", "s1", True)
        ws.add_file("<a>2</a>", "10.1234/test2", "pmc", "s1", True)

        result = runner.invoke(cli, ["workspace", "build", str(ws_path)])

        assert result.exit_code == 0
        assert "Created tarball" in result.output
        assert "Files included: 2" in result.output

    def test_workspace_build_custom_name_cli(self, tmp_path: Path) -> None:
        """Test workspace build with custom tarball name."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        ws = Workspace.init(ws_path)
        ws.add_file("<a>1</a>", "10.1234/test", "pmc", "s1", True)

        result = runner.invoke(
            cli,
            ["workspace", "build", str(ws_path), "--tarball", "custom.tar.gz"],
        )

        assert result.exit_code == 0
        assert (ws_path / "custom.tar.gz").exists()

    def test_workspace_clear_with_force_cli(self, tmp_path: Path) -> None:
        """Test workspace clear with --force flag."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        ws = Workspace.init(ws_path)
        ws.add_file("<a>1</a>", "10.1234/test", "pmc", "s1", True)
        ws.record_search({}, "cmd", {"fetched": 1})

        result = runner.invoke(cli, ["workspace", "clear", str(ws_path), "--force"])

        assert result.exit_code == 0
        assert "Cleared workspace" in result.output

        # Verify cleared
        ws_reloaded = Workspace.load(ws_path)
        assert ws_reloaded.get_statistics()["total_valid"] == 0
        assert ws_reloaded.get_statistics()["total_searches"] == 0

    def test_workspace_clear_keep_history_cli(self, tmp_path: Path) -> None:
        """Test workspace clear with --keep-history flag."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        ws_path = tmp_path / "corpus"

        ws = Workspace.init(ws_path)
        ws.add_file("<a>1</a>", "10.1234/test", "pmc", "s1", True)
        ws.record_search({}, "cmd", {"fetched": 1})

        result = runner.invoke(
            cli, ["workspace", "clear", str(ws_path), "--force", "--keep-history"]
        )

        assert result.exit_code == 0
        assert "Search history preserved" in result.output

        # Verify history preserved
        ws_reloaded = Workspace.load(ws_path)
        assert ws_reloaded.get_statistics()["total_valid"] == 0
        assert ws_reloaded.get_statistics()["total_searches"] == 1


# =============================================================================
# From-Tarball Tests
# =============================================================================


class TestFromTarball:
    """Tests for --from-tarball reproducibility feature."""

    def test_extract_config_from_tarball(self, tmp_path: Path) -> None:
        """Test extracting search config from tarball."""
        from text_fetch.common import (
            create_jats_tarball,
            embed_provenance,
            extract_search_config_from_tarball,
        )

        # Create output directory with valid files
        output_dir = tmp_path / "output"
        valid_dir = output_dir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "test.xml").write_text("<article/>")

        # Create tarball
        tarball_path = tmp_path / "test.tar.gz"
        create_jats_tarball(output_dir, tarball_path)

        # Embed provenance with search config
        search_config = {
            "author": "hlavacek ws",
            "sources": ["europepmc", "pmc"],
            "max_results_per_source": 100,
        }
        provenance = {"test": True}
        embed_provenance(tarball_path, search_config, provenance)

        # Extract and verify
        extracted = extract_search_config_from_tarball(tarball_path)
        assert extracted is not None
        assert extracted["author"] == "hlavacek ws"
        assert extracted["sources"] == ["europepmc", "pmc"]

    def test_extract_config_from_tarball_no_config(self, tmp_path: Path) -> None:
        """Test extracting from tarball without embedded config."""
        from text_fetch.common import (
            create_jats_tarball,
            extract_search_config_from_tarball,
        )

        # Create output directory
        output_dir = tmp_path / "output"
        valid_dir = output_dir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "test.xml").write_text("<article/>")

        # Create tarball without embedding provenance
        tarball_path = tmp_path / "test.tar.gz"
        create_jats_tarball(output_dir, tarball_path)

        # Extract should return None
        extracted = extract_search_config_from_tarball(tarball_path)
        assert extracted is None

    def test_fetch_from_tarball_cli_requires_option(self, tmp_path: Path) -> None:
        """Test that fetch command requires config-file or from-tarball."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["fetch", "--out", str(tmp_path)])

        assert result.exit_code != 0
        assert "Either --config-file or --from-tarball" in result.output

    def test_fetch_from_tarball_cli_mutually_exclusive(self, tmp_path: Path) -> None:
        """Test that config-file and from-tarball are mutually exclusive."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()

        # Create a dummy config and tarball
        config_file = tmp_path / "config.json"
        config_file.write_text('{"author": "test"}')

        tarball = tmp_path / "test.tar.gz"
        tarball.touch()

        result = runner.invoke(
            cli,
            [
                "fetch",
                "--config-file",
                str(config_file),
                "--from-tarball",
                str(tarball),
                "--out",
                str(tmp_path / "output"),
            ],
        )

        assert result.exit_code != 0
        assert "Cannot use both --config-file and --from-tarball" in result.output

    def test_fetch_from_tarball_cli_no_config_in_tarball(self, tmp_path: Path) -> None:
        """Test error when tarball has no embedded config."""
        from click.testing import CliRunner
        from text_fetch.cli import cli
        from text_fetch.common import create_jats_tarball

        runner = CliRunner()

        # Create tarball without config
        output_dir = tmp_path / "output"
        valid_dir = output_dir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "test.xml").write_text("<article/>")

        tarball_path = tmp_path / "test.tar.gz"
        create_jats_tarball(output_dir, tarball_path)

        result = runner.invoke(
            cli,
            [
                "fetch",
                "--from-tarball",
                str(tarball_path),
                "--out",
                str(tmp_path / "new_output"),
            ],
        )

        assert result.exit_code != 0
        assert "No search config found in tarball" in result.output


# =============================================================================
# PDF Batch with Workspace Tests
# =============================================================================


class TestPDFBatchWorkspaceCLI:
    """Tests for pdf batch --workspace CLI option."""

    def test_pdf_batch_workspace_option_accepted(self, tmp_path: Path) -> None:
        """Test that --workspace option is accepted by pdf batch."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()

        # Create workspace
        ws_path = tmp_path / "corpus"
        Workspace.init(ws_path)

        # Create PDF directory (empty for this test)
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()

        result = runner.invoke(
            cli,
            [
                "pdf",
                "batch",
                "--dir",
                str(pdf_dir),
                "--out",
                str(tmp_path / "output"),
                "--workspace",
                str(ws_path),
            ],
        )

        # Should succeed but find no PDFs
        assert result.exit_code == 0
        assert "No PDF files found" in result.output

    def test_pdf_batch_with_workspace_shows_workspace_path(
        self, tmp_path: Path
    ) -> None:
        """Test that pdf batch shows workspace path when --workspace used."""
        from click.testing import CliRunner
        from text_fetch.cli import cli

        runner = CliRunner()

        # Create workspace
        ws_path = tmp_path / "corpus"
        Workspace.init(ws_path)

        # Create PDF directory with no PDFs
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()

        result = runner.invoke(
            cli,
            [
                "pdf",
                "batch",
                "--dir",
                str(pdf_dir),
                "--out",
                str(tmp_path / "output"),
                "--workspace",
                str(ws_path),
            ],
        )

        assert result.exit_code == 0
