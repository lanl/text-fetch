"""Tests for Europe PMC client."""

from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from text_fetch.europepmc import (
    EuropePMCArticle,
    EuropePMCClient,
    ExpansionResult,
    IncompleteListError,
    expand_papers,
    fetch_europepmc,
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

    def test_normalize_pmcid_mixed_case(self) -> None:
        """Mixed-case prefix is normalized (#30). Control: main also did this."""
        assert EuropePMCClient.normalize_pmcid("Pmc123456") == "PMC123456"

    def test_normalize_pmcid_rejects_non_pmcid(self) -> None:
        """A doubled prefix or non-numeric ID is rejected, not passed on (#30)."""
        with pytest.raises(ValueError, match="Invalid PMC ID"):
            EuropePMCClient.normalize_pmcid("PMCPMC1")

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
        # Endpoint is /{PMCID}/fullTextXML, with the PMC prefix
        requests_mock.get(f"{url}/PMC123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("PMC123456")

        assert result == xml_content

    def test_get_full_text_xml_normalizes_pmcid(self, requests_mock) -> None:
        """get_full_text_xml normalizes PMCID."""
        xml_content = "<article>Test</article>"
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        # Endpoint is /{PMCID}/fullTextXML, with the PMC prefix
        requests_mock.get(f"{url}/PMC123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("123456")  # Without PMC prefix

        assert result == xml_content

    def test_get_full_text_xml_error(self, requests_mock) -> None:
        """get_full_text_xml returns None on error."""
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        # Endpoint is /{PMCID}/fullTextXML, with the PMC prefix
        requests_mock.get(f"{url}/PMC123456/fullTextXML", status_code=404)

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

    def test_get_citations_success(self, requests_mock) -> None:
        """get_citations returns citing papers."""
        response = {
            "hitCount": 2,
            "citationList": {
                "citation": [
                    {
                        "id": "11111111",
                        "source": "MED",
                        "title": "Citing Paper 1",
                        "pubYear": "2024",
                    },
                    {
                        "id": "22222222",
                        "source": "MED",
                        "title": "Citing Paper 2",
                        "pubYear": "2024",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/32487503/citations?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("MED", "32487503")

        assert total == 2
        assert len(citations) == 2
        assert citations[0]["title"] == "Citing Paper 1"

    def test_get_citations_normalizes_pmcid(self, requests_mock) -> None:
        """get_citations keeps the PMC prefix (without it the API finds nothing)."""
        response = {
            "hitCount": 1,
            "citationList": {
                "citation": [
                    {"id": "11111111", "source": "MED", "title": "Test"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC7343657/citations?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("PMC", "PMC7343657")

        assert total == 1
        assert len(citations) == 1

    def test_get_citations_empty(self, requests_mock) -> None:
        """get_citations returns empty list when no citations."""
        response = {
            "hitCount": 0,
            "citationList": {},
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/99999999/citations?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("MED", "99999999")

        assert total == 0
        assert citations == []

    def test_get_citations_single_result(self, requests_mock) -> None:
        """get_citations handles single citation returned as dict."""
        response = {
            "hitCount": 1,
            "citationList": {
                "citation": {"id": "11111111", "source": "MED", "title": "Single"},
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("MED", "12345678")

        assert total == 1
        assert len(citations) == 1
        assert citations[0]["title"] == "Single"

    def test_get_citations_api_error(self, requests_mock) -> None:
        """get_citations returns empty on API error."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=1&pageSize=1000&format=json",
            status_code=500,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("MED", "12345678")

        assert total == 0
        assert citations == []

    def test_get_references_success(self, requests_mock) -> None:
        """get_references returns referenced papers."""
        response = {
            "hitCount": 2,
            "referenceList": {
                "reference": [
                    {
                        "id": "33333333",
                        "source": "MED",
                        "title": "Referenced Paper 1",
                        "pubYear": "2020",
                    },
                    {
                        "id": "44444444",
                        "source": "MED",
                        "title": "Referenced Paper 2",
                        "pubYear": "2019",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/32487503/references?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        references, total = client.get_references("MED", "32487503")

        assert total == 2
        assert len(references) == 2
        assert references[0]["title"] == "Referenced Paper 1"

    def test_get_references_normalizes_pmcid(self, requests_mock) -> None:
        """get_references keeps the PMC prefix (without it the API finds nothing)."""
        response = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {"id": "11111111", "source": "MED", "title": "Test"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC7343657/references?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        references, total = client.get_references("PMC", "PMC7343657")

        assert total == 1
        assert len(references) == 1

    def test_get_references_empty(self, requests_mock) -> None:
        """get_references returns empty list when no references."""
        response = {
            "hitCount": 0,
            "referenceList": {},
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/99999999/references?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        references, total = client.get_references("MED", "99999999")

        assert total == 0
        assert references == []

    def test_get_references_single_result(self, requests_mock) -> None:
        """get_references handles single reference returned as dict."""
        response = {
            "hitCount": 1,
            "referenceList": {
                "reference": {"id": "11111111", "source": "MED", "title": "Single"},
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        references, total = client.get_references("MED", "12345678")

        assert total == 1
        assert len(references) == 1
        assert references[0]["title"] == "Single"

    def test_get_references_api_error(self, requests_mock) -> None:
        """get_references returns empty on API error."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=1&pageSize=1000&format=json",
            status_code=500,
        )

        client = EuropePMCClient()
        references, total = client.get_references("MED", "12345678")

        assert total == 0
        assert references == []

    def test_get_all_citations_pagination(self, requests_mock) -> None:
        """get_all_citations handles pagination."""
        # First page
        response1 = {
            "hitCount": 3,
            "citationList": {
                "citation": [
                    {"id": "1", "source": "MED", "title": "Citation 1"},
                    {"id": "2", "source": "MED", "title": "Citation 2"},
                ]
            },
        }
        # Second page
        response2 = {
            "hitCount": 3,
            "citationList": {
                "citation": [
                    {"id": "3", "source": "MED", "title": "Citation 3"},
                ]
            },
        }
        # Third page (empty - end of results)
        response3 = {
            "hitCount": 3,
            "citationList": {},
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=1&pageSize=1000&format=json",
            json=response1,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=2&pageSize=1000&format=json",
            json=response2,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=3&pageSize=1000&format=json",
            json=response3,
        )

        client = EuropePMCClient()
        citations = client.get_all_citations("MED", "12345678")

        assert len(citations) == 3

    def test_get_all_citations_max_results(self, requests_mock) -> None:
        """get_all_citations respects max_results."""
        response = {
            "hitCount": 100,
            "citationList": {
                "citation": [
                    {"id": str(i), "source": "MED", "title": f"Citation {i}"}
                    for i in range(10)
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        citations = client.get_all_citations("MED", "12345678", max_results=5)

        assert len(citations) == 5

    def test_get_all_references_pagination(self, requests_mock) -> None:
        """get_all_references handles pagination."""
        # First page
        response1 = {
            "hitCount": 3,
            "referenceList": {
                "reference": [
                    {"id": "1", "source": "MED", "title": "Reference 1"},
                    {"id": "2", "source": "MED", "title": "Reference 2"},
                ]
            },
        }
        # Second page
        response2 = {
            "hitCount": 3,
            "referenceList": {
                "reference": [
                    {"id": "3", "source": "MED", "title": "Reference 3"},
                ]
            },
        }
        # Third page (empty - end of results)
        response3 = {
            "hitCount": 3,
            "referenceList": {},
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=1&pageSize=1000&format=json",
            json=response1,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=2&pageSize=1000&format=json",
            json=response2,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=3&pageSize=1000&format=json",
            json=response3,
        )

        client = EuropePMCClient()
        references = client.get_all_references("MED", "12345678")

        assert len(references) == 3

    def test_get_all_references_max_results(self, requests_mock) -> None:
        """get_all_references respects max_results."""
        response = {
            "hitCount": 100,
            "referenceList": {
                "reference": [
                    {"id": str(i), "source": "MED", "title": f"Reference {i}"}
                    for i in range(10)
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references?page=1&pageSize=1000&format=json",
            json=response,
        )

        client = EuropePMCClient()
        references = client.get_all_references("MED", "12345678", max_results=5)

        assert len(references) == 5


class TestLinkedPapersEndpoint:
    """Citations/references use /{source}/{id}/{kind}?page=&pageSize=&format=json."""

    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    @pytest.mark.parametrize("kind", ["citations", "references"])
    def test_query_string_form(self, requests_mock, epmc_links_payload, kind) -> None:
        """One request in the query-string form; the path form returns 404 (#2)."""
        requests_mock.get(
            f"{self.BASE}/MED/32487503/{kind}",
            json=epmc_links_payload(kind, [("MED", "111"), ("PPR", "PPR222")]),
        )

        client = EuropePMCClient()
        get = client.get_citations if kind == "citations" else client.get_references
        items, total = get("MED", "32487503")

        assert [i["id"] for i in items] == ["111", "PPR222"]
        assert total == 2
        assert requests_mock.call_count == 1
        request = requests_mock.request_history[0]
        assert request.path.endswith(f"/med/32487503/{kind}")
        assert parse_qs(urlsplit(request.url).query) == {
            "page": ["1"],
            "pageSize": ["1000"],
            "format": ["json"],
        }

    @pytest.mark.parametrize("pmcid", ["PMC3531190", "pmc3531190", "3531190"])
    def test_pmc_source_keeps_prefix(self, requests_mock, epmc_links_payload, pmcid):
        """PMC lookups use /PMC/PMC123/...; /PMC/123/... returns no hits."""
        requests_mock.get(
            f"{self.BASE}/PMC/PMC3531190/citations",
            json=epmc_links_payload("citations", [("MED", "111")]),
        )

        items, total = EuropePMCClient().get_citations("PMC", pmcid)

        assert total == 1
        assert len(items) == 1
        # requests_mock matches paths case-insensitively; check the real URL
        url = requests_mock.request_history[0].url
        assert urlsplit(url).path.endswith("/PMC/PMC3531190/citations")

    @pytest.mark.parametrize(
        ("hit_count", "expected_pages"),
        [(0, 1), (1, 1), (999, 1), (1000, 1), (1001, 2), (2000, 2), (2067, 3)],
    )
    def test_get_all_pages_by_hit_count(
        self, requests_mock, epmc_links_payload, hit_count, expected_pages
    ) -> None:
        """Every page up to hitCount is fetched, and no more (#2)."""

        def page(request, context):
            n = int(parse_qs(urlsplit(request.url).query)["page"][0])
            start = (n - 1) * 1000
            ids = range(start, min(start + 1000, hit_count))
            return epmc_links_payload(
                "citations", [("MED", str(i)) for i in ids], hit_count=hit_count
            )

        requests_mock.get(f"{self.BASE}/MED/1/citations", json=page)

        items = EuropePMCClient().get_all_citations("MED", "1")

        assert [i["id"] for i in items] == [str(i) for i in range(hit_count)]
        assert requests_mock.call_count == expected_pages
        pages = [
            parse_qs(urlsplit(r.url).query)["page"][0]
            for r in requests_mock.request_history
        ]
        assert pages == [str(n) for n in range(1, expected_pages + 1)]

    def test_get_all_without_hit_count_stops_on_short_page(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """Without hitCount, paging continues while pages are full."""

        def page(request, context):
            n = int(parse_qs(urlsplit(request.url).query)["page"][0])
            count = 1000 if n == 1 else 5
            payload = epmc_links_payload(
                "references", [("MED", f"{n}-{i}") for i in range(count)]
            )
            del payload["hitCount"]
            return payload

        requests_mock.get(f"{self.BASE}/MED/1/references", json=page)

        items = EuropePMCClient().get_all_references("MED", "1")

        assert len(items) == 1005
        assert requests_mock.call_count == 2

    @pytest.mark.parametrize("hit_count", ["2", "abc", None, float("inf")])
    def test_hit_count_types(self, requests_mock, epmc_links_payload, hit_count):
        """A string hitCount is parsed; junk or null means "unknown", no crash."""
        payload = epmc_links_payload("citations", [("MED", "1"), ("MED", "2")])
        payload["hitCount"] = hit_count
        requests_mock.get(f"{self.BASE}/MED/1/citations", json=payload)

        items, total = EuropePMCClient().get_citations("MED", "1")

        assert len(items) == 2
        assert total == (2 if hit_count == "2" else None)

    def test_page_size_capped_at_api_maximum(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """A page size above the API's maximum of 1000 is sent as 1000."""
        requests_mock.get(
            f"{self.BASE}/MED/1/references",
            json=epmc_links_payload("references", []),
        )

        EuropePMCClient().get_references("MED", "1", page_size=5000)

        query = parse_qs(urlsplit(requests_mock.request_history[0].url).query)
        assert query["pageSize"] == ["1000"]

    def test_full_text_xml_uses_prefixed_pmcid(self, requests_mock) -> None:
        """Full text is requested at /PMC123/fullTextXML (#2)."""
        requests_mock.get(f"{self.BASE}/PMC3531190/fullTextXML", text="<article/>")

        assert EuropePMCClient().get_full_text_xml("pmc3531190") == "<article/>"
        assert requests_mock.call_count == 1
        url = requests_mock.request_history[0].url
        assert urlsplit(url).path.endswith("/rest/PMC3531190/fullTextXML")

    def test_failed_page_raises_with_partial_items(
        self, requests_mock, epmc_links_payload, monkeypatch
    ) -> None:
        """A failed page 2 of 3 raises; it isn't returned as the whole list."""
        monkeypatch.setattr("time.sleep", lambda _s: None)

        def page(request, context):
            n = int(parse_qs(urlsplit(request.url).query)["page"][0])
            if n == 2:
                context.status_code = 404
                return {}
            return epmc_links_payload(
                "citations", [("MED", str(i)) for i in range(1000)], hit_count=2067
            )

        requests_mock.get(f"{self.BASE}/MED/1/citations", json=page)

        with pytest.raises(IncompleteListError, match="page 2") as info:
            EuropePMCClient().get_all_citations("MED", "1")

        assert len(info.value.items) == 1000
        assert requests_mock.call_count == 2

    def test_short_list_against_hit_count_raises(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """An empty page before hitCount items arrived raises."""

        def page(request, context):
            n = int(parse_qs(urlsplit(request.url).query)["page"][0])
            records = [("MED", str(i)) for i in range(1000)] if n == 1 else []
            return epmc_links_payload("citations", records, hit_count=2067)

        requests_mock.get(f"{self.BASE}/MED/1/citations", json=page)

        with pytest.raises(IncompleteListError, match="1000 of 2067"):
            EuropePMCClient().get_all_citations("MED", "1")

    def test_no_hit_count_paging_is_bounded(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """Without hitCount, full pages forever stop at MAX_LINKED_PAGES."""
        payload = epmc_links_payload("references", [("MED", "1")] * 1000)
        del payload["hitCount"]

        def page(request, context):
            # Fail fast instead of hanging if the cap is ever removed
            if requests_mock.call_count > 10:
                raise AssertionError("paging did not stop at MAX_LINKED_PAGES")
            return payload

        requests_mock.get(f"{self.BASE}/MED/1/references", json=page)

        client = EuropePMCClient()
        client.MAX_LINKED_PAGES = 3
        with pytest.raises(IncompleteListError, match="after 3 pages"):
            client.get_all_references("MED", "1")

        assert requests_mock.call_count == 3


class TestBatchLookup:
    """Tests for batch_lookup_pmids method."""

    def test_batch_lookup_empty_list(self) -> None:
        """batch_lookup_pmids returns empty dict for empty input."""
        client = EuropePMCClient()
        result = client.batch_lookup_pmids([])
        assert result == {}

    def test_batch_lookup_returns_dict(self, requests_mock) -> None:
        """batch_lookup_pmids returns dict mapping PMID → article."""
        response = {
            "hitCount": 2,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        "pmcid": "PMC9876543",
                        "title": "Article 1",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                    {
                        "id": "23456789",
                        "source": "MED",
                        "pmid": "23456789",
                        "pmcid": "PMC8765432",
                        "title": "Article 2",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        result = client.batch_lookup_pmids(["12345678", "23456789"])

        assert len(result) == 2
        assert "12345678" in result
        assert "23456789" in result
        assert result["12345678"].pmcid == "PMC9876543"
        assert result["23456789"].pmcid == "PMC8765432"

    def test_batch_lookup_handles_missing_pmids(self, requests_mock) -> None:
        """PMIDs not found in Europe PMC are not in result dict."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        "pmcid": "PMC9876543",
                        "title": "Found Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        # Request 3 PMIDs, but only 1 is found
        result = client.batch_lookup_pmids(["12345678", "99999999", "88888888"])

        assert len(result) == 1
        assert "12345678" in result
        assert "99999999" not in result
        assert "88888888" not in result

    def test_batch_lookup_handles_duplicates(self, requests_mock) -> None:
        """Duplicate PMIDs in input are handled correctly."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        "pmcid": "PMC9876543",
                        "title": "Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        # Same PMID repeated multiple times
        result = client.batch_lookup_pmids(["12345678", "12345678", "12345678"])

        # Should still only have one entry
        assert len(result) == 1
        assert "12345678" in result

    def test_batch_lookup_respects_batch_size(self, requests_mock) -> None:
        """Large lists are split into batches."""
        # Response for batch 1 (PMIDs 1-3)
        response1 = {
            "hitCount": 3,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": str(i),
                        "source": "MED",
                        "pmid": str(i),
                        "pmcid": f"PMC{i}00",
                        "title": f"Article {i}",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                    for i in range(1, 4)
                ]
            },
        }
        # Response for batch 2 (PMIDs 4-5)
        response2 = {
            "hitCount": 2,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": str(i),
                        "source": "MED",
                        "pmid": str(i),
                        "pmcid": f"PMC{i}00",
                        "title": f"Article {i}",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    }
                    for i in range(4, 6)
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            [{"json": response1}, {"json": response2}],
        )

        client = EuropePMCClient()
        # 5 PMIDs with batch_size=3 → 2 batches
        result = client.batch_lookup_pmids(["1", "2", "3", "4", "5"], batch_size=3)

        assert len(result) == 5
        for i in range(1, 6):
            assert str(i) in result
            assert result[str(i)].pmcid == f"PMC{i}00"

    def test_batch_lookup_query_format(self, requests_mock) -> None:
        """Verify the query format used for batch lookup."""
        response = {
            "hitCount": 0,
            "nextCursorMark": "*",
            "resultList": {"result": []},
        }
        adapter = requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        client.batch_lookup_pmids(["111", "222", "333"])

        # Check that the query was formatted correctly
        # Note: URL query params are lowercased in requests_mock
        assert adapter.call_count == 1
        query_param = adapter.last_request.qs.get("query", [""])[0].lower()
        assert "ext_id:" in query_param
        assert "111" in query_param
        assert "222" in query_param
        assert "333" in query_param
        assert " or " in query_param
        assert "src:med" in query_param

    def test_batch_lookup_articles_without_pmcid(self, requests_mock) -> None:
        """Articles without PMCID are still returned in result."""
        response = {
            "hitCount": 1,
            "nextCursorMark": "*",
            "resultList": {
                "result": [
                    {
                        "id": "12345678",
                        "source": "MED",
                        "pmid": "12345678",
                        # No pmcid field
                        "title": "Article without PMCID",
                        "isOpenAccess": "Y",
                        "hasFullText": "N",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=response,
        )

        client = EuropePMCClient()
        result = client.batch_lookup_pmids(["12345678"])

        # Article should be returned even without PMCID
        assert len(result) == 1
        assert "12345678" in result
        assert result["12345678"].pmcid is None


class TestExpandPapers:
    """Tests for expand_papers function."""

    def _make_article(
        self,
        pmcid: str | None = None,
        pmid: str | None = None,
        doi: str | None = None,
        source: str = "MED",
    ) -> EuropePMCArticle:
        """Helper to create test articles."""
        return EuropePMCArticle(
            id=pmid or "12345",
            source=source,
            pmid=pmid,
            pmcid=pmcid,
            doi=doi,
            title="Test Article",
            authors=[],
            abstract="",
            journal="",
            pub_year=2024,
            first_publication_date=None,
            is_open_access=True,
            has_full_text=True,
        )

    def test_expand_no_directions(self, requests_mock) -> None:
        """expand_papers with no directions returns empty result."""
        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=False,
            expand_citations=False,
        )

        assert result.total_expanded == 0
        assert result.seed_coverage["total_seeds"] == 1

    def test_expand_references_only(self, requests_mock) -> None:
        """expand_papers follows only references."""
        # Mock reference lookup for seed
        refs_response = {
            "hitCount": 2,
            "referenceList": {
                "reference": [
                    {"id": "111", "source": "MED", "pmid": "111", "title": "Ref 1"},
                    {"id": "222", "source": "MED", "pmid": "222", "title": "Ref 2"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )

        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456", source="PMC")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=True,
            expand_citations=False,
            depth=1,
        )

        assert result.total_expanded == 2
        assert result.expansion_stats["references_found"] == 2
        assert result.expansion_stats["citations_found"] == 0
        assert result.seed_coverage["seeds_with_references"] == 1

    def test_expand_citations_only(self, requests_mock) -> None:
        """expand_papers follows only citations."""
        # Mock citation lookup for seed
        cites_response = {
            "hitCount": 2,
            "citationList": {
                "citation": [
                    {"id": "333", "source": "MED", "pmid": "333", "title": "Cite 1"},
                    {"id": "444", "source": "MED", "pmid": "444", "title": "Cite 2"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/citations?page=1&pageSize=1&format=json",
            json=cites_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/citations?page=1&pageSize=1000&format=json",
            json=cites_response,
        )

        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456", source="PMC")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=False,
            expand_citations=True,
            depth=1,
        )

        assert result.total_expanded == 2
        assert result.expansion_stats["citations_found"] == 2
        assert result.expansion_stats["references_found"] == 0
        assert result.seed_coverage["seeds_with_citations"] == 1

    def test_expand_both_directions(self, requests_mock) -> None:
        """expand_papers follows both references and citations."""
        # Mock reference and citation lookups
        refs_response = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {"id": "111", "source": "MED", "pmid": "111", "title": "Ref 1"},
                ]
            },
        }
        cites_response = {
            "hitCount": 1,
            "citationList": {
                "citation": [
                    {"id": "222", "source": "MED", "pmid": "222", "title": "Cite 1"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/citations?page=1&pageSize=1&format=json",
            json=cites_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/citations?page=1&pageSize=1000&format=json",
            json=cites_response,
        )

        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456", source="PMC")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=True,
            expand_citations=True,
            depth=1,
        )

        assert result.total_expanded == 2
        assert result.expansion_stats["references_found"] == 1
        assert result.expansion_stats["citations_found"] == 1

    def test_expand_respects_max_expansion(self, requests_mock) -> None:
        """expand_papers respects max_expansion limit."""
        # Mock lots of references
        refs_response = {
            "hitCount": 100,
            "referenceList": {
                "reference": [
                    {"id": str(i), "source": "MED", "pmid": str(i), "title": f"Ref {i}"}
                    for i in range(100)
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )

        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456", source="PMC")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=True,
            depth=1,
            max_expansion=10,
        )

        assert result.total_expanded <= 10

    def test_expand_deduplicates(self, requests_mock) -> None:
        """expand_papers deduplicates papers found from multiple seeds."""
        # Same reference found from two seeds
        refs_response = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {
                        "id": "999",
                        "source": "MED",
                        "pmid": "999",
                        "doi": "10.1234/same",
                        "title": "Same Paper",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC111/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC111/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC222/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC222/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )

        client = EuropePMCClient()
        seeds = [
            self._make_article(pmcid="PMC111", source="PMC"),
            self._make_article(pmcid="PMC222", source="PMC"),
        ]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=True,
            depth=1,
        )

        # Should only have 1 unique paper despite being found twice
        assert result.total_expanded == 1
        assert result.expansion_stats["duplicates_skipped"] == 1

    def test_expansion_result_properties(self) -> None:
        """ExpansionResult properties work correctly."""
        result = ExpansionResult(
            expanded_papers={
                1: [{"title": "P1"}, {"title": "P2"}],
                2: [{"title": "P3"}],
            },
            config={"depth": 2},
            seed_coverage={"total_seeds": 5},
            expansion_stats={"total_unique": 3},
            id_issues={"no_id": []},
            layers=[],
        )

        assert result.total_expanded == 3
        assert len(result.all_papers) == 3

    def test_expand_tracks_layers(self, requests_mock) -> None:
        """expand_papers tracks papers by depth layer."""
        refs_response = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {"id": "111", "source": "MED", "pmid": "111", "title": "Ref 1"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1&format=json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/PMC123456/references?page=1&pageSize=1000&format=json",
            json=refs_response,
        )

        client = EuropePMCClient()
        seeds = [self._make_article(pmcid="PMC123456", source="PMC")]

        result = expand_papers(
            client=client,
            seeds=seeds,
            expand_references=True,
            depth=1,
        )

        # Should have seed layer and reference layer
        assert len(result.layers) >= 1
        seed_layer = next(lyr for lyr in result.layers if lyr["type"] == "seed")
        assert seed_layer["depth"] == 0
        assert seed_layer["count"] == 1


class TestExpansionDedup:
    """Seeds and already-found papers are recognized by any identifier (#24)."""

    BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    @staticmethod
    def _seed(pmid: str, doi: str | None = None) -> EuropePMCArticle:
        return EuropePMCArticle(
            id=pmid,
            source="MED",
            pmid=pmid,
            pmcid=f"PMC{pmid}",
            doi=doi or f"10.1000/{pmid}",
            title=f"Seed {pmid}",
            authors=[],
            abstract="",
            journal="",
            pub_year=2024,
            first_publication_date=None,
            is_open_access=True,
            has_full_text=True,
        )

    def _mock_refs(self, requests_mock, build, graph: dict[str, list]) -> None:
        """Serve references for each "SOURCE/ID" key in graph."""
        for key, records in graph.items():
            requests_mock.get(
                f"{self.BASE}/{key}/references",
                json=build("references", records),
            )

    def test_seeds_citing_each_other_are_not_expanded(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """Seeds A and B reference each other and C: only C is expanded."""
        self._mock_refs(
            requests_mock,
            epmc_links_payload,
            {
                "MED/111": [("MED", "222"), ("MED", "333")],
                "MED/222": [("MED", "111")],
            },
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111"), self._seed("222")],
            expand_references=True,
        )

        assert [p["id"] for p in result.all_papers] == ["333"]
        assert result.expansion_stats["total_unique"] == 1
        assert result.expansion_stats["duplicates_skipped"] == 2

    def test_seeds_do_not_use_up_max_expansion(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """With --max-expansion 1, the one new paper is kept, not a seed."""
        self._mock_refs(
            requests_mock,
            epmc_links_payload,
            {
                "MED/111": [("MED", "222"), ("MED", "333")],
                "MED/222": [("MED", "111")],
            },
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111"), self._seed("222")],
            expand_references=True,
            max_expansion=1,
        )

        assert [p["id"] for p in result.all_papers] == ["333"]

    def test_seed_matched_by_pmcid_record(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """A PMC-source record of a MED seed (same PMCID) is a duplicate."""
        self._mock_refs(
            requests_mock,
            epmc_links_payload,
            {
                "MED/111": [("PMC", "PMC222"), ("MED", "333")],
                "MED/222": [],
            },
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111"), self._seed("222")],
            expand_references=True,
        )

        assert [p["id"] for p in result.all_papers] == ["333"]
        assert result.expansion_stats["duplicates_skipped"] == 1

    def test_preprint_found_twice_is_expanded_once(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """A PPR record cited by two seeds is one expanded paper."""
        self._mock_refs(
            requests_mock,
            epmc_links_payload,
            {
                "MED/111": [("PPR", "PPR9")],
                "MED/222": [("PPR", "PPR9"), ("PPR", "PPR10")],
            },
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111"), self._seed("222")],
            expand_references=True,
        )

        assert [p["id"] for p in result.all_papers] == ["PPR9", "PPR10"]
        assert result.expansion_stats["duplicates_skipped"] == 1

    def test_depth_two_skips_seeds_and_uses_source_ids(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """At depth 2, seeds aren't re-expanded and preprints use /PPR/{id}."""
        self._mock_refs(
            requests_mock,
            epmc_links_payload,
            {
                "MED/111": [("MED", "333"), ("PPR", "PPR9"), ("PMC", "PMC77")],
                "MED/333": [("MED", "111"), ("MED", "444")],
                "PPR/PPR9": [("MED", "555")],
                "PMC/PMC77": [("MED", "666")],
            },
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111")],
            expand_references=True,
            depth=2,
        )

        layers = result.expanded_papers
        by_depth = {d: [p["id"] for p in ps] for d, ps in layers.items()}
        assert by_depth == {1: ["333", "PPR9", "PMC77"], 2: ["444", "555", "666"]}
        assert result.expansion_stats["duplicates_skipped"] == 1
        paths = [r.path for r in requests_mock.request_history]
        # Seed: coverage check + full list; each depth-1 paper: full list
        assert paths == [
            "/europepmc/webservices/rest/med/111/references",
            "/europepmc/webservices/rest/med/111/references",
            "/europepmc/webservices/rest/med/333/references",
            "/europepmc/webservices/rest/ppr/ppr9/references",
            "/europepmc/webservices/rest/pmc/pmc77/references",
        ]

    def test_failed_list_is_reported_and_partial_items_used(
        self, requests_mock, epmc_links_payload, monkeypatch
    ) -> None:
        """A list that fails part way is used as far as it got, and reported."""
        monkeypatch.setattr("time.sleep", lambda _s: None)

        def refs(request, context):
            query = parse_qs(urlsplit(request.url).query)
            if query["pageSize"] == ["1"]:
                return epmc_links_payload("references", [("MED", "1")], 1001)
            if query["page"] == ["2"]:
                context.status_code = 404
                return {}
            records = [("MED", str(10_000 + i)) for i in range(1000)]
            return epmc_links_payload("references", records, hit_count=1001)

        requests_mock.get(f"{self.BASE}/MED/111/references", json=refs)

        result = expand_papers(
            EuropePMCClient(), [self._seed("111")], expand_references=True
        )

        assert result.total_expanded == 1000
        assert result.id_issues["lookup_failed"] == ["MED/111"]
        assert result.expansion_stats["lookup_failed"] == 1

    def test_duplicate_record_links_its_other_ids(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """A duplicate's other IDs mark the same paper when it reappears."""
        requests_mock.get(
            f"{self.BASE}/MED/111/references",
            json={
                "hitCount": 3,
                "referenceList": {
                    "reference": [
                        {"id": "5", "source": "MED"},
                        # Same paper, now with its DOI
                        {"id": "5", "source": "MED", "doi": "10.1000/five"},
                        # Same DOI, no PMID: must still be a duplicate
                        {"id": "PPR5", "source": "PPR", "doi": "10.1000/FIVE"},
                    ]
                },
            },
        )

        result = expand_papers(
            EuropePMCClient(), [self._seed("111")], expand_references=True
        )

        assert [p["id"] for p in result.all_papers] == ["5"]
        assert result.expansion_stats["duplicates_skipped"] == 2

    def test_budget_drop_is_not_a_duplicate_and_stops_requests(
        self, requests_mock, epmc_links_payload
    ) -> None:
        """Papers past --max-expansion aren't counted as duplicates or fetched.

        With a budget of 1, X fills it; Y is dropped from the references, and
        the citation list is not downloaded at all.
        """
        self._mock_refs(
            requests_mock, epmc_links_payload, {"MED/111": [("MED", "1"), ("MED", "2")]}
        )
        requests_mock.get(
            f"{self.BASE}/MED/111/citations",
            json=epmc_links_payload("citations", [("MED", "2")]),
        )

        result = expand_papers(
            EuropePMCClient(),
            [self._seed("111")],
            expand_references=True,
            expand_citations=True,
            max_expansion=1,
        )

        assert [p["id"] for p in result.all_papers] == ["1"]
        assert result.expansion_stats["duplicates_skipped"] == 0
        full_lists = [
            r.path
            for r in requests_mock.request_history
            if parse_qs(urlsplit(r.url).query)["pageSize"] == ["1000"]
        ]
        assert full_lists == ["/europepmc/webservices/rest/med/111/references"]


class TestFetchEuropepmc:
    """Tests for fetch_europepmc function."""

    def test_mark_failed_called_on_fetch_none(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """mark_failed is called when NCBI returns None."""
        # Mock search to return one article with PMCID
        search_response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
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
            json=search_response,
        )
        # Mock NCBI efetch to return empty (simulates article not found)
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            status_code=404,
        )

        stats = fetch_europepmc(
            query="test",
            output_dir=tmp_path,
            max_results=1,
            email="test@example.com",  # Required for NCBI
        )

        assert stats["errors"] == 1
        assert stats["fetched"] == 0

        # Check checkpoint contains failed ID
        checkpoint_path = tmp_path / ".text-fetch" / "checkpoint.json"
        if checkpoint_path.exists():
            import json

            checkpoint_data = json.loads(checkpoint_path.read_text())
            failed_ids = [f["id"] for f in checkpoint_data.get("failed", [])]
            assert "PMC123456" in failed_ids

    def test_checkpoint_contains_failed_ids(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """Checkpoint records failed IDs when fetch fails."""
        # Mock search with articles
        search_response = {
            "hitCount": 2,
            "resultList": {
                "result": [
                    {
                        "id": "1",
                        "source": "MED",
                        "pmcid": "PMC111111",
                        "title": "Article 1",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                    {
                        "id": "2",
                        "source": "MED",
                        "pmcid": "PMC222222",
                        "title": "Article 2",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=search_response,
        )
        # First article fails (404 = not found, no retry), second succeeds
        # Use NCBI endpoint (all PMCID articles use NCBI)
        valid_xml = """<?xml version="1.0"?>
        <pmc-articleset>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="pmc">222222</article-id>
                    <title-group><article-title>Article 2</article-title></title-group>
                </article-meta>
            </front>
            <body><p>Test content.</p></body>
        </article>
        </pmc-articleset>"""
        # Mock NCBI - first call fails (404), second succeeds
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            [
                {"status_code": 404},  # First article fails (not found)
                {"text": valid_xml},  # Second article succeeds
            ],
        )

        stats = fetch_europepmc(
            query="test",
            output_dir=tmp_path,
            max_results=2,
            email="test@example.com",  # Required for NCBI
        )

        assert stats["errors"] == 1
        assert stats["fetched"] == 1

    def test_update_source_record_not_called_on_errors(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """update_source_record not called when there are errors."""
        from unittest.mock import patch

        from text_fetch.workspace import Workspace

        # Create workspace
        ws = Workspace.init(tmp_path / "corpus")

        # Mock search to return one article
        search_response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
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
            json=search_response,
        )
        # Mock NCBI to fail
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            status_code=500,
        )

        # Spy on update_source_record using patch
        with patch.object(
            ws, "update_source_record", wraps=ws.update_source_record
        ) as mock_update:
            stats = fetch_europepmc(
                query="test",
                workspace=ws,
                max_results=1,
                email="test@example.com",  # Required for NCBI
            )

            assert stats["errors"] == 1
            # update_source_record should NOT have been called due to errors
            mock_update.assert_not_called()

    def test_update_source_record_called_on_success(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """update_source_record called when no errors."""
        from unittest.mock import patch

        from text_fetch.workspace import Workspace

        # Create workspace
        ws = Workspace.init(tmp_path / "corpus")

        # Mock search to return one article
        search_response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "MED",
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
            json=search_response,
        )
        # Mock NCBI to succeed
        valid_xml = """<?xml version="1.0"?>
        <pmc-articleset>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="pmc">123456</article-id>
                    <title-group>
                        <article-title>Test Article Title</article-title>
                    </title-group>
                </article-meta>
            </front>
            <body><p>Test content body.</p></body>
        </article>
        </pmc-articleset>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=valid_xml,
        )

        # Spy on update_source_record using patch
        with patch.object(
            ws, "update_source_record", wraps=ws.update_source_record
        ) as mock_update:
            stats = fetch_europepmc(
                query="test",
                workspace=ws,
                max_results=1,
                email="test@example.com",  # Required for NCBI
            )

            assert stats["errors"] == 0
            assert stats["fetched"] == 1
            # update_source_record SHOULD have been called
            mock_update.assert_called_once()

    def test_pmc_source_uses_ncbi_with_email(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """PMC-source articles use NCBI download when email is provided."""
        # Mock search to return one PMC-source article
        search_response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "PMC",  # PMC source requires NCBI
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
            json=search_response,
        )
        # Mock NCBI efetch to succeed
        valid_xml = """<?xml version="1.0"?>
        <pmc-articleset>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="pmc">123456</article-id>
                    <title-group>
                        <article-title>Test Article Title</article-title>
                    </title-group>
                </article-meta>
            </front>
            <body><p>Test content body.</p></body>
        </article>
        </pmc-articleset>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=valid_xml,
        )

        stats = fetch_europepmc(
            query="test",
            output_dir=tmp_path,
            max_results=1,
            email="test@example.com",
        )

        assert stats["errors"] == 0
        assert stats["fetched"] == 1

    def test_pmc_source_skipped_without_email(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """PMC-source articles are skipped when no email provided."""
        # Mock search to return one PMC-source article
        search_response = {
            "hitCount": 1,
            "resultList": {
                "result": [
                    {
                        "id": "12345",
                        "source": "PMC",  # PMC source requires NCBI
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
            json=search_response,
        )
        # No NCBI mock needed - should not be called

        stats = fetch_europepmc(
            query="test",
            output_dir=tmp_path,
            max_results=1,
            # No email provided
        )

        # Article should be skipped, not errored
        assert stats["skipped"] == 1
        assert stats["fetched"] == 0
        assert stats["errors"] == 0

    def test_all_pmcid_uses_ncbi(self, tmp_path: Path, requests_mock) -> None:
        """All PMCID articles use NCBI for download (regardless of source)."""
        # Mock search to return both MED and PMC source articles with PMCIDs
        search_response = {
            "hitCount": 2,
            "resultList": {
                "result": [
                    {
                        "id": "1",
                        "source": "MED",
                        "pmcid": "PMC111111",
                        "title": "MED Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                    {
                        "id": "2",
                        "source": "PMC",
                        "pmcid": "PMC222222",
                        "title": "PMC Article",
                        "isOpenAccess": "Y",
                        "hasFullText": "Y",
                    },
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json=search_response,
        )
        # Mock NCBI for BOTH articles (all PMCID articles use NCBI now)
        xml1 = """<?xml version="1.0"?>
        <pmc-articleset>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="pmc">111111</article-id>
                    <title-group>
                        <article-title>MED Article</article-title>
                    </title-group>
                </article-meta>
            </front>
            <body><p>MED content.</p></body>
        </article>
        </pmc-articleset>"""
        xml2 = """<?xml version="1.0"?>
        <pmc-articleset>
        <article>
            <front>
                <article-meta>
                    <article-id pub-id-type="pmc">222222</article-id>
                    <title-group>
                        <article-title>PMC Article</article-title>
                    </title-group>
                </article-meta>
            </front>
            <body><p>PMC content.</p></body>
        </article>
        </pmc-articleset>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            [{"text": xml1}, {"text": xml2}],
        )

        stats = fetch_europepmc(
            query="test",
            output_dir=tmp_path,
            max_results=2,
            email="test@example.com",
        )

        assert stats["fetched"] == 2
        assert stats["errors"] == 0

    def test_lowercase_pmcids_are_fetched(self, tmp_path: Path, requests_mock) -> None:
        """--pmcid values in any case are looked up and downloaded (#30).

        Control: main's Europe PMC path already uppercased these.
        """
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={
                "hitCount": 1,
                "resultList": {
                    "result": [
                        {
                            "id": "PMC123456",
                            "source": "PMC",
                            "pmcid": "PMC123456",
                            "title": "Test Article",
                            "isOpenAccess": "Y",
                            "hasFullText": "Y",
                        }
                    ]
                },
            },
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>Test Article</article-title></title-group>"
            "</article-meta></front></article></pmc-articleset>",
        )

        stats = fetch_europepmc(
            pmcids=["pmc123456"],
            output_dir=tmp_path,
            email="user@example.com",
        )

        assert stats["fetched"] == 1
        assert stats["errors"] == 0
        searches = [r for r in requests_mock.request_history if "/search" in r.url]
        assert parse_qs(urlsplit(searches[0].url).query)["query"] == ["PMCID:PMC123456"]
        efetch = [r for r in requests_mock.request_history if "efetch" in r.url]
        assert [r.qs["id"] for r in efetch] == [["123456"]]
        assert (tmp_path / "valid" / "PMC123456.xml").exists()

    def test_invalid_pmcid_is_an_error_not_an_abort(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """A malformed PMCID is counted as an error; the others still download.

        It is never sent to Europe PMC or NCBI (#30).
        """
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={
                "hitCount": 1,
                "resultList": {
                    "result": [
                        {
                            "id": "PMC1",
                            "source": "PMC",
                            "pmcid": "PMC1",
                            "title": "Test Article",
                        }
                    ]
                },
            },
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>Test Article</article-title></title-group>"
            "</article-meta></front></article></pmc-articleset>",
        )

        stats = fetch_europepmc(
            pmcids=["PMC1", "PMCPMC2"],
            output_dir=tmp_path,
            email="user@example.com",
        )

        assert stats["fetched"] == 1
        assert stats["errors"] == 1
        searches = [r for r in requests_mock.request_history if "/search" in r.url]
        assert len(searches) == 1
        assert sorted(p.name for p in (tmp_path / "valid").iterdir()) == ["PMC1.xml"]

    def test_unknown_pmcid_is_an_error(self, tmp_path: Path, requests_mock) -> None:
        """A requested PMCID Europe PMC doesn't know is counted, not dropped."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={"hitCount": 0, "resultList": {"result": []}},
        )

        stats = fetch_europepmc(
            pmcids=["PMC404"], output_dir=tmp_path, email="user@example.com"
        )

        assert stats["errors"] == 1
        assert stats["articles_found"] == 0

    @pytest.mark.parametrize(
        "answer",
        [
            {"id": "X", "source": "MED", "title": "No PMCID"},
            {"id": "PMC9", "source": "PMC", "pmcid": "PMC9", "title": "Other"},
        ],
    )
    def test_lookup_returning_another_article_is_an_error(
        self, tmp_path: Path, requests_mock, answer
    ) -> None:
        """An answer without the requested PMCID is an error, not a silent drop."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={"hitCount": 1, "resultList": {"result": [answer]}},
        )

        stats = fetch_europepmc(
            pmcids=["PMC2"], output_dir=tmp_path, email="user@example.com"
        )

        assert stats["errors"] == 1
        assert stats["articles_found"] == 0
        assert not (tmp_path / "valid").exists()

    def test_empty_pmcid_list_fetches_nothing(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """pmcids=[] makes no request; it is not a search for everything (#30)."""
        stats = fetch_europepmc(
            pmcids=[], output_dir=tmp_path, email="user@example.com"
        )

        assert requests_mock.call_count == 0
        assert stats["articles_found"] == 0

    def test_all_invalid_pmcids_leave_workspace_marker(
        self, tmp_path: Path, requests_mock
    ) -> None:
        """If every PMCID is invalid, the workspace's last-fetch date stays put."""
        from text_fetch.workspace import Workspace

        ws = Workspace.init(tmp_path / "corpus")

        stats = fetch_europepmc(pmcids=["PMCPMC1"], workspace=ws)

        assert stats["errors"] == 1
        assert requests_mock.call_count == 0
        assert ws.get_last_fetch_date("europepmc") is None

    def test_search_result_pmcid_normalized(self, tmp_path: Path, requests_mock):
        """A lowercase PMCID in search results is saved as PMC<digits>.xml."""
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
            json={
                "hitCount": 2,
                "resultList": {
                    "result": [
                        {"id": "1", "source": "MED", "pmcid": "pmc3", "title": "A"},
                        {"id": "2", "source": "MED", "pmcid": "PMC4x", "title": "B"},
                    ]
                },
            },
        )
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<pmc-articleset><article><front><article-meta><title-group>"
            "<article-title>A</article-title></title-group>"
            "</article-meta></front></article></pmc-articleset>",
        )

        stats = fetch_europepmc(
            query="test", output_dir=tmp_path, email="user@example.com"
        )

        assert stats["fetched"] == 1
        assert stats["errors"] == 1  # PMC4x: counted, never requested
        assert sorted(p.name for p in (tmp_path / "valid").iterdir()) == ["PMC3.xml"]
        efetch = [r for r in requests_mock.request_history if "efetch" in r.url]
        assert [r.qs["id"] for r in efetch] == [["3"]]
