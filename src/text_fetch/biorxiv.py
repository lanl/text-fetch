"""bioRxiv/medRxiv API client for preprint fetching."""

from __future__ import annotations

__all__ = [
    "BIORXIV_CATEGORIES",
    "MEDRXIV_CATEGORIES",
    "BiorxivArticle",
    "BiorxivClient",
    "fetch_biorxiv",
    "fetch_medrxiv",
]

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import requests

from .common import RateLimiter

if TYPE_CHECKING:
    from collections.abc import Callable

    from .workspace import Workspace

logger = logging.getLogger(__name__)

Server = Literal["biorxiv", "medrxiv"]

# bioRxiv categories (use underscore for spaces in API)
BIORXIV_CATEGORIES = [
    "animal_behavior_and_cognition",
    "biochemistry",
    "bioengineering",
    "bioinformatics",
    "biophysics",
    "cancer_biology",
    "cell_biology",
    "clinical_trials",
    "developmental_biology",
    "ecology",
    "epidemiology",
    "evolutionary_biology",
    "genetics",
    "genomics",
    "immunology",
    "microbiology",
    "molecular_biology",
    "neuroscience",
    "paleontology",
    "pathology",
    "pharmacology_and_toxicology",
    "physiology",
    "plant_biology",
    "scientific_communication_and_education",
    "synthetic_biology",
    "systems_biology",
    "zoology",
]

# medRxiv categories
MEDRXIV_CATEGORIES = [
    "addiction_medicine",
    "allergy_and_immunology",
    "anesthesia",
    "cardiovascular_medicine",
    "dentistry_and_oral_medicine",
    "dermatology",
    "emergency_medicine",
    "endocrinology",
    "epidemiology",
    "forensic_medicine",
    "gastroenterology",
    "genetic_and_genomic_medicine",
    "geriatric_medicine",
    "health_economics",
    "health_informatics",
    "health_policy",
    "health_systems_and_quality_improvement",
    "hematology",
    "hiv_aids",
    "infectious_diseases",
    "intensive_care_and_critical_care_medicine",
    "medical_education",
    "medical_ethics",
    "nephrology",
    "neurology",
    "nursing",
    "nutrition",
    "obstetrics_and_gynecology",
    "occupational_and_environmental_health",
    "oncology",
    "ophthalmology",
    "orthopedics",
    "otolaryngology",
    "pain_medicine",
    "palliative_medicine",
    "pathology",
    "pediatrics",
    "pharmacology_and_therapeutics",
    "primary_care_research",
    "psychiatry_and_clinical_psychology",
    "public_and_global_health",
    "radiology_and_imaging",
    "rehabilitation_medicine_and_physical_therapy",
    "respiratory_medicine",
    "rheumatology",
    "sexual_and_reproductive_health",
    "sports_medicine",
    "surgery",
    "toxicology",
    "transplantation",
    "urology",
]


@dataclass
class BiorxivArticle:
    """bioRxiv/medRxiv article metadata."""

    doi: str  # e.g., "10.1101/2024.01.15.123456"
    title: str
    authors: list[str]
    abstract: str
    category: str
    date: datetime
    version: int = 1
    license: str | None = None
    jatsxml_url: str | None = None  # Direct JATS download URL
    server: Server = "biorxiv"
    published_doi: str | None = None  # If published in journal

    @property
    def pdf_url(self) -> str:
        """Construct PDF download URL."""
        return (
            f"https://www.{self.server}.org/content/{self.doi}v{self.version}.full.pdf"
        )

    @property
    def id_short(self) -> str:
        """Short ID for filenames.

        "10.1101/2024.01.15.123456" -> "2024.01.15.123456"
        """
        return self.doi.replace("10.1101/", "")


class BiorxivClient:
    """bioRxiv/medRxiv API client with rate limiting.

    Both servers share the same API at api.biorxiv.org.
    """

    BASE_URL = "https://api.biorxiv.org"

    # Be respectful - 1 request per second
    RATE_LIMIT = 1.0

    def __init__(self, server: Server = "biorxiv") -> None:
        """Initialize client.

        Args:
            server: "biorxiv" or "medrxiv".
        """
        self.server = server
        self.limiter = RateLimiter(self.RATE_LIMIT)
        self.session = requests.Session()
        from . import __version__

        self.session.headers.update(
            {
                "User-Agent": f"text-fetch/{__version__} (scientific literature acquisition)",
            }
        )

    def _request(self, endpoint: str) -> dict[str, Any] | None:
        """Make API request with rate limiting.

        Args:
            endpoint: API endpoint path.

        Returns:
            JSON response dict or None on failure.
        """
        self.limiter.wait()
        url = f"{self.BASE_URL}{endpoint}"

        try:
            resp = self.session.get(url, timeout=30)
            resp.raise_for_status()
            result: dict[str, Any] = resp.json()
            return result
        except requests.RequestException as e:
            logger.error("API request failed: %s - %s", url, e)
            return None
        except ValueError as e:
            logger.error("Invalid JSON response: %s", e)
            return None

    def get_recent(
        self,
        days: int = 30,
        category: str | None = None,
        cursor: int = 0,
    ) -> tuple[list[BiorxivArticle], int | None]:
        """Fetch recent articles.

        Args:
            days: Number of recent days.
            category: Optional category filter (use underscore for spaces).
            cursor: Pagination cursor.

        Returns:
            Tuple of (articles, next_cursor). next_cursor is None if no more pages.
        """
        endpoint = f"/details/{self.server}/d{days}/{cursor}"
        if category:
            endpoint += f"?category={category.replace(' ', '_')}"

        data = self._request(endpoint)
        return self._parse_response(data)

    def get_by_date_range(
        self,
        start_date: str,
        end_date: str,
        category: str | None = None,
        cursor: int = 0,
    ) -> tuple[list[BiorxivArticle], int | None]:
        """Fetch articles by date range.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            category: Optional category filter.
            cursor: Pagination cursor.

        Returns:
            Tuple of (articles, next_cursor).
        """
        endpoint = f"/details/{self.server}/{start_date}/{end_date}/{cursor}"
        if category:
            endpoint += f"?category={category.replace(' ', '_')}"

        data = self._request(endpoint)
        return self._parse_response(data)

    def get_by_doi(self, doi: str) -> BiorxivArticle | None:
        """Fetch single article by DOI.

        Args:
            doi: Article DOI (e.g., "10.1101/2024.01.15.123456").

        Returns:
            BiorxivArticle or None if not found.
        """
        endpoint = f"/details/{self.server}/{doi}/na"
        data = self._request(endpoint)

        if not data:
            return None

        articles, _ = self._parse_response(data)
        return articles[0] if articles else None

    def get_by_dois(self, dois: list[str]) -> list[BiorxivArticle]:
        """Fetch multiple articles by DOI.

        Args:
            dois: List of DOIs.

        Returns:
            List of found articles.
        """
        articles = []
        for doi in dois:
            article = self.get_by_doi(doi)
            if article:
                articles.append(article)
        return articles

    def _parse_response(
        self, data: dict[str, Any] | None
    ) -> tuple[list[BiorxivArticle], int | None]:
        """Parse API response into articles.

        Returns:
            Tuple of (articles, next_cursor).
        """
        if not data:
            return [], None

        articles = []
        collection = data.get("collection", [])

        for item in collection:
            try:
                article = self._parse_item(item)
                if article:
                    articles.append(article)
            except Exception as e:
                logger.warning("Failed to parse item: %s", e)

        # Extract next cursor from messages
        next_cursor = None
        messages = data.get("messages", [])
        if messages:
            msg = messages[0]
            total = msg.get("total", 0)
            current_cursor = int(msg.get("cursor", 0))
            if current_cursor < total:
                next_cursor = current_cursor

        return articles, next_cursor

    def _parse_item(self, item: dict[str, Any]) -> BiorxivArticle | None:
        """Parse single item from API response."""
        doi = item.get("doi")
        if not doi:
            return None

        # Parse authors (semicolon-separated)
        authors_str = item.get("authors", "")
        authors = [a.strip() for a in authors_str.split(";") if a.strip()]

        # Parse date
        date_str = item.get("date", "")
        try:
            date = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            date = datetime.now()

        # Version
        version = int(item.get("version", 1))

        # Published DOI (if not "NA")
        published = item.get("published")
        published_doi = published if published and published != "NA" else None

        return BiorxivArticle(
            doi=doi,
            title=item.get("title", ""),
            authors=authors,
            abstract=item.get("abstract", ""),
            category=item.get("category", ""),
            date=date,
            version=version,
            license=item.get("license"),
            jatsxml_url=item.get("jatsxml"),
            server=self.server,
            published_doi=published_doi,
        )

    def iter_by_date_range(
        self,
        start_date: str,
        end_date: str,
        category: str | None = None,
        max_results: int | None = None,
    ) -> Iterator[BiorxivArticle]:
        """Iterate through all articles in date range.

        Handles pagination automatically.

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            category: Optional category filter.
            max_results: Maximum articles to yield.

        Yields:
            BiorxivArticle objects.
        """
        cursor = 0
        count = 0

        while True:
            articles, next_cursor = self.get_by_date_range(
                start_date, end_date, category, cursor
            )

            for article in articles:
                yield article
                count += 1
                if max_results and count >= max_results:
                    return

            if next_cursor is None or not articles:
                break
            cursor = next_cursor

    def search(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        category: str | None = None,
        days: int | None = None,
        max_results: int = 100,
    ) -> list[BiorxivArticle]:
        """Search for articles.

        Either provide date range OR days (for recent articles).

        Args:
            start_date: Start date (YYYY-MM-DD).
            end_date: End date (YYYY-MM-DD).
            category: Category filter.
            days: Alternative to date range - get N recent days.
            max_results: Maximum results.

        Returns:
            List of matching articles.
        """
        if days:
            articles, _ = self.get_recent(days, category)
            return articles[:max_results]

        if not start_date or not end_date:
            # Default to last 30 days
            end = datetime.now()
            start = end - timedelta(days=30)
            start_date = start.strftime("%Y-%m-%d")
            end_date = end.strftime("%Y-%m-%d")

        return list(
            self.iter_by_date_range(start_date, end_date, category, max_results)
        )

    def download_jats(self, article: BiorxivArticle) -> str | None:
        """Download JATS XML for article.

        Args:
            article: Article with jatsxml_url.

        Returns:
            JATS XML string or None on failure.
        """
        if not article.jatsxml_url:
            logger.debug("No JATS URL for %s", article.doi)
            return None

        self.limiter.wait()

        try:
            resp = self.session.get(article.jatsxml_url, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            logger.warning("Failed to download JATS for %s: %s", article.doi, e)
            return None

    def download_pdf(self, article: BiorxivArticle) -> bytes | None:
        """Download PDF for article.

        Args:
            article: Article to download.

        Returns:
            PDF bytes or None on failure.
        """
        self.limiter.wait()

        try:
            resp = self.session.get(article.pdf_url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            logger.warning("Failed to download PDF for %s: %s", article.doi, e)
            return None

    @staticmethod
    def normalize_doi(doi: str) -> str:
        """Normalize DOI format.

        Handles:
        - https://doi.org/10.1101/...
        - doi:10.1101/...
        - 10.1101/...

        Returns:
            Clean DOI (10.1101/...).
        """
        doi = doi.strip()
        # Remove URL prefix
        for prefix in ["https://doi.org/", "http://doi.org/", "doi:"]:
            if doi.lower().startswith(prefix.lower()):
                doi = doi[len(prefix) :]
        return doi


def _fetch_preprints(
    server: Server,
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    days: int | None = None,
    dois: list[str] | None = None,
    output_dir: str | Path = "output",
    workspace: Workspace | None = None,
    grobid_url: str | None = None,
    xslt_path: str | Path | None = None,
    max_results: int = 100,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Internal function to fetch preprints from bioRxiv or medRxiv.

    Pipeline:
    1. Search API
    2. Download JATS directly (preferred)
    3. Fall back to PDF→GROBID→JATS if no JATS available
    4. Validate and save

    Args:
        server: "biorxiv" or "medrxiv".
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        category: Category filter.
        days: Alternative - recent N days.
        dois: Alternative - list of DOIs to fetch.
        output_dir: Output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        grobid_url: GROBID service URL (for PDF fallback).
        xslt_path: Path to tei2jats.xsl.
        max_results: Maximum articles.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(doi, current, total).

    Returns:
        Statistics dict.
    """
    from .grobid import GROBIDClient
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
        "server": server,
        "articles_found": 0,
        "jats_direct": 0,
        "pdf_converted": 0,
        "valid": 0,
        "incomplete": 0,
        "duplicates_skipped": 0,
        "errors": 0,
    }

    # Initialize clients
    client = BiorxivClient(server=server)
    grobid_client = None

    # Get articles
    if dois:
        articles = client.get_by_dois([client.normalize_doi(d) for d in dois])
    else:
        articles = client.search(
            start_date=start_date,
            end_date=end_date,
            category=category,
            days=days,
            max_results=max_results,
        )

    stats["articles_found"] = len(articles)

    if verbose:
        logger.info("Found %d articles", len(articles))

    if not articles:
        return stats

    # Resolve XSLT path for GROBID fallback - use bundled package resource
    if xslt_path is None:
        from .grobid import get_default_xslt_path

        xslt_path = get_default_xslt_path()

    # Process articles
    validator = JATSValidator()
    total = len(articles)

    for i, article in enumerate(articles):
        if progress_callback:
            progress_callback(article.doi, i, total)

        # Check for duplicate DOI in workspace
        if workspace and workspace.has_doi(article.doi):
            logger.debug("Skipping duplicate DOI: %s", article.doi)
            stats["duplicates_skipped"] += 1
            continue

        try:
            jats = None

            # Try direct JATS download first
            if article.jatsxml_url:
                jats = client.download_jats(article)
                if jats:
                    stats["jats_direct"] += 1

            # Fall back to PDF→GROBID
            if jats is None and xslt_path:
                if grobid_client is None:
                    grobid_client = GROBIDClient(url=grobid_url)
                    if not grobid_client.is_available():
                        logger.warning("GROBID not available, skipping PDF fallback")
                        grobid_client = None

                if grobid_client:
                    pdf_bytes = client.download_pdf(article)
                    if pdf_bytes:
                        jats = grobid_client.pdf_to_jats(pdf_bytes, xslt_path)
                        if jats:
                            stats["pdf_converted"] += 1

            if jats is None:
                stats["errors"] += 1
                continue

            # Validate content
            result = validator.validate(jats)
            is_valid = result.status.value == "valid"

            # Save to appropriate location
            if workspace:
                # Use workspace to save file (handles DOI indexing)
                article_id = f"{server}_{article.id_short}"
                workspace.add_file(
                    jats_content=jats,
                    doi=article.doi,
                    source=server,
                    search_id=search_id or "",
                    is_valid=is_valid,
                    filename=f"{article_id}.xml",
                )
            else:
                # Save with standard method
                article_id = f"{server}:{article.id_short}"
                _saved_path, result, _entry = save_pmc_article(
                    pmcid=article_id,
                    xml_content=jats,
                    output_dir=output_path,
                    validator=validator,
                )

            if is_valid:
                stats["valid"] += 1
            else:
                stats["incomplete"] += 1

        except Exception as e:
            logger.error("Error processing %s: %s", article.doi, e)
            stats["errors"] += 1

    if verbose:
        logger.info(
            "Fetch complete: %d direct JATS, %d via GROBID, %d valid, %d errors",
            stats["jats_direct"],
            stats["pdf_converted"],
            stats["valid"],
            stats["errors"],
        )

    return stats


def fetch_biorxiv(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    days: int | None = None,
    dois: list[str] | None = None,
    output_dir: str | Path = "biorxiv_output",
    workspace: Workspace | None = None,
    grobid_url: str | None = None,
    xslt_path: str | Path | None = None,
    max_results: int = 100,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Fetch bioRxiv articles and save as JATS.

    Pipeline:
    1. Search bioRxiv API
    2. Download JATS directly (preferred)
    3. Fall back to PDF→GROBID→JATS if no JATS available
    4. Validate and save

    Args:
        start_date: Start date (YYYY-MM-DD).
        end_date: End date (YYYY-MM-DD).
        category: Category filter.
        days: Alternative - recent N days.
        dois: Alternative - list of DOIs to fetch.
        output_dir: Output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        grobid_url: GROBID service URL (for PDF fallback).
        xslt_path: Path to tei2jats.xsl.
        max_results: Maximum articles.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(doi, current, total).

    Returns:
        Statistics dict.
    """
    return _fetch_preprints(
        server="biorxiv",
        start_date=start_date,
        end_date=end_date,
        category=category,
        days=days,
        dois=dois,
        output_dir=output_dir,
        workspace=workspace,
        grobid_url=grobid_url,
        xslt_path=xslt_path,
        max_results=max_results,
        verbose=verbose,
        progress_callback=progress_callback,
    )


def fetch_medrxiv(
    start_date: str | None = None,
    end_date: str | None = None,
    category: str | None = None,
    days: int | None = None,
    dois: list[str] | None = None,
    output_dir: str | Path = "medrxiv_output",
    workspace: Workspace | None = None,
    grobid_url: str | None = None,
    xslt_path: str | Path | None = None,
    max_results: int = 100,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Fetch medRxiv articles and save as JATS.

    See fetch_biorxiv for full documentation.
    """
    return _fetch_preprints(
        server="medrxiv",
        start_date=start_date,
        end_date=end_date,
        category=category,
        days=days,
        dois=dois,
        output_dir=output_dir,
        workspace=workspace,
        grobid_url=grobid_url,
        xslt_path=xslt_path,
        max_results=max_results,
        verbose=verbose,
        progress_callback=progress_callback,
    )
