"""Tests for bioRxiv/medRxiv client."""

from datetime import datetime

import pytest
from text_fetch.biorxiv import (
    BIORXIV_CATEGORIES,
    MEDRXIV_CATEGORIES,
    BiorxivArticle,
    BiorxivClient,
)


class TestBiorxivArticle:
    """Tests for BiorxivArticle dataclass."""

    def test_pdf_url_construction(self) -> None:
        """PDF URL is constructed correctly."""
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            version=2,
            server="biorxiv",
        )
        expected = (
            "https://www.biorxiv.org/content/10.1101/2024.01.15.123456v2.full.pdf"
        )
        assert article.pdf_url == expected

    def test_id_short(self) -> None:
        """Short ID removes prefix."""
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
        )
        assert article.id_short == "2024.01.15.123456"

    def test_medrxiv_pdf_url(self) -> None:
        """medRxiv PDF URL uses correct domain."""
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            server="medrxiv",
        )
        assert "medrxiv.org" in article.pdf_url


class TestBiorxivClient:
    """Tests for BiorxivClient."""

    def test_normalize_doi_plain(self) -> None:
        """Plain DOI unchanged."""
        result = BiorxivClient.normalize_doi("10.1101/2024.01.15.123456")
        assert result == "10.1101/2024.01.15.123456"

    def test_normalize_doi_url(self) -> None:
        """URL prefix removed."""
        result = BiorxivClient.normalize_doi(
            "https://doi.org/10.1101/2024.01.15.123456"
        )
        assert result == "10.1101/2024.01.15.123456"

    def test_normalize_doi_prefix(self) -> None:
        """doi: prefix removed."""
        result = BiorxivClient.normalize_doi("doi:10.1101/2024.01.15.123456")
        assert result == "10.1101/2024.01.15.123456"

    def test_default_server_is_biorxiv(self) -> None:
        """Default server is bioRxiv."""
        client = BiorxivClient()
        assert client.server == "biorxiv"

    def test_medrxiv_server(self) -> None:
        """Can create medRxiv client."""
        client = BiorxivClient(server="medrxiv")
        assert client.server == "medrxiv"

    def test_get_by_date_range_success(self, requests_mock: pytest.fixture) -> None:
        """get_by_date_range returns articles."""
        response = {
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test Article",
                    "authors": "Smith, J.; Doe, J.",
                    "abstract": "Test abstract",
                    "category": "systems biology",
                    "date": "2024-01-15",
                    "version": "1",
                    "license": "cc_by",
                    "jatsxml": "https://example.com/jats.xml",
                    "published": "NA",
                    "server": "biorxiv",
                }
            ],
            "messages": [{"status": "ok", "count": 1, "cursor": "1", "total": 1}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0",
            json=response,
        )

        client = BiorxivClient()
        articles, next_cursor = client.get_by_date_range("2024-01-01", "2024-01-31")

        assert len(articles) == 1
        assert articles[0].doi == "10.1101/2024.01.15.123456"
        assert articles[0].title == "Test Article"
        assert articles[0].authors == ["Smith, J.", "Doe, J."]
        assert articles[0].jatsxml_url == "https://example.com/jats.xml"

    def test_get_by_doi_success(self, requests_mock: pytest.fixture) -> None:
        """get_by_doi returns single article."""
        response = {
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test",
                    "authors": "Smith, J.",
                    "abstract": "",
                    "category": "",
                    "date": "2024-01-15",
                    "version": "1",
                }
            ],
            "messages": [{"status": "ok", "count": 1}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/10.1101/2024.01.15.123456/na",
            json=response,
        )

        client = BiorxivClient()
        article = client.get_by_doi("10.1101/2024.01.15.123456")

        assert article is not None
        assert article.doi == "10.1101/2024.01.15.123456"

    def test_get_by_doi_not_found(self, requests_mock: pytest.fixture) -> None:
        """get_by_doi returns None for not found."""
        response = {"collection": [], "messages": [{"status": "ok", "count": 0}]}
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/10.1101/nonexistent/na",
            json=response,
        )

        client = BiorxivClient()
        article = client.get_by_doi("10.1101/nonexistent")

        assert article is None

    def test_api_error_returns_empty(self, requests_mock: pytest.fixture) -> None:
        """API error returns empty list."""
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0",
            status_code=500,
        )

        client = BiorxivClient()
        articles, _ = client.get_by_date_range("2024-01-01", "2024-01-31")

        assert articles == []

    def test_parse_response_with_pagination(
        self, requests_mock: pytest.fixture
    ) -> None:
        """Pagination cursor is correctly extracted."""
        response = {
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test",
                    "authors": "",
                    "abstract": "",
                    "category": "",
                    "date": "2024-01-15",
                    "version": "1",
                }
            ],
            "messages": [{"status": "ok", "count": 100, "cursor": "100", "total": 250}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0",
            json=response,
        )

        client = BiorxivClient()
        articles, next_cursor = client.get_by_date_range("2024-01-01", "2024-01-31")

        assert len(articles) == 1
        assert next_cursor == 100

    def test_parse_response_no_more_pages(self, requests_mock: pytest.fixture) -> None:
        """No next cursor when all results returned."""
        response = {
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test",
                    "authors": "",
                    "abstract": "",
                    "category": "",
                    "date": "2024-01-15",
                    "version": "1",
                }
            ],
            "messages": [{"status": "ok", "count": 1, "cursor": "1", "total": 1}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0",
            json=response,
        )

        client = BiorxivClient()
        _, next_cursor = client.get_by_date_range("2024-01-01", "2024-01-31")

        assert next_cursor is None

    def test_category_filter_in_request(self, requests_mock: pytest.fixture) -> None:
        """Category filter is included in request URL."""
        response = {
            "collection": [],
            "messages": [{"status": "ok", "count": 0, "cursor": "0", "total": 0}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0"
            "?category=systems_biology",
            json=response,
        )

        client = BiorxivClient()
        client.get_by_date_range("2024-01-01", "2024-01-31", category="systems_biology")

        assert requests_mock.called

    def test_published_doi_parsed(self, requests_mock: pytest.fixture) -> None:
        """Published DOI is parsed when not NA."""
        response = {
            "collection": [
                {
                    "doi": "10.1101/2024.01.15.123456",
                    "title": "Test",
                    "authors": "",
                    "abstract": "",
                    "category": "",
                    "date": "2024-01-15",
                    "version": "1",
                    "published": "10.1234/journal.123",
                }
            ],
            "messages": [{"status": "ok", "count": 1}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/10.1101/test/na",
            json=response,
        )

        client = BiorxivClient()
        article = client.get_by_doi("10.1101/test")

        assert article is not None
        assert article.published_doi == "10.1234/journal.123"


class TestCategories:
    """Tests for category constants."""

    def test_biorxiv_has_systems_biology(self) -> None:
        """bioRxiv categories include systems biology."""
        assert "systems_biology" in BIORXIV_CATEGORIES

    def test_medrxiv_has_epidemiology(self) -> None:
        """medRxiv categories include epidemiology."""
        assert "epidemiology" in MEDRXIV_CATEGORIES

    def test_categories_are_lowercase_underscore(self) -> None:
        """All categories use lowercase with underscores."""
        all_categories = BIORXIV_CATEGORIES + MEDRXIV_CATEGORIES
        for cat in all_categories:
            assert cat == cat.lower(), f"Category {cat} is not lowercase"
            assert " " not in cat, f"Category {cat} contains spaces"

    def test_biorxiv_category_count(self) -> None:
        """bioRxiv has expected number of categories."""
        # From the API docs
        assert len(BIORXIV_CATEGORIES) >= 25

    def test_medrxiv_category_count(self) -> None:
        """medRxiv has expected number of categories."""
        # From the API docs
        assert len(MEDRXIV_CATEGORIES) >= 40
