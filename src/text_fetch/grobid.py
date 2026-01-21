"""GROBID client for PDF→TEI→JATS conversion."""

from __future__ import annotations

__all__ = ["GROBIDClient"]

import logging
from pathlib import Path

import requests
from lxml import etree

from .common import RateLimiter

logger = logging.getLogger(__name__)


class GROBIDClient:
    """GROBID PDF→TEI conversion client."""

    DEFAULT_URL = "http://localhost:8070"

    def __init__(
        self,
        url: str | None = None,
        timeout: int = 300,
    ) -> None:
        """Initialize GROBID client.

        Args:
            url: GROBID service URL (default: localhost:8070).
            timeout: Request timeout in seconds.
        """
        self.url = (url or self.DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self.limiter = RateLimiter(1.0)  # 1 req/sec to avoid overload

    def is_available(self) -> bool:
        """Check if GROBID service is available."""
        try:
            resp = requests.get(f"{self.url}/api/isalive", timeout=5)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def process_pdf(
        self,
        pdf_content: bytes,
        full_text: bool = True,
    ) -> str | None:
        """Convert PDF to TEI XML.

        Args:
            pdf_content: PDF file bytes.
            full_text: If True, use processFulltextDocument endpoint.

        Returns:
            TEI XML string or None on failure.
        """
        self.limiter.wait()
        endpoint = "processFulltextDocument" if full_text else "processHeaderDocument"
        url = f"{self.url}/api/{endpoint}"

        try:
            resp = requests.post(
                url,
                files={"input": ("document.pdf", pdf_content, "application/pdf")},
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning("GROBID returned %d: %s", resp.status_code, resp.text[:200])
            return None
        except requests.RequestException as e:
            logger.error("GROBID request failed: %s", e)
            return None

    def tei_to_jats(self, tei_xml: str, xslt_path: Path | str) -> str | None:
        """Convert TEI XML to JATS XML via XSLT.

        Args:
            tei_xml: TEI XML string from GROBID.
            xslt_path: Path to tei2jats.xsl stylesheet.

        Returns:
            JATS XML string or None on failure.
        """
        try:
            xslt = etree.parse(str(xslt_path))
            transform = etree.XSLT(xslt)
            tei_doc = etree.fromstring(tei_xml.encode("utf-8"))
            jats_doc = transform(tei_doc)
            return etree.tostring(jats_doc, encoding="unicode", pretty_print=True)
        except Exception as e:
            logger.error("TEI to JATS conversion failed: %s", e)
            return None

    def pdf_to_jats(
        self,
        pdf_content: bytes,
        xslt_path: Path | str,
    ) -> str | None:
        """Full pipeline: PDF → TEI → JATS.

        Args:
            pdf_content: PDF file bytes.
            xslt_path: Path to tei2jats.xsl stylesheet.

        Returns:
            JATS XML string or None on failure.
        """
        tei = self.process_pdf(pdf_content)
        if not tei:
            return None
        return self.tei_to_jats(tei, xslt_path)
