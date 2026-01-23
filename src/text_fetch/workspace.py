"""Workspace management for cross-search deduplication."""

from __future__ import annotations

__all__ = [
    "DOIIndex",
    "SearchRecord",
    "SourceFetchRecord",
    "Workspace",
    "WorkspaceError",
    "WorkspaceManifest",
]

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class WorkspaceError(Exception):
    """Workspace-related errors."""


@dataclass
class SourceFetchRecord:
    """Record of last fetch from a specific source.

    Tracks when a source was last fetched, enabling incremental
    updates that only fetch papers published since the last fetch.

    Attributes:
        source: Source name (e.g., "europepmc", "biorxiv").
        last_fetch: ISO timestamp of last fetch.
        last_config_hash: Hash of config used for change detection.
        papers_fetched: Total papers fetched from this source.
    """

    source: str
    last_fetch: str
    last_config_hash: str
    papers_fetched: int

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "source": self.source,
            "last_fetch": self.last_fetch,
            "last_config_hash": self.last_config_hash,
            "papers_fetched": self.papers_fetched,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SourceFetchRecord:
        """Create from dictionary."""
        return cls(
            source=data["source"],
            last_fetch=data.get("last_fetch", ""),
            last_config_hash=data.get("last_config_hash", ""),
            papers_fetched=data.get("papers_fetched", 0),
        )


@dataclass
class WorkspaceManifest:
    """Workspace metadata stored in .text-fetch/workspace.json."""

    version: str = "1.0"
    created: str = ""
    updated: str = ""
    name: str = ""
    statistics: dict[str, int] = field(default_factory=dict)
    source_records: dict[str, SourceFetchRecord] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "version": self.version,
            "created": self.created,
            "updated": self.updated,
            "name": self.name,
            "statistics": self.statistics,
            "source_records": {k: v.to_dict() for k, v in self.source_records.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceManifest:
        """Create from dictionary."""
        source_records_data = data.get("source_records", {})
        source_records = {
            k: SourceFetchRecord.from_dict(v) for k, v in source_records_data.items()
        }
        return cls(
            version=data.get("version", "1.0"),
            created=data.get("created", ""),
            updated=data.get("updated", ""),
            name=data.get("name", ""),
            statistics=data.get("statistics", {}),
            source_records=source_records,
        )


@dataclass
class SearchRecord:
    """Record of a search execution."""

    id: str
    timestamp: str
    config: dict[str, Any]
    command: str
    statistics: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "config": self.config,
            "command": self.command,
            "statistics": self.statistics,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SearchRecord:
        """Create from dictionary."""
        return cls(
            id=data["id"],
            timestamp=data.get("timestamp", ""),
            config=data.get("config", {}),
            command=data.get("command", ""),
            statistics=data.get("statistics", {}),
        )


class DOIIndex:
    """Fast DOI lookup for deduplication.

    Stores DOI -> metadata mapping in a JSON file for persistent
    cross-search deduplication.
    """

    def __init__(self, path: Path) -> None:
        """Initialize DOI index.

        Args:
            path: Path to the doi_index.json file.
        """
        self.path = path
        self._index: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load index from disk."""
        if self.path.exists():
            try:
                with open(self.path, encoding="utf-8") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load DOI index: %s", e)
                self._index = {}

    def _save(self) -> None:
        """Save index to disk."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._index, f, indent=2)

    def _normalize_doi(self, doi: str) -> str:
        """Normalize DOI for case-insensitive comparison.

        Args:
            doi: DOI string.

        Returns:
            Normalized (lowercase, stripped) DOI.
        """
        return doi.lower().strip()

    def contains(self, doi: str) -> bool:
        """Check if DOI exists in index.

        Args:
            doi: DOI to check.

        Returns:
            True if DOI exists (case-insensitive).
        """
        return self._normalize_doi(doi) in self._index

    def add(
        self,
        doi: str,
        file_path: str,
        source: str,
        search_id: str,
    ) -> None:
        """Add DOI to index.

        Args:
            doi: DOI string.
            file_path: Relative path to the file in workspace.
            source: Source that provided the DOI (e.g., "pmc", "biorxiv").
            search_id: ID of the search that fetched this DOI.
        """
        normalized = self._normalize_doi(doi)
        self._index[normalized] = {
            "file": file_path,
            "source": source,
            "search_id": search_id,
            "added": datetime.now(UTC).isoformat(),
        }
        self._save()

    def get(self, doi: str) -> dict[str, Any] | None:
        """Get metadata for a DOI.

        Args:
            doi: DOI to look up.

        Returns:
            Metadata dict or None if not found.
        """
        return self._index.get(self._normalize_doi(doi))

    def remove(self, doi: str) -> bool:
        """Remove DOI from index.

        Args:
            doi: DOI to remove.

        Returns:
            True if DOI was removed, False if not found.
        """
        normalized = self._normalize_doi(doi)
        if normalized in self._index:
            del self._index[normalized]
            self._save()
            return True
        return False

    def clear(self) -> None:
        """Clear all DOIs from index."""
        self._index = {}
        self._save()

    def __len__(self) -> int:
        """Return number of DOIs in index."""
        return len(self._index)

    def __iter__(self):
        """Iterate over DOIs."""
        return iter(self._index)


class Workspace:
    """Manages a corpus workspace directory.

    A workspace is a directory that tracks all fetched DOIs across
    multiple searches, enabling cross-search deduplication and
    unified tarball creation.

    Directory structure:
        workspace/
        ├── .text-fetch/
        │   ├── workspace.json     # Workspace manifest
        │   ├── searches/          # Search history
        │   │   ├── search_001.json
        │   │   └── ...
        │   └── doi_index.json     # DOI → location mapping
        ├── valid/                 # Complete JATS files
        │   └── *.xml
        ├── incomplete/            # Incomplete JATS files
        │   └── *.xml
        └── manifest.json          # Standard text-fetch manifest
    """

    META_DIR = ".text-fetch"
    MANIFEST_FILE = "workspace.json"
    DOI_INDEX_FILE = "doi_index.json"
    SEARCHES_DIR = "searches"

    def __init__(self, path: Path | str) -> None:
        """Initialize workspace instance.

        Args:
            path: Path to workspace directory.
        """
        self.path = Path(path).resolve()
        self.meta_dir = self.path / self.META_DIR
        self.valid_dir = self.path / "valid"
        self.incomplete_dir = self.path / "incomplete"

        self._manifest: WorkspaceManifest | None = None
        self._doi_index: DOIIndex | None = None
        self._search_counter: int = 0

    @property
    def manifest(self) -> WorkspaceManifest:
        """Get workspace manifest, loading if needed."""
        if self._manifest is None:
            self._load_manifest()
        assert self._manifest is not None
        return self._manifest

    @property
    def doi_index(self) -> DOIIndex:
        """Get DOI index, loading if needed."""
        if self._doi_index is None:
            self._doi_index = DOIIndex(self.meta_dir / self.DOI_INDEX_FILE)
        return self._doi_index

    def _load_manifest(self) -> None:
        """Load manifest from disk."""
        manifest_path = self.meta_dir / self.MANIFEST_FILE
        if manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as f:
                data = json.load(f)
                self._manifest = WorkspaceManifest.from_dict(data)
        else:
            self._manifest = WorkspaceManifest()

    def _save_manifest(self) -> None:
        """Save manifest to disk."""
        manifest_path = self.meta_dir / self.MANIFEST_FILE
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest.to_dict(), f, indent=2)

    def _get_next_search_id(self) -> str:
        """Get next search ID."""
        searches_dir = self.meta_dir / self.SEARCHES_DIR
        if not searches_dir.exists():
            return "search_001"

        # Find highest existing search number
        max_num = 0
        for search_file in searches_dir.glob("search_*.json"):
            try:
                num = int(search_file.stem.split("_")[1])
                max_num = max(max_num, num)
            except (IndexError, ValueError):
                continue

        return f"search_{max_num + 1:03d}"

    @classmethod
    def init(
        cls,
        path: Path | str,
        name: str | None = None,
    ) -> Workspace:
        """Initialize a new workspace directory.

        Creates the workspace directory structure and manifest.

        Args:
            path: Path for the new workspace.
            name: Optional workspace name (defaults to directory name).

        Returns:
            Initialized Workspace instance.

        Raises:
            WorkspaceError: If workspace already exists.
        """
        path = Path(path).resolve()
        meta_dir = path / cls.META_DIR

        if meta_dir.exists():
            raise WorkspaceError(f"Workspace already exists: {path}")

        # Create directory structure
        path.mkdir(parents=True, exist_ok=True)
        meta_dir.mkdir()
        (meta_dir / cls.SEARCHES_DIR).mkdir()
        (path / "valid").mkdir()
        (path / "incomplete").mkdir()

        # Create manifest
        now = datetime.now(UTC).isoformat()
        ws = cls(path)
        ws._manifest = WorkspaceManifest(
            version="1.0",
            created=now,
            updated=now,
            name=name or path.name,
            statistics={
                "total_searches": 0,
                "total_valid": 0,
                "total_incomplete": 0,
                "unique_dois": 0,
                "duplicates_skipped": 0,
            },
        )
        ws._save_manifest()

        # Initialize empty DOI index
        ws._doi_index = DOIIndex(meta_dir / cls.DOI_INDEX_FILE)

        logger.info("Initialized workspace: %s", path)
        return ws

    @classmethod
    def load(cls, path: Path | str) -> Workspace:
        """Load an existing workspace.

        Args:
            path: Path to workspace directory.

        Returns:
            Loaded Workspace instance.

        Raises:
            WorkspaceError: If path is not a valid workspace.
        """
        path = Path(path).resolve()
        meta_dir = path / cls.META_DIR

        if not meta_dir.exists():
            raise WorkspaceError(f"Not a workspace: {path}")

        ws = cls(path)
        ws._load_manifest()
        return ws

    @classmethod
    def load_or_init(
        cls,
        path: Path | str,
        name: str | None = None,
    ) -> Workspace:
        """Load existing workspace or initialize new one.

        Args:
            path: Path to workspace directory.
            name: Optional workspace name (for new workspaces).

        Returns:
            Workspace instance.
        """
        path = Path(path).resolve()
        if (path / cls.META_DIR).exists():
            return cls.load(path)
        return cls.init(path, name)

    def is_workspace(self) -> bool:
        """Check if this path is a valid workspace.

        Returns:
            True if path contains workspace metadata.
        """
        return self.meta_dir.exists() and (self.meta_dir / self.MANIFEST_FILE).exists()

    def has_doi(self, doi: str) -> bool:
        """Check if DOI already exists in workspace.

        Args:
            doi: DOI to check.

        Returns:
            True if DOI exists (case-insensitive).
        """
        return self.doi_index.contains(doi)

    def record_duplicate_skip(self, doi: str) -> None:
        """Record that a duplicate DOI was skipped.

        Call this when a fetcher skips an article because has_doi() returned True.
        This ensures workspace statistics accurately reflect all skipped duplicates.

        Args:
            doi: The DOI that was skipped.
        """
        self.manifest.statistics["duplicates_skipped"] = (
            self.manifest.statistics.get("duplicates_skipped", 0) + 1
        )
        self._save_manifest()
        logger.debug("Recorded duplicate skip for DOI: %s", doi)

    def add_file(
        self,
        jats_content: str,
        doi: str | None,
        source: str,
        search_id: str,
        is_valid: bool,
        filename: str | None = None,
    ) -> Path | None:
        """Add a JATS file to the workspace.

        Args:
            jats_content: JATS XML content.
            doi: DOI of the article (optional).
            source: Source that provided the file (e.g., "pmc", "biorxiv").
            search_id: ID of the search that fetched this file.
            is_valid: True if file passes validation.
            filename: Optional filename (auto-generated if not provided).

        Returns:
            Path to written file, or None if skipped (duplicate DOI).
        """
        # Check for duplicate DOI
        if doi and self.has_doi(doi):
            logger.debug("Skipping duplicate DOI: %s", doi)
            self.manifest.statistics["duplicates_skipped"] = (
                self.manifest.statistics.get("duplicates_skipped", 0) + 1
            )
            self._save_manifest()
            return None

        # Determine target directory
        target_dir = self.valid_dir if is_valid else self.incomplete_dir

        # Generate filename if not provided
        if filename is None:
            if doi:
                # Create filename from DOI
                safe_doi = doi.replace("/", "_").replace(":", "_")
                filename = f"{source}_{safe_doi}.xml"
            else:
                # Generate timestamp-based filename
                ts = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
                filename = f"{source}_{ts}.xml"

        # Write file
        target_path = target_dir / filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(jats_content, encoding="utf-8")

        # Update DOI index
        if doi:
            rel_path = target_path.relative_to(self.path)
            self.doi_index.add(doi, str(rel_path), source, search_id)

        # Update statistics
        if is_valid:
            self.manifest.statistics["total_valid"] = (
                self.manifest.statistics.get("total_valid", 0) + 1
            )
        else:
            self.manifest.statistics["total_incomplete"] = (
                self.manifest.statistics.get("total_incomplete", 0) + 1
            )

        if doi:
            self.manifest.statistics["unique_dois"] = len(self.doi_index)

        self.manifest.updated = datetime.now(UTC).isoformat()
        self._save_manifest()

        logger.debug("Added file to workspace: %s", target_path)
        return target_path

    def record_search(
        self,
        config: dict[str, Any],
        command: str,
        stats: dict[str, int],
    ) -> str:
        """Record a search execution.

        Args:
            config: Search configuration dict.
            command: Original command line.
            stats: Search statistics.

        Returns:
            Search ID for this search.
        """
        search_id = self._get_next_search_id()

        record = SearchRecord(
            id=search_id,
            timestamp=datetime.now(UTC).isoformat(),
            config=config,
            command=command,
            statistics=stats,
        )

        # Save search record
        searches_dir = self.meta_dir / self.SEARCHES_DIR
        searches_dir.mkdir(parents=True, exist_ok=True)
        search_file = searches_dir / f"{search_id}.json"
        with open(search_file, "w", encoding="utf-8") as f:
            json.dump(record.to_dict(), f, indent=2)

        # Update manifest
        self.manifest.statistics["total_searches"] = (
            self.manifest.statistics.get("total_searches", 0) + 1
        )
        self.manifest.updated = datetime.now(UTC).isoformat()
        self._save_manifest()

        logger.info("Recorded search %s in workspace", search_id)
        return search_id

    def get_searches(self) -> list[SearchRecord]:
        """Get all search records.

        Returns:
            List of SearchRecord objects, ordered by timestamp (newest first).
        """
        searches: list[SearchRecord] = []
        searches_dir = self.meta_dir / self.SEARCHES_DIR

        if not searches_dir.exists():
            return searches

        for search_file in searches_dir.glob("search_*.json"):
            try:
                with open(search_file, encoding="utf-8") as f:
                    data = json.load(f)
                    searches.append(SearchRecord.from_dict(data))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load search record %s: %s", search_file, e)

        # Sort by timestamp (newest first)
        searches.sort(key=lambda s: s.timestamp, reverse=True)
        return searches

    def get_statistics(self) -> dict[str, Any]:
        """Get workspace statistics.

        Returns:
            Statistics dict including:
            - name: Workspace name
            - path: Workspace path
            - created: Creation timestamp
            - updated: Last update timestamp
            - total_searches: Number of searches
            - total_valid: Number of valid files
            - total_incomplete: Number of incomplete files
            - unique_dois: Number of unique DOIs
            - duplicates_skipped: Number of duplicates skipped
        """
        # Recount files to ensure accuracy
        valid_count = (
            len(list(self.valid_dir.glob("*.xml"))) if self.valid_dir.exists() else 0
        )
        incomplete_count = (
            len(list(self.incomplete_dir.glob("*.xml")))
            if self.incomplete_dir.exists()
            else 0
        )

        return {
            "name": self.manifest.name,
            "path": str(self.path),
            "created": self.manifest.created,
            "updated": self.manifest.updated,
            "total_searches": self.manifest.statistics.get("total_searches", 0),
            "total_valid": valid_count,
            "total_incomplete": incomplete_count,
            "unique_dois": len(self.doi_index),
            "duplicates_skipped": self.manifest.statistics.get("duplicates_skipped", 0),
        }

    def clear(self, keep_history: bool = False) -> None:
        """Clear workspace contents.

        Args:
            keep_history: If True, keep search history but clear files.
        """
        import shutil

        # Clear files
        if self.valid_dir.exists():
            shutil.rmtree(self.valid_dir)
        if self.incomplete_dir.exists():
            shutil.rmtree(self.incomplete_dir)

        # Recreate directories
        self.valid_dir.mkdir()
        self.incomplete_dir.mkdir()

        # Clear DOI index
        self.doi_index.clear()

        if not keep_history:
            # Clear search history
            searches_dir = self.meta_dir / self.SEARCHES_DIR
            if searches_dir.exists():
                shutil.rmtree(searches_dir)
                searches_dir.mkdir()

            # Reset statistics
            self.manifest.statistics = {
                "total_searches": 0,
                "total_valid": 0,
                "total_incomplete": 0,
                "unique_dois": 0,
                "duplicates_skipped": 0,
            }
        else:
            # Keep search count, reset file counts
            self.manifest.statistics["total_valid"] = 0
            self.manifest.statistics["total_incomplete"] = 0
            self.manifest.statistics["unique_dois"] = 0
            self.manifest.statistics["duplicates_skipped"] = 0

        self.manifest.updated = datetime.now(UTC).isoformat()
        self._save_manifest()

        logger.info("Cleared workspace: %s (keep_history=%s)", self.path, keep_history)

    def update_source_record(
        self,
        source: str,
        papers_fetched: int,
        config_hash: str | None = None,
    ) -> None:
        """Update or create a source fetch record.

        Call this after successfully fetching from a source to track
        the last fetch time for incremental updates.

        Args:
            source: Source name (e.g., "europepmc", "biorxiv").
            papers_fetched: Number of papers fetched in this operation.
            config_hash: Optional config hash for change detection.
        """
        now = datetime.now(UTC).isoformat()

        if source in self.manifest.source_records:
            # Update existing record
            record = self.manifest.source_records[source]
            record.last_fetch = now
            record.papers_fetched += papers_fetched
            if config_hash:
                record.last_config_hash = config_hash
        else:
            # Create new record
            self.manifest.source_records[source] = SourceFetchRecord(
                source=source,
                last_fetch=now,
                last_config_hash=config_hash or "",
                papers_fetched=papers_fetched,
            )

        self.manifest.updated = now
        self._save_manifest()
        logger.debug(
            "Updated source record for %s: %d papers",
            source,
            papers_fetched,
        )

    def get_source_record(self, source: str) -> SourceFetchRecord | None:
        """Get the fetch record for a source.

        Args:
            source: Source name (e.g., "europepmc", "biorxiv").

        Returns:
            SourceFetchRecord if source has been fetched, None otherwise.
        """
        return self.manifest.source_records.get(source)

    def get_last_fetch_date(self, source: str) -> str | None:
        """Get the last fetch date for a source.

        Args:
            source: Source name (e.g., "europepmc", "biorxiv").

        Returns:
            ISO date string (YYYY-MM-DD) or None if no previous fetch.
        """
        record = self.get_source_record(source)
        if record and record.last_fetch:
            # Extract date portion from ISO timestamp
            return record.last_fetch[:10]
        return None

    def build_tarball(
        self,
        output_path: Path | str,
        include_incomplete: bool = False,
        compression: str = "gz",
    ) -> dict[str, Any]:
        """Build tarball from workspace contents.

        Args:
            output_path: Output tarball path.
            include_incomplete: If True, include incomplete files.
            compression: Compression type - "gz", "bz2", or "none".

        Returns:
            Statistics dict with keys:
            - files_included: Number of files added
            - bytes: Tarball size in bytes
            - valid_count: Number of valid files
            - incomplete_count: Number of incomplete files
        """
        from .common import create_jats_tarball

        output_path = Path(output_path)

        stats = create_jats_tarball(
            self.path,
            output_path,
            include_incomplete=include_incomplete,
            compression=compression,
        )

        logger.info(
            "Built tarball: %s (%d files, %d bytes)",
            output_path,
            stats["files_included"],
            stats["bytes"],
        )

        return stats
