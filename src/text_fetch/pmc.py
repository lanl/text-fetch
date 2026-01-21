"""PubMed Central fetching and JATS validation.

Provides JATS/NXML validation for sorting articles into valid/incomplete
folders based on completeness criteria for RAG pipelines.
"""

from __future__ import annotations

__all__ = [
    "JATSValidator",
    "ValidationResult",
    "ValidationStatus",
    "save_pmc_article",
    "read_manifest",
    "write_manifest",
]

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

logger = logging.getLogger(__name__)

# Minimum body content threshold (characters) for "valid" status
BODY_MIN_CHARS = 1000


class ValidationStatus(Enum):
    """JATS document validation status."""

    VALID = "valid"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"  # Not valid XML at all


@dataclass
class ValidationResult:
    """Result of JATS document validation."""

    status: ValidationStatus
    has_title: bool
    has_abstract: bool
    has_body: bool
    body_chars: int = 0
    errors: list[str] = field(default_factory=list)
    pmcid: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "status": self.status.value,
            "has_title": self.has_title,
            "has_abstract": self.has_abstract,
            "has_body": self.has_body,
            "body_chars": self.body_chars,
            "errors": self.errors,
            "pmcid": self.pmcid,
        }


class JATSValidator:
    """Validates JATS/NXML documents for completeness.

    Validation criteria for "valid" status (aligned with litkit requirements):
    - Has non-empty <article-title>
    - Has non-empty <abstract>
    - Has <body> with >= BODY_MIN_CHARS characters of content

    Documents missing any required element are marked "incomplete".
    Invalid XML is marked "invalid".

    Example:
        >>> validator = JATSValidator()
        >>> result = validator.validate(xml_content)
        >>> if result.status == ValidationStatus.VALID:
        ...     print("Document is complete for RAG")
    """

    def __init__(self, body_min_chars: int = BODY_MIN_CHARS) -> None:
        """Initialize validator.

        Args:
            body_min_chars: Minimum characters in body for valid status.
        """
        self.body_min_chars = body_min_chars

    def validate(self, xml_content: str) -> ValidationResult:
        """Validate JATS XML content.

        Args:
            xml_content: JATS/NXML XML string.

        Returns:
            ValidationResult with status and field detection results.
        """
        errors: list[str] = []

        # Try to parse XML
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError as e:
            return ValidationResult(
                status=ValidationStatus.INVALID,
                has_title=False,
                has_abstract=False,
                has_body=False,
                body_chars=0,
                errors=[f"XML parse error: {e}"],
            )

        # Extract PMCID if available
        pmcid = self._extract_pmcid(root)

        # Check for required elements
        has_title, title_text = self._check_title(root)
        has_abstract, abstract_text = self._check_abstract(root)
        has_body, body_chars = self._check_body(root)

        # Build error list for incomplete documents
        if not has_title:
            errors.append("Missing or empty <article-title>")
        if not has_abstract:
            errors.append("Missing or empty <abstract>")
        if not has_body:
            if body_chars == 0:
                errors.append("Missing or empty <body>")
            else:
                errors.append(
                    f"Body too short: {body_chars} chars "
                    f"(minimum: {self.body_min_chars})"
                )

        # Determine status
        if has_title and has_abstract and has_body:
            status = ValidationStatus.VALID
        else:
            status = ValidationStatus.INCOMPLETE

        return ValidationResult(
            status=status,
            has_title=has_title,
            has_abstract=has_abstract,
            has_body=has_body,
            body_chars=body_chars,
            errors=errors,
            pmcid=pmcid,
        )

    def validate_file(self, path: Path | str) -> ValidationResult:
        """Validate JATS XML from file.

        Args:
            path: Path to JATS/NXML file.

        Returns:
            ValidationResult with status and field detection results.
        """
        path = Path(path)
        try:
            xml_content = path.read_text(encoding="utf-8")
        except OSError as e:
            return ValidationResult(
                status=ValidationStatus.INVALID,
                has_title=False,
                has_abstract=False,
                has_body=False,
                errors=[f"File read error: {e}"],
            )
        return self.validate(xml_content)

    def _extract_pmcid(self, root: ET.Element) -> str | None:
        """Extract PMCID from article-id elements."""
        # Try various paths for article-id with pmcid type
        for article_id in root.iter("article-id"):
            pub_id_type = article_id.get("pub-id-type", "").lower()
            if pub_id_type == "pmcid" and article_id.text:
                return article_id.text.strip()
        return None

    def _check_title(self, root: ET.Element) -> tuple[bool, str]:
        """Check for non-empty article-title.

        Returns:
            Tuple of (has_valid_title, title_text).
        """
        # Try to find article-title anywhere in document
        for title_el in root.iter("article-title"):
            text = self._get_all_text(title_el)
            if text:
                return True, text
        return False, ""

    def _check_abstract(self, root: ET.Element) -> tuple[bool, str]:
        """Check for non-empty abstract.

        Returns:
            Tuple of (has_valid_abstract, abstract_text).
        """
        for abstract_el in root.iter("abstract"):
            text = self._get_all_text(abstract_el)
            if text:
                return True, text
        return False, ""

    def _check_body(self, root: ET.Element) -> tuple[bool, int]:
        """Check for body with sufficient content.

        Returns:
            Tuple of (has_valid_body, body_char_count).
        """
        total_chars = 0
        for body_el in root.iter("body"):
            text = self._get_all_text(body_el)
            total_chars += len(text)

        has_valid_body = total_chars >= self.body_min_chars
        return has_valid_body, total_chars

    def _get_all_text(self, element: ET.Element) -> str:
        """Extract all text content from element and descendants.

        Normalizes whitespace (collapses runs of whitespace to single space).
        """
        texts = []
        if element.text:
            texts.append(element.text)
        for child in element:
            texts.append(self._get_all_text(child))
            if child.tail:
                texts.append(child.tail)
        return " ".join(" ".join(texts).split())


@dataclass
class ManifestEntry:
    """Entry in the PMC download manifest."""

    pmcid: str
    filename: str
    status: str  # "valid" or "incomplete"
    has_title: bool
    has_abstract: bool
    has_body: bool
    body_chars: int
    saved_at: str  # ISO timestamp
    sha256: str  # Content hash for deduplication

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestEntry:
        """Create from dictionary."""
        return cls(**data)


def compute_sha256(content: str | bytes) -> str:
    """Compute SHA256 hash of content."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def read_manifest(output_dir: Path | str) -> dict[str, ManifestEntry]:
    """Read existing manifest for incremental updates.

    Args:
        output_dir: Directory containing manifest.json.

    Returns:
        Dictionary mapping PMCID to ManifestEntry.
    """
    output_dir = Path(output_dir)
    manifest_path = output_dir / "manifest.json"

    if not manifest_path.exists():
        return {}

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        entries = data.get("articles", [])
        return {e["pmcid"]: ManifestEntry.from_dict(e) for e in entries if "pmcid" in e}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read manifest: %s", e)
        return {}


def write_manifest(
    output_dir: Path | str,
    entries: dict[str, ManifestEntry],
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write/update manifest.json with validation results.

    Args:
        output_dir: Directory to write manifest.json.
        entries: Dictionary mapping PMCID to ManifestEntry.
        metadata: Optional additional metadata to include.

    Returns:
        Path to written manifest file.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"

    # Count statistics
    valid_count = sum(1 for e in entries.values() if e.status == "valid")
    incomplete_count = sum(1 for e in entries.values() if e.status == "incomplete")

    manifest_data = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "statistics": {
            "total": len(entries),
            "valid": valid_count,
            "incomplete": incomplete_count,
        },
        "articles": [e.to_dict() for e in entries.values()],
    }

    if metadata:
        manifest_data["metadata"] = metadata

    manifest_path.write_text(
        json.dumps(manifest_data, indent=2),
        encoding="utf-8",
    )

    logger.debug("Wrote manifest with %d entries to %s", len(entries), manifest_path)
    return manifest_path


def save_pmc_article(
    pmcid: str,
    xml_content: str,
    output_dir: Path | str,
    validator: JATSValidator | None = None,
    existing_manifest: dict[str, ManifestEntry] | None = None,
) -> tuple[Path | None, ValidationResult, ManifestEntry]:
    """Save PMC article with validation-based folder sorting.

    Saves to output_dir/valid/ or output_dir/incomplete/ based on validation.
    Skips saving if PMCID already exists in manifest with same content hash.

    Args:
        pmcid: PMC identifier (e.g., "PMC12345").
        xml_content: JATS/NXML content.
        output_dir: Base output directory.
        validator: JATSValidator instance (creates default if None).
        existing_manifest: Existing manifest for duplicate detection.

    Returns:
        Tuple of (saved_path, validation_result, manifest_entry).
        saved_path is None if skipped due to duplicate.
    """
    output_dir = Path(output_dir)
    validator = validator or JATSValidator()

    # Normalize PMCID
    pmcid_norm = pmcid if pmcid.upper().startswith("PMC") else f"PMC{pmcid}"

    # Compute content hash for deduplication
    content_hash = compute_sha256(xml_content)

    # Check for duplicate
    if existing_manifest and pmcid_norm in existing_manifest:
        existing = existing_manifest[pmcid_norm]
        if existing.sha256 == content_hash:
            logger.debug("Skipping %s: already in manifest with same hash", pmcid_norm)
            # Return existing info without re-saving
            result = ValidationResult(
                status=ValidationStatus(existing.status),
                has_title=existing.has_title,
                has_abstract=existing.has_abstract,
                has_body=existing.has_body,
                body_chars=existing.body_chars,
                pmcid=pmcid_norm,
            )
            return None, result, existing

    # Validate content
    result = validator.validate(xml_content)
    result.pmcid = pmcid_norm

    # Determine target folder
    if result.status == ValidationStatus.VALID:
        target_dir = output_dir / "valid"
    else:
        target_dir = output_dir / "incomplete"

    target_dir.mkdir(parents=True, exist_ok=True)

    # Save file
    filename = f"{pmcid_norm}.xml"
    file_path = target_dir / filename
    file_path.write_text(xml_content, encoding="utf-8")

    logger.debug(
        "Saved %s to %s (%s)",
        pmcid_norm,
        result.status.value,
        file_path,
    )

    # Create manifest entry
    entry = ManifestEntry(
        pmcid=pmcid_norm,
        filename=f"{result.status.value}/{filename}",
        status=result.status.value,
        has_title=result.has_title,
        has_abstract=result.has_abstract,
        has_body=result.has_body,
        body_chars=result.body_chars,
        saved_at=datetime.now(timezone.utc).isoformat(),
        sha256=content_hash,
    )

    return file_path, result, entry
