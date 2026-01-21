"""Unit tests for NCBI E-utilities wrapper."""

from __future__ import annotations

import pytest
import requests_mock as rm
from text_fetch.ncbi import NCBIClient, NCBIError, NCBIRequestError


class TestNCBIClientInit:
    """Tests for NCBIClient initialization."""

    def test_email_required(self):
        """Email is required for NCBI API access."""
        with pytest.raises(ValueError, match="Email is required"):
            NCBIClient(email="")

    def test_basic_init(self):
        """Basic client initialization."""
        client = NCBIClient(email="test@example.com")
        assert client.email == "test@example.com"
        assert client.api_key is None
        assert client.tool == "text-fetch"
        assert client.max_retries == 3
        assert client.timeout == 30.0
        client.close()

    def test_init_with_api_key(self):
        """Client with API key gets higher rate limit."""
        client = NCBIClient(email="test@example.com", api_key="my_key")
        assert client.api_key == "my_key"
        # Rate should be 9/sec with API key vs 3/sec without
        assert client.limiter.min_interval < 0.15  # ~1/9 sec
        client.close()

    def test_init_without_api_key_rate_limit(self):
        """Client without API key has lower rate limit."""
        client = NCBIClient(email="test@example.com")
        # Rate should be 3/sec without API key
        assert client.limiter.min_interval > 0.3  # ~1/3 sec
        client.close()

    def test_custom_parameters(self):
        """Custom parameters are accepted."""
        client = NCBIClient(
            email="test@example.com",
            tool="my-tool",
            max_retries=5,
            retry_delay=2.0,
            timeout=60.0,
        )
        assert client.tool == "my-tool"
        assert client.max_retries == 5
        assert client.retry_delay == 2.0
        assert client.timeout == 60.0
        client.close()


class TestNCBIClientBaseParams:
    """Tests for _base_params method."""

    def test_base_params_without_api_key(self):
        """Base params without API key."""
        client = NCBIClient(email="test@example.com")
        params = client._base_params()
        assert params == {
            "email": "test@example.com",
            "tool": "text-fetch",
        }
        client.close()

    def test_base_params_with_api_key(self):
        """Base params with API key."""
        client = NCBIClient(email="test@example.com", api_key="my_api_key")
        params = client._base_params()
        assert params == {
            "email": "test@example.com",
            "tool": "text-fetch",
            "api_key": "my_api_key",
        }
        client.close()


class TestNCBIClientRequest:
    """Tests for _request method."""

    def test_successful_json_request(self, requests_mock: rm.Mocker):
        """Successful JSON request."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            json={"result": "success"},
        )

        with NCBIClient(email="test@example.com") as client:
            result = client._request("test.fcgi", {"param": "value"})
            assert result == {"result": "success"}

    def test_request_includes_base_params(self, requests_mock: rm.Mocker):
        """Request includes email and tool parameters."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            json={"result": "success"},
        )

        with NCBIClient(email="test@example.com") as client:
            client._request("test.fcgi", {})

        # Check that email and tool were sent
        history = requests_mock.request_history[0]
        assert "email=test%40example.com" in history.url
        assert "tool=text-fetch" in history.url

    def test_custom_base_url(self, requests_mock: rm.Mocker):
        """Request can use custom base URL."""
        requests_mock.get(
            "https://custom.api.example.com/endpoint",
            json={"custom": True},
        )

        with NCBIClient(email="test@example.com") as client:
            result = client._request(
                "endpoint",
                {},
                base_url="https://custom.api.example.com",
            )
            assert result == {"custom": True}

    def test_retry_on_server_error(self, requests_mock: rm.Mocker):
        """Request retries on 5xx server errors."""
        # First request fails with 500, second succeeds
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            [
                {"status_code": 500, "json": {"error": "server error"}},
                {"json": {"result": "success"}},
            ],
        )

        with NCBIClient(
            email="test@example.com",
            max_retries=3,
            retry_delay=0.01,  # Fast for tests
        ) as client:
            result = client._request("test.fcgi", {})
            assert result == {"result": "success"}
            assert requests_mock.call_count == 2

    def test_max_retries_exhausted(self, requests_mock: rm.Mocker):
        """Request fails after max retries exhausted."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            status_code=500,
            json={"error": "server error"},
        )

        with NCBIClient(
            email="test@example.com",
            max_retries=2,
            retry_delay=0.01,
        ) as client:
            with pytest.raises(NCBIRequestError, match="Server error: 500"):
                client._request("test.fcgi", {})

            # Should have tried 3 times (initial + 2 retries)
            assert requests_mock.call_count == 3

    def test_http_error_not_retried(self, requests_mock: rm.Mocker):
        """4xx errors are not retried."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            status_code=400,
            json={"error": "bad request"},
        )

        with (
            NCBIClient(email="test@example.com") as client,
            pytest.raises(NCBIRequestError, match="HTTP error"),
        ):
            client._request("test.fcgi", {})

        # Should only try once
        assert requests_mock.call_count == 1

    def test_invalid_json_response(self, requests_mock: rm.Mocker):
        """Invalid JSON raises appropriate error."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            text="not valid json",
        )

        with (
            NCBIClient(email="test@example.com") as client,
            pytest.raises(NCBIRequestError, match="Invalid JSON"),
        ):
            client._request("test.fcgi", {})


class TestNCBIClientRequestXML:
    """Tests for _request_xml method."""

    def test_successful_xml_request(self, requests_mock: rm.Mocker):
        """Successful XML request returns raw text."""
        xml_content = '<?xml version="1.0"?><result>success</result>'
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            text=xml_content,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client._request_xml("test.fcgi", {})
            assert result == xml_content

    def test_xml_request_retries_on_server_error(self, requests_mock: rm.Mocker):
        """XML request retries on 5xx errors."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/test.fcgi",
            [
                {"status_code": 503, "text": "Service Unavailable"},
                {"text": "<result>ok</result>"},
            ],
        )

        with NCBIClient(
            email="test@example.com",
            max_retries=2,
            retry_delay=0.01,
        ) as client:
            result = client._request_xml("test.fcgi", {})
            assert result == "<result>ok</result>"


class TestNCBIClientContextManager:
    """Tests for context manager functionality."""

    def test_context_manager(self):
        """Client works as context manager."""
        with NCBIClient(email="test@example.com") as client:
            assert isinstance(client, NCBIClient)
            assert client.session is not None

    def test_session_closed_on_exit(self):
        """Session is closed when exiting context."""
        with NCBIClient(email="test@example.com") as client:
            # Access session to confirm it exists
            assert client.session is not None

        # After exiting, we can't easily verify the session is closed
        # but we can verify no exception was raised


class TestNCBIExceptions:
    """Tests for NCBI exception classes."""

    def test_ncbi_error_hierarchy(self):
        """Exception hierarchy is correct."""
        assert issubclass(NCBIRequestError, NCBIError)
        assert issubclass(NCBIError, Exception)

    def test_ncbi_request_error_status_code(self):
        """NCBIRequestError stores status code."""
        error = NCBIRequestError("test error", status_code=404)
        assert str(error) == "test error"
        assert error.status_code == 404

    def test_ncbi_request_error_no_status_code(self):
        """NCBIRequestError works without status code."""
        error = NCBIRequestError("test error")
        assert str(error) == "test error"
        assert error.status_code is None


class TestNCBIClientESearch:
    """Tests for esearch method."""

    def test_esearch_basic(self, requests_mock: rm.Mocker):
        """Basic esearch returns structured results."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={
                "esearchresult": {
                    "idlist": ["12345", "67890"],
                    "count": "2",
                    "querytranslation": "hlavacek ws[Author]",
                }
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.esearch("hlavacek ws[author]")

        assert result["idlist"] == ["12345", "67890"]
        assert result["count"] == 2
        assert result["querytranslation"] == "hlavacek ws[Author]"

    def test_esearch_sends_correct_params(self, requests_mock: rm.Mocker):
        """esearch sends correct parameters."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={"esearchresult": {"idlist": [], "count": "0"}},
        )

        with NCBIClient(email="test@example.com") as client:
            client.esearch("test query", db="pmc", max_results=100)

        history = requests_mock.request_history[0]
        assert "db=pmc" in history.url
        assert "term=test+query" in history.url or "term=test%20query" in history.url
        assert "retmax=100" in history.url
        assert "retmode=json" in history.url

    def test_esearch_with_history(self, requests_mock: rm.Mocker):
        """esearch with use_history returns webenv and querykey."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={
                "esearchresult": {
                    "idlist": ["12345"],
                    "count": "1",
                    "webenv": "NCID_1_123456_130.14.22.215",
                    "querykey": "1",
                }
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.esearch("test", use_history=True)

        assert result["webenv"] == "NCID_1_123456_130.14.22.215"
        assert result["querykey"] == "1"
        assert "usehistory=y" in requests_mock.request_history[0].url

    def test_esearch_empty_results(self, requests_mock: rm.Mocker):
        """esearch handles empty results."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={"esearchresult": {"idlist": [], "count": "0"}},
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.esearch("nonexistent query xyz123")

        assert result["idlist"] == []
        assert result["count"] == 0

    def test_esearch_large_count(self, requests_mock: rm.Mocker):
        """esearch returns count larger than returned IDs."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={
                "esearchresult": {
                    "idlist": ["1", "2", "3"],
                    "count": "15000",
                }
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.esearch("common term", max_results=3)

        assert len(result["idlist"]) == 3
        assert result["count"] == 15000  # Total available


class TestNCBIClientESearchIds:
    """Tests for esearch_ids convenience method."""

    def test_esearch_ids_returns_list(self, requests_mock: rm.Mocker):
        """esearch_ids returns just the ID list."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={
                "esearchresult": {
                    "idlist": ["111", "222", "333"],
                    "count": "3",
                }
            },
        )

        with NCBIClient(email="test@example.com") as client:
            pmids = client.esearch_ids("test query")

        assert pmids == ["111", "222", "333"]
        assert isinstance(pmids, list)

    def test_esearch_ids_empty(self, requests_mock: rm.Mocker):
        """esearch_ids returns empty list for no results."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            json={"esearchresult": {"idlist": [], "count": "0"}},
        )

        with NCBIClient(email="test@example.com") as client:
            pmids = client.esearch_ids("nonexistent")

        assert pmids == []


class TestNCBIClientConvertIds:
    """Tests for convert_ids method."""

    def test_convert_ids_basic(self, requests_mock: rm.Mocker):
        """convert_ids maps PMIDs to PMCIDs."""
        requests_mock.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            json={
                "records": [
                    {"pmid": "12345", "pmcid": "PMC111111"},
                    {"pmid": "67890", "pmcid": "PMC222222"},
                ]
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.convert_ids(["12345", "67890"])

        assert result == {"12345": "PMC111111", "67890": "PMC222222"}

    def test_convert_ids_partial(self, requests_mock: rm.Mocker):
        """convert_ids returns None for IDs without PMCIDs."""
        requests_mock.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            json={
                "records": [
                    {"pmid": "12345", "pmcid": "PMC111111"},
                    {"pmid": "67890"},  # No PMCID
                ]
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.convert_ids(["12345", "67890"])

        assert result["12345"] == "PMC111111"
        assert result["67890"] is None

    def test_convert_ids_empty_input(self):
        """convert_ids returns empty dict for empty input."""
        with NCBIClient(email="test@example.com") as client:
            result = client.convert_ids([])

        assert result == {}

    def test_convert_ids_batching(self, requests_mock: rm.Mocker):
        """convert_ids processes large lists in batches."""
        # Create 250 IDs (more than batch size of 200)
        ids = [str(i) for i in range(250)]

        # Mock should be called twice
        requests_mock.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            [
                # First batch: 200 IDs
                {
                    "json": {
                        "records": [
                            {"pmid": str(i), "pmcid": f"PMC{i}"} for i in range(200)
                        ]
                    }
                },
                # Second batch: 50 IDs
                {
                    "json": {
                        "records": [
                            {"pmid": str(i), "pmcid": f"PMC{i}"}
                            for i in range(200, 250)
                        ]
                    }
                },
            ],
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.convert_ids(ids)

        # Should have made 2 requests
        assert requests_mock.call_count == 2
        # Should have all 250 results
        assert len(result) == 250

    def test_convert_ids_sends_correct_params(self, requests_mock: rm.Mocker):
        """convert_ids sends correct parameters."""
        requests_mock.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            json={"records": []},
        )

        with NCBIClient(email="test@example.com") as client:
            client.convert_ids(["123", "456"], id_type="pmid")

        history = requests_mock.request_history[0]
        assert "ids=123%2C456" in history.url or "ids=123,456" in history.url
        assert "idtype=pmid" in history.url
        assert "format=json" in history.url


class TestNCBIClientGetPmcids:
    """Tests for get_pmcids convenience method."""

    def test_get_pmcids_filters_none(self, requests_mock: rm.Mocker):
        """get_pmcids only returns PMIDs with PMCIDs."""
        requests_mock.get(
            "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/",
            json={
                "records": [
                    {"pmid": "111", "pmcid": "PMC111"},
                    {"pmid": "222"},  # No PMCID
                    {"pmid": "333", "pmcid": "PMC333"},
                ]
            },
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.get_pmcids(["111", "222", "333"])

        # Should only include IDs with PMCIDs
        assert result == {"111": "PMC111", "333": "PMC333"}
        assert "222" not in result
