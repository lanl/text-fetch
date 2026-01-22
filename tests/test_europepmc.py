"""Tests for Europe PMC client."""

from datetime import datetime

from text_fetch.europepmc import (
    EuropePMCArticle,
    EuropePMCClient,
)


class TestEuropePMCArticle:
    """Tests for EuropePMCArticle dataclass."""

    def test_id_for_filename_pmcid(self) -> None:
        """Uses PMCID when available."""
        article = EuropePMCArticle(
            id="12345",
            source="MED",
            pmid="12345",
            pmcid="PMC67890",
            doi=None,
            title="Test",
            authors=[],
            abstract="",
            journal="",
            pub_year=None,
            first_publication_date=None,
            is_open_access=True,
            has_full_text=True,
        )
        assert article.id_for_filename == "PMC67890"

    def test_id_for_filename_pmid(self) -> None:
        """Falls back to PMID when no PMCID."""
        article = EuropePMCArticle(
            id="12345",
            source="MED",
            pmid="12345",
            pmcid=None,
            doi=None,
            title="Test",
            authors=[],
            abstract="",
            journal="",
            pub_year=None,
            first_publication_date=None,
            is_open_access=True,
            has_full_text=False,
        )
        assert article.id_for_filename == "PMID12345"

    def test_id_for_filename_fallback(self) -> None:
        """Falls back to EPMC ID when no PMCID or PMID."""
        article = EuropePMCArticle(
            id="12345",
            source="PPR",
            pmid=None,
            pmcid=None,
            doi="10.1234/test",
            title="Test",
            authors=[],
            abstract="",
            journal="",
            pub_year=None,
            first_publication_date=None,
            is_open_access=True,
            has_full_text=True,
        )
        assert article.id_for_filename == "EPMC12345"


class TestEuropePMCClient:
    """Tests for EuropePMCClient."""

    def test_normalize_pmcid_with_prefix(self) -> None:
        """PMCID with prefix unchanged."""
        assert EuropePMCClient.normalize_pmcid("PMC123456") == "PMC123456"

    def test_normalize_pmcid_without_prefix(self) -> None:
        """PMCID without prefix gets prefix added."""
        assert EuropePMCClient.normalize_pmcid("123456") == "PMC123456"

    def test_normalize_pmcid_lowercase(self) -> None:
        """Lowercase PMCID normalized to uppercase."""
        assert EuropePMCClient.normalize_pmcid("pmc123456") == "PMC123456"

    def test_normalize_pmcid_with_spaces(self) -> None:
        """PMCID with spaces gets trimmed."""
        assert EuropePMCClient.normalize_pmcid("  PMC123456  ") == "PMC123456"

    def test_build_query_author(self) -> None:
        """Query with author."""
        query = EuropePMCClient.build_query(author="hlavacek ws")
        assert 'AUTH:"hlavacek ws"' in query

    def test_build_query_keywords(self) -> None:
        """Query with keywords."""
        keywords = ["systems biology", "modeling"]
        query = EuropePMCClient.build_query(keywords=keywords)
        assert '"systems biology"' in query
        assert '"modeling"' in query
        assert "OR" in query

    def test_build_query_title_keywords(self) -> None:
        """Query with title keywords."""
        title_kw = ["network", "model"]
        query = EuropePMCClient.build_query(title_keywords=title_kw)
        assert 'TITLE:"network"' in query
        assert 'TITLE:"model"' in query

    def test_build_query_date_range(self) -> None:
        """Query with date range."""
        query = EuropePMCClient.build_query(
            date_from="2024-01-01",
            date_to="2024-12-31",
        )
        assert "FIRST_PDATE:[2024-01-01 TO 2024-12-31]" in query

    def test_build_query_date_from_only(self) -> None:
        """Query with only start date."""
        query = EuropePMCClient.build_query(date_from="2024-01-01")
        assert "FIRST_PDATE:[2024-01-01 TO *]" in query

    def test_build_query_date_to_only(self) -> None:
        """Query with only end date."""
        query = EuropePMCClient.build_query(date_to="2024-12-31")
        assert "FIRST_PDATE:[* TO 2024-12-31]" in query

    def test_build_query_open_access(self) -> None:
        """Query includes open access filter by default."""
        query = EuropePMCClient.build_query(author="test")
        assert "OPEN_ACCESS:Y" in query

    def test_build_query_no_open_access(self) -> None:
        """Query without open access filter."""
        query = EuropePMCClient.build_query(author="test", open_access_only=False)
        assert "OPEN_ACCESS:Y" not in query

    def test_build_query_full_text(self) -> None:
        """Query includes full-text filter by default."""
        query = EuropePMCClient.build_query(author="test")
        assert "HAS_FT:Y" in query

    def test_build_query_no_full_text(self) -> None:
        """Query without full-text filter."""
        query = EuropePMCClient.build_query(author="test", has_full_text=False)
        assert "HAS_FT:Y" not in query

    def test_build_query_empty(self) -> None:
        """Empty query returns wildcard."""
        query = EuropePMCClient.build_query(
            open_access_only=False,
            has_full_text=False,
        )
        assert query == "*"

    def test_build_query_combined(self) -> None:
        """Query with multiple parameters."""
        query = EuropePMCClient.build_query(
            author="smith j",
            keywords=["cancer"],
            date_from="2023-01-01",
        )
        assert 'AUTH:"smith j"' in query
        assert '"cancer"' in query
        assert "FIRST_PDATE:[2023-01-01 TO *]" in query
        assert "OPEN_ACCESS:Y" in query
        assert "HAS_FT:Y" in query
        # Check AND joins
        assert " AND " in query

    def test_search_success(self, requests_mock) -> None:
        """search returns articles."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "AoE/abc123",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        "pmcid": "PMC9876543",
                        "doi": "10.1234/test",
                        "title": "Test Article",
                        "authorString": "Smith J, Doe A.",
                        "journalTitle": "Test Journal",
                        "pubYear": "2024",
                        "abstractText": "Test abstract",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                        "firstPublicationDate": "2024-01-15",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        articles, next_cursor, total = client.search("test")

        assert total == 1
        assert len(articles) == 1
        assert articles[0].pmcid == "PMC9876543"
        assert articles[0].is_open_access is True
        assert articles[0].has_full_text is True
        assert next_cursor == "AoE/abc123"

    def test_search_with_author_list(self, requests_mock) -> None:
        """search parses authorList correctly."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "cursor2",
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
                        "title": "Test",
                        "authorList": {
                            "author": [
                                {"firstName": "John", "lastName": "Smith"},
                                {"firstName": "Alice", "lastName": "Doe"},
                            ]
                        },
                        "isOpenAccess": "N",
                        "hasFullText": "N",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        articles, _, _ = client.search("test")

        assert len(articles) == 1
        assert articles[0].authors == ["John Smith", "Alice Doe"]

    def test_search_parses_date(self, requests_mock) -> None:
        """search parses firstPublicationDate."""
        response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
                        "title": "Test",
                        "firstPublicationDate": "2024-06-15",
                        "pubYear": "2024",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        articles, _, _ = client.search("test")

        assert articles[0].first_publication_date == datetime(2024, 6, 15)
        assert articles[0].pub_year == 2024

    def test_search_cursor_unchanged_means_end(self, requests_mock) -> None:
        """When cursor unchanged, no more results."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "*",  # Same as start cursor
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
                        "title": "Test",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        articles, next_cursor, total = client.search("test", cursor="*")

        assert next_cursor is None  # Should be None since cursor unchanged

    def test_api_error_returns_empty(self, requests_mock) -> None:
        """API error returns empty list."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            status_code=500,
        )

        client = EuropePMCClient()
        articles, next_cursor, total = client.search("test")

        assert articles == []
        assert total == 0
        assert next_cursor is None

    def test_get_full_text_xml_success(self, requests_mock) -> None:
        """get_full_text_xml returns XML content."""
        xml_content = '<?xml version="1.0"?><article>Test</article>'
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        requests_mock.get(f"{url}/PMC/PMC123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("PMC123456")

        assert result == xml_content

    def test_get_full_text_xml_normalizes_pmcid(self, requests_mock) -> None:
        """get_full_text_xml normalizes PMCID."""
        xml_content = "<article>Test</article>"
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        requests_mock.get(f"{url}/PMC/PMC123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("123456")  # Without PMC prefix

        assert result == xml_content

    def test_get_full_text_xml_error(self, requests_mock) -> None:
        """get_full_text_xml returns None on error."""
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        requests_mock.get(f"{url}/PMC/PMC123456/fullTextXML", status_code=404)

        client = EuropePMCClient()
        result = client.get_full_text_xml("PMC123456")

        assert result is None

    def test_get_by_pmcid(self, requests_mock) -> None:
        """get_by_pmcid returns article."""
        response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "PMC",
                        "pmcid": "PMC123456",
                        "title": "Test Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        article = client.get_by_pmcid("PMC123456")

        assert article is not None
        assert article.pmcid == "PMC123456"

    def test_get_by_pmcid_not_found(self, requests_mock) -> None:
        """get_by_pmcid returns None when not found."""
        response = {
            "hitCount": 0,
            "resultList": {"result": []},
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        article = client.get_by_pmcid("PMC999999")

        assert article is None

    def test_get_by_doi(self, requests_mock) -> None:
        """get_by_doi returns article."""
        response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
                        "doi": "10.1234/test.2024",
                        "title": "Test Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        article = client.get_by_doi("10.1234/test.2024")

        assert article is not None
        assert article.doi == "10.1234/test.2024"

    def test_iter_search(self, requests_mock) -> None:
        """iter_search iterates through pages."""
        # First page
        response1 = {
            "hitCount": 3,
            "nextCursorMark": "cursor2",
            "resultList": {
                "result": [
                    {
                        "id": "1",
                        "source": "MED",
                        "title": "Article 1",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                    {
                        "id": "2",
                        "source": "MED",
                        "title": "Article 2",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        # Second page (last)
        response2 = {
            "hitCount": 3,
            "nextCursorMark": "cursor2",  # Same cursor = end
            "resultList": {
                "result": [
                    {
                        "id": "3",
                        "source": "MED",
                        "title": "Article 3",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            [{"json": response1}, {"json": response2}],
        )

        client = EuropePMCClient()
        articles = list(client.iter_search("test"))

        assert len(articles) == 3
        assert articles[0].id == "1"
        assert articles[2].id == "3"

    def test_iter_search_max_results(self, requests_mock) -> None:
        """iter_search respects max_results."""
        response = {
            "hitCount": 100,
            "nextCursorMark": "cursor2",
            "resultList": {
                "result": [
                    {
                        "id": str(i),
                        "source": "MED",
                        "title": f"Article {i}",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                    for i in range(10)
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        articles = list(client.iter_search("test", max_results=5))

        assert len(articles) == 5
