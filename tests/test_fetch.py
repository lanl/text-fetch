"""Tests for unified multi-source fetch."""

from __future__ import annotations

from pathlib import Path

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
        from text_fetch.fetch import deduplicate_by_doi

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
        assert (tmp_path / "_duplicates" / "PMC456.xml").exists()

    def test_keeps_pmc_over_others(self, tmp_path: Path) -> None:
        """PMC articles take priority over others."""
        from text_fetch.fetch import deduplicate_by_doi

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
        assert (tmp_path / "_duplicates" / "arxiv_123.xml").exists()
        assert (pmc_dir / "PMC123.xml").exists()

    def test_no_duplicates(self, tmp_path: Path) -> None:
        """Handles case with no duplicates."""
        from text_fetch.fetch import deduplicate_by_doi

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
        from text_fetch.fetch import deduplicate_by_doi

        result = deduplicate_by_doi(tmp_path)

        assert result["removed"] == 0
        assert result["unique_dois"] == []

    def test_case_insensitive_doi(self, tmp_path: Path) -> None:
        """DOI comparison is case-insensitive."""
        from text_fetch.fetch import deduplicate_by_doi

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
        from text_fetch.fetch import _wrap_callback

        result = _wrap_callback(None, "pmc")
        assert result is None

    def test_wrap_callback_adds_source(self) -> None:
        """Wrapped callback adds source parameter."""
        from text_fetch.fetch import _wrap_callback

        calls: list[tuple[str, str, int, int]] = []

        def cb(source: str, article_id: str, current: int, total: int) -> None:
            calls.append((source, article_id, current, total))

        wrapped = _wrap_callback(cb, "europepmc")
        assert wrapped is not None

        wrapped("PMC123", 1, 10)

        assert len(calls) == 1
        assert calls[0] == ("europepmc", "PMC123", 1, 10)
