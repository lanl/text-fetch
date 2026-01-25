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
    "ExpansionResult",
    "expand_papers",
    "fetch_europepmc",
]

import contextlib
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
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


@dataclass
class ExpansionResult:
    """Result of citation/reference expansion.

    Attributes:
        expanded_papers: Papers discovered through expansion, grouped by depth.
        config: Expansion configuration used.
        seed_coverage: Statistics about seed paper citation/reference availability.
        expansion_stats: Statistics about the expansion results.
        id_issues: Problems encountered with paper identifiers.
        layers: Summary of papers at each depth level.
    """

    expanded_papers: dict[int, list[dict]] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    seed_coverage: dict[str, Any] = field(default_factory=dict)
    expansion_stats: dict[str, Any] = field(default_factory=dict)
    id_issues: dict[str, list[str]] = field(default_factory=dict)
    layers: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total_expanded(self) -> int:
        """Total number of unique expanded papers."""
        return sum(len(papers) for papers in self.expanded_papers.values())

    @property
    def all_papers(self) -> list[dict]:
        """Flat list of all expanded papers."""
        result: list[dict] = []
        for papers in self.expanded_papers.values():
            result.extend(papers)
        return result


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
        from . import __version__

        self.session.headers.update(
            {
                "User-Agent": (
                    f"text-fetch/{__version__} (scientific literature acquisition)"
                ),
                "Accept": "application/json, application/xml",
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

        # PMC-source articles always have full-text (PMC doesn't accept without it)
        # but API sometimes returns hasFullText=null for PMC articles
        source = item.get("source", "")
        has_full_text = item.get("hasFullText") == "Y" or source == "PMC"

        return EuropePMCArticle(
            id=article_id,
            source=source,
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
            has_full_text=has_full_text,
        )

    def get_full_text_xml(self, pmcid: str) -> str | None:
        """Download full-text JATS XML for article.

        Args:
            pmcid: PMC ID (e.g., "PMC123456" or "123456").

        Returns:
            JATS XML string or None if not available.
        """
        # Normalize then strip prefix for API endpoint
        # API expects /PMC/{id}/fullTextXML where id is numeric (no PMC prefix)
        pmcid = self.normalize_pmcid(pmcid)
        pmcid_numeric = pmcid[3:]  # Strip "PMC" prefix

        # Endpoint: /{source}/{id}/fullTextXML
        endpoint = f"/PMC/{pmcid_numeric}/fullTextXML"
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

    def get_citations(
        self,
        source: str,
        identifier: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> tuple[list[dict], int]:
        """Get papers that cite the given paper.

        Args:
            source: Data source (MED, PMC, PPR, etc.).
            identifier: Identifier (PMID, PMCID without prefix, etc.).
            page: Page number (1-indexed).
            page_size: Results per page (max 1000).

        Returns:
            Tuple of (list of citation dicts, total count).
        """
        # Normalize identifier - remove PMC prefix if present for API call
        if source == "PMC" and identifier.upper().startswith("PMC"):
            identifier = identifier[3:]

        endpoint = f"/{source}/{identifier}/citations/{page}/{page_size}/json"
        data = self._request(endpoint)

        if not data:
            return [], 0

        citation_list = data.get("citationList", {})
        citations = citation_list.get("citation", [])
        # Handle case where API returns single citation as dict instead of list
        if isinstance(citations, dict):
            citations = [citations]

        total = data.get("hitCount", len(citations))
        return citations, total

    def get_references(
        self,
        source: str,
        identifier: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> tuple[list[dict], int]:
        """Get papers cited by the given paper (references).

        Args:
            source: Data source (MED, PMC, PPR, etc.).
            identifier: Identifier (PMID, PMCID without prefix, etc.).
            page: Page number (1-indexed).
            page_size: Results per page (max 1000).

        Returns:
            Tuple of (list of reference dicts, total count).
        """
        # Normalize identifier - remove PMC prefix if present for API call
        if source == "PMC" and identifier.upper().startswith("PMC"):
            identifier = identifier[3:]

        endpoint = f"/{source}/{identifier}/references/{page}/{page_size}/json"
        data = self._request(endpoint)

        if not data:
            return [], 0

        reference_list = data.get("referenceList", {})
        references = reference_list.get("reference", [])
        # Handle case where API returns single reference as dict instead of list
        if isinstance(references, dict):
            references = [references]

        total = data.get("hitCount", len(references))
        return references, total

    def get_all_citations(
        self,
        source: str,
        identifier: str,
        max_results: int | None = None,
    ) -> list[dict]:
        """Get all citations with automatic pagination.

        Args:
            source: Data source (MED, PMC, PPR, etc.).
            identifier: Identifier (PMID, PMCID without prefix, etc.).
            max_results: Optional cap on total results.

        Returns:
            List of all citation dicts.
        """
        all_citations: list[dict] = []
        page = 1
        page_size = 1000

        while True:
            citations, total = self.get_citations(source, identifier, page, page_size)

            if not citations:
                break

            all_citations.extend(citations)

            # Check if we've reached max_results
            if max_results and len(all_citations) >= max_results:
                all_citations = all_citations[:max_results]
                break

            # Check if we've fetched all available
            if len(all_citations) >= total:
                break

            page += 1

        return all_citations

    def get_all_references(
        self,
        source: str,
        identifier: str,
        max_results: int | None = None,
    ) -> list[dict]:
        """Get all references with automatic pagination.

        Args:
            source: Data source (MED, PMC, PPR, etc.).
            identifier: Identifier (PMID, PMCID without prefix, etc.).
            max_results: Optional cap on total results.

        Returns:
            List of all reference dicts.
        """
        all_references: list[dict] = []
        page = 1
        page_size = 1000

        while True:
            references, total = self.get_references(source, identifier, page, page_size)

            if not references:
                break

            all_references.extend(references)

            # Check if we've reached max_results
            if max_results and len(all_references) >= max_results:
                all_references = all_references[:max_results]
                break

            # Check if we've fetched all available
            if len(all_references) >= total:
                break

            page += 1

        return all_references

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


# =============================================================================
# Expansion Helper Functions
# =============================================================================


def _get_best_id(paper: dict) -> tuple[str | None, str | None]:
    """Extract best available identifier from paper metadata.

    Uses priority: PMCID > PMID > DOI for API lookups.

    Args:
        paper: Paper metadata dict with pmcid, pmid, and/or doi fields.

    Returns:
        (source, identifier) tuple for Europe PMC API, or (None, None).
    """
    pmcid = paper.get("pmcid")
    if pmcid:
        # Normalize PMCID - remove prefix for API call
        if pmcid.upper().startswith("PMC"):
            pmcid = pmcid[3:]
        return ("PMC", pmcid)

    pmid = paper.get("pmid") or paper.get("id")
    source = paper.get("source", "")
    if pmid and source == "MED":
        return ("MED", str(pmid))

    # DOI requires search lookup, not direct API call
    # Return None for now - could enhance later
    return (None, None)


def _get_canonical_key(paper: dict) -> str | None:
    """Get canonical key for deduplication.

    Uses priority: DOI (most universal) > PMCID > PMID.

    Args:
        paper: Paper metadata dict.

    Returns:
        Canonical key string or None if no usable ID.
    """
    doi = paper.get("doi")
    if doi:
        return f"doi:{doi.lower()}"

    pmcid = paper.get("pmcid")
    if pmcid:
        # Normalize PMCID
        pmcid_upper = pmcid.upper()
        if not pmcid_upper.startswith("PMC"):
            pmcid_upper = f"PMC{pmcid_upper}"
        return f"pmcid:{pmcid_upper}"

    pmid = paper.get("pmid") or paper.get("id")
    source = paper.get("source", "")
    if pmid and source == "MED":
        return f"pmid:{pmid}"

    return None


def _get_canonical_key_from_article(article: EuropePMCArticle) -> str | None:
    """Get canonical key from EuropePMCArticle object."""
    if article.doi:
        return f"doi:{article.doi.lower()}"
    if article.pmcid:
        return f"pmcid:{article.pmcid.upper()}"
    if article.pmid:
        return f"pmid:{article.pmid}"
    return None


def _article_to_dict(article: EuropePMCArticle) -> dict:
    """Convert EuropePMCArticle to dict for expansion processing."""
    return {
        "id": article.id,
        "source": article.source,
        "pmid": article.pmid,
        "pmcid": article.pmcid,
        "doi": article.doi,
        "title": article.title,
    }


# =============================================================================
# Expansion Function
# =============================================================================


def expand_papers(
    client: EuropePMCClient,
    seeds: list[EuropePMCArticle],
    expand_references: bool = False,
    expand_citations: bool = False,
    depth: int = 1,
    max_expansion: int | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> ExpansionResult:
    """Expand seed papers by following citation relationships.

    Uses breadth-first search to discover related papers through
    citation and reference links.

    Args:
        client: Europe PMC client instance.
        seeds: List of seed papers to expand from.
        expand_references: If True, follow references (papers seeds cite).
        expand_citations: If True, follow citations (papers citing seeds).
        depth: Number of expansion hops (1 = direct only).
        max_expansion: Optional cap on total expanded papers.
        progress_callback: Optional callback(stage, current, total).

    Returns:
        ExpansionResult with expanded papers and metadata.
    """
    from collections import deque

    # Track configuration
    config = {
        "expand_references": expand_references,
        "expand_citations": expand_citations,
        "depth": depth,
        "max_expansion": max_expansion,
    }

    # Initialize tracking
    seen_keys: set[str] = set()
    id_issues: dict[str, list[str]] = {
        "no_id": [],
        "lookup_failed": [],
    }

    # Add seeds to seen set
    seeds_with_citations = 0
    seeds_with_references = 0
    seeds_with_both = 0
    seeds_with_neither = 0

    for seed in seeds:
        key = _get_canonical_key_from_article(seed)
        if key:
            seen_keys.add(key)

    # Determine expansion directions
    directions: list[str] = []
    if expand_references:
        directions.append("references")
    if expand_citations:
        directions.append("citations")

    if not directions:
        # No expansion requested
        return ExpansionResult(
            expanded_papers={},
            config=config,
            seed_coverage={
                "total_seeds": len(seeds),
                "seeds_with_citations": 0,
                "seeds_with_references": 0,
                "seeds_with_both": 0,
                "seeds_with_neither": len(seeds),
                "citation_coverage_pct": 0.0,
                "reference_coverage_pct": 0.0,
            },
            expansion_stats={
                "references_found": 0,
                "citations_found": 0,
                "total_unique": 0,
                "duplicates_skipped": 0,
            },
            id_issues=id_issues,
            layers=[{"depth": 0, "type": "seed", "count": len(seeds)}],
        )

    # BFS expansion
    expanded_papers: dict[int, list[dict]] = {}
    total_refs_found = 0
    total_cites_found = 0
    duplicates_skipped = 0

    # Queue: (paper_dict, current_depth)
    queue: deque[tuple[dict, int]] = deque()

    # Initialize queue with seeds
    for seed in seeds:
        seed_dict = _article_to_dict(seed)
        queue.append((seed_dict, 0))

    processed_at_depth: dict[int, int] = {0: 0}
    total_seeds = len(seeds)

    while queue:
        paper, current_depth = queue.popleft()

        # Don't expand beyond max depth
        if current_depth >= depth:
            continue

        # Check max_expansion limit
        total_expanded = sum(len(p) for p in expanded_papers.values())
        if max_expansion and total_expanded >= max_expansion:
            break

        # Get best ID for API lookup
        source, identifier = _get_best_id(paper)
        if not source or not identifier:
            title = paper.get("title", "Unknown")[:50]
            id_issues["no_id"].append(title)
            continue

        # Track progress
        processed_at_depth[current_depth] = processed_at_depth.get(current_depth, 0) + 1
        if progress_callback and current_depth == 0:
            progress_callback("expanding", processed_at_depth[0], total_seeds)

        # Track seed coverage
        if current_depth == 0:
            has_cites = False
            has_refs = False

            if "citations" in directions:
                cites, _ = client.get_citations(source, identifier, page_size=1)
                has_cites = len(cites) > 0

            if "references" in directions:
                refs, _ = client.get_references(source, identifier, page_size=1)
                has_refs = len(refs) > 0

            if has_cites:
                seeds_with_citations += 1
            if has_refs:
                seeds_with_references += 1
            if has_cites and has_refs:
                seeds_with_both += 1
            if not has_cites and not has_refs:
                seeds_with_neither += 1

        # Get related papers
        next_depth = current_depth + 1
        if next_depth not in expanded_papers:
            expanded_papers[next_depth] = []

        for direction in directions:
            try:
                if direction == "citations":
                    related = client.get_all_citations(source, identifier)
                    total_cites_found += len(related)
                else:
                    related = client.get_all_references(source, identifier)
                    total_refs_found += len(related)

                for related_paper in related:
                    canonical_key = _get_canonical_key(related_paper)
                    if not canonical_key:
                        continue

                    if canonical_key in seen_keys:
                        duplicates_skipped += 1
                        continue

                    seen_keys.add(canonical_key)

                    # Check max_expansion
                    total_so_far = sum(len(p) for p in expanded_papers.values())
                    if max_expansion and total_so_far >= max_expansion:
                        break

                    # Add paper type annotation
                    related_paper["_expansion_type"] = direction
                    related_paper["_expansion_depth"] = next_depth
                    expanded_papers[next_depth].append(related_paper)

                    # Queue for further expansion if we have a usable ID
                    if _get_best_id(related_paper)[0] and next_depth < depth:
                        queue.append((related_paper, next_depth))

            except Exception as e:
                logger.warning(
                    "Failed to get %s for %s/%s: %s",
                    direction,
                    source,
                    identifier,
                    e,
                )
                id_issues["lookup_failed"].append(f"{source}/{identifier}")

    # Build layers summary
    layers: list[dict[str, Any]] = [{"depth": 0, "type": "seed", "count": len(seeds)}]
    for d in sorted(expanded_papers.keys()):
        papers_at_depth = expanded_papers[d]
        refs_at_depth = sum(
            1 for p in papers_at_depth if p.get("_expansion_type") == "references"
        )
        cites_at_depth = sum(
            1 for p in papers_at_depth if p.get("_expansion_type") == "citations"
        )
        if refs_at_depth > 0:
            layers.append({"depth": d, "type": "reference", "count": refs_at_depth})
        if cites_at_depth > 0:
            layers.append({"depth": d, "type": "citation", "count": cites_at_depth})

    # Calculate coverage percentages
    cite_pct = (seeds_with_citations / len(seeds) * 100) if seeds else 0.0
    ref_pct = (seeds_with_references / len(seeds) * 100) if seeds else 0.0

    return ExpansionResult(
        expanded_papers=expanded_papers,
        config=config,
        seed_coverage={
            "total_seeds": len(seeds),
            "seeds_with_citations": seeds_with_citations,
            "seeds_with_references": seeds_with_references,
            "seeds_with_both": seeds_with_both,
            "seeds_with_neither": seeds_with_neither,
            "citation_coverage_pct": round(cite_pct, 1),
            "reference_coverage_pct": round(ref_pct, 1),
        },
        expansion_stats={
            "references_found": total_refs_found,
            "citations_found": total_cites_found,
            "total_unique": sum(len(p) for p in expanded_papers.values()),
            "duplicates_skipped": duplicates_skipped,
        },
        id_issues=id_issues,
        layers=layers,
    )


# =============================================================================
# Fetch Function
# =============================================================================


def fetch_europepmc(
    query: str | None = None,
    author: str | None = None,
    keywords: list[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    pmcids: list[str] | None = None,
    output_dir: str | Path = "europepmc_output",
    workspace: Workspace | None = None,
    max_results: int | None = None,
    open_access_only: bool = True,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
    resume: bool = False,
    update: bool = False,
    email: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch Europe PMC articles and save as JATS.

    Pipeline:
    1. Search Europe PMC or use provided PMCIDs
    2. Filter for full-text availability
    3. Download JATS XML (uses NCBI for PMC-source articles)
    4. Validate and save

    Note: Europe PMC doesn't host full-text XML for PMC-source articles.
    For articles with source="PMC", this function uses NCBI's efetch API
    to download the full-text. This requires the email parameter.

    Args:
        query: Raw Lucene query string (overrides other search params).
        author: Author name for search.
        keywords: Keywords for search.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        pmcids: Alternative - list of PMC IDs to fetch directly.
        output_dir: Output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        max_results: Maximum articles to fetch (None = unlimited).
        open_access_only: Only fetch open access articles.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(pmcid, current, total).
        resume: Resume from checkpoint if available.
        update: Only fetch papers since last fetch (requires workspace).
        email: Email for NCBI API (required for PMC-source articles).
        api_key: Optional NCBI API key for higher rate limits.

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
        - resumed_from: Number of papers already completed (if resumed)
    """
    from .checkpoint import (
        FetchCheckpoint,
        clear_checkpoint,
        get_checkpoint_path,
        load_checkpoint_if_exists,
    )
    from .ncbi import NCBIClient
    from .pmc import JATSValidator, save_pmc_article

    # Determine output path and search_id
    if workspace:
        search_id = workspace._get_next_search_id()
        output_path = workspace.path
    else:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        search_id = None

    # Handle update mode - adjust date_from based on last fetch
    effective_date_from = date_from
    if update and workspace:
        last_fetch = workspace.get_last_fetch_date("europepmc")
        if last_fetch:
            # Use last fetch date as start date (subtract 1 day for safety)
            effective_date_from = last_fetch
            if verbose:
                logger.info("Update mode: fetching papers since %s", last_fetch)
        else:
            if verbose:
                logger.info(
                    "Update mode: no previous fetch, proceeding with full fetch"
                )

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
        "resumed_from": 0,
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
                date_from=effective_date_from,
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
        # Update workspace source record even if no results
        if workspace:
            workspace.update_source_record("europepmc", 0)
        return stats

    # Build config for checkpoint
    fetch_config = {
        "query": query,
        "author": author,
        "keywords": keywords,
        "date_from": effective_date_from,
        "date_to": date_to,
        "pmcids": pmcids,
        "max_results": max_results,
        "open_access_only": open_access_only,
    }

    # Load or create checkpoint
    checkpoint = None
    checkpoint_path = get_checkpoint_path(output_path)

    if resume:
        checkpoint = load_checkpoint_if_exists(output_path)
        if checkpoint:
            # Validate config hasn't changed
            if not checkpoint.validate_config(fetch_config):
                logger.warning("Config changed since checkpoint. Starting fresh.")
                checkpoint = None
            else:
                stats["resumed_from"] = len(checkpoint.completed)
                if verbose:
                    logger.info(
                        "Resuming from checkpoint: %d completed",
                        len(checkpoint.completed),
                    )

    if checkpoint is None:
        checkpoint = FetchCheckpoint.create(
            config=fetch_config,
            source="europepmc",
            total_expected=len(fetchable),
            output_path=output_path,
        )
        checkpoint.reset_save_tracking()

    # Check if any PMC-source articles exist (require email for NCBI download)
    pmc_source_articles = [a for a in fetchable if a.source == "PMC"]
    if pmc_source_articles and not email:
        logger.warning(
            "Found %d PMC-source articles but no email provided. "
            "PMC-source articles require NCBI API (--email). "
            "These articles will be skipped.",
            len(pmc_source_articles),
        )

    # Create NCBI client if needed (lazy initialization)
    ncbi_client: NCBIClient | None = None

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

        # Skip if already completed in checkpoint
        if checkpoint.is_complete(article_pmcid):
            stats["skipped"] += 1
            continue

        # Check for duplicate DOI in workspace
        if workspace and article.doi and workspace.has_doi(article.doi):
            logger.debug("Skipping duplicate DOI: %s", article.doi)
            workspace.record_duplicate_skip(article.doi)
            stats["duplicates_skipped"] += 1
            # Mark as complete in checkpoint to avoid retry
            checkpoint.mark_complete(article_pmcid)
            continue

        try:
            # Download full-text XML based on source
            # PMC-source articles: Europe PMC doesn't host their full-text,
            # so we must use NCBI's efetch API
            if article.source == "PMC":
                if not email:
                    # Skip PMC-source articles if no email (already warned above)
                    stats["skipped"] += 1
                    checkpoint.mark_failed(
                        article_pmcid,
                        "PMC-source requires --email for NCBI download",
                    )
                    checkpoint.save_if_needed(checkpoint_path)
                    continue

                # Initialize NCBI client on first use
                if ncbi_client is None:
                    ncbi_client = NCBIClient(email=email, api_key=api_key)
                    if verbose:
                        logger.info("Using NCBI for PMC-source article downloads")

                xml_content = ncbi_client.fetch_pmc_xml(article_pmcid)
            else:
                # Non-PMC sources (MED, PPR, etc.): use Europe PMC directly
                xml_content = client.get_full_text_xml(article_pmcid)

            if xml_content is None:
                stats["errors"] += 1
                checkpoint.mark_failed(article_pmcid, "Failed to fetch full-text XML")
                checkpoint.save_if_needed(checkpoint_path)
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

            # Mark complete and save checkpoint periodically
            checkpoint.mark_complete(article_pmcid)
            checkpoint.save_if_needed(checkpoint_path)

        except Exception as e:
            logger.error("Error processing %s: %s", article_pmcid, e)
            stats["errors"] += 1
            checkpoint.mark_failed(article_pmcid, str(e))
            checkpoint.save_if_needed(checkpoint_path)

    # Final checkpoint save and cleanup
    checkpoint.save(checkpoint_path)

    # Clear checkpoint on successful completion (all attempted)
    attempted = stats["fetched"] + stats["errors"] + stats["duplicates_skipped"]
    if attempted >= len(fetchable) - stats["resumed_from"]:
        clear_checkpoint(output_path)
        if verbose:
            logger.info("Fetch complete, checkpoint cleared")

    # Update workspace source record only if no errors
    if workspace and stats["errors"] == 0:
        workspace.update_source_record(
            "europepmc",
            stats["fetched"],
        )

    if verbose:
        logger.info(
            "Fetch complete: %d fetched, %d valid, %d errors",
            stats["fetched"],
            stats["valid"],
            stats["errors"],
        )

    return stats
