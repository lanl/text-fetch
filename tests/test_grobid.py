"""Tests for GROBID client."""

from text_fetch.grobid import GROBIDClient


class TestGROBIDClient:
    """Tests for GROBIDClient."""

    def test_is_available_success(self, requests_mock):
        """is_available returns True when GROBID responds."""
        requests_mock.get("http://localhost:8070/api/isalive", status_code=200)
        client = GROBIDClient()
        assert client.is_available() is True

    def test_is_available_failure(self, requests_mock):
        """is_available returns False when GROBID is down."""
        requests_mock.get("http://localhost:8070/api/isalive", status_code=500)
        client = GROBIDClient()
        assert client.is_available() is False

    def test_is_available_connection_error(self, requests_mock):
        """is_available returns False on connection error."""
        import requests

        requests_mock.get(
            "http://localhost:8070/api/isalive",
            exc=requests.exceptions.ConnectionError,
        )
        client = GROBIDClient()
        assert client.is_available() is False

    def test_process_pdf_success(self, requests_mock):
        """process_pdf returns TEI on success."""
        tei_response = '<?xml version="1.0"?><TEI>...</TEI>'
        requests_mock.post(
            "http://localhost:8070/api/processFulltextDocument",
            text=tei_response,
        )
        client = GROBIDClient()
        result = client.process_pdf(b"fake pdf content")
        assert result == tei_response

    def test_process_pdf_header_only(self, requests_mock):
        """process_pdf uses header endpoint when full_text=False."""
        tei_response = '<?xml version="1.0"?><TEI>header</TEI>'
        requests_mock.post(
            "http://localhost:8070/api/processHeaderDocument",
            text=tei_response,
        )
        client = GROBIDClient()
        result = client.process_pdf(b"fake pdf content", full_text=False)
        assert result == tei_response

    def test_process_pdf_failure(self, requests_mock):
        """process_pdf returns None on error."""
        requests_mock.post(
            "http://localhost:8070/api/processFulltextDocument",
            status_code=500,
            text="Internal Server Error",
        )
        client = GROBIDClient()
        result = client.process_pdf(b"fake pdf content")
        assert result is None

    def test_process_pdf_connection_error(self, requests_mock):
        """process_pdf returns None on connection error."""
        import requests

        requests_mock.post(
            "http://localhost:8070/api/processFulltextDocument",
            exc=requests.exceptions.ConnectionError,
        )
        client = GROBIDClient()
        result = client.process_pdf(b"fake pdf content")
        assert result is None

    def test_custom_url(self):
        """Custom URL is used."""
        client = GROBIDClient(url="http://grobid.example.com:8080/")
        assert client.url == "http://grobid.example.com:8080"

    def test_custom_url_no_trailing_slash(self):
        """URL trailing slash is stripped."""
        client = GROBIDClient(url="http://grobid.example.com:8080")
        assert client.url == "http://grobid.example.com:8080"

    def test_default_url(self):
        """Default URL is localhost:8070."""
        client = GROBIDClient()
        assert client.url == "http://localhost:8070"

    def test_custom_timeout(self):
        """Custom timeout is set."""
        client = GROBIDClient(timeout=600)
        assert client.timeout == 600

    def test_tei_to_jats_invalid_xslt(self, tmp_path):
        """tei_to_jats returns None with invalid XSLT."""
        xslt_path = tmp_path / "invalid.xsl"
        xslt_path.write_text("not valid xslt")
        client = GROBIDClient()
        result = client.tei_to_jats("<TEI/>", xslt_path)
        assert result is None

    def test_tei_to_jats_missing_xslt(self):
        """tei_to_jats returns None with missing XSLT file."""
        client = GROBIDClient()
        result = client.tei_to_jats("<TEI/>", "/nonexistent/path.xsl")
        assert result is None
