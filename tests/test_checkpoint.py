"""Tests for checkpoint system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from text_fetch.checkpoint import (
    CheckpointError,
    FetchCheckpoint,
    clear_checkpoint,
    get_checkpoint_path,
    load_checkpoint_if_exists,
)


class TestFetchCheckpoint:
    """Tests for FetchCheckpoint dataclass."""

    def test_create_checkpoint(self) -> None:
        """Test creating a new checkpoint."""
        config = {"source": "europepmc", "query": "test"}
        checkpoint = FetchCheckpoint.create(
            config=config,
            source="europepmc",
            total_expected=100,
            output_path="/tmp/output",
        )

        assert checkpoint.checkpoint_id  # UUID is set
        assert checkpoint.config_hash  # Hash is computed
        assert checkpoint.source == "europepmc"
        assert checkpoint.total_expected == 100
        assert checkpoint.completed == []
        assert checkpoint.failed == []
        assert checkpoint.config == config
        assert checkpoint.output_path == "/tmp/output"
        assert checkpoint.started  # Timestamp is set
        assert checkpoint.last_update  # Timestamp is set

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Test saving and loading checkpoint."""
        config = {"source": "biorxiv", "query": "covid"}
        checkpoint = FetchCheckpoint.create(
            config=config,
            source="biorxiv",
            total_expected=50,
        )

        # Mark some progress
        checkpoint.mark_complete("10.1234/paper1")
        checkpoint.mark_complete("10.1234/paper2")
        checkpoint.mark_failed("10.1234/paper3", "404 Not Found")

        # Save
        checkpoint_path = tmp_path / "checkpoint.json"
        checkpoint.save(checkpoint_path)

        assert checkpoint_path.exists()

        # Load
        loaded = FetchCheckpoint.load(checkpoint_path)

        assert loaded.checkpoint_id == checkpoint.checkpoint_id
        assert loaded.config_hash == checkpoint.config_hash
        assert loaded.source == "biorxiv"
        assert loaded.total_expected == 50
        assert loaded.completed == ["10.1234/paper1", "10.1234/paper2"]
        assert len(loaded.failed) == 1
        assert loaded.failed[0]["id"] == "10.1234/paper3"
        assert loaded.failed[0]["error"] == "404 Not Found"
        assert loaded.config == config

    def test_mark_complete(self) -> None:
        """Test marking papers as complete."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint.mark_complete("paper1")
        checkpoint.mark_complete("paper2")
        checkpoint.mark_complete("paper1")  # Duplicate should be ignored

        assert checkpoint.completed == ["paper1", "paper2"]
        assert len(checkpoint.completed) == 2

    def test_mark_failed(self) -> None:
        """Test marking papers as failed."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint.mark_failed("paper1", "Error 1")
        checkpoint.mark_failed("paper2", "Error 2")
        # Update existing error
        checkpoint.mark_failed("paper1", "Updated error")

        assert len(checkpoint.failed) == 2
        # First entry should have updated error message
        paper1_entry = next(e for e in checkpoint.failed if e["id"] == "paper1")
        assert paper1_entry["error"] == "Updated error"

    def test_is_complete(self) -> None:
        """Test checking if paper is complete."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint.mark_complete("paper1")

        assert checkpoint.is_complete("paper1") is True
        assert checkpoint.is_complete("paper2") is False

    def test_is_failed(self) -> None:
        """Test checking if paper has failed."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint.mark_failed("paper1", "Error")

        assert checkpoint.is_failed("paper1") is True
        assert checkpoint.is_failed("paper2") is False

    def test_should_skip(self) -> None:
        """Test should_skip logic."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint.mark_complete("paper1")
        checkpoint.mark_failed("paper2", "Error")

        # Only completed papers should be skipped
        assert checkpoint.should_skip("paper1") is True
        assert checkpoint.should_skip("paper2") is False  # Failed can retry
        assert checkpoint.should_skip("paper3") is False

    def test_config_hash_detection(self) -> None:
        """Test config hash for detecting changes."""
        config1 = {"source": "europepmc", "query": "test"}
        config2 = {"source": "europepmc", "query": "test"}  # Same content
        config3 = {"source": "europepmc", "query": "different"}  # Different

        checkpoint = FetchCheckpoint.create(
            config=config1,
            source="europepmc",
            total_expected=10,
        )

        assert checkpoint.validate_config(config2) is True
        assert checkpoint.validate_config(config3) is False

    def test_get_progress(self) -> None:
        """Test progress statistics."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=100,
        )

        # Initial progress
        progress = checkpoint.get_progress()
        assert progress["completed"] == 0
        assert progress["failed"] == 0
        assert progress["remaining"] == 100
        assert progress["total"] == 100
        assert progress["percent"] == 0

        # After some progress
        for i in range(25):
            checkpoint.mark_complete(f"paper{i}")
        for i in range(5):
            checkpoint.mark_failed(f"failed{i}", "Error")

        progress = checkpoint.get_progress()
        assert progress["completed"] == 25
        assert progress["failed"] == 5
        assert progress["remaining"] == 70
        assert progress["total"] == 100
        assert progress["percent"] == 25.0

    def test_str_representation(self) -> None:
        """Test string representation."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=100,
        )

        for i in range(10):
            checkpoint.mark_complete(f"paper{i}")

        s = str(checkpoint)
        assert "10/100 completed" in s
        assert "10.0%" in s

    def test_load_invalid_json(self, tmp_path: Path) -> None:
        """Test loading invalid JSON raises error."""
        checkpoint_path = tmp_path / "bad.json"
        checkpoint_path.write_text("not valid json")

        with pytest.raises(CheckpointError, match="Failed to load checkpoint"):
            FetchCheckpoint.load(checkpoint_path)

    def test_load_missing_fields(self, tmp_path: Path) -> None:
        """Test loading checkpoint with missing fields raises error."""
        checkpoint_path = tmp_path / "incomplete.json"
        checkpoint_path.write_text(json.dumps({"checkpoint_id": "test"}))

        with pytest.raises(CheckpointError, match="missing required field"):
            FetchCheckpoint.load(checkpoint_path)

    def test_save_creates_directories(self, tmp_path: Path) -> None:
        """Test save creates parent directories."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint_path = tmp_path / "nested" / "dirs" / "checkpoint.json"
        checkpoint.save(checkpoint_path)

        assert checkpoint_path.exists()

    def test_atomic_save(self, tmp_path: Path) -> None:
        """Test that save is atomic (via temp file)."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint_path = tmp_path / "checkpoint.json"
        checkpoint.save(checkpoint_path)

        # Temp file should not exist after save
        temp_path = checkpoint_path.with_suffix(".tmp")
        assert not temp_path.exists()
        assert checkpoint_path.exists()


class TestCheckpointHelpers:
    """Tests for checkpoint helper functions."""

    def test_get_checkpoint_path(self, tmp_path: Path) -> None:
        """Test getting checkpoint path."""
        path = get_checkpoint_path(tmp_path)
        assert path == tmp_path / ".text-fetch" / "checkpoint.json"

    def test_load_checkpoint_if_exists_not_found(self, tmp_path: Path) -> None:
        """Test loading non-existent checkpoint returns None."""
        result = load_checkpoint_if_exists(tmp_path)
        assert result is None

    def test_load_checkpoint_if_exists_found(self, tmp_path: Path) -> None:
        """Test loading existing checkpoint."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint_path = get_checkpoint_path(tmp_path)
        checkpoint.save(checkpoint_path)

        loaded = load_checkpoint_if_exists(tmp_path)
        assert loaded is not None
        assert loaded.checkpoint_id == checkpoint.checkpoint_id

    def test_load_checkpoint_if_exists_corrupted(self, tmp_path: Path) -> None:
        """Test loading corrupted checkpoint returns None."""
        checkpoint_path = get_checkpoint_path(tmp_path)
        checkpoint_path.parent.mkdir(parents=True)
        checkpoint_path.write_text("corrupted data")

        result = load_checkpoint_if_exists(tmp_path)
        assert result is None

    def test_clear_checkpoint(self, tmp_path: Path) -> None:
        """Test clearing checkpoint."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=10,
        )

        checkpoint_path = get_checkpoint_path(tmp_path)
        checkpoint.save(checkpoint_path)

        assert checkpoint_path.exists()

        result = clear_checkpoint(tmp_path)
        assert result is True
        assert not checkpoint_path.exists()

    def test_clear_checkpoint_not_found(self, tmp_path: Path) -> None:
        """Test clearing non-existent checkpoint returns False."""
        result = clear_checkpoint(tmp_path)
        assert result is False


class TestCheckpointSaveIntervals:
    """Tests for checkpoint save interval logic."""

    def test_should_save_count_interval(self) -> None:
        """Test save triggered by count interval."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=100,
        )

        # Reset tracking to set initial time
        checkpoint.reset_save_tracking()

        # Below interval
        for i in range(9):
            checkpoint.mark_complete(f"paper{i}")
        assert checkpoint.should_save() is False

        # At interval
        checkpoint.mark_complete("paper9")
        assert checkpoint.should_save() is True

    def test_save_if_needed(self, tmp_path: Path) -> None:
        """Test save_if_needed saves at interval."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=100,
        )

        checkpoint_path = tmp_path / "checkpoint.json"

        # Reset tracking
        checkpoint.reset_save_tracking()

        # Below interval - should not save
        for i in range(5):
            checkpoint.mark_complete(f"paper{i}")
        saved = checkpoint.save_if_needed(checkpoint_path)
        assert saved is False

        # At interval - should save
        for i in range(5, 10):
            checkpoint.mark_complete(f"paper{i}")
        saved = checkpoint.save_if_needed(checkpoint_path)
        assert saved is True
        assert checkpoint_path.exists()

    def test_reset_save_tracking(self) -> None:
        """Test resetting save tracking."""
        checkpoint = FetchCheckpoint.create(
            config={},
            source="test",
            total_expected=100,
        )

        # Add items to reach threshold
        for i in range(10):
            checkpoint.mark_complete(f"paper{i}")
        assert checkpoint.should_save() is True

        # Reset
        checkpoint.reset_save_tracking()
        assert checkpoint._save_counter == 0
