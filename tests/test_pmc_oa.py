"""Tests for PMC OA sync functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from text_fetch.pmc_oa import (
    PMCOAClient,
    PMCOAFileEntry,
    SyncManifest,
    SyncManifestEntry,
    parse_file_list,
    read_sync_manifest,
    write_sync_manifest,
)

# Sample CSV content matching PMC OA format
SAMPLE_CSV = """File,Article Citation,Accession ID,Last Updated (YYYY-MM-DD HH:MM:SS),PMID,License
oa_package/00/00/PMC12345.tar.gz,"Author A et al. (2024) Title.",PMC12345,2024-01-15 10:30:00,12345678,CC BY
oa_package/00/01/PMC67890.tar.gz,"Author B et al. (2024) Another.",PMC67890,2024-01-16 14:20:00,87654321,CC BY-NC
"""


class TestPMCOAFileEntry:
    """Tests for PMCOAFileEntry dataclass."""

    def test_last_updated_dt_parses_timestamp(self):
        """Should parse timestamp string to datetime."""
        entry = PMCOAFileEntry(
            filename="test.tar.gz",
            citation="Test",
            accession_id="PMC12345",
            last_updated="2024-01-15 10:30:00",
            pmid="12345",
            license="CC BY",
        )
        dt = entry.last_updated_dt
        assert dt is not None
        assert dt.year == 2024
        assert dt.month == 1
        assert dt.day == 15
        assert dt.hour == 10
        assert dt.minute == 30

    def test_last_updated_dt_empty_string(self):
        """Should return None for empty timestamp."""
        entry = PMCOAFileEntry(
            filename="test.tar.gz",
            citation="Test",
            accession_id="PMC12345",
            last_updated="",
            pmid="12345",
            license="CC BY",
        )
        assert entry.last_updated_dt is None

    def test_last_updated_dt_invalid_format(self):
        """Should return None for invalid timestamp format."""
        entry = PMCOAFileEntry(
            filename="test.tar.gz",
            citation="Test",
            accession_id="PMC12345",
            last_updated="invalid-date",
            pmid="12345",
            license="CC BY",
        )
        assert entry.last_updated_dt is None

    def test_to_dict_roundtrip(self):
        """Should serialize and deserialize correctly."""
        entry = PMCOAFileEntry(
            filename="test.tar.gz",
            citation="Test Citation",
            accession_id="PMC12345",
            last_updated="2024-01-15 10:30:00",
            pmid="12345",
            license="CC BY",
            subset="oa_comm",
        )
        data = entry.to_dict()
        restored = PMCOAFileEntry.from_dict(data)
        assert restored.filename == entry.filename
        assert restored.accession_id == entry.accession_id
        assert restored.subset == entry.subset


class TestParseFileList:
    """Tests for parse_file_list function."""

    def test_parses_valid_csv(self):
        """Should parse PMC OA file list CSV."""
        entries = parse_file_list(SAMPLE_CSV, subset="oa_comm")
        assert len(entries) == 2

        assert entries[0].accession_id == "PMC12345"
        assert entries[0].filename == "oa_package/00/00/PMC12345.tar.gz"
        assert entries[0].pmid == "12345678"
        assert entries[0].license == "CC BY"
        assert entries[0].subset == "oa_comm"

        assert entries[1].accession_id == "PMC67890"

    def test_skips_invalid_entries(self):
        """Should skip entries without required fields."""
        csv = """File,Article Citation,Accession ID,Last Updated (YYYY-MM-DD HH:MM:SS),PMID,License
,Citation,PMC123,2024-01-15 10:30:00,123,CC BY
file.tar.gz,Citation,,2024-01-15 10:30:00,123,CC BY
valid.tar.gz,Citation,PMC456,2024-01-15 10:30:00,456,CC BY
"""
        entries = parse_file_list(csv)
        assert len(entries) == 1
        assert entries[0].accession_id == "PMC456"

    def test_empty_csv(self):
        """Should return empty list for empty CSV."""
        entries = parse_file_list("")
        assert entries == []

    def test_header_only(self):
        """Should return empty list for header-only CSV."""
        csv = "File,Article Citation,Accession ID,Last Updated (YYYY-MM-DD HH:MM:SS),PMID,License\n"
        entries = parse_file_list(csv)
        assert entries == []


class TestSyncManifest:
    """Tests for SyncManifest dataclass."""

    def test_empty_manifest(self):
        """Should create empty manifest."""
        manifest = SyncManifest()
        assert manifest.version == "1.0"
        assert manifest.last_sync == ""
        assert manifest.entries == {}

    def test_to_dict_roundtrip(self):
        """Should serialize and deserialize correctly."""
        entry = SyncManifestEntry(
            filename="oa_comm/test.tar.gz",
            accession_id="PMC12345",
            downloaded_at="2024-01-15T10:30:00Z",
            source_updated="2024-01-15 10:30:00",
            size_bytes=1024,
            sha256="abc123",
            subset="oa_comm",
        )
        manifest = SyncManifest(
            version="1.0",
            last_sync="2024-01-15T12:00:00Z",
            subsets=["oa_comm"],
            statistics={"total_files": 1},
            entries={"PMC12345": entry},
        )

        data = manifest.to_dict()
        restored = SyncManifest.from_dict(data)

        assert restored.version == manifest.version
        assert restored.last_sync == manifest.last_sync
        assert restored.subsets == manifest.subsets
        assert len(restored.entries) == 1
        assert restored.entries["PMC12345"].filename == entry.filename


class TestManifestIO:
    """Tests for manifest read/write functions."""

    def test_write_and_read_manifest(self, tmp_path: Path):
        """Should write and read manifest correctly."""
        entry = SyncManifestEntry(
            filename="oa_comm/test.tar.gz",
            accession_id="PMC12345",
            downloaded_at="2024-01-15T10:30:00Z",
            source_updated="2024-01-15 10:30:00",
            size_bytes=1024,
            sha256="abc123",
            subset="oa_comm",
        )
        manifest = SyncManifest(
            version="1.0",
            last_sync="2024-01-15T12:00:00Z",
            subsets=["oa_comm"],
            entries={"PMC12345": entry},
        )

        write_sync_manifest(tmp_path, manifest)
        loaded = read_sync_manifest(tmp_path)

        assert loaded.version == "1.0"
        assert len(loaded.entries) == 1
        assert loaded.entries["PMC12345"].sha256 == "abc123"

    def test_read_nonexistent_manifest(self, tmp_path: Path):
        """Should return empty manifest when file doesn't exist."""
        manifest = read_sync_manifest(tmp_path)
        assert manifest.entries == {}
        assert manifest.version == "1.0"

    def test_read_invalid_json(self, tmp_path: Path):
        """Should return empty manifest for invalid JSON."""
        manifest_path = tmp_path / "sync_manifest.json"
        manifest_path.write_text("invalid json{")

        manifest = read_sync_manifest(tmp_path)
        assert manifest.entries == {}

    def test_creates_directory(self, tmp_path: Path):
        """Should create directory if it doesn't exist."""
        new_dir = tmp_path / "new" / "nested" / "dir"
        manifest = SyncManifest()

        write_sync_manifest(new_dir, manifest)

        assert (new_dir / "sync_manifest.json").exists()


class TestPMCOAClient:
    """Tests for PMCOAClient class."""

    def test_init_sets_defaults(self, tmp_path: Path):
        """Should initialize with default settings."""
        client = PMCOAClient(tmp_path)
        assert client.storage_dir == tmp_path
        assert len(client.subsets) == 3
        assert "oa_comm" in client.subsets

    def test_init_custom_subsets(self, tmp_path: Path):
        """Should accept custom subsets."""
        client = PMCOAClient(tmp_path, subsets=["oa_comm"])
        assert client.subsets == ["oa_comm"]

    def test_context_manager(self, tmp_path: Path):
        """Should work as context manager."""
        with PMCOAClient(tmp_path) as client:
            assert client.storage_dir == tmp_path

    @patch("text_fetch.pmc_oa.requests.Session")
    def test_fetch_file_list(self, mock_session_cls, tmp_path: Path):
        """Should fetch and parse file list."""
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session
        mock_response = MagicMock()
        mock_response.text = SAMPLE_CSV
        mock_session.get.return_value = mock_response

        client = PMCOAClient(tmp_path)
        entries = client.fetch_file_list("oa_comm")

        assert len(entries) == 2
        assert entries[0].subset == "oa_comm"
        mock_session.get.assert_called_once()

    def test_get_updates_new_files(self, tmp_path: Path):
        """Should identify new files to download."""
        manifest = SyncManifest()
        entries = [
            PMCOAFileEntry(
                filename="test1.tar.gz",
                citation="Test 1",
                accession_id="PMC111",
                last_updated="2024-01-15 10:00:00",
                pmid="111",
                license="CC BY",
                subset="oa_comm",
            ),
            PMCOAFileEntry(
                filename="test2.tar.gz",
                citation="Test 2",
                accession_id="PMC222",
                last_updated="2024-01-15 11:00:00",
                pmid="222",
                license="CC BY",
                subset="oa_comm",
            ),
        ]

        client = PMCOAClient(tmp_path)
        updates = client.get_updates(manifest, entries)

        assert len(updates) == 2

    def test_get_updates_existing_files(self, tmp_path: Path):
        """Should skip existing unchanged files."""
        manifest = SyncManifest(
            entries={
                "PMC111": SyncManifestEntry(
                    filename="test1.tar.gz",
                    accession_id="PMC111",
                    downloaded_at="2024-01-15T10:00:00Z",
                    source_updated="2024-01-15 10:00:00",
                    size_bytes=1000,
                    sha256="abc",
                    subset="oa_comm",
                )
            }
        )
        entries = [
            PMCOAFileEntry(
                filename="test1.tar.gz",
                citation="Test 1",
                accession_id="PMC111",
                last_updated="2024-01-15 10:00:00",  # Same timestamp
                pmid="111",
                license="CC BY",
                subset="oa_comm",
            ),
            PMCOAFileEntry(
                filename="test2.tar.gz",
                citation="Test 2",
                accession_id="PMC222",
                last_updated="2024-01-15 11:00:00",
                pmid="222",
                license="CC BY",
                subset="oa_comm",
            ),
        ]

        client = PMCOAClient(tmp_path)
        updates = client.get_updates(manifest, entries)

        assert len(updates) == 1
        assert updates[0].accession_id == "PMC222"

    def test_get_updates_modified_files(self, tmp_path: Path):
        """Should include files with newer timestamps."""
        manifest = SyncManifest(
            entries={
                "PMC111": SyncManifestEntry(
                    filename="test1.tar.gz",
                    accession_id="PMC111",
                    downloaded_at="2024-01-15T10:00:00Z",
                    source_updated="2024-01-15 10:00:00",
                    size_bytes=1000,
                    sha256="abc",
                    subset="oa_comm",
                )
            }
        )
        entries = [
            PMCOAFileEntry(
                filename="test1.tar.gz",
                citation="Test 1",
                accession_id="PMC111",
                last_updated="2024-01-16 10:00:00",  # Newer timestamp
                pmid="111",
                license="CC BY",
                subset="oa_comm",
            ),
        ]

        client = PMCOAClient(tmp_path)
        updates = client.get_updates(manifest, entries)

        assert len(updates) == 1
        assert updates[0].accession_id == "PMC111"

    def test_iter_entries(self, tmp_path: Path):
        """Should iterate over downloaded files."""
        # Create a test file
        (tmp_path / "oa_comm").mkdir()
        (tmp_path / "oa_comm" / "test.tar.gz").write_bytes(b"test")

        # Create manifest pointing to the file
        entry = SyncManifestEntry(
            filename="oa_comm/test.tar.gz",
            accession_id="PMC12345",
            downloaded_at="2024-01-15T10:00:00Z",
            source_updated="2024-01-15 10:00:00",
            size_bytes=4,
            sha256="abc",
            subset="oa_comm",
        )
        manifest = SyncManifest(entries={"PMC12345": entry})
        write_sync_manifest(tmp_path, manifest)

        client = PMCOAClient(tmp_path)
        items = list(client.iter_entries())

        assert len(items) == 1
        assert items[0][0] == "PMC12345"
        assert items[0][1].name == "test.tar.gz"


class TestPMCOAClientSync:
    """Tests for PMCOAClient.sync method."""

    @patch.object(PMCOAClient, "get_all_entries")
    @patch.object(PMCOAClient, "download_file")
    def test_sync_downloads_files(
        self,
        mock_download: MagicMock,
        mock_get_entries: MagicMock,
        tmp_path: Path,
    ):
        """Should download files and update manifest."""
        # Mock entries
        mock_get_entries.return_value = [
            PMCOAFileEntry(
                filename="test.tar.gz",
                citation="Test",
                accession_id="PMC12345",
                last_updated="2024-01-15 10:00:00",
                pmid="12345",
                license="CC BY",
                subset="oa_comm",
            )
        ]

        # Mock download to create file
        test_file = tmp_path / "oa_comm" / "test.tar.gz"

        def fake_download(entry, callback=None):
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_bytes(b"test content")
            return test_file, 12

        mock_download.side_effect = fake_download

        client = PMCOAClient(tmp_path)
        stats = client.sync(max_files=1)

        assert stats["downloaded"] == 1
        assert stats["failed"] == 0

        # Check manifest was updated
        manifest = read_sync_manifest(tmp_path)
        assert "PMC12345" in manifest.entries

    @patch.object(PMCOAClient, "get_all_entries")
    @patch.object(PMCOAClient, "download_file")
    def test_sync_handles_download_errors(
        self,
        mock_download: MagicMock,
        mock_get_entries: MagicMock,
        tmp_path: Path,
    ):
        """Should handle download failures gracefully."""
        import requests

        mock_get_entries.return_value = [
            PMCOAFileEntry(
                filename="test.tar.gz",
                citation="Test",
                accession_id="PMC12345",
                last_updated="2024-01-15 10:00:00",
                pmid="12345",
                license="CC BY",
                subset="oa_comm",
            )
        ]
        mock_download.side_effect = requests.RequestException("Download failed")

        client = PMCOAClient(tmp_path)
        stats = client.sync(max_files=1)

        assert stats["downloaded"] == 0
        assert stats["failed"] == 1

    @patch.object(PMCOAClient, "get_all_entries")
    def test_sync_update_only(
        self,
        mock_get_entries: MagicMock,
        tmp_path: Path,
    ):
        """Should only download new files in update mode."""
        # Create existing manifest
        entry = SyncManifestEntry(
            filename="oa_comm/existing.tar.gz",
            accession_id="PMC111",
            downloaded_at="2024-01-15T10:00:00Z",
            source_updated="2024-01-15 10:00:00",
            size_bytes=100,
            sha256="abc",
            subset="oa_comm",
        )
        manifest = SyncManifest(entries={"PMC111": entry})
        write_sync_manifest(tmp_path, manifest)

        mock_get_entries.return_value = [
            PMCOAFileEntry(
                filename="existing.tar.gz",
                citation="Existing",
                accession_id="PMC111",
                last_updated="2024-01-15 10:00:00",  # Same timestamp
                pmid="111",
                license="CC BY",
                subset="oa_comm",
            )
        ]

        client = PMCOAClient(tmp_path)
        stats = client.sync(update_only=True)

        # Should skip existing file
        assert stats["to_download"] == 0
        assert stats["downloaded"] == 0
