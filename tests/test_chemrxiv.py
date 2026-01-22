"""Tests for ChemRxiv client."""

from datetime import datetime

import pytest
from text_fetch.chemrxiv import (
    CHEMRXIV_CATEGORIES,
    ChemrxivArticle,
    ChemrxivClient,
    get_category_id,
    get_category_ids,
)


class TestChemrxivArticle:
    """Tests for ChemrxivArticle dataclass."""

    def test_id_short(self) -> None:
        """Short ID removes prefix."""
        article = ChemrxivArticle(
            item_id="item_2024-abc123",
            doi="10.26434/chemrxiv-2024-abc123",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            subjects=[],
            published_date=datetime.now(),
        )
        assert article.id_short == "2024-abc123"

    def test_id_short_no_prefix(self) -> None:
        """Short ID handles missing prefix."""
        article = ChemrxivArticle(
            item_id="2024-abc123",
            doi="10.26434/chemrxiv-2024-abc123",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            subjects=[],
            published_date=datetime.now(),
        )
        assert article.id_short == "2024-abc123"


class TestChemrxivClient:
    """Tests for ChemrxivClient."""

    def test_normalize_id_plain(self) -> None:
        """Plain ID with prefix unchanged."""
        result = ChemrxivClient.normalize_id("item_2024-abc123")
        assert result == "item_2024-abc123"

    def test_normalize_id_no_prefix(self) -> None:
        """ID without prefix gets prefix added."""
        result = ChemrxivClient.normalize_id("2024-abc123")
        assert result == "item_2024-abc123"

    def test_normalize_id_with_spaces(self) -> None:
        """ID with whitespace is trimmed."""
        result = ChemrxivClient.normalize_id("  item_2024-abc123  ")
        assert result == "item_2024-abc123"

    def test_normalize_id_from_url(self) -> None:
        """ID is extracted from URL."""
        url = "https://chemrxiv.org/engage/chemrxiv/article/item_2024-abc123"
        result = ChemrxivClient.normalize_id(url)
        assert result == "item_2024-abc123"

    def test_search_success(self, requests_mock: pytest.fixture) -> None:
        """search returns articles."""
        response = {
            "totalCount": 1,
            "itemHits": [
                {
                    "item": {
                        "id": "item_2024-abc123",
                        "doi": "10.26434/chemrxiv-2024-abc123",
                        "title": "Test Article",
                        "authors": [{"firstName": "John", "lastName": "Doe"}],
                        "abstract": "Test abstract",
                        "publishedDate": "2024-01-15T00:00:00.000Z",
                        "version": 1,
                        "categories": [{"id": 17, "name": "Organic Chemistry"}],
                        "subjects": [{"id": 100, "name": "Synthesis"}],
                        "asset": {"original": {"url": "https://example.com/test.pdf"}},
                        "license": {"name": "CC BY 4.0"},
                    }
                }
            ],
        }
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
            json=response,
        )

        client = ChemrxivClient()
        articles, total = client.search(term="test")

        assert total == 1
        assert len(articles) == 1
        assert articles[0].item_id == "item_2024-abc123"
        assert articles[0].doi == "10.26434/chemrxiv-2024-abc123"
        assert articles[0].authors == ["John Doe"]
        assert articles[0].title == "Test Article"
        assert articles[0].categories == ["Organic Chemistry"]
        assert articles[0].subjects == ["Synthesis"]
        assert articles[0].pdf_url == "https://example.com/test.pdf"
        assert articles[0].license == "CC BY 4.0"

    def test_search_empty_response(self, requests_mock: pytest.fixture) -> None:
        """search handles empty response."""
        response = {
            "totalCount": 0,
            "itemHits": [],
        }
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
            json=response,
        )

        client = ChemrxivClient()
        articles, total = client.search(term="nonexistent")

        assert total == 0
        assert articles == []

    def test_api_error_returns_empty(self, requests_mock: pytest.fixture) -> None:
        """API error returns empty list."""
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
            status_code=500,
        )

        client = ChemrxivClient()
        articles, total = client.search(term="test")

        assert articles == []
        assert total == 0

    def test_get_by_id_success(self, requests_mock: pytest.fixture) -> None:
        """get_by_id returns article."""
        response = {
            "id": "item_2024-abc123",
            "doi": "10.26434/chemrxiv-2024-abc123",
            "title": "Test Article",
            "authors": [{"firstName": "Jane", "lastName": "Smith"}],
            "abstract": "Abstract text",
            "publishedDate": "2024-03-01T12:00:00.000Z",
            "version": 2,
            "categories": [],
            "subjects": [],
            "asset": {},
        }
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1"
            "/items/item_2024-abc123",
            json=response,
        )

        client = ChemrxivClient()
        article = client.get_by_id("item_2024-abc123")

        assert article is not None
        assert article.item_id == "item_2024-abc123"
        assert article.version == 2
        assert article.authors == ["Jane Smith"]

    def test_get_by_id_not_found(self, requests_mock: pytest.fixture) -> None:
        """get_by_id returns None for missing article."""
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1"
            "/items/item_2024-missing",
            status_code=404,
        )

        client = ChemrxivClient()
        article = client.get_by_id("item_2024-missing")

        assert article is None

    def test_parse_item_missing_id(self) -> None:
        """_parse_item returns None if id missing."""
        client = ChemrxivClient()
        result = client._parse_item({"title": "No ID"})
        assert result is None

    def test_parse_item_handles_missing_fields(self) -> None:
        """_parse_item handles missing optional fields."""
        client = ChemrxivClient()
        item = {
            "id": "item_2024-test",
            "publishedDate": "2024-01-01T00:00:00Z",
        }
        result = client._parse_item(item)

        assert result is not None
        assert result.item_id == "item_2024-test"
        assert result.doi == ""
        assert result.title == ""
        assert result.authors == []
        assert result.abstract == ""
        assert result.categories == []
        assert result.subjects == []
        assert result.pdf_url is None

    def test_parse_item_invalid_date(self) -> None:
        """_parse_item handles invalid date gracefully."""
        client = ChemrxivClient()
        item = {
            "id": "item_2024-test",
            "publishedDate": "invalid-date",
        }
        result = client._parse_item(item)

        assert result is not None
        # Should use datetime.now() for invalid dates
        assert isinstance(result.published_date, datetime)


class TestCategories:
    """Tests for category helpers."""

    def test_get_category_id_found(self) -> None:
        """Category ID lookup works."""
        cat_id = get_category_id("organic_chemistry")
        assert cat_id is not None
        assert cat_id == 17

    def test_get_category_id_not_found(self) -> None:
        """Unknown category returns None."""
        assert get_category_id("unknown_category") is None

    def test_get_category_id_normalized_spaces(self) -> None:
        """Category names with spaces are normalized."""
        assert get_category_id("organic chemistry") == get_category_id(
            "organic_chemistry"
        )

    def test_get_category_id_normalized_hyphens(self) -> None:
        """Category names with hyphens are normalized."""
        assert get_category_id("organic-chemistry") == get_category_id(
            "organic_chemistry"
        )

    def test_get_category_id_case_insensitive(self) -> None:
        """Category names are case-insensitive."""
        assert get_category_id("Organic_Chemistry") == get_category_id(
            "organic_chemistry"
        )

    def test_get_category_ids_filters_none(self) -> None:
        """get_category_ids filters out unknown categories."""
        result = get_category_ids(
            [
                "organic_chemistry",
                "unknown",
                "catalysis",
            ]
        )
        assert len(result) == 2
        assert 17 in result  # organic_chemistry
        assert 4 in result  # catalysis

    def test_get_category_ids_empty_input(self) -> None:
        """get_category_ids handles empty list."""
        result = get_category_ids([])
        assert result == []

    def test_chemrxiv_categories_not_empty(self) -> None:
        """CHEMRXIV_CATEGORIES has entries."""
        assert len(CHEMRXIV_CATEGORIES) >= 20

    def test_chemrxiv_categories_has_expected_keys(self) -> None:
        """CHEMRXIV_CATEGORIES has expected categories."""
        expected = [
            "organic_chemistry",
            "inorganic_chemistry",
            "biochemistry",
            "catalysis",
            "computational_chemistry",
        ]
        for cat in expected:
            assert cat in CHEMRXIV_CATEGORIES


class TestIterSearch:
    """Tests for iter_search pagination."""

    def test_iter_search_single_page(self, requests_mock: pytest.fixture) -> None:
        """iter_search handles single page."""
        response = {
            "totalCount": 2,
            "itemHits": [
                {
                    "item": {
                        "id": "item_2024-001",
                        "publishedDate": "2024-01-01T00:00:00Z",
                    }
                },
                {
                    "item": {
                        "id": "item_2024-002",
                        "publishedDate": "2024-01-02T00:00:00Z",
                    }
                },
            ],
        }
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
            json=response,
        )

        client = ChemrxivClient()
        articles = list(client.iter_search(term="test"))

        assert len(articles) == 2
        assert articles[0].item_id == "item_2024-001"
        assert articles[1].item_id == "item_2024-002"

    def test_iter_search_respects_max_results(
        self, requests_mock: pytest.fixture
    ) -> None:
        """iter_search stops at max_results."""
        response = {
            "totalCount": 100,
            "itemHits": [
                {
                    "item": {
                        "id": f"item_2024-{i:03d}",
                        "publishedDate": "2024-01-01T00:00:00Z",
                    }
                }
                for i in range(50)
            ],
        }
        requests_mock.get(
            "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items",
            json=response,
        )

        client = ChemrxivClient()
        articles = list(client.iter_search(term="test", max_results=10))

        assert len(articles) == 10
