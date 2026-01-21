"""Tests for arXiv client."""

from datetime import datetime

from text_fetch.arxiv import ArxivArticle, ArxivClient, build_query


class TestBuildQuery:
    """Tests for query builder."""

    def test_author_only(self):
        """Author-only query."""
        q = build_query(author="hlavacek ws")
        assert 'au:"hlavacek ws"' in q

    def test_categories_only(self):
        """Category-only query."""
        q = build_query(categories=["q-bio.MN", "cs.AI"])
        assert "cat:q-bio.MN" in q
        assert "cat:cs.AI" in q
        assert " OR " in q

    def test_all_keywords(self):
        """Keywords search anywhere."""
        q = build_query(all_keywords=["systems biology", "modeling"])
        assert 'all:"systems biology"' in q
        assert 'all:"modeling"' in q

    def test_title_keywords(self):
        """Keywords search in title."""
        q = build_query(title_keywords=["neural network"])
        assert 'ti:"neural network"' in q

    def test_abstract_keywords(self):
        """Keywords search in abstract."""
        q = build_query(abstract_keywords=["machine learning"])
        assert 'abs:"machine learning"' in q

    def test_combined(self):
        """Combined query."""
        q = build_query(
            author="hlavacek",
            categories=["q-bio.MN"],
            all_keywords=["rule-based"],
        )
        assert "au:" in q
        assert "cat:" in q
        assert "all:" in q
        assert " AND " in q

    def test_empty_query(self):
        """Empty query returns empty string."""
        q = build_query()
        assert q == ""


class TestArxivArticle:
    """Tests for ArxivArticle dataclass."""

    def test_id_for_url_removes_version(self):
        """Version suffix removed for URL."""
        article = ArxivArticle(
            arxiv_id="2301.12345v2",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
        )
        assert article.id_for_url == "2301.12345"

    def test_id_for_url_no_version(self):
        """ID without version stays the same."""
        article = ArxivArticle(
            arxiv_id="2301.12345",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
        )
        assert article.id_for_url == "2301.12345"

    def test_old_style_id(self):
        """Old-style arXiv ID (hep-th/...)."""
        article = ArxivArticle(
            arxiv_id="hep-th/9901001v1",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
        )
        assert article.id_for_url == "hep-th/9901001"


class TestArxivClient:
    """Tests for ArxivClient."""

    def test_search_success(self, requests_mock):
        """search returns parsed articles."""
        # Sample arXiv Atom response
        atom_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2301.12345v1</id>
    <title>Test Article Title</title>
    <summary>This is the abstract.</summary>
    <author><name>John Doe</name></author>
    <author><name>Jane Smith</name></author>
    <published>2023-01-15T00:00:00Z</published>
    <updated>2023-01-16T00:00:00Z</updated>
    <arxiv:primary_category term="cs.AI"/>
    <category term="cs.AI"/>
    <category term="cs.LG"/>
  </entry>
</feed>"""
        requests_mock.get(
            "http://export.arxiv.org/api/query",
            text=atom_response,
        )
        client = ArxivClient()
        articles = client.search('au:"Doe"')

        assert len(articles) == 1
        article = articles[0]
        assert article.arxiv_id == "2301.12345v1"
        assert article.title == "Test Article Title"
        assert article.abstract == "This is the abstract."
        assert article.authors == ["John Doe", "Jane Smith"]
        assert "cs.AI" in article.categories
        assert article.pdf_url == "https://arxiv.org/pdf/2301.12345.pdf"

    def test_search_empty_results(self, requests_mock):
        """search handles empty results."""
        atom_response = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
</feed>"""
        requests_mock.get(
            "http://export.arxiv.org/api/query",
            text=atom_response,
        )
        client = ArxivClient()
        articles = client.search('au:"nonexistent"')
        assert articles == []

    def test_search_api_error(self, requests_mock):
        """search returns empty list on API error."""
        requests_mock.get(
            "http://export.arxiv.org/api/query",
            status_code=500,
        )
        client = ArxivClient()
        articles = client.search('au:"Doe"')
        assert articles == []

    def test_search_connection_error(self, requests_mock):
        """search handles connection error."""
        import requests

        requests_mock.get(
            "http://export.arxiv.org/api/query",
            exc=requests.exceptions.ConnectionError,
        )
        client = ArxivClient()
        articles = client.search('au:"Doe"')
        assert articles == []

    def test_download_pdf_success(self, requests_mock):
        """download_pdf returns PDF bytes."""
        pdf_content = b"%PDF-1.4 fake pdf content"
        requests_mock.get(
            "https://arxiv.org/pdf/2301.12345.pdf",
            content=pdf_content,
        )
        article = ArxivArticle(
            arxiv_id="2301.12345v1",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
            pdf_url="https://arxiv.org/pdf/2301.12345.pdf",
        )
        client = ArxivClient()
        result = client.download_pdf(article)
        assert result == pdf_content

    def test_download_pdf_failure(self, requests_mock):
        """download_pdf returns None on error."""
        requests_mock.get(
            "https://arxiv.org/pdf/2301.12345.pdf",
            status_code=404,
        )
        article = ArxivArticle(
            arxiv_id="2301.12345v1",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
            pdf_url="https://arxiv.org/pdf/2301.12345.pdf",
        )
        client = ArxivClient()
        result = client.download_pdf(article)
        assert result is None

    def test_download_pdf_no_url(self):
        """download_pdf returns None when no URL."""
        article = ArxivArticle(
            arxiv_id="2301.12345v1",
            title="Test",
            authors=[],
            abstract="",
            categories=[],
            published=datetime.now(),
            pdf_url=None,
        )
        client = ArxivClient()
        result = client.download_pdf(article)
        assert result is None

    def test_rate_limiter_initialized(self):
        """Client has rate limiter configured."""
        client = ArxivClient()
        assert client.limiter is not None
        # arXiv wants 3 second delay, so 1/3 requests per second
        assert client.limiter.min_interval >= 3.0
