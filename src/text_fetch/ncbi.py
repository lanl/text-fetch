"""NCBI E-utilities wrapper.

Provides a rate-limited client for interacting with NCBI E-utilities API,
including ESearch, ID conversion, and PMC OA retrieval.
"""

from __future__ import annotations

__all__ = [
    "NCBIClient",
    "NCBIError",
    "NCBIRateLimitError",
    "NCBIRequestError",
]

import logging
import time
from typing import Any

import requests

from text_fetch.common import RateLimiter

logger = logging.getLogger(__name__)


class NCBIError(Exception):
    """Base exception for NCBI API errors."""

    pass


class NCBIRateLimitError(NCBIError):
    """Raised when NCBI rate limit is exceeded."""

    pass


class NCBIRequestError(NCBIError):
    """Raised when an NCBI API request fails."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class NCBIClient:
    """NCBI E-utilities API client with rate limiting.

    Handles rate limiting according to NCBI guidelines:
    - Without API key: max 3 requests/second
    - With API key: max 10 requests/second

    Args:
        email: Required email for NCBI API identification.
        api_key: Optional NCBI API key for higher rate limits.
        tool: Tool name for NCBI identification (default: "text-fetch").
        max_retries: Maximum number of retry attempts for failed requests.
        retry_delay: Initial delay in seconds between retries (exponential backoff).
        timeout: Request timeout in seconds.

    Example:
        >>> client = NCBIClient(email="user@example.com")
        >>> pmids = client.esearch("hlavacek ws[author]")
    """

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    ID_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"

    def __init__(
        self,
        email: str,
        api_key: str | None = None,
        tool: str = "text-fetch",
        max_retries: int = 3,
        retry_delay: float = 1.0,
        timeout: float = 30.0,
    ) -> None:
        if not email:
            raise ValueError("Email is required for NCBI API access")

        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout

        # NCBI rate limits: 3/sec without key, 10/sec with key
        # We use slightly lower values to be safe
        rate = 9.0 if api_key else 3.0
        self.limiter = RateLimiter(rate)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": f"{tool}/1.0 ({email})",
            }
        )

    def _base_params(self) -> dict[str, str]:
        """Return base parameters required for all NCBI requests."""
        params: dict[str, str] = {
            "email": self.email,
            "tool": self.tool,
        }
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _request(
        self,
        endpoint: str,
        params: dict[str, Any],
        base_url: str | None = None,
    ) -> dict[str, Any]:
        """Make rate-limited request to NCBI.

        Args:
            endpoint: API endpoint (e.g., "esearch.fcgi").
            params: Request parameters.
            base_url: Optional base URL override (for ID converter, etc.).

        Returns:
            Parsed JSON response as a dictionary.

        Raises:
            NCBIRequestError: If the request fails after all retries.
            NCBIRateLimitError: If rate limit is exceeded.
        """
        url = f"{base_url or self.BASE_URL}/{endpoint}"
        all_params = {**self._base_params(), **params}

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self.limiter.wait()

            try:
                logger.debug(
                    "NCBI request: %s (attempt %d/%d)",
                    endpoint,
                    attempt + 1,
                    self.max_retries + 1,
                )
                response = self.session.get(
                    url,
                    params=all_params,
                    timeout=self.timeout,
                )

                # Check for rate limiting (HTTP 429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        "NCBI rate limit hit, waiting %d seconds", retry_after
                    )
                    time.sleep(retry_after)
                    continue

                # Check for server errors (5xx) - retry
                if response.status_code >= 500:
                    logger.warning(
                        "NCBI server error %d, retrying...", response.status_code
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay * (2**attempt))
                        continue
                    raise NCBIRequestError(
                        f"Server error: {response.status_code}",
                        status_code=response.status_code,
                    )

                # Raise for client errors (4xx)
                response.raise_for_status()

                # Parse JSON response
                data: dict[str, Any] = response.json()
                return data

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(
                    "Request timeout (attempt %d/%d)", attempt + 1, self.max_retries + 1
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue

            except requests.exceptions.ConnectionError as e:
                last_error = e
                logger.warning(
                    "Connection error (attempt %d/%d)",
                    attempt + 1,
                    self.max_retries + 1,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue

            except requests.exceptions.HTTPError as e:
                raise NCBIRequestError(
                    f"HTTP error: {e}",
                    status_code=e.response.status_code if e.response else None,
                ) from e

            except requests.exceptions.JSONDecodeError as e:
                raise NCBIRequestError(f"Invalid JSON response: {e}") from e

        # All retries exhausted
        raise NCBIRequestError(
            f"Request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def _request_xml(
        self,
        endpoint: str,
        params: dict[str, Any],
        base_url: str | None = None,
    ) -> str:
        """Make rate-limited request expecting XML response.

        Args:
            endpoint: API endpoint.
            params: Request parameters.
            base_url: Optional base URL override.

        Returns:
            Raw XML response as string.

        Raises:
            NCBIRequestError: If the request fails after all retries.
        """
        url = f"{base_url or self.BASE_URL}/{endpoint}"
        all_params = {**self._base_params(), **params}

        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            self.limiter.wait()

            try:
                logger.debug(
                    "NCBI XML request: %s (attempt %d/%d)",
                    endpoint,
                    attempt + 1,
                    self.max_retries + 1,
                )
                response = self.session.get(
                    url,
                    params=all_params,
                    timeout=self.timeout,
                )

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 60))
                    logger.warning(
                        "NCBI rate limit hit, waiting %d seconds", retry_after
                    )
                    time.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    logger.warning(
                        "NCBI server error %d, retrying...", response.status_code
                    )
                    if attempt < self.max_retries:
                        time.sleep(self.retry_delay * (2**attempt))
                        continue
                    raise NCBIRequestError(
                        f"Server error: {response.status_code}",
                        status_code=response.status_code,
                    )

                response.raise_for_status()
                return response.text

            except requests.exceptions.Timeout as e:
                last_error = e
                logger.warning(
                    "Request timeout (attempt %d/%d)", attempt + 1, self.max_retries + 1
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue

            except requests.exceptions.ConnectionError as e:
                last_error = e
                logger.warning(
                    "Connection error (attempt %d/%d)",
                    attempt + 1,
                    self.max_retries + 1,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay * (2**attempt))
                    continue

            except requests.exceptions.HTTPError as e:
                raise NCBIRequestError(
                    f"HTTP error: {e}",
                    status_code=e.response.status_code if e.response else None,
                ) from e

        raise NCBIRequestError(
            f"Request failed after {self.max_retries + 1} attempts: {last_error}"
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> NCBIClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def esearch(
        self,
        query: str,
        db: str = "pubmed",
        max_results: int = 10000,
        use_history: bool = False,
    ) -> dict[str, Any]:
        """Search a database and return matching IDs.

        Args:
            query: Search query using PubMed query syntax.
                   Examples: "hlavacek ws[author]", "systems biology[tiab]"
            db: Database to search (default: "pubmed").
            max_results: Maximum number of results to return (default: 10000).
            use_history: If True, store results on server for later retrieval.

        Returns:
            Dictionary with search results containing:
            - idlist: List of matching IDs (PMIDs for pubmed)
            - count: Total number of matches (may exceed max_results)
            - querytranslation: How NCBI interpreted the query
            - webenv, querykey: For history-based retrieval (if use_history=True)

        Example:
            >>> client = NCBIClient(email="user@example.com")
            >>> result = client.esearch("hlavacek ws[author]")
            >>> pmids = result["idlist"]
            >>> print(f"Found {result['count']} papers, retrieved {len(pmids)}")
        """
        params: dict[str, Any] = {
            "db": db,
            "term": query,
            "retmax": max_results,
            "retmode": "json",
        }

        if use_history:
            params["usehistory"] = "y"

        response = self._request("esearch.fcgi", params)

        # Extract esearchresult from response
        result = response.get("esearchresult", {})

        # Normalize the response structure
        return {
            "idlist": result.get("idlist", []),
            "count": int(result.get("count", 0)),
            "querytranslation": result.get("querytranslation", ""),
            "webenv": result.get("webenv", ""),
            "querykey": result.get("querykey", ""),
        }

    def esearch_ids(
        self,
        query: str,
        db: str = "pubmed",
        max_results: int = 10000,
    ) -> list[str]:
        """Search and return just the list of IDs.

        Convenience method that wraps esearch() and returns only the ID list.

        Args:
            query: Search query using PubMed query syntax.
            db: Database to search (default: "pubmed").
            max_results: Maximum number of results to return.

        Returns:
            List of matching IDs (PMIDs for pubmed database).

        Example:
            >>> client = NCBIClient(email="user@example.com")
            >>> pmids = client.esearch_ids("hlavacek ws[author]")
            >>> print(f"Found {len(pmids)} papers")
        """
        result = self.esearch(query, db=db, max_results=max_results)
        idlist: list[str] = result["idlist"]
        return idlist

    def convert_ids(
        self,
        ids: list[str],
        id_type: str = "pmid",
    ) -> dict[str, str | None]:
        """Convert PMIDs to PMCIDs or vice versa.

        Uses the NCBI ID Converter service to map between identifiers.
        Only returns entries that have corresponding PMC full-text.

        Args:
            ids: List of IDs to convert (PMIDs by default).
            id_type: Type of input IDs ("pmid", "pmcid", or "doi").

        Returns:
            Dictionary mapping input IDs to PMCIDs.
            Value is None if no PMCID exists for that ID.
            Only PMIDs with PMC full-text will have non-None values.

        Example:
            >>> client = NCBIClient(email="user@example.com")
            >>> mapping = client.convert_ids(["12345", "67890"])
            >>> for pmid, pmcid in mapping.items():
            ...     if pmcid:
            ...         print(f"PMID {pmid} -> {pmcid}")
        """
        if not ids:
            return {}

        # Process in batches of 200 (API limit)
        batch_size = 200
        results: dict[str, str | None] = {}

        for i in range(0, len(ids), batch_size):
            batch = ids[i : i + batch_size]
            batch_results = self._convert_ids_batch(batch, id_type)
            results.update(batch_results)

        return results

    def _convert_ids_batch(
        self,
        ids: list[str],
        id_type: str,
    ) -> dict[str, str | None]:
        """Convert a single batch of IDs (internal method).

        Args:
            ids: List of IDs (max 200).
            id_type: Type of input IDs.

        Returns:
            Dictionary mapping input IDs to PMCIDs.
        """
        # ID converter uses a different URL and format
        params: dict[str, Any] = {
            "ids": ",".join(ids),
            "idtype": id_type,
            "format": "json",
        }

        response = self._request(
            "",
            params,
            base_url=self.ID_CONVERTER_URL.rstrip("/"),
        )

        results: dict[str, str | None] = {id_: None for id_ in ids}

        # Parse the response
        records = response.get("records", [])
        for record in records:
            # Get the input ID
            if id_type == "pmid":
                input_id = record.get("pmid")
            elif id_type == "doi":
                input_id = record.get("doi")
            else:
                input_id = record.get("pmcid")

            if input_id and input_id in results:
                # Get PMCID if available
                pmcid = record.get("pmcid")
                if pmcid:
                    results[input_id] = pmcid

        return results

    def get_pmcids(self, pmids: list[str]) -> dict[str, str]:
        """Get PMCIDs for a list of PMIDs (only those with PMC full-text).

        Convenience method that filters out PMIDs without PMCIDs.

        Args:
            pmids: List of PubMed IDs.

        Returns:
            Dictionary mapping PMIDs to PMCIDs (only includes PMIDs
            that have corresponding PMC full-text).

        Example:
            >>> client = NCBIClient(email="user@example.com")
            >>> pmids = client.esearch_ids("hlavacek ws[author]")
            >>> pmcids = client.get_pmcids(pmids)
            >>> print(f"{len(pmcids)} of {len(pmids)} have PMC full-text")
        """
        mapping = self.convert_ids(pmids, id_type="pmid")
        return {pmid: pmcid for pmid, pmcid in mapping.items() if pmcid is not None}
