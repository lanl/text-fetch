"""Tests for bioRxiv/medRxiv client."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest
from text_fetch.biorxiv import (
    BIORXIV_CATEGORIES,
    MEDRXIV_CATEGORIES,
    BiorxivArticle,
    BiorxivClient,
    fetch_biorxiv,
    fetch_medrxiv,
)

if TYPE_CHECKING:
    pass


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


class TestBiorxivClientDownloads:
    """Tests for BiorxivClient download methods."""

    def test_download_jats_success(self, requests_mock: pytest.fixture) -> None:
        """Downloads JATS XML successfully."""
        jats_content = "<article><front>Test</front></article>"
        requests_mock.get(
            "https://www.biorxiv.org/content/test.xml",
            text=jats_content,
        )

        client = BiorxivClient()
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            jatsxml_url="https://www.biorxiv.org/content/test.xml",
        )

        result = client.download_jats(article)

        assert result is not None
        assert "<article>" in result

    def test_download_jats_no_url(self) -> None:
        """Returns None when no JATS URL."""
        client = BiorxivClient()
        article = BiorxivArticle(
            doi="10.1101/test",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            jatsxml_url=None,
        )

        result = client.download_jats(article)

        assert result is None

    def test_download_jats_failure(self, requests_mock: pytest.fixture) -> None:
        """Returns None on download failure."""
        requests_mock.get(
            "https://www.biorxiv.org/content/test.xml",
            status_code=404,
        )

        client = BiorxivClient()
        article = BiorxivArticle(
            doi="10.1101/test",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            jatsxml_url="https://www.biorxiv.org/content/test.xml",
        )

        result = client.download_jats(article)

        assert result is None

    def test_download_pdf_success(self, requests_mock: pytest.fixture) -> None:
        """Downloads PDF successfully."""
        pdf_content = b"%PDF-1.4 test content"
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            version=1,
            server="biorxiv",
        )

        requests_mock.get(article.pdf_url, content=pdf_content)

        client = BiorxivClient()
        result = client.download_pdf(article)

        assert result is not None
        assert result.startswith(b"%PDF")

    def test_download_pdf_failure(self, requests_mock: pytest.fixture) -> None:
        """Returns None on PDF download failure."""
        article = BiorxivArticle(
            doi="10.1101/test",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            version=1,
            server="biorxiv",
        )

        requests_mock.get(article.pdf_url, status_code=404)

        client = BiorxivClient()
        result = client.download_pdf(article)

        assert result is None


class TestBiorxivClientIteration:
    """Tests for BiorxivClient iteration methods."""

    def test_iter_by_date_range_single_page(
        self, requests_mock: pytest.fixture
    ) -> None:
        """Iterates through single page of results."""
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
        articles = list(client.iter_by_date_range("2024-01-01", "2024-01-31"))

        assert len(articles) == 1

    def test_iter_by_date_range_max_results(
        self, requests_mock: pytest.fixture
    ) -> None:
        """Stops after max_results."""
        response = {
            "collection": [
                {
                    "doi": f"10.1101/2024.01.15.{i:06d}",
                    "title": f"Test {i}",
                    "authors": "",
                    "abstract": "",
                    "category": "",
                    "date": "2024-01-15",
                    "version": "1",
                }
                for i in range(10)
            ],
            "messages": [{"status": "ok", "count": 10, "cursor": "10", "total": 100}],
        }
        requests_mock.get(
            "https://api.biorxiv.org/details/biorxiv/2024-01-01/2024-01-31/0",
            json=response,
        )

        client = BiorxivClient()
        articles = list(
            client.iter_by_date_range("2024-01-01", "2024-01-31", max_results=5)
        )

        assert len(articles) == 5

    def test_search_with_days(self, requests_mock: pytest.fixture) -> None:
        """Search using days parameter."""
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
            "https://api.biorxiv.org/details/biorxiv/d30/0",
            json=response,
        )

        client = BiorxivClient()
        articles = client.search(days=30, max_results=10)

        assert len(articles) == 1

    @patch.object(BiorxivClient, "iter_by_date_range")
    def test_search_default_date_range(self, mock_iter: MagicMock) -> None:
        """Search defaults to last 30 days when no dates provided."""
        mock_iter.return_value = iter([])

        client = BiorxivClient()
        articles = client.search()

        assert articles == []
        mock_iter.assert_called_once()

    def test_get_by_dois_multiple(self, requests_mock: pytest.fixture) -> None:
        """Fetches multiple articles by DOI."""
        for i in range(3):
            response = {
                "collection": [
                    {
                        "doi": f"10.1101/2024.01.{i:02d}.123456",
                        "title": f"Test {i}",
                        "authors": "",
                        "abstract": "",
                        "category": "",
                        "date": "2024-01-15",
                        "version": "1",
                    }
                ],
                "messages": [{"status": "ok", "count": 1}],
            }
            requests_mock.get(
                f"https://api.biorxiv.org/details/biorxiv/"
                f"10.1101/2024.01.{i:02d}.123456/na",
                json=response,
            )

        client = BiorxivClient()
        dois = [f"10.1101/2024.01.{i:02d}.123456" for i in range(3)]
        articles = client.get_by_dois(dois)

        assert len(articles) == 3


class TestFetchBiorxiv:
    """Tests for fetch_biorxiv orchestrator."""

    @patch("text_fetch.biorxiv.BiorxivClient")
    @patch("text_fetch.pmc.save_pmc_article")
    def test_fetch_with_jats_direct(
        self,
        mock_save: MagicMock,
        mock_client_class: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Fetches articles with direct JATS download."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        # Mock article with JATS URL
        article = BiorxivArticle(
            doi="10.1101/2024.01.15.123456",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
            jatsxml_url="https://example.com/jats.xml",
        )
        mock_client.search.return_value = [article]
        mock_client.download_jats.return_value = "<article>Test</article>"

        # Mock save result
        from text_fetch.pmc import ValidationResult, ValidationStatus

        mock_result = ValidationResult(
            status=ValidationStatus.VALID,
            has_title=True,
            has_abstract=True,
            has_body=True,
            body_chars=1000,
        )
        mock_save.return_value = (tmp_path / "test.xml", mock_result, {})

        stats = fetch_biorxiv(
            start_date="2024-01-01",
            end_date="2024-01-31",
            output_dir=tmp_path,
        )

        assert stats["articles_found"] == 1
        assert stats["jats_direct"] == 1
        mock_save.assert_called_once()

    @patch("text_fetch.biorxiv.BiorxivClient")
    def test_fetch_no_articles(
        self,
        mock_client_class: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Handles no articles found."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = []

        stats = fetch_biorxiv(
            start_date="2024-01-01",
            end_date="2024-01-31",
            output_dir=tmp_path,
        )

        assert stats["articles_found"] == 0
        assert stats["valid"] == 0

    @patch("text_fetch.biorxiv.BiorxivClient")
    def test_fetch_with_dois(
        self,
        mock_client_class: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Fetches specific DOIs."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.get_by_dois.return_value = []

        stats = fetch_biorxiv(
            dois=["10.1101/2024.01.15.123456"],
            output_dir=tmp_path,
        )

        mock_client.get_by_dois.assert_called_once()
        assert stats["articles_found"] == 0

    @patch("text_fetch.biorxiv.BiorxivClient")
    def test_fetch_with_progress_callback(
        self,
        mock_client_class: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Progress callback is called."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        article = BiorxivArticle(
            doi="10.1101/test",
            title="Test",
            authors=[],
            abstract="",
            category="",
            date=datetime.now(),
        )
        mock_client.search.return_value = [article]
        mock_client.download_jats.return_value = None

        calls = []

        def callback(doi: str, current: int, total: int) -> None:
            calls.append((doi, current, total))

        fetch_biorxiv(
            start_date="2024-01-01",
            end_date="2024-01-31",
            output_dir=tmp_path,
            progress_callback=callback,
        )

        assert len(calls) == 1
        assert calls[0][0] == "10.1101/test"


class TestFetchMedrxiv:
    """Tests for fetch_medrxiv orchestrator."""

    @patch("text_fetch.biorxiv.BiorxivClient")
    def test_uses_medrxiv_server(
        self,
        mock_client_class: MagicMock,
        tmp_path: Path,
    ) -> None:
        """Uses medRxiv server."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search.return_value = []

        fetch_medrxiv(
            start_date="2024-01-01",
            end_date="2024-01-31",
            output_dir=tmp_path,
        )

        mock_client_class.assert_called_once_with(server="medrxiv")


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
