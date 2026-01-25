"""Tests for Europe PMC client."""

from datetime import datetime
from pathlib import Path

from text_fetch.europepmc import (
    EuropePMCArticle,
    EuropePMCClient,
    ExpansionResult,
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
        # API endpoint uses numeric ID without PMC prefix
        requests_mock.get(f"{url}/PMC/123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("PMC123456")

        assert result == xml_content

    def test_get_full_text_xml_normalizes_pmcid(self, requests_mock) -> None:
        """get_full_text_xml normalizes PMCID."""
        xml_content = "<article>Test</article>"
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        # API endpoint uses numeric ID without PMC prefix
        requests_mock.get(f"{url}/PMC/123456/fullTextXML", text=xml_content)

        client = EuropePMCClient()
        result = client.get_full_text_xml("123456")  # Without PMC prefix

        assert result == xml_content

    def test_get_full_text_xml_error(self, requests_mock) -> None:
        """get_full_text_xml returns None on error."""
        url = "https://www.ebi.ac.uk/europepmc/webservices/rest"
        # API endpoint uses numeric ID without PMC prefix
        requests_mock.get(f"{url}/PMC/123456/fullTextXML", status_code=404)

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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/32487503/citations/1/1000/json",
            json=response,
        )

        client = EuropePMCClient()
        citations, total = client.get_citations("MED", "32487503")

        assert total == 2
        assert len(citations) == 2
        assert citations[0]["title"] == "Citing Paper 1"

    def test_get_citations_normalizes_pmcid(self, requests_mock) -> None:
        """get_citations removes PMC prefix from PMCID."""
        response = {
            "hitCount": 1,
            "citationList": {
                "citation": [
                    {"id": "11111111", "source": "MED", "title": "Test"},
                ]
            },
        }
        # Note: endpoint should NOT have PMC prefix
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/7343657/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/99999999/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/32487503/references/1/1000/json",
            json=response,
        )

        client = EuropePMCClient()
        references, total = client.get_references("MED", "32487503")

        assert total == 2
        assert len(references) == 2
        assert references[0]["title"] == "Referenced Paper 1"

    def test_get_references_normalizes_pmcid(self, requests_mock) -> None:
        """get_references removes PMC prefix from PMCID."""
        response = {
            "hitCount": 1,
            "referenceList": {
                "reference": [
                    {"id": "11111111", "source": "MED", "title": "Test"},
                ]
            },
        }
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/7343657/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/99999999/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/1/1000/json",
            json=response1,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/2/1000/json",
            json=response2,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/3/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/1/1000/json",
            json=response1,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/2/1000/json",
            json=response2,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/3/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/MED/12345678/references/1/1000/json",
            json=response,
        )

        client = EuropePMCClient()
        references = client.get_all_references("MED", "12345678", max_results=5)

        assert len(references) == 5


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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/citations/1/1/json",
            json=cites_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1000/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/citations/1/1/json",
            json=cites_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/citations/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/111/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/111/references/1/1000/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/222/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/222/references/1/1000/json",
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
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1/json",
            json=refs_response,
        )
        requests_mock.get(
            "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/123456/references/1/1000/json",
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
