"""arXiv API client for preprint fetching."""

from __future__ import annotations

__all__ = ["ArxivClient", "ArxivArticle", "build_query", "fetch_arxiv"]

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

from .common import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class ArxivArticle:
    """arXiv article metadata."""

    arxiv_id: str  # e.g., "2301.12345" or "hep-th/9901001"
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: datetime
    updated: datetime | None = None
    doi: str | None = None
    pdf_url: str | None = None

    @property
    def id_for_url(self) -> str:
        """Get ID suitable for URL construction."""
        # Remove version suffix if present
        return re.sub(r"v\d+$", "", self.arxiv_id)


def build_query(
    author: str | None = None,
    title_keywords: list[str] | None = None,
    abstract_keywords: list[str] | None = None,
    categories: list[str] | None = None,
    all_keywords: list[str] | None = None,
) -> str:
    """Build arXiv query string.

    arXiv query syntax:
    - au:author_name (author)
    - ti:keyword (title)
    - abs:keyword (abstract)
    - all:keyword (anywhere)
    - cat:category (e.g., q-bio.MN, cs.AI)
    - AND, OR, ANDNOT operators

    Args:
        author: Author name to search.
        title_keywords: Keywords to search in title.
        abstract_keywords: Keywords to search in abstract.
        categories: arXiv categories to filter.
        all_keywords: Keywords to search anywhere.

    Returns:
        arXiv query string.
    """
    parts = []

    if author:
        # Handle multi-word author names
        parts.append(f'au:"{author}"')

    if title_keywords:
        kw_parts = [f'ti:"{kw}"' for kw in title_keywords]
        parts.append(f"({' OR '.join(kw_parts)})")

    if abstract_keywords:
        kw_parts = [f'abs:"{kw}"' for kw in abstract_keywords]
        parts.append(f"({' OR '.join(kw_parts)})")

    if all_keywords:
        kw_parts = [f'all:"{kw}"' for kw in all_keywords]
        parts.append(f"({' OR '.join(kw_parts)})")

    if categories:
        cat_parts = [f"cat:{cat}" for cat in categories]
        parts.append(f"({' OR '.join(cat_parts)})")

    return " AND ".join(parts)


class ArxivClient:
    """arXiv API client with rate limiting."""

    BASE_URL = "http://export.arxiv.org/api/query"
    PDF_URL_TEMPLATE = "https://arxiv.org/pdf/{arxiv_id}.pdf"

    # arXiv requests 3-second delay between requests
    RATE_LIMIT = 3.0

    def __init__(self) -> None:
        """Initialize arXiv client."""
        self.limiter = RateLimiter(1.0 / self.RATE_LIMIT)  # 1 req per 3 sec
        self.session = requests.Session()

    def search(
        self,
        query: str,
        max_results: int = 100,
        start: int = 0,
    ) -> list[ArxivArticle]:
        """Search arXiv and return list of articles.

        Args:
            query: arXiv query string (see build_query for syntax).
            max_results: Maximum number of results.
            start: Starting index for pagination.

        Returns:
            List of ArxivArticle objects.
        """
        self.limiter.wait()

        params: dict[str, str | int] = {
            "search_query": query,
            "start": start,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        try:
            resp = self.session.get(
                self.BASE_URL,
                params=params,
                timeout=30,
            )
            resp.raise_for_status()
            return self._parse_atom_feed(resp.text)
        except requests.RequestException as e:
            logger.error("arXiv API request failed: %s", e)
            return []

    def _parse_atom_feed(self, xml_content: str) -> list[ArxivArticle]:
        """Parse arXiv Atom feed into article list."""
        # arXiv uses Atom namespace
        ns = {
            "atom": "http://www.w3.org/2005/Atom",
            "arxiv": "http://arxiv.org/schemas/atom",
        }

        articles = []
        root = ET.fromstring(xml_content)

        for entry in root.findall("atom:entry", ns):
            try:
                article = self._parse_entry(entry, ns)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.warning("Failed to parse entry: %s", e)

        return articles

    def _parse_entry(
        self, entry: ET.Element, ns: dict[str, str]
    ) -> ArxivArticle | None:
        """Parse single Atom entry."""
        # Extract ID (format: http://arxiv.org/abs/2301.12345v1)
        id_elem = entry.find("atom:id", ns)
        if id_elem is None or id_elem.text is None:
            return None
        arxiv_id = id_elem.text.split("/abs/")[-1]

        # Title
        title_elem = entry.find("atom:title", ns)
        title = ""
        if title_elem is not None and title_elem.text:
            title = title_elem.text.strip()

        # Authors
        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.find("atom:name", ns)
            if name is not None and name.text:
                authors.append(name.text)

        # Abstract
        summary_elem = entry.find("atom:summary", ns)
        abstract = ""
        if summary_elem is not None and summary_elem.text:
            abstract = summary_elem.text.strip()

        # Categories
        categories = []
        for cat in entry.findall("arxiv:primary_category", ns):
            term = cat.get("term")
            if term:
                categories.append(term)
        for cat in entry.findall("atom:category", ns):
            term = cat.get("term")
            if term and term not in categories:
                categories.append(term)

        # Dates
        published_elem = entry.find("atom:published", ns)
        if published_elem is not None and published_elem.text:
            published = datetime.fromisoformat(
                published_elem.text.replace("Z", "+00:00")
            )
        else:
            published = datetime.now()

        updated_elem = entry.find("atom:updated", ns)
        updated = None
        if updated_elem is not None and updated_elem.text:
            updated = datetime.fromisoformat(updated_elem.text.replace("Z", "+00:00"))

        # DOI (if available)
        doi = None
        for link in entry.findall("atom:link", ns):
            if link.get("title") == "doi":
                doi = link.get("href", "").replace("http://dx.doi.org/", "")

        # PDF URL
        pdf_url = self.PDF_URL_TEMPLATE.format(arxiv_id=arxiv_id.split("v")[0])

        return ArxivArticle(
            arxiv_id=arxiv_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            published=published,
            updated=updated,
            doi=doi,
            pdf_url=pdf_url,
        )

    def download_pdf(self, article: ArxivArticle) -> bytes | None:
        """Download PDF for an article.

        Args:
            article: ArxivArticle with pdf_url.

        Returns:
            PDF content as bytes, or None on failure.
        """
        if not article.pdf_url:
            return None

        self.limiter.wait()

        try:
            resp = self.session.get(article.pdf_url, timeout=60)
            resp.raise_for_status()
            content: bytes = resp.content
            return content
        except requests.RequestException as e:
            logger.error("Failed to download PDF for %s: %s", article.arxiv_id, e)
            return None


def fetch_arxiv(
    config: Any = None,
    query: str | None = None,
    output_dir: str | Path = "arxiv_output",
    grobid_url: str | None = None,
    xslt_path: str | Path | None = None,
    max_results: int = 100,
    verbose: bool = False,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Fetch arXiv articles and convert to JATS.

    Pipeline:
    1. Search arXiv with query
    2. Download PDFs
    3. Convert via GROBID → JATS
    4. Validate and save

    Args:
        config: SearchConfig instance (optional if query provided).
        query: Raw arXiv query (optional if config provided).
        output_dir: Output directory for JATS files.
        grobid_url: GROBID service URL.
        xslt_path: Path to tei2jats.xsl.
        max_results: Maximum articles to fetch.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(arxiv_id, current, total).

    Returns:
        Statistics dict with search/fetch/conversion results.

    Raises:
        ValueError: If neither config nor query provided.
        RuntimeError: If GROBID service is not available.
    """
    from .grobid import GROBIDClient
    from .pmc import JATSValidator, save_pmc_article

    # Validate inputs
    if config is None and query is None:
        raise ValueError("Either config or query must be provided")

    # Build query
    arxiv_query = config.to_arxiv_query() if config else query

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Default XSLT path - look in package root
    if xslt_path is None:
        # Try common locations
        possible_paths = [
            Path(__file__).parent.parent.parent / "tei2jats.xsl",
            Path.cwd() / "tei2jats.xsl",
        ]
        for p in possible_paths:
            if p.exists():
                xslt_path = p
                break
        if xslt_path is None:
            raise ValueError("tei2jats.xsl not found. Please provide xslt_path.")

    # Initialize stats
    stats: dict[str, Any] = {
        "query": arxiv_query,
        "articles_found": 0,
        "pdfs_downloaded": 0,
        "converted": 0,
        "valid": 0,
        "incomplete": 0,
        "errors": 0,
    }

    # Initialize clients
    arxiv_client = ArxivClient()
    grobid_client = GROBIDClient(url=grobid_url)

    # Check GROBID availability
    if not grobid_client.is_available():
        raise RuntimeError(f"GROBID not available at {grobid_client.url}")

    if verbose:
        logger.info("Query: %s", arxiv_query)
        logger.info("GROBID: %s", grobid_client.url)

    # Search arXiv
    articles = arxiv_client.search(arxiv_query, max_results=max_results)
    stats["articles_found"] = len(articles)

    if verbose:
        logger.info("Found %d articles", len(articles))

    if not articles:
        return stats

    # Process each article
    validator = JATSValidator()
    total = len(articles)

    for i, article in enumerate(articles):
        if progress_callback:
            progress_callback(article.arxiv_id, i, total)

        try:
            # Download PDF
            pdf_bytes = arxiv_client.download_pdf(article)
            if pdf_bytes is None:
                stats["errors"] += 1
                continue
            stats["pdfs_downloaded"] += 1

            # Convert to JATS via GROBID
            jats = grobid_client.pdf_to_jats(pdf_bytes, xslt_path)
            if jats is None:
                stats["errors"] += 1
                continue
            stats["converted"] += 1

            # Save with validation (reuse PMC infrastructure)
            # Use arxiv: prefix for PMCID field
            arxiv_pmcid = f"arxiv:{article.arxiv_id}"
            _saved_path, result, _entry = save_pmc_article(
                pmcid=arxiv_pmcid,
                xml_content=jats,
                output_dir=output_path,
                validator=validator,
            )

            if result.status.value == "valid":
                stats["valid"] += 1
            else:
                stats["incomplete"] += 1

        except Exception as e:
            logger.error("Error processing %s: %s", article.arxiv_id, e)
            stats["errors"] += 1

    if verbose:
        logger.info(
            "Fetch complete: %d converted, %d valid, %d incomplete, %d errors",
            stats["converted"],
            stats["valid"],
            stats["incomplete"],
            stats["errors"],
        )

    return stats
