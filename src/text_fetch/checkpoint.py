"""Checkpoint system for resuming interrupted fetches."""

from __future__ import annotations

__all__ = [
    "CheckpointError",
    "FetchCheckpoint",
]

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class CheckpointError(Exception):
    """Checkpoint-related errors."""


def _compute_config_hash(config: dict[str, Any]) -> str:
    """Compute SHA256 hash of config for change detection.

    Args:
        config: Configuration dictionary.

    Returns:
        Hex string of SHA256 hash.
    """
    # Sort keys for deterministic ordering
    config_str = json.dumps(config, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()[:16]


@dataclass
class FetchCheckpoint:
    """Checkpoint for resuming interrupted fetches.

    Tracks progress of a fetch operation, allowing resumption after
    interruption. Stores completed/failed paper IDs and the original
    config for change detection.

    Attributes:
        checkpoint_id: UUID for this fetch operation.
        config_hash: SHA256 hash of search config (for change detection).
        source: Current source being fetched (e.g., "europepmc").
        total_expected: Total papers expected from this source.
        completed: List of completed paper IDs (DOIs/PMCIDs).
        failed: List of failed paper IDs with error messages.
        started: ISO timestamp when fetch started.
        last_update: ISO timestamp of last progress update.
        config: Full search config snapshot for reproducibility.
        output_path: Output directory path (for validation).
    """

    checkpoint_id: str
    config_hash: str
    source: str
    total_expected: int
    completed: list[str]
    failed: list[dict[str, str]]  # [{"id": "...", "error": "..."}]
    started: str
    last_update: str
    config: dict[str, Any]
    output_path: str = ""

    # Internal tracking (not serialized)
    _save_counter: int = field(default=0, repr=False, compare=False)
    _last_save_time: float = field(default=0.0, repr=False, compare=False)

    # Save every N completions or M seconds
    SAVE_INTERVAL_COUNT: int = 10
    SAVE_INTERVAL_SECONDS: float = 30.0

    @classmethod
    def create(
        cls,
        config: dict[str, Any],
        source: str,
        total_expected: int,
        output_path: Path | str | None = None,
    ) -> FetchCheckpoint:
        """Create a new checkpoint for a fetch operation.

        Args:
            config: Search configuration dictionary.
            source: Source being fetched (e.g., "europepmc").
            total_expected: Total number of papers expected.
            output_path: Output directory path.

        Returns:
            New FetchCheckpoint instance.
        """
        now = datetime.now(UTC).isoformat()
        return cls(
            checkpoint_id=str(uuid.uuid4()),
            config_hash=_compute_config_hash(config),
            source=source,
            total_expected=total_expected,
            completed=[],
            failed=[],
            started=now,
            last_update=now,
            config=config,
            output_path=str(output_path) if output_path else "",
        )

    @classmethod
    def load(cls, path: Path) -> FetchCheckpoint:
        """Load checkpoint from disk.

        Args:
            path: Path to checkpoint JSON file.

        Returns:
            Loaded FetchCheckpoint instance.

        Raises:
            CheckpointError: If checkpoint file is invalid or corrupted.
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise CheckpointError(f"Failed to load checkpoint: {e}") from e

        # Validate required fields
        required_fields = [
            "checkpoint_id",
            "config_hash",
            "source",
            "total_expected",
            "completed",
            "failed",
            "started",
            "last_update",
            "config",
        ]
        for field_name in required_fields:
            if field_name not in data:
                msg = f"Checkpoint missing required field: {field_name}"
                raise CheckpointError(msg)

        return cls(
            checkpoint_id=data["checkpoint_id"],
            config_hash=data["config_hash"],
            source=data["source"],
            total_expected=data["total_expected"],
            completed=data["completed"],
            failed=data["failed"],
            started=data["started"],
            last_update=data["last_update"],
            config=data["config"],
            output_path=data.get("output_path", ""),
        )

    def save(self, path: Path) -> None:
        """Save checkpoint to disk.

        Args:
            path: Path to checkpoint JSON file.
        """
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "checkpoint_id": self.checkpoint_id,
            "config_hash": self.config_hash,
            "source": self.source,
            "total_expected": self.total_expected,
            "completed": self.completed,
            "failed": self.failed,
            "started": self.started,
            "last_update": self.last_update,
            "config": self.config,
            "output_path": self.output_path,
        }

        # Write atomically via temp file
        temp_path = path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        temp_path.rename(path)

        logger.debug(
            "Saved checkpoint: %d/%d completed",
            len(self.completed),
            self.total_expected,
        )

    def mark_complete(self, paper_id: str) -> None:
        """Mark a paper as successfully completed.

        Args:
            paper_id: Paper identifier (DOI, PMCID, etc.).
        """
        if paper_id not in self.completed:
            self.completed.append(paper_id)
            self.last_update = datetime.now(UTC).isoformat()
            self._save_counter += 1

    def mark_failed(self, paper_id: str, error: str) -> None:
        """Mark a paper as failed.

        Args:
            paper_id: Paper identifier.
            error: Error message describing the failure.
        """
        # Check if already in failed list
        for entry in self.failed:
            if entry["id"] == paper_id:
                entry["error"] = error  # Update error message
                return

        self.failed.append({"id": paper_id, "error": error})
        self.last_update = datetime.now(UTC).isoformat()
        self._save_counter += 1

    def is_complete(self, paper_id: str) -> bool:
        """Check if a paper has been completed.

        Args:
            paper_id: Paper identifier to check.

        Returns:
            True if paper was successfully completed.
        """
        return paper_id in self.completed

    def is_failed(self, paper_id: str) -> bool:
        """Check if a paper has failed.

        Args:
            paper_id: Paper identifier to check.

        Returns:
            True if paper failed previously.
        """
        return any(entry["id"] == paper_id for entry in self.failed)

    def should_skip(self, paper_id: str) -> bool:
        """Check if a paper should be skipped on resume.

        Only skips completed papers. Failed papers will be retried,
        which is the intended behavior for transient errors.

        Args:
            paper_id: Paper identifier to check.

        Returns:
            True if paper was successfully completed and should be skipped.
        """
        return self.is_complete(paper_id)

    def should_save(self) -> bool:
        """Check if checkpoint should be saved based on interval.

        Returns:
            True if checkpoint should be saved now.
        """
        import time

        # Check count interval
        if self._save_counter >= self.SAVE_INTERVAL_COUNT:
            return True

        # Check time interval
        current_time = time.time()
        if current_time - self._last_save_time >= self.SAVE_INTERVAL_SECONDS:
            return True

        return False

    def save_if_needed(self, path: Path) -> bool:
        """Save checkpoint if interval has been reached.

        Args:
            path: Path to checkpoint file.

        Returns:
            True if checkpoint was saved.
        """
        import time

        if self.should_save():
            self.save(path)
            self._save_counter = 0
            self._last_save_time = time.time()
            return True
        return False

    def reset_save_tracking(self) -> None:
        """Reset save interval tracking after manual save."""
        import time

        self._save_counter = 0
        self._last_save_time = time.time()

    def validate_config(self, config: dict[str, Any]) -> bool:
        """Check if config matches checkpoint config.

        Args:
            config: Configuration to compare against.

        Returns:
            True if configs match.
        """
        new_hash = _compute_config_hash(config)
        return new_hash == self.config_hash

    def get_progress(self) -> dict[str, Any]:
        """Get progress statistics.

        Returns:
            Dict with progress info:
            - completed: Number completed
            - failed: Number failed
            - remaining: Number remaining
            - total: Total expected
            - percent: Completion percentage
        """
        completed = len(self.completed)
        failed = len(self.failed)
        remaining = max(0, self.total_expected - completed - failed)
        if self.total_expected > 0:
            percent = completed / self.total_expected * 100
        else:
            percent = 0

        return {
            "completed": completed,
            "failed": failed,
            "remaining": remaining,
            "total": self.total_expected,
            "percent": round(percent, 1),
        }

    def __str__(self) -> str:
        """Human-readable progress string."""
        progress = self.get_progress()
        return (
            f"Checkpoint {self.checkpoint_id[:8]}: "
            f"{progress['completed']}/{progress['total']} completed "
            f"({progress['percent']}%), {progress['failed']} failed"
        )


def get_checkpoint_path(output_dir: Path) -> Path:
    """Get the standard checkpoint file path for an output directory.

    Args:
        output_dir: Output directory path.

    Returns:
        Path to checkpoint file (.text-fetch/checkpoint.json).
    """
    return output_dir / ".text-fetch" / "checkpoint.json"


def load_checkpoint_if_exists(output_dir: Path) -> FetchCheckpoint | None:
    """Load checkpoint from output directory if it exists.

    Args:
        output_dir: Output directory to check.

    Returns:
        FetchCheckpoint if found and valid, None otherwise.
    """
    checkpoint_path = get_checkpoint_path(output_dir)
    if not checkpoint_path.exists():
        return None

    try:
        return FetchCheckpoint.load(checkpoint_path)
    except CheckpointError as e:
        logger.warning("Failed to load checkpoint: %s", e)
        return None


def clear_checkpoint(output_dir: Path) -> bool:
    """Remove checkpoint file from output directory.

    Args:
        output_dir: Output directory.

    Returns:
        True if checkpoint was removed, False if not found.
    """
    checkpoint_path = get_checkpoint_path(output_dir)
    if checkpoint_path.exists():
        checkpoint_path.unlink()
        logger.info("Cleared checkpoint: %s", checkpoint_path)
        return True
    return False
