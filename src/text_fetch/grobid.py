"""GROBID client for PDF→TEI→JATS conversion."""

from __future__ import annotations

__all__ = ["GROBIDClient", "GROBIDOCRError", "get_default_xslt_path"]

import logging
from importlib.resources import files
from pathlib import Path

import requests
from lxml import etree

from .common import RateLimiter

logger = logging.getLogger(__name__)


class GROBIDOCRError(Exception):
    """Raised when OCR is requested but GROBID does not have OCR support."""

    pass


def get_default_xslt_path() -> Path:
    """Get path to bundled tei2jats.xsl stylesheet.

    Returns:
        Path to the XSLT file bundled with the package.
    """
    return Path(str(files("text_fetch.data").joinpath("tei2jats.xsl")))


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

    def has_ocr_support(self) -> bool:
        """Check if GROBID has OCR (Tesseract) support.

        The -full GROBID image includes Tesseract for OCR.
        The -crf image does not have OCR support.

        This method queries the /api/version endpoint to detect the image type.

        Returns:
            True if GROBID has OCR support, False otherwise.
        """
        try:
            resp = requests.get(f"{self.url}/api/version", timeout=5)
            if resp.status_code != 200:
                # Can't determine - assume no OCR to be safe
                return False

            # Check response for indicators of full image
            # The version endpoint may contain info about Tesseract availability
            version_info = resp.text.lower()

            # Fallback: check if version contains "full" indicator
            if "full" in version_info:
                return True

            # Try properties endpoint which lists available models
            props_resp = requests.get(f"{self.url}/service/properties", timeout=5)
            if props_resp.status_code == 200:
                props = props_resp.text.lower()
                # The full image typically has pdfalto with OCR support
                # Check for specific OCR indicators (tesseract, or ocr= enabled)
                if "tesseract" in props:
                    return True
                # Check for ocr=true or ocr.enabled=true patterns
                # But avoid matching "no.ocr" or similar negations
                if "ocr=true" in props or "ocr.enabled=true" in props:
                    return True
                # Check for pdfalto.ocr configuration (indicates OCR engine set)
                if "pdfalto.ocr=" in props:
                    return True

            # Conservative default: assume no OCR
            return False
        except requests.RequestException:
            return False

    def process_pdf(
        self,
        pdf_content: bytes,
        full_text: bool = True,
        ocr: bool = False,
        consolidate_header: bool = True,
    ) -> str | None:
        """Convert PDF to TEI XML.

        Args:
            pdf_content: PDF file bytes.
            full_text: If True, use processFulltextDocument endpoint.
            ocr: If True, enable OCR for scanned PDFs (requires GROBID with Tesseract).
            consolidate_header: If True, consolidate header for better metadata.

        Returns:
            TEI XML string or None on failure.

        Raises:
            GROBIDOCRError: If OCR is requested but GROBID does not have OCR support.
        """
        # Check OCR capability if OCR is requested
        if ocr and not self.has_ocr_support():
            raise GROBIDOCRError(
                "OCR requested but GROBID does not have OCR support. "
                "The standard GROBID image (grobid:X.X.X-crf) does not include Tesseract. "
                "Use the full image: ./scripts/start_grobid_with_ocr.sh"
            )

        self.limiter.wait()
        endpoint = "processFulltextDocument" if full_text else "processHeaderDocument"
        url = f"{self.url}/api/{endpoint}"

        # Build form data
        data: dict[str, str] = {}
        if consolidate_header:
            data["consolidateHeader"] = "1"
        if ocr:
            data["ocr"] = "true"

        try:
            resp = requests.post(
                url,
                files={"input": ("document.pdf", pdf_content, "application/pdf")},
                data=data if data else None,
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
        ocr: bool = False,
    ) -> str | None:
        """Full pipeline: PDF → TEI → JATS.

        Args:
            pdf_content: PDF file bytes.
            xslt_path: Path to tei2jats.xsl stylesheet.
            ocr: If True, enable OCR for scanned PDFs.

        Returns:
            JATS XML string or None on failure.
        """
        tei = self.process_pdf(pdf_content, ocr=ocr)
        if not tei:
            return None
        return self.tei_to_jats(tei, xslt_path)
