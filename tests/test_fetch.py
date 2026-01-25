"""Tests for unified multi-source fetch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from text_fetch.fetch import (
    ExpansionPlan,
    _fetch_from_source,
    _wrap_callback,
    _write_unified_manifest,
    deduplicate_by_doi,
    unified_fetch,
)
from text_fetch.query import SearchConfig, SourceOptions


class TestSearchConfigMultiSource:
    """Tests for multi-source SearchConfig extensions."""

    def test_from_dict_with_sources(self) -> None:
        """Loads sources from dict."""
        data = {
            "author": "test",
            "sources": ["pmc", "europepmc"],
            "max_results_per_source": 50,
        }
        config = SearchConfig.from_dict(data)

        assert config.sources == ["pmc", "europepmc"]
        assert config.max_results_per_source == 50

    def test_from_dict_with_source_options(self) -> None:
        """Loads source-specific options."""
        data = {
            "author": "test",
            "sources": ["arxiv", "biorxiv"],
            "source_options": {
                "arxiv": {"categories": ["q-bio.MN", "q-bio.QM"]},
                "biorxiv": {"categories": ["systems_biology"]},
            },
        }
        config = SearchConfig.from_dict(data)

        assert "arxiv" in config.source_options
        arxiv_opts = config.source_options["arxiv"]
        assert arxiv_opts.categories == ["q-bio.MN", "q-bio.QM"]
        biorxiv_opts = config.source_options["biorxiv"]
        assert biorxiv_opts.categories == ["systems_biology"]

    def test_from_dict_defaults(self) -> None:
        """Uses default values when not specified."""
        data = {"author": "test"}
        config = SearchConfig.from_dict(data)

        assert config.sources == []
        assert config.source_options == {}
        assert config.max_results_per_source == 100
        assert config.open_access_only is True
        assert config.deduplicate_by_doi is True

    def test_to_europepmc_query(self) -> None:
        """Generates Europe PMC query."""
        config = SearchConfig(
            author="hlavacek ws",
            keywords=["systems biology"],
            open_access_only=True,
        )
        query = config.to_europepmc_query()

        assert 'AUTH:"hlavacek ws"' in query
        assert "OPEN_ACCESS:Y" in query

    def test_to_biorxiv_params(self) -> None:
        """Generates bioRxiv params."""
        config = SearchConfig(
            max_results_per_source=50,
            source_options={
                "biorxiv": SourceOptions(categories=["systems_biology"]),
            },
        )
        params = config.to_biorxiv_params("biorxiv")

        assert params["max_results"] == 50
        assert params["category"] == "systems_biology"

    def test_to_biorxiv_params_override_max_results(self) -> None:
        """Source-specific max_results overrides global."""
        config = SearchConfig(
            max_results_per_source=100,
            source_options={
                "biorxiv": SourceOptions(max_results=25),
            },
        )
        params = config.to_biorxiv_params("biorxiv")

        assert params["max_results"] == 25

    def test_to_chemrxiv_params(self) -> None:
        """Generates ChemRxiv params."""
        config = SearchConfig(
            keywords=["catalysis", "organic"],
            max_results_per_source=50,
        )
        params = config.to_chemrxiv_params()

        assert params["max_results"] == 50
        assert params["term"] == "catalysis organic"

    def test_to_dict_round_trip(self) -> None:
        """Config survives round-trip through dict."""
        config = SearchConfig(
            name="test_corpus",
            author="test",
            sources=["pmc", "europepmc"],
            max_results_per_source=100,
            deduplicate_by_doi=True,
        )
        data = config.to_dict()
        restored = SearchConfig.from_dict(data)

        assert restored.name == config.name
        assert restored.sources == config.sources

    def test_to_dict_includes_source_options(self) -> None:
        """to_dict includes source_options."""
        config = SearchConfig(
            author="test",
            source_options={
                "arxiv": SourceOptions(categories=["q-bio.MN"]),
            },
        )
        data = config.to_dict()

        assert "source_options" in data
        assert "arxiv" in data["source_options"]
        assert data["source_options"]["arxiv"]["categories"] == ["q-bio.MN"]

    def test_date_iso_conversion(self) -> None:
        """Converts date format correctly."""
        from text_fetch.query import DateRange

        config = SearchConfig(
            author="test",
            date_range=DateRange(start="2020/01/01", end="2024/12/31"),
        )

        assert config._date_iso("start") == "2020-01-01"
        assert config._date_iso("end") == "2024-12-31"

    def test_str_includes_sources(self) -> None:
        """String representation includes sources."""
        config = SearchConfig(
            name="test",
            author="test",
            sources=["pmc", "europepmc"],
        )
        s = str(config)

        assert "name='test'" in s
        assert "sources=" in s


class TestSourceOptions:
    """Tests for SourceOptions dataclass."""

    def test_from_dict(self) -> None:
        """Creates from dict."""
        data = {
            "categories": ["q-bio.MN"],
            "extra_keywords": ["modeling"],
            "max_results": 50,
        }
        opts = SourceOptions.from_dict(data)

        assert opts.categories == ["q-bio.MN"]
        assert opts.extra_keywords == ["modeling"]
        assert opts.max_results == 50

    def test_to_dict(self) -> None:
        """Converts to dict."""
        opts = SourceOptions(
            categories=["q-bio.MN"],
            max_results=50,
        )
        data = opts.to_dict()

        assert data["categories"] == ["q-bio.MN"]
        assert data["max_results"] == 50
        assert "extra_keywords" not in data  # Empty list not included

    def test_defaults(self) -> None:
        """Has sensible defaults."""
        opts = SourceOptions()

        assert opts.categories == []
        assert opts.extra_keywords == []
        assert opts.max_results is None


class TestDeduplication:
    """Tests for DOI-based deduplication."""

    def test_deduplicate_removes_duplicates(self, tmp_path: Path) -> None:
        """Removes duplicate DOIs across sources."""
        # Create test structure
        pmc_dir = tmp_path / "pmc" / "valid"
        pmc_dir.mkdir(parents=True)
        europepmc_dir = tmp_path / "europepmc" / "valid"
        europepmc_dir.mkdir(parents=True)

        # Same DOI in both sources
        xml_template = """<?xml version="1.0"?>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="doi">{doi}</article-id>
                </article-meta>
            </front>
        </article>"""

        (pmc_dir / "PMC123.xml").write_text(xml_template.format(doi="10.1234/test"))
        (europepmc_dir / "PMC456.xml").write_text(
            xml_template.format(doi="10.1234/test")
        )

        # Different DOI in europepmc
        (europepmc_dir / "PMC789.xml").write_text(
            xml_template.format(doi="10.5678/other")
        )

        result = deduplicate_by_doi(tmp_path)

        assert result["removed"] == 1  # One duplicate removed
        assert "10.1234/test" in result["unique_dois"]
        assert "10.5678/other" in result["unique_dois"]
        # Filename is now prefixed with source and subdir
        assert (tmp_path / "_duplicates" / "europepmc_valid_PMC456.xml").exists()

    def test_keeps_pmc_over_others(self, tmp_path: Path) -> None:
        """PMC articles take priority over others."""
        # Create test structure with same DOI
        pmc_dir = tmp_path / "pmc" / "valid"
        pmc_dir.mkdir(parents=True)
        arxiv_dir = tmp_path / "arxiv" / "valid"
        arxiv_dir.mkdir(parents=True)

        xml_template = """<?xml version="1.0"?>
        <article>
            <front><article-meta>
                <article-id pub-id-type="doi">{doi}</article-id>
            </article-meta></front>
        </article>"""

        (pmc_dir / "PMC123.xml").write_text(xml_template.format(doi="10.1234/test"))
        (arxiv_dir / "arxiv_123.xml").write_text(
            xml_template.format(doi="10.1234/test")
        )

        result = deduplicate_by_doi(tmp_path)

        # arXiv version should be removed (PMC has priority)
        assert result["removed"] == 1
        # Filename is now prefixed with source and subdir
        assert (tmp_path / "_duplicates" / "arxiv_valid_arxiv_123.xml").exists()
        assert (pmc_dir / "PMC123.xml").exists()

    def test_no_duplicates(self, tmp_path: Path) -> None:
        """Handles case with no duplicates."""
        pmc_dir = tmp_path / "pmc" / "valid"
        pmc_dir.mkdir(parents=True)

        xml_template = """<?xml version="1.0"?>
        <article>
            <front><article-meta>
                <article-id pub-id-type="doi">{doi}</article-id>
            </article-meta></front>
        </article>"""

        (pmc_dir / "PMC123.xml").write_text(xml_template.format(doi="10.1234/unique1"))
        (pmc_dir / "PMC456.xml").write_text(xml_template.format(doi="10.1234/unique2"))

        result = deduplicate_by_doi(tmp_path)

        assert result["removed"] == 0
        assert len(result["unique_dois"]) == 2

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Handles empty directory."""
        result = deduplicate_by_doi(tmp_path)

        assert result["removed"] == 0
        assert result["unique_dois"] == []

    def test_case_insensitive_doi(self, tmp_path: Path) -> None:
        """DOI comparison is case-insensitive."""
        pmc_dir = tmp_path / "pmc" / "valid"
        pmc_dir.mkdir(parents=True)
        europepmc_dir = tmp_path / "europepmc" / "valid"
        europepmc_dir.mkdir(parents=True)

        xml_template = """<?xml version="1.0"?>
        <article>
            <front><article-meta>
                <article-id pub-id-type="doi">{doi}</article-id>
            </article-meta></front>
        </article>"""

        # Same DOI with different case
        (pmc_dir / "PMC123.xml").write_text(xml_template.format(doi="10.1234/TEST"))
        (europepmc_dir / "PMC456.xml").write_text(
            xml_template.format(doi="10.1234/test")
        )

        result = deduplicate_by_doi(tmp_path)

        # Check that duplicate was removed
        assert result["removed"] == 1
        assert (tmp_path / "_duplicates").exists()


class TestUnifiedFetchHelpers:
    """Tests for unified fetch helper functions."""

    def test_wrap_callback_none(self) -> None:
        """Returns None for None callback."""
        result = _wrap_callback(None, "pmc")
        assert result is None

    def test_wrap_callback_adds_source(self) -> None:
        """Wrapped callback adds source parameter."""
        calls: list[tuple[str, str, int, int]] = []

        def cb(source: str, article_id: str, current: int, total: int) -> None:
            calls.append((source, article_id, current, total))

        wrapped = _wrap_callback(cb, "europepmc")
        assert wrapped is not None

        wrapped("PMC123", 1, 10)

        assert len(calls) == 1
        assert calls[0] == ("europepmc", "PMC123", 1, 10)


class TestUnifiedFetch:
    """Tests for unified_fetch orchestrator."""

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_fetches_from_single_source(
        self,
        mock_write_manifest: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Fetches from single PMC source."""
        mock_fetch_source.return_value = {
            "fetched": 5,
            "valid": 3,
            "incomplete": 2,
            "errors": 0,
        }

        config = SearchConfig(author="test", sources=["pmc"])

        result = unified_fetch(
            config,
            output_dir=tmp_path,
            email="test@example.com",
        )

        assert result["total_fetched"] == 5
        assert result["per_source"]["pmc"]["valid"] == 3
        mock_fetch_source.assert_called_once()

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_fetches_from_multiple_sources(
        self,
        mock_write_manifest: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Fetches from multiple sources."""
        mock_fetch_source.side_effect = [
            {"fetched": 5, "valid": 3, "incomplete": 2, "errors": 0},
            {"fetched": 10, "valid": 8, "incomplete": 2, "errors": 0},
        ]

        config = SearchConfig(
            author="test",
            sources=["pmc", "europepmc"],
        )

        result = unified_fetch(
            config,
            output_dir=tmp_path,
            email="test@example.com",
        )

        assert result["total_fetched"] == 15
        assert "pmc" in result["per_source"]
        assert "europepmc" in result["per_source"]
        assert mock_fetch_source.call_count == 2

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_handles_source_error(
        self,
        mock_write_manifest: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Continues after source failure."""
        mock_fetch_source.side_effect = [
            Exception("API error"),
            {"fetched": 10, "valid": 8, "incomplete": 2, "errors": 0},
        ]

        config = SearchConfig(
            author="test",
            sources=["pmc", "europepmc"],
        )

        result = unified_fetch(
            config,
            output_dir=tmp_path,
            email="test@example.com",
        )

        assert result["total_errors"] >= 1
        assert "error" in result["per_source"]["pmc"]
        assert result["per_source"]["europepmc"]["valid"] == 8

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch.deduplicate_by_doi")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_deduplication_runs(
        self,
        mock_write_manifest: MagicMock,
        mock_dedup: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Deduplication is called when enabled."""
        mock_fetch_source.return_value = {
            "fetched": 5,
            "valid": 5,
            "incomplete": 0,
            "errors": 0,
        }
        mock_dedup.return_value = {"removed": 1, "unique_dois": ["10.1234/test"]}

        config = SearchConfig(
            author="test",
            sources=["pmc"],
            deduplicate_by_doi=True,
        )

        result = unified_fetch(config, output_dir=tmp_path, email="test@example.com")

        mock_dedup.assert_called_once_with(tmp_path)
        assert result["duplicates_removed"] == 1

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch.deduplicate_by_doi")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_skips_deduplication_when_disabled(
        self,
        mock_write_manifest: MagicMock,
        mock_dedup: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Skips deduplication when disabled."""
        mock_fetch_source.return_value = {
            "fetched": 5,
            "valid": 5,
            "incomplete": 0,
            "errors": 0,
        }

        config = SearchConfig(
            author="test",
            sources=["pmc"],
            deduplicate_by_doi=False,
        )

        unified_fetch(config, output_dir=tmp_path, email="test@example.com")

        mock_dedup.assert_not_called()

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_uses_default_pmc_source(
        self,
        mock_write_manifest: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Defaults to PMC if no sources specified."""
        mock_fetch_source.return_value = {
            "fetched": 5,
            "valid": 5,
            "incomplete": 0,
            "errors": 0,
        }

        config = SearchConfig(author="test", sources=[])

        result = unified_fetch(config, output_dir=tmp_path, email="test@example.com")

        assert result["sources"] == ["pmc"]

    @patch("text_fetch.fetch._fetch_from_source")
    @patch("text_fetch.fetch._write_unified_manifest")
    def test_creates_output_directory(
        self,
        mock_write_manifest: MagicMock,
        mock_fetch_source: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Creates output directory if it doesn't exist."""
        mock_fetch_source.return_value = {
            "fetched": 0,
            "valid": 0,
            "incomplete": 0,
            "errors": 0,
        }

        config = SearchConfig(author="test", sources=["pmc"])
        output_dir = tmp_path / "new_dir" / "nested"

        unified_fetch(config, output_dir=output_dir, email="test@example.com")

        assert output_dir.exists()


class TestFetchFromSource:
    """Tests for _fetch_from_source dispatch."""

    @patch("text_fetch.pmc.fetch_pmc")
    def test_dispatches_to_pmc(self, mock_fetch: MagicMock, tmp_path: Path) -> None:
        """Routes to fetch_pmc for 'pmc' source."""
        mock_fetch.return_value = {"fetched": 5}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "pmc",
            config,
            tmp_path,
            workspace=None,
            email="test@example.com",
            api_key=None,
            grobid_url=None,
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    @patch("text_fetch.europepmc.fetch_europepmc")
    def test_dispatches_to_europepmc(
        self, mock_fetch: MagicMock, tmp_path: Path
    ) -> None:
        """Routes to fetch_europepmc for 'europepmc' source."""
        mock_fetch.return_value = {"fetched": 10}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "europepmc",
            config,
            tmp_path,
            workspace=None,
            email=None,
            api_key=None,
            grobid_url=None,
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    @patch("text_fetch.biorxiv.fetch_biorxiv")
    def test_dispatches_to_biorxiv(self, mock_fetch: MagicMock, tmp_path: Path) -> None:
        """Routes to fetch_biorxiv for 'biorxiv' source."""
        mock_fetch.return_value = {"fetched": 5}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "biorxiv",
            config,
            tmp_path,
            workspace=None,
            email=None,
            api_key=None,
            grobid_url=None,
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    @patch("text_fetch.biorxiv.fetch_medrxiv")
    def test_dispatches_to_medrxiv(self, mock_fetch: MagicMock, tmp_path: Path) -> None:
        """Routes to fetch_medrxiv for 'medrxiv' source."""
        mock_fetch.return_value = {"fetched": 5}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "medrxiv",
            config,
            tmp_path,
            workspace=None,
            email=None,
            api_key=None,
            grobid_url=None,
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    @patch("text_fetch.arxiv.fetch_arxiv")
    def test_dispatches_to_arxiv(self, mock_fetch: MagicMock, tmp_path: Path) -> None:
        """Routes to fetch_arxiv for 'arxiv' source."""
        mock_fetch.return_value = {"fetched": 5}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "arxiv",
            config,
            tmp_path,
            workspace=None,
            email=None,
            api_key=None,
            grobid_url="http://localhost:8070",
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    def test_arxiv_requires_grobid(self, tmp_path: Path) -> None:
        """arXiv source requires GROBID URL."""
        config = SearchConfig(author="test")

        with pytest.raises(ValueError, match="GROBID"):
            _fetch_from_source(
                "arxiv",
                config,
                tmp_path,
                workspace=None,
                email=None,
                api_key=None,
                grobid_url=None,
                verbose=False,
                progress_callback=None,
            )

    @patch("text_fetch.chemrxiv.fetch_chemrxiv")
    def test_dispatches_to_chemrxiv(
        self, mock_fetch: MagicMock, tmp_path: Path
    ) -> None:
        """Routes to fetch_chemrxiv for 'chemrxiv' source."""
        mock_fetch.return_value = {"fetched": 5}

        config = SearchConfig(author="test")
        _fetch_from_source(
            "chemrxiv",
            config,
            tmp_path,
            workspace=None,
            email=None,
            api_key=None,
            grobid_url="http://localhost:8070",
            verbose=False,
            progress_callback=None,
        )

        mock_fetch.assert_called_once()

    def test_chemrxiv_requires_grobid(self, tmp_path: Path) -> None:
        """ChemRxiv source requires GROBID URL."""
        config = SearchConfig(author="test")

        with pytest.raises(ValueError, match="GROBID"):
            _fetch_from_source(
                "chemrxiv",
                config,
                tmp_path,
                workspace=None,
                email=None,
                api_key=None,
                grobid_url=None,
                verbose=False,
                progress_callback=None,
            )

    def test_raises_for_unknown_source(self, tmp_path: Path) -> None:
        """Raises ValueError for unknown source."""
        config = SearchConfig(author="test")

        with pytest.raises(ValueError, match="Unknown source"):
            _fetch_from_source(
                "unknown",
                config,
                tmp_path,
                workspace=None,
                email=None,
                api_key=None,
                grobid_url=None,
                verbose=False,
                progress_callback=None,
            )


class TestWriteUnifiedManifest:
    """Tests for _write_unified_manifest."""

    def test_writes_manifest(self, tmp_path: Path) -> None:
        """Writes manifest.json with correct structure."""
        stats: dict[str, Any] = {
            "sources": ["pmc"],
            "per_source": {"pmc": {"fetched": 5, "valid": 5}},
            "total_fetched": 5,
            "total_valid": 5,
            "total_incomplete": 0,
            "total_errors": 0,
            "duplicates_removed": 0,
            "unique_dois": [],
        }
        config = SearchConfig(author="test", sources=["pmc"])

        _write_unified_manifest(tmp_path, stats, config)

        manifest_path = tmp_path / "manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["version"] == "1.0"
        assert "created_at" in manifest
        assert manifest["statistics"]["total_fetched"] == 5
        assert "config" in manifest

    def test_manifest_includes_per_source_stats(self, tmp_path: Path) -> None:
        """Manifest includes per-source statistics."""
        stats: dict[str, Any] = {
            "sources": ["pmc", "europepmc"],
            "per_source": {
                "pmc": {"fetched": 5, "valid": 5},
                "europepmc": {"fetched": 10, "valid": 8},
            },
            "total_fetched": 15,
            "total_valid": 13,
            "total_incomplete": 0,
            "total_errors": 0,
            "duplicates_removed": 2,
            "unique_dois": [],
        }
        config = SearchConfig(author="test", sources=["pmc", "europepmc"])

        _write_unified_manifest(tmp_path, stats, config)

        manifest = json.loads((tmp_path / "manifest.json").read_text())
        assert "pmc" in manifest["per_source"]
        assert "europepmc" in manifest["per_source"]
        assert manifest["statistics"]["duplicates_removed"] == 2


class TestExpansionPlan:
    """Tests for ExpansionPlan dataclass."""

    def test_to_json_produces_valid_json(self) -> None:
        """to_json produces valid JSON string."""
        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="ebola.json",
            query="test query",
            sources=["europepmc"],
            seed_pmcids=["PMC123", "PMC456"],
            expanded_pmcids=["PMC789", "PMC012"],
            expansion_config={"depth": 1},
            stats={"seeds_found": 100},
        )

        json_str = plan.to_json()
        data = json.loads(json_str)

        assert data["created_at"] == "2025-01-25T12:00:00Z"
        assert data["text_fetch_version"] == "0.3.2"
        assert data["config_file"] == "ebola.json"
        assert data["query"] == "test query"
        assert data["sources"] == ["europepmc"]
        assert data["seed_pmcids"] == ["PMC123", "PMC456"]
        assert data["expanded_pmcids"] == ["PMC789", "PMC012"]
        assert data["expansion_config"]["depth"] == 1
        assert data["stats"]["seeds_found"] == 100

    def test_from_json_loads_plan(self, tmp_path: Path) -> None:
        """from_json loads plan from file."""
        data = {
            "created_at": "2025-01-25T12:00:00Z",
            "text_fetch_version": "0.3.2",
            "config_file": "test.json",
            "query": "test query",
            "sources": ["europepmc"],
            "seed_pmcids": ["PMC123"],
            "expanded_pmcids": ["PMC789"],
            "expansion_config": {"depth": 2},
            "stats": {},
        }

        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(data))

        plan = ExpansionPlan.from_json(plan_path)

        assert plan.created_at == "2025-01-25T12:00:00Z"
        assert plan.text_fetch_version == "0.3.2"
        assert plan.seed_pmcids == ["PMC123"]
        assert plan.expanded_pmcids == ["PMC789"]
        assert plan.expansion_config["depth"] == 2

    def test_save_creates_hidden_file(self, tmp_path: Path) -> None:
        """save creates .expansion_plan.json file."""
        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="test.json",
            query="test",
            sources=["europepmc"],
            seed_pmcids=["PMC123"],
            expanded_pmcids=["PMC789"],
        )

        path = plan.save(tmp_path)

        assert path.name == ".expansion_plan.json"
        assert path.exists()
        assert path == tmp_path / ".expansion_plan.json"

        # Verify content
        loaded = json.loads(path.read_text())
        assert loaded["seed_pmcids"] == ["PMC123"]

    def test_save_creates_directory_if_needed(self, tmp_path: Path) -> None:
        """save creates parent directory if it doesn't exist."""
        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="test.json",
            query="test",
            sources=["europepmc"],
            seed_pmcids=["PMC123"],
            expanded_pmcids=[],
        )

        nested_dir = tmp_path / "nested" / "deep"
        path = plan.save(nested_dir)

        assert path.exists()
        assert nested_dir.exists()

    def test_total_papers_deduplicates(self) -> None:
        """total_papers returns unique count."""
        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="test.json",
            query="test",
            sources=["europepmc"],
            seed_pmcids=["PMC1", "PMC2"],
            expanded_pmcids=["PMC2", "PMC3"],  # PMC2 is duplicate
        )

        # Should be 3: PMC1, PMC2, PMC3
        assert plan.total_papers == 3

    def test_total_papers_empty(self) -> None:
        """total_papers handles empty lists."""
        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="test.json",
            query="test",
            sources=["europepmc"],
            seed_pmcids=[],
            expanded_pmcids=[],
        )

        assert plan.total_papers == 0

    def test_round_trip_json(self, tmp_path: Path) -> None:
        """Plan survives save/load round-trip."""
        original = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="ebola.json",
            query="complex query",
            sources=["europepmc"],
            seed_pmcids=["PMC1", "PMC2", "PMC3"],
            expanded_pmcids=["PMC4", "PMC5"],
            expansion_config={
                "expand_references": True,
                "expand_citations": True,
                "depth": 2,
                "max_expansion": 1000,
            },
            stats={
                "seeds_found": 50,
                "seeds_with_pmcid": 45,
            },
        )

        # Save and reload
        path = original.save(tmp_path)
        loaded = ExpansionPlan.from_json(path)

        assert loaded.created_at == original.created_at
        assert loaded.text_fetch_version == original.text_fetch_version
        assert loaded.config_file == original.config_file
        assert loaded.query == original.query
        assert loaded.sources == original.sources
        assert loaded.seed_pmcids == original.seed_pmcids
        assert loaded.expanded_pmcids == original.expanded_pmcids
        assert loaded.expansion_config == original.expansion_config
        assert loaded.stats == original.stats


class TestUnifiedFetchWithPlan:
    """Tests for unified_fetch with expansion_plan parameter."""

    @patch("text_fetch.fetch._fetch_from_expansion_plan")
    def test_uses_plan_directly(
        self,
        mock_fetch_plan: MagicMock,
        tmp_path: Path,
    ) -> None:
        """When expansion_plan provided, uses it directly."""
        mock_fetch_plan.return_value = {
            "sources": ["europepmc"],
            "per_source": {},
            "total_fetched": 10,
            "total_valid": 10,
            "total_incomplete": 0,
            "total_errors": 0,
            "duplicates_removed": 0,
            "duplicates_skipped": 0,
            "from_plan": True,
        }

        plan = ExpansionPlan(
            created_at="2025-01-25T12:00:00Z",
            text_fetch_version="0.3.2",
            config_file="test.json",
            query="test",
            sources=["europepmc"],
            seed_pmcids=["PMC1"],
            expanded_pmcids=["PMC2"],
        )

        result = unified_fetch(
            output_dir=tmp_path,
            expansion_plan=plan,
        )

        assert result["from_plan"] is True
        mock_fetch_plan.assert_called_once()

    def test_requires_config_without_plan(self, tmp_path: Path) -> None:
        """Raises error if no config and no plan."""
        with pytest.raises(ValueError, match="config is required"):
            unified_fetch(output_dir=tmp_path)
