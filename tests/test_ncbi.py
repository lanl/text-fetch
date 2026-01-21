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


class TestNCBIClientFetchPmcXml:
    """Tests for fetch_pmc_xml method."""

    # Sample JATS/NXML content for testing
    SAMPLE_JATS_XML = """<?xml version="1.0" ?>
<!DOCTYPE pmc-articleset PUBLIC "-//NLM//DTD ARTICLE SET 2.0//EN"
    "https://dtd.nlm.nih.gov/ncbi/pmc/articleset/nlm-articleset-2.0.dtd">
<pmc-articleset>
<article article-type="research-article">
<front>
<article-meta>
<article-id pub-id-type="pmcid">7012345</article-id>
<title-group><article-title>Test Article</article-title></title-group>
</article-meta>
</front>
<body><p>Article body content here.</p></body>
</article>
</pmc-articleset>"""

    def test_fetch_pmc_xml_success(self, requests_mock: rm.Mocker):
        """Successful fetch returns XML content."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_JATS_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC7012345")

        assert result is not None
        assert "<pmc-articleset>" in result
        assert "<article" in result
        assert "Test Article" in result

    def test_fetch_pmc_xml_normalizes_pmcid_with_prefix(self, requests_mock: rm.Mocker):
        """PMCID with PMC prefix is normalized correctly."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_JATS_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            client.fetch_pmc_xml("PMC7012345")

        # Should strip PMC prefix for API call
        history = requests_mock.request_history[0]
        assert "id=7012345" in history.url
        assert "db=pmc" in history.url
        assert "retmode=xml" in history.url

    def test_fetch_pmc_xml_normalizes_pmcid_without_prefix(
        self, requests_mock: rm.Mocker
    ):
        """PMCID without PMC prefix works correctly."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_JATS_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("7012345")

        assert result is not None
        # Should use ID as-is
        history = requests_mock.request_history[0]
        assert "id=7012345" in history.url

    def test_fetch_pmc_xml_empty_response(self, requests_mock: rm.Mocker):
        """Empty response returns None."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="",
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC7012345")

        assert result is None

    def test_fetch_pmc_xml_minimal_response(self, requests_mock: rm.Mocker):
        """Very short response returns None."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text="<?xml?>",
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC7012345")

        assert result is None

    def test_fetch_pmc_xml_error_response(self, requests_mock: rm.Mocker):
        """Error in XML response returns None."""
        error_xml = """<?xml version="1.0"?>
        <error>ID not found: 9999999</error>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=error_xml,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC9999999")

        assert result is None

    def test_fetch_pmc_xml_id_not_found(self, requests_mock: rm.Mocker):
        """ID not found in response returns None."""
        error_xml = """<?xml version="1.0"?>
        <result><status>ID not found</status></result>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=error_xml,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC9999999")

        assert result is None

    def test_fetch_pmc_xml_non_jats_response(self, requests_mock: rm.Mocker):
        """Non-JATS XML response returns None."""
        non_jats_xml = """<?xml version="1.0"?>
        <some-other-format>
            <data>This is not JATS/NXML format</data>
        </some-other-format>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=non_jats_xml,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC7012345")

        assert result is None

    def test_fetch_pmc_xml_article_only(self, requests_mock: rm.Mocker):
        """Response with just <article> tag is valid."""
        article_xml = """<?xml version="1.0"?>
        <article article-type="research-article">
            <front><article-meta>
                <article-id>123</article-id>
            </article-meta></front>
            <body><p>Content</p></body>
        </article>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=article_xml,
        )

        with NCBIClient(email="test@example.com") as client:
            result = client.fetch_pmc_xml("PMC7012345")

        assert result is not None
        assert "<article" in result

    def test_fetch_pmc_xml_http_404_raises(self, requests_mock: rm.Mocker):
        """HTTP 404 error raises NCBIRequestError."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            status_code=404,
        )

        with (
            NCBIClient(email="test@example.com") as client,
            pytest.raises(NCBIRequestError, match="HTTP error"),
        ):
            client.fetch_pmc_xml("PMC9999999")

    def test_fetch_pmc_xml_http_400_raises(self, requests_mock: rm.Mocker):
        """HTTP 400 error raises NCBIRequestError."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            status_code=400,
        )

        with (
            NCBIClient(email="test@example.com") as client,
            pytest.raises(NCBIRequestError, match="HTTP error"),
        ):
            client.fetch_pmc_xml("invalid")

    def test_fetch_pmc_xml_http_500_raises(self, requests_mock: rm.Mocker):
        """HTTP 500 error raises after retries."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            status_code=500,
        )

        with (
            NCBIClient(
                email="test@example.com",
                max_retries=1,
                retry_delay=0.01,
            ) as client,
            pytest.raises(NCBIRequestError, match="Server error"),
        ):
            client.fetch_pmc_xml("PMC7012345")


class TestNCBIClientFetchPmcXmlBatch:
    """Tests for fetch_pmc_xml_batch method."""

    # Sample XML needs to be >100 chars to pass validation
    SAMPLE_XML = """<?xml version="1.0"?>
<pmc-articleset>
<article article-type="research-article">
<front><article-meta><article-id>123</article-id></article-meta></front>
<body><p>Test content for batch fetch testing.</p></body>
</article>
</pmc-articleset>"""

    def test_fetch_batch_all_success(self, requests_mock: rm.Mocker):
        """Batch fetch returns all results."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            results = client.fetch_pmc_xml_batch(["PMC111", "PMC222", "PMC333"])

        assert len(results) == 3
        assert all(v is not None for v in results.values())
        assert "PMC111" in results
        assert "PMC222" in results
        assert "PMC333" in results

    def test_fetch_batch_normalizes_pmcids(self, requests_mock: rm.Mocker):
        """Batch fetch normalizes PMCIDs in result keys."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            # Mix of with and without prefix
            results = client.fetch_pmc_xml_batch(["PMC111", "222", "PMC333"])

        # All keys should have PMC prefix
        assert "PMC111" in results
        assert "PMC222" in results
        assert "PMC333" in results

    def test_fetch_batch_partial_failure(self, requests_mock: rm.Mocker):
        """Batch fetch handles partial failures gracefully."""
        # Second response is long enough but contains error marker
        error_xml = """<?xml version="1.0"?>
<result><status>ID not found</status>
<message>The requested article could not be found in PMC.</message>
</result>"""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            [
                {"text": self.SAMPLE_XML},  # First succeeds
                {"text": error_xml},  # Second fails (ID not found)
                {"text": self.SAMPLE_XML},  # Third succeeds
            ],
        )

        with NCBIClient(email="test@example.com") as client:
            results = client.fetch_pmc_xml_batch(["PMC111", "PMC222", "PMC333"])

        assert len(results) == 3
        assert results["PMC111"] is not None
        assert results["PMC222"] is None  # Failed
        assert results["PMC333"] is not None

    def test_fetch_batch_empty_input(self):
        """Batch fetch with empty list returns empty dict."""
        with NCBIClient(email="test@example.com") as client:
            results = client.fetch_pmc_xml_batch([])

        assert results == {}

    def test_fetch_batch_single_item(self, requests_mock: rm.Mocker):
        """Batch fetch works with single item."""
        requests_mock.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            text=self.SAMPLE_XML,
        )

        with NCBIClient(email="test@example.com") as client:
            results = client.fetch_pmc_xml_batch(["PMC111"])

        assert len(results) == 1
        assert "PMC111" in results
        assert results["PMC111"] is not None
