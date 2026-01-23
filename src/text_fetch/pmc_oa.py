"""PMC Open Access corpus sync functionality.

Provides tools for downloading and maintaining a local mirror of the
PMC Open Access subset with incremental updates.
"""

from __future__ import annotations

__all__ = [
    "PMCOAClient",
    "PMCOAFileEntry",
    "SyncManifest",
    "parse_file_list",
    "read_sync_manifest",
    "write_sync_manifest",
]

import csv
import hashlib
import io
import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import requests

from text_fetch.common import RateLimiter

logger = logging.getLogger(__name__)

# Type for progress callbacks
ProgressCallback = Callable[[str, int, int], None]

# PMC OA FTP base URL (HTTP access)
PMC_OA_FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/pub/pmc"

# Available subsets
OA_SUBSETS = ("oa_comm", "oa_noncomm", "oa_other")


@dataclass
class PMCOAFileEntry:
    """Entry from PMC OA file list CSV."""

    filename: str  # Relative path to tar.gz file
    citation: str  # Article citation/title
    accession_id: str  # PMC accession ID (e.g., PMC12345)
    last_updated: str  # Timestamp (YYYY-MM-DD HH:MM:SS)
    pmid: str  # PubMed ID
    license: str  # License type
    subset: str = ""  # Which subset (oa_comm, oa_noncomm, oa_other)

    @property
    def last_updated_dt(self) -> datetime | None:
        """Parse last_updated as datetime."""
        if not self.last_updated:
            return None
        try:
            dt = datetime.strptime(self.last_updated, "%Y-%m-%d %H:%M:%S")
            return dt.replace(tzinfo=UTC)
        except ValueError:
            return None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PMCOAFileEntry:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SyncManifestEntry:
    """Entry tracking a downloaded file in the sync manifest."""

    filename: str  # Local filename
    accession_id: str  # PMC accession ID
    downloaded_at: str  # ISO timestamp
    source_updated: str  # Original file timestamp
    size_bytes: int  # File size
    sha256: str  # Content hash
    subset: str  # Which subset

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncManifestEntry:
        """Create from dictionary."""
        return cls(**data)


@dataclass
class SyncManifest:
    """Manifest tracking PMC OA sync state."""

    version: str = "1.0"
    last_sync: str = ""
    subsets: list[str] = field(default_factory=list)
    statistics: dict[str, int] = field(default_factory=dict)
    entries: dict[str, SyncManifestEntry] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "last_sync": self.last_sync,
            "subsets": self.subsets,
            "statistics": self.statistics,
            "entries": {k: v.to_dict() for k, v in self.entries.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SyncManifest:
        """Create from dictionary."""
        entries = {
            k: SyncManifestEntry.from_dict(v)
            for k, v in data.get("entries", {}).items()
        }
        return cls(
            version=data.get("version", "1.0"),
            last_sync=data.get("last_sync", ""),
            subsets=data.get("subsets", []),
            statistics=data.get("statistics", {}),
            entries=entries,
        )


def parse_file_list(
    csv_content: str,
    subset: str = "",
) -> list[PMCOAFileEntry]:
    """Parse PMC OA file list CSV content.

    The CSV format from PMC has columns:
    File, Article Citation, Accession ID, Last Updated, PMID, License

    Args:
        csv_content: Raw CSV content as string.
        subset: Subset name to tag entries with.

    Returns:
        List of PMCOAFileEntry objects.
    """
    entries = []
    reader = csv.DictReader(io.StringIO(csv_content))

    for row in reader:
        entry = PMCOAFileEntry(
            filename=row.get("File", ""),
            citation=row.get("Article Citation", ""),
            accession_id=row.get("Accession ID", ""),
            last_updated=row.get("Last Updated (YYYY-MM-DD HH:MM:SS)", ""),
            pmid=row.get("PMID", ""),
            license=row.get("License", ""),
            subset=subset,
        )
        if entry.filename and entry.accession_id:
            entries.append(entry)

    return entries


def read_sync_manifest(storage_dir: Path | str) -> SyncManifest:
    """Read sync manifest from storage directory.

    Args:
        storage_dir: Directory containing sync_manifest.json.

    Returns:
        SyncManifest object (empty if not found).
    """
    storage_dir = Path(storage_dir)
    manifest_path = storage_dir / "sync_manifest.json"

    if not manifest_path.exists():
        return SyncManifest()

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return SyncManifest.from_dict(data)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read sync manifest: %s", e)
        return SyncManifest()


def write_sync_manifest(
    storage_dir: Path | str,
    manifest: SyncManifest,
) -> Path:
    """Write sync manifest to storage directory.

    Args:
        storage_dir: Directory to write sync_manifest.json.
        manifest: SyncManifest to write.

    Returns:
        Path to written manifest file.
    """
    storage_dir = Path(storage_dir)
    storage_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = storage_dir / "sync_manifest.json"

    manifest_path.write_text(
        json.dumps(manifest.to_dict(), indent=2),
        encoding="utf-8",
    )

    logger.debug("Wrote sync manifest with %d entries", len(manifest.entries))
    return manifest_path


def compute_file_sha256(path: Path) -> str:
    """Compute SHA256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


class PMCOAClient:
    """Client for downloading PMC Open Access corpus files.

    Handles file list fetching, incremental updates, and progress tracking.

    Args:
        storage_dir: Local directory for downloaded files.
        subsets: Which subsets to sync ("oa_comm", "oa_noncomm", "oa_other").
        timeout: Request timeout in seconds.

    Example:
        >>> client = PMCOAClient("/path/to/pmc-oa")
        >>> client.sync(update_only=False)  # Initial sync
        >>> client.sync(update_only=True)   # Incremental update
    """

    def __init__(
        self,
        storage_dir: str | Path,
        subsets: tuple[str, ...] | list[str] = OA_SUBSETS,
        timeout: float = 60.0,
    ) -> None:
        self.storage_dir = Path(storage_dir)
        self.subsets = list(subsets)
        self.timeout = timeout

        # Conservative rate limit for FTP/HTTP downloads
        self.limiter = RateLimiter(2.0)

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "text-fetch/1.0",
            }
        )

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self.session.close()

    def __enter__(self) -> PMCOAClient:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def fetch_file_list(self, subset: str) -> list[PMCOAFileEntry]:
        """Fetch and parse file list for a subset.

        Args:
            subset: Subset name (e.g., "oa_comm").

        Returns:
            List of file entries.
        """
        # File list URL (CSV format)
        url = f"{PMC_OA_FTP_BASE}/{subset}/xml/oa_file_list.csv"

        logger.info("Fetching file list from %s", url)
        self.limiter.wait()

        response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()

        entries = parse_file_list(response.text, subset=subset)
        logger.info("Found %d entries in %s", len(entries), subset)

        return entries

    def get_all_entries(self) -> list[PMCOAFileEntry]:
        """Fetch file lists for all configured subsets.

        Returns:
            Combined list of all file entries.
        """
        all_entries = []
        for subset in self.subsets:
            try:
                entries = self.fetch_file_list(subset)
                all_entries.extend(entries)
            except requests.RequestException as e:
                logger.error("Failed to fetch file list for %s: %s", subset, e)
        return all_entries

    def get_updates(
        self,
        manifest: SyncManifest,
        entries: list[PMCOAFileEntry] | None = None,
    ) -> list[PMCOAFileEntry]:
        """Get list of new or updated files.

        Args:
            manifest: Existing sync manifest.
            entries: File entries to check (fetches if None).

        Returns:
            List of entries that need to be downloaded.
        """
        if entries is None:
            entries = self.get_all_entries()

        updates = []
        for entry in entries:
            existing = manifest.entries.get(entry.accession_id)
            if existing is None:
                # New file
                updates.append(entry)
            elif entry.last_updated > existing.source_updated:
                # Updated file
                updates.append(entry)

        return updates

    def download_file(
        self,
        entry: PMCOAFileEntry,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> tuple[Path, int]:
        """Download a single file.

        Args:
            entry: File entry to download.
            progress_callback: Optional callback(downloaded_bytes, total_bytes).

        Returns:
            Tuple of (local_path, file_size).
        """
        # Build download URL
        url = f"{PMC_OA_FTP_BASE}/{entry.subset}/xml/{entry.filename}"

        # Local path preserves subset structure
        local_path = self.storage_dir / entry.subset / entry.filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        logger.debug("Downloading %s", url)
        self.limiter.wait()

        response = self.session.get(url, stream=True, timeout=self.timeout)
        response.raise_for_status()

        total_size = int(response.headers.get("content-length", 0))
        downloaded = 0

        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback:
                    progress_callback(downloaded, total_size)

        return local_path, downloaded

    def sync(
        self,
        update_only: bool = False,
        progress_callback: Callable[[str, int, int], None] | None = None,
        max_files: int | None = None,
    ) -> dict[str, Any]:
        """Synchronize local storage with PMC OA corpus.

        Args:
            update_only: If True, only download new/updated files.
            progress_callback: Optional callback(filename, current, total).
            max_files: Maximum number of files to download (for testing).

        Returns:
            Statistics dictionary with counts.
        """
        # Load existing manifest
        manifest = read_sync_manifest(self.storage_dir)

        # Fetch file lists
        all_entries = self.get_all_entries()

        # Determine what to download
        if update_only and manifest.entries:
            to_download = self.get_updates(manifest, all_entries)
        else:
            to_download = all_entries

        if max_files:
            to_download = to_download[:max_files]

        stats = {
            "total_remote": len(all_entries),
            "to_download": len(to_download),
            "downloaded": 0,
            "failed": 0,
            "skipped": 0,
            "bytes_downloaded": 0,
        }

        logger.info(
            "Sync: %d remote, %d to download",
            stats["total_remote"],
            stats["to_download"],
        )

        # Download files
        for i, entry in enumerate(to_download):
            if progress_callback:
                progress_callback(entry.accession_id, i, len(to_download))

            try:
                local_path, size = self.download_file(entry)
                sha256 = compute_file_sha256(local_path)

                # Update manifest
                manifest.entries[entry.accession_id] = SyncManifestEntry(
                    filename=str(local_path.relative_to(self.storage_dir)),
                    accession_id=entry.accession_id,
                    downloaded_at=datetime.now(UTC).isoformat(),
                    source_updated=entry.last_updated,
                    size_bytes=size,
                    sha256=sha256,
                    subset=entry.subset,
                )

                stats["downloaded"] += 1
                stats["bytes_downloaded"] += size

            except requests.RequestException as e:
                logger.error("Failed to download %s: %s", entry.accession_id, e)
                stats["failed"] += 1
            except OSError as e:
                logger.error("Failed to save %s: %s", entry.accession_id, e)
                stats["failed"] += 1

            # Save manifest periodically (every 100 files)
            if stats["downloaded"] % 100 == 0 and stats["downloaded"] > 0:
                self._update_manifest_stats(manifest, stats)
                write_sync_manifest(self.storage_dir, manifest)

        # Final manifest update
        manifest.last_sync = datetime.now(UTC).isoformat()
        manifest.subsets = self.subsets
        self._update_manifest_stats(manifest, stats)
        write_sync_manifest(self.storage_dir, manifest)

        return stats

    def _update_manifest_stats(
        self, manifest: SyncManifest, stats: dict[str, Any]
    ) -> None:
        """Update manifest statistics."""
        manifest.statistics = {
            "total_files": len(manifest.entries),
            "last_download_count": stats["downloaded"],
            "last_failed_count": stats["failed"],
        }

    def iter_entries(
        self,
        manifest: SyncManifest | None = None,
    ) -> Iterator[tuple[str, Path]]:
        """Iterate over downloaded files.

        Args:
            manifest: Sync manifest (reads from disk if None).

        Yields:
            Tuples of (accession_id, local_path).
        """
        if manifest is None:
            manifest = read_sync_manifest(self.storage_dir)

        for accession_id, entry in manifest.entries.items():
            local_path = self.storage_dir / entry.filename
            if local_path.exists():
                yield accession_id, local_path

    def verify_files(
        self,
        manifest: SyncManifest | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """Verify local files against manifest.

        Checks that files exist and have correct sizes.

        Args:
            manifest: Sync manifest (reads from disk if None).
            progress_callback: Optional callback(accession_id, current, total).

        Returns:
            Dictionary with verification results.
        """
        if manifest is None:
            manifest = read_sync_manifest(self.storage_dir)

        total = len(manifest.entries)
        verified = 0
        missing = 0
        size_mismatch = 0
        missing_files: list[str] = []
        mismatched_files: list[dict[str, Any]] = []

        entries = list(manifest.entries.items())
        for i, (accession_id, entry) in enumerate(entries):
            if progress_callback:
                progress_callback(accession_id, i, len(entries))

            local_path = self.storage_dir / entry.filename

            if not local_path.exists():
                missing += 1
                missing_files.append(accession_id)
            elif local_path.stat().st_size != entry.size_bytes:
                size_mismatch += 1
                mismatched_files.append(
                    {
                        "accession_id": accession_id,
                        "expected": entry.size_bytes,
                        "actual": local_path.stat().st_size,
                    }
                )
            else:
                verified += 1

        return {
            "total": total,
            "verified": verified,
            "missing": missing,
            "size_mismatch": size_mismatch,
            "missing_files": missing_files,
            "mismatched_files": mismatched_files,
        }

    def get_status(self) -> dict[str, Any]:
        """Get status of local PMC OA mirror.

        Returns:
            Dictionary with status information.
        """
        manifest = read_sync_manifest(self.storage_dir)

        # Count files by subset
        subset_counts: dict[str, int] = {}
        subset_bytes: dict[str, int] = {}
        for entry in manifest.entries.values():
            subset = entry.subset or "unknown"
            subset_counts[subset] = subset_counts.get(subset, 0) + 1
            subset_bytes[subset] = subset_bytes.get(subset, 0) + entry.size_bytes

        total_files = len(manifest.entries)
        total_bytes = sum(e.size_bytes for e in manifest.entries.values())

        return {
            "storage_dir": str(self.storage_dir),
            "last_sync": manifest.last_sync,
            "subsets": manifest.subsets,
            "total_files": total_files,
            "total_bytes": total_bytes,
            "subset_counts": subset_counts,
            "subset_bytes": subset_bytes,
            "manifest_exists": bool(manifest.entries),
        }


def import_existing(
    storage_dir: Path | str,
    subsets: list[str] | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    """Import existing .tar.gz files into sync manifest.

    Scans the storage directory for existing .tar.gz files and
    cross-references them with PMC file lists to create manifest entries.

    Args:
        storage_dir: Directory containing existing .tar.gz files.
        subsets: Subsets to scan (default: all).
        progress_callback: Optional callback(filename, current, total).

    Returns:
        Dictionary with import statistics.
    """
    storage_dir = Path(storage_dir)
    subsets = subsets or list(OA_SUBSETS)

    scanned = 0
    matched = 0
    unmatched = 0
    unmatched_files: list[str] = []

    # Find all .tar.gz files
    logger.info("Scanning %s for .tar.gz files...", storage_dir)
    local_files: dict[str, Path] = {}

    for subset in subsets:
        subset_dir = storage_dir / subset
        if subset_dir.exists():
            for tar_file in subset_dir.rglob("*.tar.gz"):
                # Extract accession ID from filename (e.g., PMC12345.tar.gz)
                stem = tar_file.stem.replace(".tar", "")
                if stem.startswith("PMC"):
                    local_files[stem] = tar_file
                scanned += 1

    if not local_files:
        # Also check root directory for files
        for tar_file in storage_dir.rglob("*.tar.gz"):
            stem = tar_file.stem.replace(".tar", "")
            if stem.startswith("PMC"):
                local_files[stem] = tar_file
            scanned += 1

    logger.info("Found %d .tar.gz files with PMC IDs", len(local_files))

    # Fetch file lists from PMC
    with PMCOAClient(storage_dir, subsets=subsets) as client:
        all_entries = client.get_all_entries()

    # Build lookup by accession ID
    entry_lookup: dict[str, PMCOAFileEntry] = {e.accession_id: e for e in all_entries}

    # Match local files to PMC entries
    manifest = read_sync_manifest(storage_dir)
    total = len(local_files)

    for i, (accession_id, local_path) in enumerate(local_files.items()):
        if progress_callback:
            progress_callback(accession_id, i, total)

        pmc_entry = entry_lookup.get(accession_id)

        if pmc_entry:
            # Create manifest entry
            file_size = local_path.stat().st_size
            sha256 = compute_file_sha256(local_path)

            manifest.entries[accession_id] = SyncManifestEntry(
                filename=str(local_path.relative_to(storage_dir)),
                accession_id=accession_id,
                downloaded_at=datetime.now(UTC).isoformat(),
                source_updated=pmc_entry.last_updated,
                size_bytes=file_size,
                sha256=sha256,
                subset=pmc_entry.subset,
            )
            matched += 1
        else:
            unmatched += 1
            unmatched_files.append(str(local_path.relative_to(storage_dir)))

    # Update manifest
    manifest.last_sync = datetime.now(UTC).isoformat()
    manifest.subsets = subsets
    manifest.statistics = {
        "total_files": len(manifest.entries),
        "last_import_matched": matched,
        "last_import_unmatched": unmatched,
    }
    write_sync_manifest(storage_dir, manifest)

    return {
        "scanned": scanned,
        "matched": matched,
        "unmatched": unmatched,
        "unmatched_files": unmatched_files,
    }
