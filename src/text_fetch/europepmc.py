"""Europe PMC API client for full-text article fetching.

Europe PMC (European PubMed Central) provides access to ~39 million life
sciences records with native JATS XML full-text (no GROBID needed).

Key advantages over NCBI PMC:
- Native JATS XML output
- Cursor-based pagination (fast for deep queries)
- Lucene query syntax
- No documented rate limit (we use 5 req/sec to be respectful)
"""

from __future__ import annotations

__all__ = [
    "EuropePMCClient",
    "EuropePMCArticle",
    "fetch_europepmc",
]

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests

from .common import RateLimiter

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)


@dataclass
class EuropePMCArticle:
    """Europe PMC article metadata."""

    id: str  # Internal ID
    source: str  # MED, PMC, PPR, etc.
    pmid: str | None
    pmcid: str | None
    doi: str | None
    title: str
    authors: list[str]
    abstract: str
    journal: str
    pub_year: int | None
    first_publication_date: datetime | None
    is_open_access: bool
    has_full_text: bool

    @property
    def id_for_filename(self) -> str:
        """ID suitable for filename."""
        if self.pmcid:
            return self.pmcid
        if self.pmid:
            return f"PMID{self.pmid}"
        return f"EPMC{self.id}"


class EuropePMCClient:
    """Europe PMC REST API client.

    Provides search and full-text download from Europe PMC.

    Example:
        >>> client = EuropePMCClient()
        >>> articles, next_cursor, total = client.search('AUTH:"hlavacek ws"')
        >>> for article in articles:
        ...     print(article.title)
    """

    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    # Europe PMC doesn't document rate limits, but be respectful
    # Can likely handle 5-10 req/sec safely
    RATE_LIMIT = 5.0

    def __init__(self) -> None:
        """Initialize client."""
        self.limiter = RateLimiter(self.RATE_LIMIT)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "text-fetch/0.1.5 (literature acquisition)",
                "Accept": "application/json",
            }
        )

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Make API request with rate limiting."""
        self.limiter.wait()
        url = f"{self.BASE_URL}{endpoint}"

        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
        except requests.RequestException as e:
            logger.error("API request failed: %s - %s", url, e)
            return None
        except ValueError as e:
            logger.error("Invalid JSON response: %s", e)
            return None

    def _request_xml(self, endpoint: str) -> str | None:
        """Make API request expecting XML response."""
        self.limiter.wait()
        url = f"{self.BASE_URL}{endpoint}"

        try:
            resp = self.session.get(url, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.error("API request failed: %s - %s", url, e)
            return None

    def search(
        self,
        query: str,
        page_size: int = 100,
        cursor: str = "*",
        result_type: str = "core",
    ) -> tuple[list[EuropePMCArticle], str | None, int]:
        """Search for articles.

        Args:
            query: Lucene query string.
            page_size: Results per page (max 1000).
            cursor: Cursor for pagination (* for start).
            result_type: "core" for full metadata, "lite" for minimal.

        Returns:
            Tuple of (articles, next_cursor, total_count).
            next_cursor is None if no more results.
        """
        params = {
            "query": query,
            "format": "json",
            "pageSize": min(page_size, 1000),
            "cursorMark": cursor,
            "resultType": result_type,
        }

        data = self._request("/search", params)
        return self._parse_search_response(data, cursor)

    def iter_search(
        self,
        query: str,
        max_results: int | None = None,
        page_size: int = 100,
    ) -> Iterator[EuropePMCArticle]:
        """Iterate through all search results.

        Handles cursor pagination automatically.

        Args:
            query: Lucene query string.
            max_results: Maximum articles to yield.
            page_size: Results per page.

        Yields:
            EuropePMCArticle objects.
        """
        cursor = "*"
        count = 0

        while True:
            articles, next_cursor, _total = self.search(
                query=query,
                page_size=page_size,
                cursor=cursor,
            )

            for article in articles:
                yield article
                count += 1
                if max_results and count >= max_results:
                    return

            # Cursor unchanged means no more results
            if next_cursor is None or next_cursor == cursor:
                break
            cursor = next_cursor

    def _parse_search_response(
        self,
        data: dict[str, Any] | None,
        current_cursor: str,
    ) -> tuple[list[EuropePMCArticle], str | None, int]:
        """Parse search response."""
        if not data:
            return [], None, 0

        total = data.get("hitCount", 0)
        next_cursor = data.get("nextCursorMark")

        # If cursor unchanged, no more results
        if next_cursor == current_cursor:
            next_cursor = None

        articles = []
        result_list = data.get("resultList", {}).get("result", [])

        for item in result_list:
            try:
                article = self._parse_article(item)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.warning("Failed to parse article: %s", e)

        return articles, next_cursor, total

    def _parse_article(self, item: dict[str, Any]) -> EuropePMCArticle | None:
        """Parse single article from response."""
        article_id = item.get("id")
        if not article_id:
            return None

        # Parse authors from authorString or authorList
        authors = []
        if item.get("authorList"):
            for author in item["authorList"].get("author", []):
                first = author.get("firstName", "")
                last = author.get("lastName", "")
                name = f"{first} {last}".strip()
                if name:
                    authors.append(name)
        elif item.get("authorString"):
            # Fall back to author string parsing
            authors = [a.strip() for a in item["authorString"].split(",")]

        # Parse publication date
        pub_date = None
        date_str = item.get("firstPublicationDate")
        if date_str:
            with contextlib.suppress(ValueError):
                pub_date = datetime.strptime(date_str, "%Y-%m-%d")

        # Parse year
        pub_year = None
        year_str = item.get("pubYear")
        if year_str:
            with contextlib.suppress(ValueError):
                pub_year = int(year_str)

        return EuropePMCArticle(
            id=article_id,
            source=item.get("source", ""),
            pmid=item.get("pmid"),
            pmcid=item.get("pmcid"),
            doi=item.get("doi"),
            title=item.get("title", ""),
            authors=authors,
            abstract=item.get("abstractText", ""),
            journal=item.get("journalTitle", ""),
            pub_year=pub_year,
            first_publication_date=pub_date,
            is_open_access=item.get("isOpenAccess") == "Y",
            has_full_text=item.get("hasFullText") == "Y",
        )

    def get_full_text_xml(self, pmcid: str) -> str | None:
        """Download full-text JATS XML for article.

        Args:
            pmcid: PMC ID (e.g., "PMC123456").

        Returns:
            JATS XML string or None if not available.
        """
        # Normalize PMCID
        pmcid = self.normalize_pmcid(pmcid)

        # Endpoint: /{source}/{id}/fullTextXML
        endpoint = f"/PMC/{pmcid}/fullTextXML"
        return self._request_xml(endpoint)

    def get_by_pmcid(self, pmcid: str) -> EuropePMCArticle | None:
        """Fetch article metadata by PMC ID.

        Args:
            pmcid: PMC ID.

        Returns:
            EuropePMCArticle or None.
        """
        pmcid = self.normalize_pmcid(pmcid)
        query = f"PMCID:{pmcid}"
        articles, _, _ = self.search(query, page_size=1)
        return articles[0] if articles else None

    def get_by_pmid(self, pmid: str) -> EuropePMCArticle | None:
        """Fetch article metadata by PubMed ID.

        Args:
            pmid: PubMed ID.

        Returns:
            EuropePMCArticle or None.
        """
        query = f"EXT_ID:{pmid} AND SRC:MED"
        articles, _, _ = self.search(query, page_size=1)
        return articles[0] if articles else None

    def get_by_doi(self, doi: str) -> EuropePMCArticle | None:
        """Fetch article metadata by DOI.

        Args:
            doi: Article DOI.

        Returns:
            EuropePMCArticle or None.
        """
        query = f'DOI:"{doi}"'
        articles, _, _ = self.search(query, page_size=1)
        return articles[0] if articles else None

    @staticmethod
    def normalize_pmcid(pmcid: str) -> str:
        """Normalize PMC ID format.

        Handles:
        - PMC123456
        - 123456
        - pmc123456

        Returns:
            Clean PMC ID (PMC123456).
        """
        pmcid = pmcid.strip().upper()
        if not pmcid.startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        return pmcid

    @staticmethod
    def build_query(
        author: str | None = None,
        keywords: list[str] | None = None,
        title_keywords: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        open_access_only: bool = True,
        has_full_text: bool = True,
    ) -> str:
        """Build Lucene query string.

        Args:
            author: Author name.
            keywords: Keywords to search anywhere.
            title_keywords: Keywords in title only.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            open_access_only: Only open access articles.
            has_full_text: Only articles with full-text.

        Returns:
            Lucene query string.
        """
        parts = []

        if author:
            parts.append(f'AUTH:"{author}"')

        if keywords:
            kw_parts = [f'"{kw}"' for kw in keywords]
            parts.append(f"({' OR '.join(kw_parts)})")

        if title_keywords:
            for kw in title_keywords:
                parts.append(f'TITLE:"{kw}"')

        if date_from or date_to:
            start = date_from or "*"
            end = date_to or "*"
            parts.append(f"FIRST_PDATE:[{start} TO {end}]")

        if open_access_only:
            parts.append("OPEN_ACCESS:Y")

        if has_full_text:
            parts.append("HAS_FT:Y")

        return " AND ".join(parts) if parts else "*"


def fetch_europepmc(
    query: str | None = None,
    author: str | None = None,
    keywords: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    pmcids: list[str] | None = None,
    output_dir: str | Path = "europepmc_output",
    workspace: Workspace | None = None,
    max_results: int = 100,
    open_access_only: bool = True,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Fetch Europe PMC articles and save as JATS.

    Pipeline:
    1. Search Europe PMC or use provided PMCIDs
    2. Filter for full-text availability
    3. Download JATS XML
    4. Validate and save

    Args:
        query: Raw Lucene query string (overrides other search params).
        author: Author name for search.
        keywords: Keywords for search.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        pmcids: Alternative - list of PMC IDs to fetch directly.
        output_dir: Output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        max_results: Maximum articles to fetch.
        open_access_only: Only fetch open access articles.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(pmcid, current, total).

    Returns:
        Statistics dict with:
        - source: "europepmc"
        - articles_found: Number from search
        - full_text_available: Number with full-text
        - fetched: Number downloaded
        - valid: Number passing validation
        - incomplete: Number incomplete
        - skipped: Number skipped (duplicates)
        - duplicates_skipped: Number of DOI duplicates (workspace mode)
        - errors: Number of errors
    """
    from .pmc import JATSValidator, save_pmc_article

    # Determine output path and search_id
    if workspace:
        search_id = workspace._get_next_search_id()
        output_path = workspace.path
    else:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        search_id = None

    # Initialize stats
    stats: dict[str, Any] = {
        "source": "europepmc",
        "articles_found": 0,
        "full_text_available": 0,
        "fetched": 0,
        "valid": 0,
        "incomplete": 0,
        "skipped": 0,
        "duplicates_skipped": 0,
        "errors": 0,
    }

    client = EuropePMCClient()

    # Get articles either by search or by PMCIDs
    if pmcids:
        # Direct PMCID lookup
        articles = []
        for pmcid in pmcids:
            article = client.get_by_pmcid(pmcid)
            if article:
                articles.append(article)
        stats["articles_found"] = len(articles)
    else:
        # Build and execute search
        if query is None:
            query = EuropePMCClient.build_query(
                author=author,
                keywords=keywords,
                date_from=date_from,
                date_to=date_to,
                open_access_only=open_access_only,
                has_full_text=True,
            )

        if verbose:
            logger.info("Query: %s", query)

        articles = list(client.iter_search(query, max_results=max_results))
        stats["articles_found"] = len(articles)

    if verbose:
        logger.info("Found %d articles", len(articles))

    # Filter for those with full-text in PMC
    fetchable = [a for a in articles if a.pmcid and a.has_full_text]
    stats["full_text_available"] = len(fetchable)

    if verbose:
        logger.info("%d have full-text available", len(fetchable))

    if not fetchable:
        return stats

    # Process articles
    validator = JATSValidator()
    total = len(fetchable)

    for i, article in enumerate(fetchable):
        # We know pmcid is not None because we filtered for it above
        if article.pmcid is None:
            continue  # Should never happen due to filter, but satisfies mypy
        article_pmcid: str = article.pmcid

        if progress_callback:
            progress_callback(article_pmcid, i, total)

        # Check for duplicate DOI in workspace
        if workspace and article.doi and workspace.has_doi(article.doi):
            logger.debug("Skipping duplicate DOI: %s", article.doi)
            stats["duplicates_skipped"] += 1
            continue

        try:
            # Download full-text XML
            xml_content = client.get_full_text_xml(article_pmcid)
            if xml_content is None:
                stats["errors"] += 1
                continue
            stats["fetched"] += 1

            # Validate content
            result = validator.validate(xml_content)
            is_valid = result.status.value == "valid"

            # Save to appropriate location
            if workspace:
                # Use workspace to save file (handles DOI indexing)
                workspace.add_file(
                    jats_content=xml_content,
                    doi=article.doi,
                    source="europepmc",
                    search_id=search_id or "",
                    is_valid=is_valid,
                    filename=f"{article_pmcid}.xml",
                )
            else:
                # Save with standard method
                _saved_path, result, _entry = save_pmc_article(
                    pmcid=article_pmcid,
                    xml_content=xml_content,
                    output_dir=output_path,
                    validator=validator,
                )

            if is_valid:
                stats["valid"] += 1
            else:
                stats["incomplete"] += 1

        except Exception as e:
            logger.error("Error processing %s: %s", article_pmcid, e)
            stats["errors"] += 1

    if verbose:
        logger.info(
            "Fetch complete: %d fetched, %d valid, %d errors",
            stats["fetched"],
            stats["valid"],
            stats["errors"],
        )

    return stats
