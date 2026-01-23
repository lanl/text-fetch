"""Tests for query builder module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from text_fetch.query import DateRange, SearchConfig, SearchConfigError


class TestDateRange:
    """Tests for DateRange dataclass."""

    def test_to_pubmed_filter(self):
        """Should convert to PubMed date filter syntax."""
        dr = DateRange(start="2024/01/01", end="2024/12/31")
        assert dr.to_pubmed_filter() == "2024/01/01:2024/12/31[dp]"

    def test_validate_valid_dates(self):
        """Should pass validation for correct format."""
        dr = DateRange(start="2024/01/01", end="2024/12/31")
        assert dr.validate() == []

    def test_validate_invalid_start(self):
        """Should catch invalid start date format."""
        dr = DateRange(start="2024-01-01", end="2024/12/31")
        errors = dr.validate()
        assert len(errors) == 1
        assert "start date" in errors[0]

    def test_validate_invalid_end(self):
        """Should catch invalid end date format."""
        dr = DateRange(start="2024/01/01", end="12/31/2024")
        errors = dr.validate()
        assert len(errors) == 1
        assert "end date" in errors[0]


class TestSearchConfig:
    """Tests for SearchConfig dataclass."""

    def test_author_only(self):
        """Should generate author-only query."""
        config = SearchConfig(author="hlavacek ws")
        query = config.to_pubmed_query()
        assert query == "hlavacek ws[au]"

    def test_single_keyword(self):
        """Should generate single keyword query."""
        config = SearchConfig(keywords=["systems biology"])
        query = config.to_pubmed_query()
        assert query == '"systems biology"[tiab]'

    def test_multiple_keywords(self):
        """Should combine keywords with OR."""
        config = SearchConfig(keywords=["systems biology", "modeling"])
        query = config.to_pubmed_query()
        assert '"systems biology"[tiab]' in query
        assert '"modeling"[tiab]' in query
        assert " OR " in query
        assert query.startswith("(")
        assert query.endswith(")")

    def test_author_and_keywords(self):
        """Should combine author and keywords with AND."""
        config = SearchConfig(
            author="hlavacek ws", keywords=["systems biology", "rule-based"]
        )
        query = config.to_pubmed_query()
        assert "hlavacek ws[au]" in query
        assert " AND " in query
        assert '"systems biology"[tiab]' in query

    def test_date_range(self):
        """Should include date range filter."""
        config = SearchConfig(
            author="hlavacek ws",
            date_range=DateRange(start="2020/01/01", end="2024/12/31"),
        )
        query = config.to_pubmed_query()
        assert "2020/01/01:2024/12/31[dp]" in query

    def test_all_keywords_combines_categories(self):
        """Should combine all keyword categories."""
        config = SearchConfig(
            keywords=["a"],
            virus_keywords=["b", "c"],
            disease_keywords=["d"],
            vaccine_keywords=["e", "f"],
        )
        assert len(config.all_keywords) == 6
        assert "a" in config.all_keywords
        assert "b" in config.all_keywords
        assert "f" in config.all_keywords

    def test_to_pubmed_query_by_category(self):
        """Should group keywords by category with AND."""
        config = SearchConfig(
            virus_keywords=["ebola", "marburg"],
            disease_keywords=["hemorrhagic fever"],
            vaccine_keywords=["vaccine"],
        )
        query = config.to_pubmed_query_by_category()

        # Should have AND between categories
        assert " AND " in query

        # Virus keywords grouped with OR
        assert '"ebola"[tiab]' in query
        assert '"marburg"[tiab]' in query

    def test_validate_empty_config(self):
        """Should reject config with no search criteria."""
        config = SearchConfig()
        errors = config.validate()
        assert len(errors) == 1
        assert "at least one of" in errors[0]

    def test_validate_valid_config(self):
        """Should pass validation for valid config."""
        config = SearchConfig(author="hlavacek ws")
        assert config.validate() == []

    def test_to_pubmed_query_raises_on_invalid(self):
        """Should raise SearchConfigError for invalid config."""
        config = SearchConfig()
        with pytest.raises(SearchConfigError):
            config.to_pubmed_query()

    def test_str_representation(self):
        """Should produce readable string representation."""
        config = SearchConfig(
            author="hlavacek ws",
            keywords=["a", "b"],
            date_range=DateRange(start="2024/01/01", end="2024/12/31"),
        )
        s = str(config)
        assert "hlavacek ws" in s
        assert "keywords=2" in s
        assert "2024/01/01" in s


class TestSearchConfigFromJson:
    """Tests for loading SearchConfig from JSON."""

    def test_from_dict_simple(self):
        """Should load simple config from dict."""
        data = {
            "author": "hlavacek ws",
            "keywords": ["systems biology"],
        }
        config = SearchConfig.from_dict(data)
        assert config.author == "hlavacek ws"
        assert config.keywords == ["systems biology"]

    def test_from_dict_with_date_range(self):
        """Should parse date_range from dict."""
        data = {
            "author": "hlavacek ws",
            "date_range": {
                "start": "2024/01/01",
                "end": "2024/12/31",
            },
        }
        config = SearchConfig.from_dict(data)
        assert config.date_range is not None
        assert config.date_range.start == "2024/01/01"

    def test_from_dict_ebola_format(self):
        """Should load ebola.json format."""
        data = {
            "virus_keywords": ["Ebola", "Marburg"],
            "disease_keywords": ["hemorrhagic fever"],
            "vaccine_keywords": ["vaccine", "immunization"],
            "date_range": {
                "start": "2024/01/01",
                "end": "2024/02/28",
            },
        }
        config = SearchConfig.from_dict(data)
        assert len(config.virus_keywords) == 2
        assert len(config.disease_keywords) == 1
        assert len(config.vaccine_keywords) == 2
        assert config.date_range is not None

    def test_from_json_file(self, tmp_path: Path):
        """Should load config from JSON file."""
        config_file = tmp_path / "search.json"
        config_file.write_text(
            json.dumps(
                {
                    "author": "hlavacek ws",
                    "keywords": ["modeling"],
                }
            )
        )

        config = SearchConfig.from_json(config_file)
        assert config.author == "hlavacek ws"
        assert config.source_path == str(config_file)

    def test_from_json_file_not_found(self, tmp_path: Path):
        """Should raise SearchConfigError for missing file."""
        with pytest.raises(SearchConfigError) as exc:
            SearchConfig.from_json(tmp_path / "missing.json")
        assert "not found" in str(exc.value)

    def test_from_json_invalid_json(self, tmp_path: Path):
        """Should raise SearchConfigError for invalid JSON."""
        config_file = tmp_path / "bad.json"
        config_file.write_text("not valid json{")

        with pytest.raises(SearchConfigError) as exc:
            SearchConfig.from_json(config_file)
        assert "Invalid JSON" in str(exc.value)

    def test_to_dict_roundtrip(self):
        """Should serialize and deserialize correctly."""
        original = SearchConfig(
            author="hlavacek ws",
            keywords=["a", "b"],
            virus_keywords=["c"],
            date_range=DateRange(start="2024/01/01", end="2024/12/31"),
        )
        data = original.to_dict()
        restored = SearchConfig.from_dict(data)

        assert restored.author == original.author
        assert restored.keywords == original.keywords
        assert restored.virus_keywords == original.virus_keywords
        assert restored.date_range is not None
        assert restored.date_range.start == original.date_range.start


class TestEbolaJsonIntegration:
    """Integration tests with actual ebola.json file."""

    @pytest.fixture
    def ebola_config(self) -> SearchConfig:
        """Load ebola.json if it exists."""
        ebola_path = Path("scripts/legacy/ebola.json")
        if not ebola_path.exists():
            pytest.skip("scripts/legacy/ebola.json not found")
        return SearchConfig.from_json(ebola_path)

    def test_ebola_loads(self, ebola_config: SearchConfig):
        """Should load ebola.json without errors."""
        assert len(ebola_config.virus_keywords) > 0
        assert len(ebola_config.disease_keywords) > 0
        assert len(ebola_config.vaccine_keywords) > 0

    def test_ebola_has_date_range(self, ebola_config: SearchConfig):
        """Should have date range."""
        assert ebola_config.date_range is not None

    def test_ebola_validates(self, ebola_config: SearchConfig):
        """Should pass validation."""
        errors = ebola_config.validate()
        assert errors == []

    def test_ebola_generates_query(self, ebola_config: SearchConfig):
        """Should generate valid PubMed query."""
        query = ebola_config.to_pubmed_query()
        assert len(query) > 0
        assert "[tiab]" in query
        assert "[dp]" in query

    def test_ebola_generates_category_query(self, ebola_config: SearchConfig):
        """Should generate category-grouped query."""
        query = ebola_config.to_pubmed_query_by_category()
        # With 3 keyword categories + date, should have multiple AND
        assert query.count(" AND ") >= 3
