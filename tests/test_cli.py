"""CLI integration tests using Click's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from text_fetch.cli import cli

if TYPE_CHECKING:
    pass


@pytest.fixture
def runner() -> CliRunner:
    """Create a CliRunner instance."""
    return CliRunner()


@pytest.fixture
def mock_config_file(tmp_path: Path) -> Path:
    """Create a test JSON search config file."""
    config = {
        "name": "test_corpus",
        "author": "hlavacek ws",
        "keywords": ["systems biology"],
        "sources": ["pmc"],
        "max_results_per_source": 10,
    }
    config_path = tmp_path / "search.json"
    config_path.write_text(json.dumps(config))
    return config_path


@pytest.fixture
def mock_toml_config(tmp_path: Path) -> Path:
    """Create a test TOML config file."""
    config_content = """
[ncbi]
email = "test@example.com"
api_key = "test-api-key"

[grobid]
url = "http://localhost:8070"
"""
    config_path = tmp_path / "text-fetch.toml"
    config_path.write_text(config_content)
    return config_path


class TestConfigCommand:
    """Tests for the config command."""

    def test_config_show(self, runner: CliRunner, tmp_path: Path) -> None:
        """--show displays current configuration."""
        # Create temp config
        config_file = tmp_path / "text-fetch.toml"
        config_file.write_text('[ncbi]\nemail = "test@example.com"\n')

        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Copy config to current dir
            (Path.cwd() / "text-fetch.toml").write_text(
                '[ncbi]\nemail = "test@example.com"\n'
            )
            result = runner.invoke(cli, ["config", "--show"])

        assert result.exit_code == 0
        assert "test@example.com" in result.output

    def test_config_no_file(self, runner: CliRunner, tmp_path: Path) -> None:
        """Handles missing config file gracefully."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["config", "--show"])

        assert result.exit_code == 0
        assert "(not set)" in result.output or "Not found" in result.output

    def test_config_shows_grobid_url(self, runner: CliRunner, tmp_path: Path) -> None:
        """Shows GROBID URL configuration."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            # Create config with grobid
            (Path.cwd() / "text-fetch.toml").write_text(
                '[grobid]\nurl = "http://localhost:8070"\n'
            )
            result = runner.invoke(cli, ["config", "--show"])

        assert result.exit_code == 0
        assert "http://localhost:8070" in result.output


class TestPmcFetchCommand:
    """Tests for the pmc fetch command."""

    def test_pmc_fetch_requires_query_or_config(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Fails without --config-file or --query."""
        result = runner.invoke(cli, ["pmc", "fetch", "--out", str(tmp_path / "output")])

        assert result.exit_code != 0
        assert "Either --config-file or --query is required" in result.output

    def test_pmc_fetch_requires_email(
        self, runner: CliRunner, tmp_path: Path, mock_config_file: Path
    ) -> None:
        """Fails without email when no config provides it."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "pmc",
                    "fetch",
                    "--config-file",
                    str(mock_config_file),
                    "--out",
                    str(tmp_path / "output"),
                ],
            )

        assert result.exit_code != 0
        assert "email" in result.output.lower()

    @patch("text_fetch.pmc.fetch_pmc")
    def test_pmc_fetch_with_query_and_email(
        self,
        mock_fetch_pmc: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Succeeds with query and email."""
        mock_fetch_pmc.return_value = {
            "pmids_found": 10,
            "pmcids_available": 5,
            "fetched": 5,
            "valid": 4,
            "incomplete": 1,
            "skipped": 0,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "pmc",
                    "fetch",
                    "--query",
                    "hlavacek ws[au]",
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "Fetch complete" in result.output
        mock_fetch_pmc.assert_called_once()

    @patch("text_fetch.pmc.fetch_pmc")
    def test_pmc_fetch_with_config_file(
        self,
        mock_fetch_pmc: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
        mock_config_file: Path,
    ) -> None:
        """Succeeds with config file and email."""
        mock_fetch_pmc.return_value = {
            "pmids_found": 10,
            "pmcids_available": 5,
            "fetched": 5,
            "valid": 4,
            "incomplete": 1,
            "skipped": 0,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "pmc",
                    "fetch",
                    "--config-file",
                    str(mock_config_file),
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "Fetch complete" in result.output

    @patch("text_fetch.pmc.fetch_pmc")
    def test_pmc_fetch_verbose_mode(
        self,
        mock_fetch_pmc: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Verbose mode shows additional info."""
        mock_fetch_pmc.return_value = {
            "pmids_found": 0,
            "pmcids_available": 0,
            "fetched": 0,
            "valid": 0,
            "incomplete": 0,
            "skipped": 0,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "pmc",
                    "fetch",
                    "--query",
                    "test",
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                    "-v",
                ],
            )

        assert result.exit_code == 0
        assert "Using NCBI email" in result.output


class TestUnifiedFetchCommand:
    """Tests for the unified fetch command."""

    def test_fetch_requires_config_file(self, runner: CliRunner) -> None:
        """Fails without --config-file."""
        result = runner.invoke(cli, ["fetch", "--out", "./output"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    @patch("text_fetch.fetch.unified_fetch")
    def test_fetch_with_pmc_source(
        self,
        mock_unified_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches from PMC source."""
        mock_unified_fetch.return_value = {
            "sources": ["pmc"],
            "per_source": {
                "pmc": {"fetched": 5, "valid": 4, "incomplete": 1, "errors": 0}
            },
            "total_fetched": 5,
            "total_valid": 4,
            "total_incomplete": 1,
            "total_errors": 0,
            "duplicates_removed": 0,
            "unique_dois": [],
        }

        config = {"author": "test", "sources": ["pmc"]}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "fetch",
                    "--config-file",
                    str(config_path),
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "Unified fetch complete" in result.output
        mock_unified_fetch.assert_called_once()

    @patch("text_fetch.fetch.unified_fetch")
    def test_fetch_with_multiple_sources(
        self,
        mock_unified_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches from multiple sources."""
        mock_unified_fetch.return_value = {
            "sources": ["pmc", "europepmc"],
            "per_source": {
                "pmc": {"fetched": 5, "valid": 4, "incomplete": 1, "errors": 0},
                "europepmc": {"fetched": 10, "valid": 8, "incomplete": 2, "errors": 0},
            },
            "total_fetched": 15,
            "total_valid": 12,
            "total_incomplete": 3,
            "total_errors": 0,
            "duplicates_removed": 2,
            "unique_dois": [],
        }

        config = {"author": "test", "sources": ["pmc", "europepmc"]}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "fetch",
                    "--config-file",
                    str(config_path),
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "pmc" in result.output
        assert "europepmc" in result.output

    @patch("text_fetch.fetch.unified_fetch")
    def test_fetch_override_sources(
        self,
        mock_unified_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """--sources overrides config sources."""
        mock_unified_fetch.return_value = {
            "sources": ["europepmc"],
            "per_source": {
                "europepmc": {"fetched": 5, "valid": 5, "incomplete": 0, "errors": 0}
            },
            "total_fetched": 5,
            "total_valid": 5,
            "total_incomplete": 0,
            "total_errors": 0,
            "duplicates_removed": 0,
            "unique_dois": [],
        }

        # Config has pmc, but we override to europepmc
        config = {"author": "test", "sources": ["pmc"]}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "fetch",
                    "--config-file",
                    str(config_path),
                    "--sources",
                    "europepmc",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        # Verify SearchConfig was modified (check call args)
        call_kwargs = mock_unified_fetch.call_args.kwargs
        assert call_kwargs["config"].sources == ["europepmc"]

    @patch("text_fetch.fetch.unified_fetch")
    def test_fetch_no_dedupe_flag(
        self,
        mock_unified_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """--no-dedupe disables deduplication."""
        mock_unified_fetch.return_value = {
            "sources": ["pmc"],
            "per_source": {"pmc": {"fetched": 5, "valid": 5}},
            "total_fetched": 5,
            "total_valid": 5,
            "total_incomplete": 0,
            "total_errors": 0,
            "duplicates_removed": 0,
            "unique_dois": [],
        }

        config = {"author": "test", "sources": ["pmc"], "deduplicate_by_doi": True}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "fetch",
                    "--config-file",
                    str(config_path),
                    "--email",
                    "test@example.com",
                    "--no-dedupe",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_unified_fetch.call_args.kwargs
        assert call_kwargs["config"].deduplicate_by_doi is False

    @patch("text_fetch.fetch.unified_fetch")
    def test_fetch_handles_source_error(
        self,
        mock_unified_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Displays source errors properly."""
        mock_unified_fetch.return_value = {
            "sources": ["pmc", "europepmc"],
            "per_source": {
                "pmc": {"error": "API error"},
                "europepmc": {"fetched": 10, "valid": 8},
            },
            "total_fetched": 10,
            "total_valid": 8,
            "total_incomplete": 0,
            "total_errors": 1,
            "duplicates_removed": 0,
            "unique_dois": [],
        }

        config = {"author": "test", "sources": ["pmc", "europepmc"]}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "fetch",
                    "--config-file",
                    str(config_path),
                    "--email",
                    "test@example.com",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "ERROR" in result.output


class TestBiorxivFetchCommand:
    """Tests for biorxiv fetch command."""

    @patch("text_fetch.biorxiv.fetch_biorxiv")
    def test_biorxiv_fetch_by_days(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches by recent days."""
        mock_fetch.return_value = {
            "articles_found": 10,
            "jats_direct": 8,
            "pdf_converted": 2,
            "valid": 9,
            "incomplete": 1,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "biorxiv",
                    "fetch",
                    "--days",
                    "7",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        assert "Fetch complete" in result.output
        mock_fetch.assert_called_once()

    @patch("text_fetch.biorxiv.fetch_biorxiv")
    def test_biorxiv_fetch_by_date_range(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches by date range."""
        mock_fetch.return_value = {
            "articles_found": 5,
            "jats_direct": 5,
            "pdf_converted": 0,
            "valid": 5,
            "incomplete": 0,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "biorxiv",
                    "fetch",
                    "--start-date",
                    "2024-01-01",
                    "--end-date",
                    "2024-01-31",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        mock_fetch.assert_called_once()


class TestEuropepmcFetchCommand:
    """Tests for europepmc fetch command."""

    @patch("text_fetch.europepmc.fetch_europepmc")
    def test_europepmc_fetch_by_author(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches by author."""
        mock_fetch.return_value = {
            "articles_found": 20,
            "full_text_available": 15,
            "fetched": 15,
            "valid": 14,
            "incomplete": 1,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "europepmc",
                    "fetch",
                    "--author",
                    "hlavacek ws",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        # The europepmc CLI now shows detailed output format
        assert "SEED PAPERS" in result.output or "Fetch complete" in result.output


class TestArxivFetchCommand:
    """Tests for arxiv fetch command."""

    def test_arxiv_requires_query_or_config(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Fails without query or config."""
        result = runner.invoke(
            cli,
            ["arxiv", "fetch", "--out", str(tmp_path / "output")],
        )

        assert result.exit_code != 0

    @patch("text_fetch.arxiv.fetch_arxiv")
    def test_arxiv_fetch_with_query(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches with query."""
        mock_fetch.return_value = {
            "articles_found": 10,
            "pdfs_downloaded": 10,
            "converted": 8,
            "valid": 8,
            "incomplete": 0,
            "errors": 2,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "arxiv",
                    "fetch",
                    "--query",
                    'au:"hlavacek"',
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0


class TestChemrxivFetchCommand:
    """Tests for chemrxiv fetch command."""

    @patch("text_fetch.chemrxiv.fetch_chemrxiv")
    @patch("text_fetch.chemrxiv.get_category_ids")
    def test_chemrxiv_fetch_by_term(
        self,
        mock_get_cats: MagicMock,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches by search term."""
        mock_get_cats.return_value = None
        mock_fetch.return_value = {
            "articles_found": 5,
            "pdfs_downloaded": 5,
            "converted": 4,
            "valid": 4,
            "incomplete": 0,
            "errors": 1,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "chemrxiv",
                    "fetch",
                    "--term",
                    "catalysis",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0


class TestMedrxivFetchCommand:
    """Tests for medrxiv fetch command."""

    @patch("text_fetch.biorxiv.fetch_medrxiv")
    def test_medrxiv_fetch_by_days(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Fetches by recent days."""
        mock_fetch.return_value = {
            "articles_found": 10,
            "jats_direct": 8,
            "pdf_converted": 2,
            "valid": 9,
            "incomplete": 1,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                [
                    "medrxiv",
                    "fetch",
                    "--days",
                    "7",
                    "--out",
                    "./output",
                ],
            )

        assert result.exit_code == 0
        mock_fetch.assert_called_once()


class TestVersionCommand:
    """Tests for version display."""

    def test_version_option(self, runner: CliRunner) -> None:
        """--version shows version."""
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert "text-fetch" in result.output


class TestHelpCommand:
    """Tests for help display."""

    def test_help_option(self, runner: CliRunner) -> None:
        """--help shows help."""
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "Acquire scientific literature" in result.output

    def test_subcommand_help(self, runner: CliRunner) -> None:
        """Subcommand --help shows subcommand help."""
        result = runner.invoke(cli, ["pmc", "--help"])

        assert result.exit_code == 0
        assert "PubMed Central" in result.output

    def test_fetch_help(self, runner: CliRunner) -> None:
        """fetch --help shows fetch command help."""
        result = runner.invoke(cli, ["fetch", "--help"])

        assert result.exit_code == 0
        assert "--config-file" in result.output
