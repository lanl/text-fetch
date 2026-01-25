"""Corpus comparison utilities.

This module provides functions for comparing two corpora to measure overlap
and evaluate coverage. It supports text-fetch tarballs (.tar.gz) with
manifest.json and plain text ID lists (.txt).
"""

from __future__ import annotations

import json
import logging
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from text_fetch import __version__

logger = logging.getLogger(__name__)

# Type alias for ID types
IDType = Literal["pmcid", "doi", "pmid", "unknown"]


@dataclass
class ComparisonResult:
    """Result of corpus comparison.

    Attributes:
        reference_label: Display label for reference corpus
        reference_source: Path to reference corpus file
        reference_ids: Set of normalized IDs from reference
        reference_id_types: Count of each ID type in reference
        candidate_label: Display label for candidate corpus
        candidate_source: Path to candidate corpus file
        candidate_ids: Set of normalized IDs from candidate
        candidate_id_types: Count of each ID type in candidate
        overlap: Set of IDs present in both corpora
        reference_only: Set of IDs only in reference
        candidate_only: Set of IDs only in candidate
        normalized: Whether Europe PMC ID normalization was applied
    """

    reference_label: str
    reference_source: str
    reference_ids: set[str]
    reference_id_types: dict[str, int]

    candidate_label: str
    candidate_source: str
    candidate_ids: set[str]
    candidate_id_types: dict[str, int]

    overlap: set[str] = field(default_factory=set)
    reference_only: set[str] = field(default_factory=set)
    candidate_only: set[str] = field(default_factory=set)

    normalized: bool = False

    @property
    def jaccard(self) -> float:
        """Jaccard similarity: |A ∩ B| / |A ∪ B|."""
        union = len(self.reference_ids | self.candidate_ids)
        if union == 0:
            return 0.0
        return len(self.overlap) / union

    @property
    def recall(self) -> float:
        """Recall: |A ∩ B| / |Reference|."""
        if len(self.reference_ids) == 0:
            return 0.0
        return len(self.overlap) / len(self.reference_ids)

    @property
    def precision(self) -> float:
        """Precision: |A ∩ B| / |Candidate|."""
        if len(self.candidate_ids) == 0:
            return 0.0
        return len(self.overlap) / len(self.candidate_ids)

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict.

        Returns:
            Dict with metadata, corpus info, overlap metrics, and ID lists.
        """
        return {
            "metadata": {
                "text_fetch_version": __version__,
                "timestamp": datetime.now(UTC).isoformat(),
                "normalized": self.normalized,
            },
            "reference": {
                "label": self.reference_label,
                "source": self.reference_source,
                "count": len(self.reference_ids),
                "id_types": self.reference_id_types,
            },
            "candidate": {
                "label": self.candidate_label,
                "source": self.candidate_source,
                "count": len(self.candidate_ids),
                "id_types": self.candidate_id_types,
            },
            "overlap": {
                "count": len(self.overlap),
                "jaccard": round(self.jaccard, 4),
                "recall": round(self.recall, 4),
                "precision": round(self.precision, 4),
            },
            "reference_only": sorted(self.reference_only),
            "candidate_only": sorted(self.candidate_only),
        }


def detect_id_type(id_string: str) -> IDType:
    """Detect the type of a paper ID.

    Auto-detection rules:
    - Starts with "PMC" (case-insensitive) → PMCID
    - Contains "/" → DOI
    - 7+ digits only → PMID
    - Otherwise → Unknown

    Args:
        id_string: A paper identifier string

    Returns:
        IDType: "pmcid", "doi", "pmid", or "unknown"

    Examples:
        >>> detect_id_type("PMC123456")
        'pmcid'
        >>> detect_id_type("10.1016/j.cell.2020.01.001")
        'doi'
        >>> detect_id_type("32847729")
        'pmid'
    """
    id_string = id_string.strip()

    # PMCID: starts with "PMC" (case-insensitive)
    if id_string.upper().startswith("PMC"):
        return "pmcid"

    # DOI: contains "/"
    if "/" in id_string:
        return "doi"

    # PMID: 7+ digits (typical PubMed ID)
    if id_string.isdigit() and len(id_string) >= 7:
        return "pmid"

    return "unknown"


def normalize_id(id_string: str) -> str:
    """Normalize an ID for comparison.

    Normalization rules:
    - PMCIDs: uppercase, ensure "PMC" prefix
    - DOIs: lowercase
    - PMIDs: keep as-is

    Args:
        id_string: Raw ID string

    Returns:
        Normalized ID string
    """
    id_type = detect_id_type(id_string)
    id_string = id_string.strip()

    if id_type == "pmcid":
        # Normalize to uppercase with PMC prefix
        upper = id_string.upper()
        if not upper.startswith("PMC"):
            return f"PMC{upper}"
        return upper

    if id_type == "doi":
        # DOIs are case-insensitive, normalize to lowercase
        return id_string.lower()

    return id_string


def parse_id_list(path: Path) -> tuple[set[str], dict[str, int]]:
    """Parse a text file containing paper IDs.

    Reads a plain text file with one ID per line. Comments (lines starting
    with #) and blank lines are ignored.

    Args:
        path: Path to text file with one ID per line

    Returns:
        Tuple of (set of normalized IDs, dict of ID type counts)

    Example file format:
        # corpus_ids.txt
        PMC123456
        PMC789012
        10.1016/j.cell.2020.01.001
        32847729
        # Comments and blank lines ignored
    """
    ids: set[str] = set()
    type_counts: dict[str, int] = {"pmcid": 0, "doi": 0, "pmid": 0, "unknown": 0}

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith("#"):
                continue

            id_type = detect_id_type(line)
            type_counts[id_type] += 1

            if id_type == "unknown":
                logger.warning("Unknown ID type: %s", line)

            normalized = normalize_id(line)
            ids.add(normalized)

    return ids, type_counts


def _extract_id_from_entry(
    entry: dict, type_counts: dict[str, int]
) -> tuple[str | None, bool]:
    """Extract and normalize ID from a manifest entry.

    Priority: PMCID > DOI > path/filename

    Args:
        entry: Manifest entry dict
        type_counts: Dict to update with ID type counts

    Returns:
        Tuple of (normalized ID or None, whether extraction succeeded)
    """
    # Priority: PMCID > DOI > filename
    if entry.get("pmcid"):
        pmcid = normalize_id(entry["pmcid"])
        type_counts["pmcid"] += 1
        return pmcid, True

    if entry.get("doi"):
        doi = normalize_id(entry["doi"])
        type_counts["doi"] += 1
        return doi, True

    # Try to extract from path/filename
    path_key = entry.get("path") or entry.get("filename")
    if path_key:
        filename = Path(path_key).stem
        id_type = detect_id_type(filename)
        if id_type != "unknown":
            type_counts[id_type] += 1
            return normalize_id(filename), True
        else:
            type_counts["unknown"] += 1
            logger.warning("Unknown ID from path: %s", path_key)
            return None, False

    return None, False


def extract_ids_from_tarball(path: Path) -> tuple[set[str], dict[str, int]]:
    """Extract paper IDs from a text-fetch tarball.

    Reads manifest.json from the tarball and extracts IDs.
    Supports multiple manifest schemas:
    - "files" list (comparison-format manifest)
    - "articles" list (PMC fetch manifest)
    - "per_source" dict (unified fetch manifest)
    - Fallback to XML filename scanning if no manifest found

    Priority: PMCID > DOI > filename parsing

    Args:
        path: Path to .tar.gz tarball

    Returns:
        Tuple of (set of normalized IDs, dict of ID type counts)
    """
    ids: set[str] = set()
    type_counts: dict[str, int] = {"pmcid": 0, "doi": 0, "pmid": 0, "unknown": 0}

    with tarfile.open(path, "r:gz") as tar:
        # Try to find manifest.json
        manifest_member = None
        for member in tar.getmembers():
            if member.name.endswith("manifest.json"):
                manifest_member = member
                break

        if manifest_member:
            f = tar.extractfile(manifest_member)
            if f:
                manifest = json.load(f)

                # Try different manifest schemas
                entries_found = False

                # Schema 1: "files" list (comparison-format)
                if "files" in manifest and manifest["files"]:
                    entries_found = True
                    for entry in manifest["files"]:
                        id_val, _ = _extract_id_from_entry(entry, type_counts)
                        if id_val:
                            ids.add(id_val)

                # Schema 2: "articles" list (PMC fetch manifest)
                if "articles" in manifest and manifest["articles"]:
                    entries_found = True
                    for entry in manifest["articles"]:
                        id_val, _ = _extract_id_from_entry(entry, type_counts)
                        if id_val:
                            ids.add(id_val)

                # Schema 3: "per_source" dict (unified fetch manifest)
                if "per_source" in manifest and manifest["per_source"]:
                    entries_found = True
                    for _source_name, source_data in manifest["per_source"].items():
                        # Each source may have "articles" or "files"
                        source_entries = source_data.get(
                            "articles", source_data.get("files", [])
                        )
                        for entry in source_entries:
                            id_val, _ = _extract_id_from_entry(entry, type_counts)
                            if id_val:
                                ids.add(id_val)

                if not entries_found:
                    logger.warning(
                        "Manifest in %s has no recognized article list "
                        "(tried: files, articles, per_source)",
                        path,
                    )

        # Fallback to XML filename scanning if no manifest or no entries
        if not ids:
            logger.warning(
                "No IDs extracted from manifest in %s, using XML filenames", path
            )
            for member in tar.getmembers():
                if member.name.endswith(".xml"):
                    filename = Path(member.name).stem
                    id_type = detect_id_type(filename)
                    ids.add(normalize_id(filename))
                    type_counts[id_type] += 1

    return ids, type_counts


def load_corpus_ids(path: Path) -> tuple[set[str], dict[str, int]]:
    """Load IDs from a corpus file (tarball or ID list).

    Auto-detects file type based on extension:
    - .tar.gz or .gz: Treated as tarball with manifest.json
    - Other: Treated as plain text ID list

    Args:
        path: Path to corpus file (.tar.gz or .txt)

    Returns:
        Tuple of (set of normalized IDs, dict of ID type counts)
    """
    if path.suffix == ".gz" or str(path).endswith(".tar.gz"):
        return extract_ids_from_tarball(path)
    else:
        return parse_id_list(path)


def normalize_ids_via_europepmc(
    ids: set[str],
    id_types: dict[str, int],
) -> tuple[set[str], dict[str, list[str]]]:
    """Normalize IDs to PMCIDs via Europe PMC API.

    Queries Europe PMC to resolve DOIs and PMIDs to PMCIDs for more
    accurate corpus comparison.

    Args:
        ids: Set of IDs to normalize
        id_types: Dict of ID type counts (for logging)

    Returns:
        Tuple of (set of normalized PMCIDs, dict of resolution issues)
        Issues dict has keys: "unresolved", "no_pmcid"
    """
    from .europepmc import EuropePMCClient

    client = EuropePMCClient()
    normalized: set[str] = set()
    issues: dict[str, list[str]] = {"unresolved": [], "no_pmcid": []}

    # Group IDs by type for efficient lookup
    pmcids: list[str] = []
    dois: list[str] = []
    pmids: list[str] = []

    for id_val in ids:
        id_type = detect_id_type(id_val)
        if id_type == "pmcid":
            pmcids.append(id_val)
        elif id_type == "doi":
            dois.append(id_val)
        elif id_type == "pmid":
            pmids.append(id_val)
        else:
            # Unknown IDs kept as-is
            normalized.add(id_val)
            issues["unresolved"].append(id_val)

    # PMCIDs already normalized - add directly
    for pmcid in pmcids:
        normalized.add(normalize_id(pmcid))

    # Resolve DOIs via Europe PMC
    for doi in dois:
        article = client.get_by_doi(doi)
        if article and article.pmcid:
            normalized.add(article.pmcid.upper())
        elif article:
            # Article found but no PMCID
            issues["no_pmcid"].append(doi)
            # Keep DOI as fallback
            normalized.add(normalize_id(doi))
        else:
            issues["unresolved"].append(doi)
            normalized.add(normalize_id(doi))

    # Resolve PMIDs via Europe PMC
    for pmid in pmids:
        article = client.get_by_pmid(pmid)
        if article and article.pmcid:
            normalized.add(article.pmcid.upper())
        elif article:
            # Article found but no PMCID
            issues["no_pmcid"].append(pmid)
            normalized.add(pmid)
        else:
            issues["unresolved"].append(pmid)
            normalized.add(pmid)

    # Log summary - count only IDs that actually resolved to a PMCID
    # (exclude both unresolved and no_pmcid cases)
    unresolved_set = set(issues["unresolved"])
    no_pmcid_set = set(issues["no_pmcid"])
    resolved_to_pmcid = (
        len(pmcids)
        + len([d for d in dois if d not in unresolved_set and d not in no_pmcid_set])
        + len([p for p in pmids if p not in unresolved_set and p not in no_pmcid_set])
    )
    logger.info(
        "ID normalization: %d/%d IDs are PMCIDs (%d already, %d resolved)",
        resolved_to_pmcid,
        len(ids),
        len(pmcids),
        resolved_to_pmcid - len(pmcids),
    )
    if issues["unresolved"]:
        logger.warning(
            "%d IDs could not be resolved: %s...",
            len(issues["unresolved"]),
            issues["unresolved"][:3],
        )
    if issues["no_pmcid"]:
        logger.warning(
            "%d articles found but have no PMCID: %s...",
            len(issues["no_pmcid"]),
            issues["no_pmcid"][:3],
        )

    return normalized, issues


def compare_corpora(
    reference_path: Path,
    candidate_path: Path,
    reference_label: str | None = None,
    candidate_label: str | None = None,
    normalize: bool = False,
) -> ComparisonResult:
    """Compare two corpora and compute overlap metrics.

    Loads IDs from both corpora and computes:
    - Jaccard similarity: |A ∩ B| / |A ∪ B|
    - Recall: |A ∩ B| / |Reference|
    - Precision: |A ∩ B| / |Candidate|

    Args:
        reference_path: Path to reference corpus
        candidate_path: Path to candidate corpus
        reference_label: Optional label for reference corpus
        candidate_label: Optional label for candidate corpus
        normalize: If True, normalize all IDs to PMCIDs via Europe PMC

    Returns:
        ComparisonResult with metrics and ID sets
    """
    ref_ids, ref_types = load_corpus_ids(reference_path)
    cand_ids, cand_types = load_corpus_ids(candidate_path)

    # Optionally normalize IDs via Europe PMC
    if normalize:
        logger.info("Normalizing reference corpus IDs...")
        ref_ids, _ref_issues = normalize_ids_via_europepmc(ref_ids, ref_types)
        logger.info("Normalizing candidate corpus IDs...")
        cand_ids, _cand_issues = normalize_ids_via_europepmc(cand_ids, cand_types)

    overlap = ref_ids & cand_ids
    ref_only = ref_ids - cand_ids
    cand_only = cand_ids - ref_ids

    return ComparisonResult(
        reference_label=reference_label or reference_path.name,
        reference_source=str(reference_path),
        reference_ids=ref_ids,
        reference_id_types=ref_types,
        candidate_label=candidate_label or candidate_path.name,
        candidate_source=str(candidate_path),
        candidate_ids=cand_ids,
        candidate_id_types=cand_types,
        overlap=overlap,
        reference_only=ref_only,
        candidate_only=cand_only,
        normalized=normalize,
    )
