"""NCBI E-utilities wrapper.

Provides a rate-limited client for interacting with NCBI E-utilities API,
including ESearch, ID conversion, and PMC OA retrieval.
"""

from __future__ import annotations

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
