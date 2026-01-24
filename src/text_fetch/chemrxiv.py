"""ChemRxiv API client for preprint fetching."""

from __future__ import annotations

__all__ = [
    "CHEMRXIV_CATEGORIES",
    "ChemrxivArticle",
    "ChemrxivClient",
    "fetch_chemrxiv",
    "get_category_id",
    "get_category_ids",
]

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import requests

from .checkpoint import (
    FetchCheckpoint,
    clear_checkpoint,
    get_checkpoint_path,
    load_checkpoint_if_exists,
)
from .common import RateLimiter

if TYPE_CHECKING:
    from .workspace import Workspace

logger = logging.getLogger(__name__)

# ChemRxiv categories with their IDs
# Note: IDs may need verification against live API
CHEMRXIV_CATEGORIES: dict[str, int] = {
    "analytical_chemistry": 1,
    "biochemistry": 2,
    "biological_chemistry": 3,
    "catalysis": 4,
    "chemical_biology": 5,
    "chemical_engineering": 6,
    "chemical_physics": 7,
    "computational_chemistry": 8,
    "earth_space_chemistry": 9,
    "electrochemistry": 10,
    "energy": 11,
    "environmental_chemistry": 12,
    "inorganic_chemistry": 13,
    "materials_chemistry": 14,
    "medicinal_chemistry": 15,
    "nanoscience": 16,
    "organic_chemistry": 17,
    "organometallic_chemistry": 18,
    "physical_chemistry": 19,
    "polymer_chemistry": 20,
    "supramolecular_chemistry": 21,
    "theoretical_chemistry": 22,
}


def get_category_id(name: str) -> int | None:
    """Get category ID by name.

    Args:
        name: Category name (case-insensitive, spaces/underscores OK).

    Returns:
        Category ID or None if not found.
    """
    normalized = name.lower().replace(" ", "_").replace("-", "_")
    return CHEMRXIV_CATEGORIES.get(normalized)


def get_category_ids(names: list[str]) -> list[int]:
    """Get category IDs for a list of names.

    Args:
        names: List of category names.

    Returns:
        List of found category IDs.
    """
    ids = []
    for name in names:
        cat_id = get_category_id(name)
        if cat_id is not None:
            ids.append(cat_id)
    return ids


@dataclass
class ChemrxivArticle:
    """ChemRxiv article metadata."""

    item_id: str  # e.g., "item_2024-abc123"
    doi: str  # e.g., "10.26434/chemrxiv-2024-abc123"
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    subjects: list[str]
    published_date: datetime
    version: int = 1
    license: str | None = None
    pdf_url: str | None = None

    @property
    def id_short(self) -> str:
        """Short ID for filenames."""
        # "item_2024-abc123" -> "2024-abc123"
        return self.item_id.replace("item_", "")


class ChemrxivClient:
    """ChemRxiv API client with rate limiting."""

    BASE_URL = "https://chemrxiv.org/engage/chemrxiv/public-api/v1"

    # Be respectful - 1 request per second
    RATE_LIMIT = 1.0

    def __init__(self) -> None:
        """Initialize client."""
        self.limiter = RateLimiter(self.RATE_LIMIT)
        self.session = requests.Session()
        from . import __version__

        self.session.headers.update(
            {
                "User-Agent": f"text-fetch/{__version__} (scientific literature acquisition)",
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

    def search(
        self,
        term: str | None = None,
        category_ids: list[int] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 50,
        skip: int = 0,
    ) -> tuple[list[ChemrxivArticle], int]:
        """Search for articles.

        Args:
            term: Search query (searches title, abstract, authors).
            category_ids: Filter by category IDs.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            limit: Results per page (max 50).
            skip: Pagination offset.

        Returns:
            Tuple of (articles, total_count).
        """
        params: dict[str, Any] = {
            "limit": min(limit, 50),
            "skip": skip,
            "sort": "PUBLISHED_DATE_DESC",
        }

        if term:
            params["term"] = term
        if category_ids:
            params["categoryIds"] = ",".join(str(c) for c in category_ids)
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to

        data = self._request("/items", params)
        return self._parse_response(data)

    def iter_search(
        self,
        term: str | None = None,
        category_ids: list[int] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        max_results: int | None = None,
    ) -> Iterator[ChemrxivArticle]:
        """Iterate through all search results.

        Handles pagination automatically.

        Args:
            term: Search query.
            category_ids: Filter by category IDs.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            max_results: Maximum articles to yield.

        Yields:
            ChemrxivArticle objects.
        """
        skip = 0
        count = 0
        limit = 50

        while True:
            articles, total = self.search(
                term=term,
                category_ids=category_ids,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                skip=skip,
            )

            for article in articles:
                yield article
                count += 1
                if max_results and count >= max_results:
                    return

            if not articles or skip + len(articles) >= total:
                break
            skip += limit

    def get_by_id(self, item_id: str) -> ChemrxivArticle | None:
        """Fetch single article by item ID.

        Args:
            item_id: Article ID (e.g., "item_2024-abc123").

        Returns:
            ChemrxivArticle or None if not found.
        """
        # Normalize ID
        item_id = self.normalize_id(item_id)

        data = self._request(f"/items/{item_id}")
        if not data:
            return None

        return self._parse_item(data)

    def get_by_doi(self, doi: str) -> ChemrxivArticle | None:
        """Fetch single article by DOI.

        Args:
            doi: Article DOI (e.g., "10.26434/chemrxiv-2024-abc123").

        Returns:
            ChemrxivArticle or None if not found.
        """
        # Search by DOI - ChemRxiv search supports DOI
        articles, _ = self.search(term=doi, limit=1)
        for article in articles:
            if article.doi == doi:
                return article
        return None

    def download_pdf(self, article: ChemrxivArticle) -> bytes | None:
        """Download PDF for article.

        Args:
            article: Article with pdf_url.

        Returns:
            PDF bytes or None on failure.
        """
        if not article.pdf_url:
            logger.warning("No PDF URL for %s", article.item_id)
            return None

        self.limiter.wait()

        try:
            resp = self.session.get(article.pdf_url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as e:
            logger.warning("Failed to download PDF for %s: %s", article.item_id, e)
            return None

    def _parse_response(
        self, data: dict[str, Any] | None
    ) -> tuple[list[ChemrxivArticle], int]:
        """Parse API response into articles."""
        if not data:
            return [], 0

        total = data.get("totalCount", 0)
        articles = []

        for hit in data.get("itemHits", []):
            try:
                article = self._parse_item(hit.get("item", {}))
                if article:
                    articles.append(article)
            except Exception as e:
                logger.warning("Failed to parse item: %s", e)

        return articles, total

    def _parse_item(self, item: dict[str, Any]) -> ChemrxivArticle | None:
        """Parse single item from API response."""
        item_id = item.get("id")
        if not item_id:
            return None

        # Parse authors
        authors = []
        for author in item.get("authors", []):
            first = author.get("firstName", "")
            last = author.get("lastName", "")
            name = f"{first} {last}".strip()
            if name:
                authors.append(name)

        # Parse date
        date_str = item.get("publishedDate", "")
        try:
            iso_str = date_str.replace("Z", "+00:00")
            published_date = datetime.fromisoformat(iso_str)
        except ValueError:
            published_date = datetime.now()

        # Parse categories and subjects
        categories = [
            c.get("name", "") for c in item.get("categories", []) if c.get("name")
        ]
        subjects = [
            s.get("name", "") for s in item.get("subjects", []) if s.get("name")
        ]

        # Get PDF URL
        asset = item.get("asset", {})
        pdf_url = None
        original = asset.get("original", {})
        if original.get("url"):
            pdf_url = original["url"]

        # License
        license_info = item.get("license", {})
        license_name = license_info.get("name") if license_info else None

        return ChemrxivArticle(
            item_id=item_id,
            doi=item.get("doi", ""),
            title=item.get("title", ""),
            authors=authors,
            abstract=item.get("abstract", ""),
            categories=categories,
            subjects=subjects,
            published_date=published_date,
            version=item.get("version", 1),
            license=license_name,
            pdf_url=pdf_url,
        )

    @staticmethod
    def normalize_id(item_id: str) -> str:
        """Normalize item ID format.

        Handles:
            - item_2024-abc123
            - 2024-abc123
            - https://chemrxiv.org/.../item_2024-abc123

        Returns:
            Clean item ID (item_2024-abc123).
        """
        item_id = item_id.strip()

        # Extract ID from URL
        if "chemrxiv.org" in item_id:
            parts = item_id.split("/")
            for part in reversed(parts):
                if part.startswith("item_") or "202" in part:
                    item_id = part
                    break

        # Add prefix if missing
        if not item_id.startswith("item_"):
            item_id = f"item_{item_id}"

        return item_id


def fetch_chemrxiv(
    term: str | None = None,
    category_ids: list[int] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    item_ids: list[str] | None = None,
    output_dir: str | Path = "chemrxiv_output",
    workspace: Workspace | None = None,
    grobid_url: str | None = None,
    xslt_path: str | Path | None = None,
    max_results: int = 100,
    verbose: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
    resume: bool = False,
    update: bool = False,
) -> dict[str, Any]:
    """Fetch ChemRxiv articles and convert to JATS.

    Pipeline:
    1. Search ChemRxiv API
    2. Download PDFs
    3. Convert via GROBID → JATS
    4. Validate and save

    Args:
        term: Search query.
        category_ids: Filter by category IDs.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        item_ids: Alternative - list of item IDs to fetch.
        output_dir: Output directory (used if workspace is None).
        workspace: Optional workspace for deduplication and output.
        grobid_url: GROBID service URL.
        xslt_path: Path to tei2jats.xsl.
        max_results: Maximum articles.
        verbose: Enable verbose logging.
        progress_callback: Optional callback(item_id, current, total).
        resume: Resume from checkpoint if available.
        update: Only fetch papers since last fetch (requires workspace).

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

    # Handle update mode - adjust date_from based on last fetch
    effective_date_from = date_from
    if update and workspace:
        last_fetch = workspace.get_last_fetch_date("chemrxiv")
        if last_fetch:
            # Use last fetch date as start date
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
        "source": "chemrxiv",
        "articles_found": 0,
        "pdfs_downloaded": 0,
        "converted": 0,
        "valid": 0,
        "incomplete": 0,
        "skipped": 0,
        "duplicates_skipped": 0,
        "errors": 0,
        "resumed_from": 0,
    }

    # Initialize clients
    client = ChemrxivClient()

    # Get articles
    if item_ids:
        articles = []
        for item_id in item_ids:
            article = client.get_by_id(client.normalize_id(item_id))
            if article:
                articles.append(article)
    else:
        articles = list(
            client.iter_search(
                term=term,
                category_ids=category_ids,
                date_from=effective_date_from,
                date_to=date_to,
                max_results=max_results,
            )
        )

    stats["articles_found"] = len(articles)

    if verbose:
        logger.info("Found %d articles", len(articles))

    if not articles:
        # Update workspace source record even if no results
        if workspace:
            workspace.update_source_record("chemrxiv", 0)
        return stats

    # Build config for checkpoint
    fetch_config = {
        "term": term,
        "category_ids": category_ids,
        "date_from": effective_date_from,
        "date_to": date_to,
        "item_ids": item_ids,
        "max_results": max_results,
    }

    # Load or create checkpoint
    checkpoint: FetchCheckpoint | None = None
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
            source="chemrxiv",
            total_expected=len(articles),
            output_path=output_path,
        )
        checkpoint.reset_save_tracking()

    # Resolve XSLT path - use bundled package resource
    if xslt_path is None:
        from .grobid import get_default_xslt_path

        xslt_path = get_default_xslt_path()

    # Initialize GROBID
    grobid_client = GROBIDClient(url=grobid_url)
    if not grobid_client.is_available():
        msg = f"GROBID not available at {grobid_client.url}"
        raise RuntimeError(msg)

    # Process articles
    validator = JATSValidator()
    total = len(articles)

    for i, article in enumerate(articles):
        if progress_callback:
            progress_callback(article.item_id, i, total)

        # Skip if already completed in checkpoint
        if checkpoint.is_complete(article.item_id):
            stats["skipped"] += 1
            continue

        # Check for duplicate DOI in workspace
        if workspace and article.doi and workspace.has_doi(article.doi):
            logger.debug("Skipping duplicate DOI: %s", article.doi)
            workspace.record_duplicate_skip(article.doi)
            stats["duplicates_skipped"] += 1
            # Mark as complete in checkpoint to avoid retry
            checkpoint.mark_complete(article.item_id)
            continue

        try:
            # Download PDF
            pdf_bytes = client.download_pdf(article)
            if pdf_bytes is None:
                stats["errors"] += 1
                checkpoint.mark_failed(article.item_id, "Failed to download PDF")
                checkpoint.save_if_needed(checkpoint_path)
                continue
            stats["pdfs_downloaded"] += 1

            # Convert to JATS via GROBID
            jats = grobid_client.pdf_to_jats(pdf_bytes, xslt_path)
            if jats is None:
                stats["errors"] += 1
                checkpoint.mark_failed(article.item_id, "GROBID conversion failed")
                checkpoint.save_if_needed(checkpoint_path)
                continue
            stats["converted"] += 1

            # Validate content
            result = validator.validate(jats)
            is_valid = result.status.value == "valid"

            # Save to appropriate location
            if workspace:
                # Use workspace to save file (handles DOI indexing)
                workspace.add_file(
                    jats_content=jats,
                    doi=article.doi,
                    source="chemrxiv",
                    search_id=search_id or "",
                    is_valid=is_valid,
                    filename=f"chemrxiv_{article.id_short}.xml",
                )
            else:
                # Save with standard method
                article_id = f"chemrxiv:{article.id_short}"
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

            # Mark complete and save checkpoint periodically
            checkpoint.mark_complete(article.item_id)
            checkpoint.save_if_needed(checkpoint_path)

        except Exception as e:
            logger.error("Error processing %s: %s", article.item_id, e)
            stats["errors"] += 1
            checkpoint.mark_failed(article.item_id, str(e))
            checkpoint.save_if_needed(checkpoint_path)

    # Final checkpoint save and cleanup
    checkpoint.save(checkpoint_path)

    # Clear checkpoint on successful completion (all attempted)
    attempted = stats["converted"] + stats["errors"] + stats["duplicates_skipped"]
    if attempted >= len(articles) - stats["resumed_from"]:
        clear_checkpoint(output_path)
        if verbose:
            logger.info("Fetch complete, checkpoint cleared")

    # Update workspace source record only if no errors
    if workspace and stats["errors"] == 0:
        workspace.update_source_record("chemrxiv", stats["converted"])

    if verbose:
        logger.info(
            "Fetch complete: %d downloaded, %d converted, %d valid, %d errors",
            stats["pdfs_downloaded"],
            stats["converted"],
            stats["valid"],
            stats["errors"],
        )

    return stats
