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
        assert "Total errors: 1" in result.output


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

    @patch("text_fetch.europepmc.fetch_europepmc")
    def test_europepmc_fetch_passes_pmcids_through(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """Valid --pmcid values reach the fetcher unchanged.

        Unchanged, so that a checkpoint written by an earlier run of the same
        command still matches on --resume. Control: main also passed them on.
        """
        mock_fetch.return_value = {
            "articles_found": 2,
            "full_text_available": 2,
            "fetched": 2,
            "valid": 2,
            "incomplete": 0,
            "errors": 0,
        }

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["europepmc", "fetch", "--pmcid", "pmc123", "--pmcid", "Pmc456"]
                + ["--out", "./output"],
            )

        assert result.exit_code == 0, result.output
        assert mock_fetch.call_args.kwargs["pmcids"] == ["pmc123", "Pmc456"]

    @patch("text_fetch.europepmc.fetch_europepmc")
    def test_europepmc_fetch_rejects_bad_pmcid(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """A malformed --pmcid is a usage error, and nothing is fetched (#30)."""
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["europepmc", "fetch", "--pmcid", "PMCPMC1", "--out", "./output"],
            )

        assert result.exit_code == 2
        assert "Invalid PMC ID" in result.output
        mock_fetch.assert_not_called()


class TestEuropepmcExpansionInvalidPmcid:
    """A malformed PMCID from a batch lookup skips one paper (#30)."""

    def test_bad_lookup_pmcid_does_not_abort(
        self, runner: CliRunner, tmp_path: Path, requests_mock, monkeypatch
    ) -> None:
        """Seeds and good expanded papers are saved; the bad one is skipped."""
        from urllib.parse import parse_qs, urlsplit

        from text_fetch.europepmc import ExpansionResult

        monkeypatch.setenv("HOME", str(tmp_path))
        records = {
            "PMC1": {"id": "PMC1", "source": "PMC", "pmcid": "PMC1"},
            "PMC10": {"id": "10", "source": "MED", "pmid": "10", "pmcid": "PMC10"},
            "PMC20": {"id": "PMC20", "source": "PMC", "pmcid": "PMC20"},
        }

        def search(request, context):
            query = parse_qs(urlsplit(request.url).query)["query"][0]
            if query.startswith("EXT_ID:"):
                hits = [
                    records["PMC10"],
                    {"id": "11", "source": "MED", "pmid": "11", "pmcid": "PMC11a"},
                ]
            elif query.startswith("PMCID:"):
                hits = [records[query.split(":", 1)[1]]]
            else:
                hits = [records["PMC1"]]
            return {"hitCount": len(hits), "resultList": {"result": hits}}

        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search", json=search
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>T</article-title></title-group></article-meta>"
            "</front></article></pmc-articleset>",
        )
        expansion = ExpansionResult(
            expanded_papers={
                1: [
                    {"id": "10", "source": "MED", "_expansion_type": "references"},
                    {"id": "11", "source": "MED", "_expansion_type": "references"},
                    # PMC-source record: its id is the PMCID
                    {"id": "PMC20", "source": "PMC", "_expansion_type": "references"},
                ]
            },
            expansion_stats={"references_found": 3, "total_unique": 3},
        )

        with (
            runner.isolated_filesystem(temp_dir=tmp_path),
            patch("text_fetch.europepmc.expand_papers", return_value=expansion),
        ):
            result = runner.invoke(
                cli,
                ["europepmc", "fetch", "--query", "x", "--expand-references"]
                + ["--email", "user@example.com", "--out", "o", "--yes"],
            )
            files = sorted(p.name for p in Path("o", "valid").iterdir())

        assert result.exit_code == 0, result.output
        assert files == ["PMC1.xml", "PMC10.xml", "PMC20.xml"]
        assert "2 downloadable, 1 without full-text" in result.output

    def test_malformed_cli_seed_not_expanded(
        self, runner: CliRunner, tmp_path: Path, requests_mock, monkeypatch
    ) -> None:
        """europepmc fetch drops a seed with a malformed PMCID before expanding."""
        from text_fetch.europepmc import ExpansionResult

        monkeypatch.setenv("HOME", str(tmp_path))
        hits = [
            {"id": "PMC1", "source": "PMC", "pmcid": "PMC1"},
            {"id": "2", "source": "MED", "pmid": "2", "pmcid": "PMC22a"},
        ]
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={"hitCount": 2, "resultList": {"result": hits}},
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>T</article-title></title-group></article-meta>"
            "</front></article></pmc-articleset>",
        )

        with (
            runner.isolated_filesystem(temp_dir=tmp_path),
            patch(
                "text_fetch.europepmc.expand_papers",
                return_value=ExpansionResult(),
            ) as expand,
        ):
            result = runner.invoke(
                cli,
                ["europepmc", "fetch", "--query", "x", "--expand-references"]
                + ["--email", "user@example.com", "--out", "o", "--yes"],
            )

        assert result.exit_code == 0, result.output
        seeds = expand.call_args.kwargs["seeds"]
        assert [s.pmcid for s in seeds] == ["PMC1"]


class TestFetchFromPlanCommand:
    """Tests for fetch --from-plan input validation."""

    @patch("text_fetch.fetch.unified_fetch")
    def test_plan_without_valid_pmcids_is_refused(
        self,
        mock_fetch: MagicMock,
        runner: CliRunner,
        tmp_path: Path,
    ) -> None:
        """A plan with no valid PMC ID exits 1 and fetches nothing (#30).

        An empty ID list must never reach the fetcher as "search everything".
        """
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "created_at": "2025-01-25T12:00:00Z",
                    "text_fetch_version": "0.3.2",
                    "config_file": "test.json",
                    "query": "test",
                    "sources": ["europepmc"],
                    "seed_pmcids": ["PMC1a"],
                    "expanded_pmcids": ["PMCPMC2"],
                }
            )
        )

        result = runner.invoke(
            cli,
            ["fetch", "--from-plan", str(plan), "--out", str(tmp_path / "o"), "-y"],
        )

        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit)  # a ClickException
        assert "lists no valid PMC IDs" in result.output
        assert "LOADING EXPANSION PLAN" not in result.output
        mock_fetch.assert_not_called()


class TestDryRunReport:
    """The unified dry-run report shows incomplete expansion lists."""

    @pytest.mark.parametrize(("failed", "shown"), [(0, False), (2, True)])
    def test_lookup_failures_shown(self, capsys, failed: int, shown: bool) -> None:
        """A warning appears only when some lists failed to load in full."""
        from text_fetch.cli.fetch import _display_dry_run_report

        stats = {
            "expansion_result": {
                "seed_stats": {"articles_found": 1, "with_pmcid": 1},
                "expansion_config": {},
                "seed_coverage": {},
                "expansion_stats": {"total_unique": 5, "lookup_failed": failed},
            }
        }

        _display_dry_run_report(stats, "out", True, False)

        out = capsys.readouterr().out
        assert ("2 citation/reference lists failed to load" in out) is shown


class TestExpansionLookupFailureReported:
    """Citation/reference lists that fail to load are reported (#2)."""

    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    SEED = {"id": "111", "source": "MED", "pmid": "111", "pmcid": "PMC111"}

    def _mock(self, requests_mock, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        requests_mock.get(
            f"{self.BASE}/search",
            json={"hitCount": 1, "resultList": {"result": [self.SEED]}},
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>T</article-title></title-group></article-meta>"
            "</front></article></pmc-articleset>",
        )
        # Every references request fails
        requests_mock.get(f"{self.BASE}/MED/111/references", status_code=404)

    def test_europepmc_fetch_warns_when_every_list_fails(
        self, runner: CliRunner, tmp_path: Path, requests_mock, monkeypatch
    ) -> None:
        """Nothing expanded because every list failed: the run says so."""
        self._mock(requests_mock, monkeypatch, tmp_path)

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["europepmc", "fetch", "--query", "x", "--expand-references"]
                + ["--email", "user@example.com", "--out", "o", "--yes"],
            )
            manifest = json.loads(Path("o", "expansion_manifest.json").read_text())

        assert result.exit_code == 0, result.output
        assert "1 citation/reference lists failed to load" in result.output
        # Recorded on disk too, for unattended runs that don't read stdout
        assert manifest["id_issues"]["lookup_failed_count"] == 1

    def test_unified_fetch_warns_when_every_list_fails(
        self, runner: CliRunner, tmp_path: Path, requests_mock, monkeypatch
    ) -> None:
        """The unified fetch summary warns too, without --dry-run."""
        self._mock(requests_mock, monkeypatch, tmp_path)
        config = tmp_path / "search.json"
        config.write_text(json.dumps({"author": "x", "sources": ["europepmc"]}))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(
                cli,
                ["fetch", "--config-file", str(config), "--expand-references"]
                + ["--email", "user@example.com", "--out", "o", "--yes"],
            )

        assert result.exit_code == 0, result.output
        assert "1 citation/reference lists failed to load" in result.output

    def test_from_plan_repeats_the_warning(
        self, runner: CliRunner, tmp_path: Path, requests_mock, monkeypatch
    ) -> None:
        """A plan made while lists failed says so when it is fetched later."""
        self._mock(requests_mock, monkeypatch, tmp_path)
        config = tmp_path / "search.json"
        config.write_text(json.dumps({"author": "x", "sources": ["europepmc"]}))

        with runner.isolated_filesystem(temp_dir=tmp_path):
            dry = runner.invoke(
                cli,
                ["fetch", "--config-file", str(config), "--expand-references"]
                + ["--email", "user@example.com", "--out", "o", "--dry-run"],
                input="n\n",
            )
            result = runner.invoke(
                cli,
                ["fetch", "--from-plan", "o/.expansion_plan.json", "--out", "o2"]
                + ["--email", "user@example.com", "--yes"],
            )

        assert dry.exit_code == 0, dry.output
        assert result.exit_code == 0, result.output
        assert "1 citation/reference lists failed to load" in result.output


class TestFromPlanMalformedStats:
    """Odd plan stats never stop a --from-plan fetch."""

    @pytest.mark.parametrize(
        "stats",
        [None, {"expansion_stats": None}, {"expansion_stats": []}]
        + [{"expansion_stats": {"lookup_failed": "2"}}, "x"],
    )
    @patch("text_fetch.fetch.unified_fetch")
    def test_runs_without_warning(
        self, mock_fetch: MagicMock, runner: CliRunner, tmp_path: Path, stats
    ) -> None:
        """No crash and no warning for stats that aren't a proper count."""
        mock_fetch.return_value = {
            "total_fetched": 0,
            "total_valid": 0,
            "total_incomplete": 0,
            "total_errors": 0,
        }
        plan = tmp_path / "plan.json"
        plan.write_text(
            json.dumps(
                {
                    "created_at": "2025-01-25T12:00:00Z",
                    "text_fetch_version": "0.3.2",
                    "config_file": "test.json",
                    "query": "test",
                    "sources": ["europepmc"],
                    "seed_pmcids": ["PMC1"],
                    "expanded_pmcids": [],
                    "stats": stats,
                }
            )
        )

        result = runner.invoke(
            cli,
            ["fetch", "--from-plan", str(plan), "--out", str(tmp_path / "o"), "-y"],
        )

        assert result.exit_code == 0, result.output
        assert "failed to load" not in result.output


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
