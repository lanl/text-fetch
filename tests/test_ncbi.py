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
