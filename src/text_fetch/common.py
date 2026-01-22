"""Shared utilities for text-fetch."""

from __future__ import annotations

__all__ = [
    "RateLimiter",
    "build_provenance",
    "clean",
    "create_jats_tarball",
    "create_tarball",
    "embed_provenance",
    "extract_doi_from_text",
    "read_tarball_provenance",
    "sha1_of_bytes",
    "sha1_of_file",
]

import hashlib
import io
import json
import re
import tarfile
import tempfile
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from unidecode import unidecode


def clean(text: str, normalize_unicode: bool = False) -> str:
    """Clean and normalize text.

    Args:
        text: Input text string.
        normalize_unicode: If True, convert Unicode to ASCII via unidecode.

    Returns:
        Cleaned text with normalized whitespace.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    text = re.sub(r"\s+", " ", text).strip()
    if normalize_unicode:
        text = unidecode(text)
    return text


def sha1_of_file(path: str) -> str:
    """Compute SHA1 hash of a file.

    Args:
        path: Path to the file.

    Returns:
        Hexadecimal SHA1 hash string.
    """
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def sha1_of_bytes(data: bytes) -> str:
    """Compute SHA1 hash of bytes.

    Args:
        data: Bytes to hash.

    Returns:
        Hexadecimal SHA1 hash string.
    """
    return hashlib.sha1(data).hexdigest()


def create_tarball(directory: str, output_file: str) -> None:
    """Create a tar.gz archive of a directory.

    Args:
        directory: Path to the directory to archive.
        output_file: Path for the output tar.gz file.
    """
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(directory, arcname=Path(directory).name)


class RateLimiter:
    """Simple rate limiter for API requests.

    Args:
        max_per_sec: Maximum requests per second. If <= 0, no limiting.
    """

    def __init__(self, max_per_sec: float) -> None:
        self.min_interval = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
        self.last: float = 0.0

    def wait(self) -> None:
        """Block until enough time has passed since last request."""
        if self.min_interval <= 0:
            return
        now = time.time()
        delta = now - self.last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last = time.time()


def extract_doi_from_text(text: str) -> str | None:
    """Extract DOI from text using regex.

    Args:
        text: Text to search for DOI.

    Returns:
        DOI string if found, None otherwise.
    """
    if not text:
        return None
    m = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", text, flags=re.IGNORECASE)
    if m:
        return m.group(0).rstrip(" .;,)\n\r")
    return None


def create_jats_tarball(
    output_dir: str | Path,
    tarball_path: str | Path,
    include_incomplete: bool = False,
    compression: str = "gz",
) -> dict[str, Any]:
    """Create tarball from JATS output directory.

    Creates a tarball containing XML files from the valid/ subdirectory
    (and optionally incomplete/), along with manifest.json if present.

    Args:
        output_dir: Directory containing valid/ and incomplete/ subdirs.
        tarball_path: Output tarball path.
        include_incomplete: If True, include incomplete/ directory.
        compression: Compression type - "gz", "bz2", or "none".

    Returns:
        Statistics dict with keys:
            - files_included: Number of XML files added
            - bytes: Total tarball size in bytes
            - sources: List of source directories found
            - valid_count: Number of files from valid/
            - incomplete_count: Number of files from incomplete/ (if included)
    """
    output_dir = Path(output_dir)
    tarball_path = Path(tarball_path)

    # Determine compression mode
    if compression == "gz":
        mode = "w:gz"
    elif compression == "bz2":
        mode = "w:bz2"
    else:
        mode = "w"

    stats: dict[str, Any] = {
        "files_included": 0,
        "bytes": 0,
        "sources": [],
        "valid_count": 0,
        "incomplete_count": 0,
    }

    with tarfile.open(tarball_path, mode) as tar:
        # Add manifest.json if it exists at root
        manifest_path = output_dir / "manifest.json"
        if manifest_path.exists():
            tar.add(manifest_path, arcname="manifest.json")

        # Check for valid/ directory at root level (single-source fetch)
        root_valid = output_dir / "valid"
        if root_valid.is_dir():
            stats["sources"].append("root")
            for xml_file in root_valid.glob("*.xml"):
                tar.add(xml_file, arcname=f"valid/{xml_file.name}")
                stats["files_included"] += 1
                stats["valid_count"] += 1

        # Check for incomplete/ at root level
        root_incomplete = output_dir / "incomplete"
        if include_incomplete and root_incomplete.is_dir():
            for xml_file in root_incomplete.glob("*.xml"):
                tar.add(xml_file, arcname=f"incomplete/{xml_file.name}")
                stats["files_included"] += 1
                stats["incomplete_count"] += 1

        # Check for source subdirectories (unified fetch structure)
        # e.g., pmc/valid/, europepmc/valid/, biorxiv/valid/
        for subdir in output_dir.iterdir():
            if subdir.is_dir() and subdir.name not in (
                "valid",
                "incomplete",
                "_duplicates",
            ):
                source_valid = subdir / "valid"
                if source_valid.is_dir():
                    if subdir.name not in stats["sources"]:
                        stats["sources"].append(subdir.name)
                    for xml_file in source_valid.glob("*.xml"):
                        tar.add(
                            xml_file,
                            arcname=f"{subdir.name}/valid/{xml_file.name}",
                        )
                        stats["files_included"] += 1
                        stats["valid_count"] += 1

                # Include incomplete from source subdirs
                source_incomplete = subdir / "incomplete"
                if include_incomplete and source_incomplete.is_dir():
                    for xml_file in source_incomplete.glob("*.xml"):
                        tar.add(
                            xml_file,
                            arcname=f"{subdir.name}/incomplete/{xml_file.name}",
                        )
                        stats["files_included"] += 1
                        stats["incomplete_count"] += 1

    # Get final tarball size
    stats["bytes"] = tarball_path.stat().st_size

    return stats


def embed_provenance(
    tarball_path: Path | str,
    search_config: dict[str, Any] | None,
    provenance: dict[str, Any],
    fetch_log: list[str] | None = None,
) -> None:
    """Embed provenance data in existing tarball.

    Creates a .text-fetch/ directory inside the tarball containing:
    - search_config.json (if provided)
    - provenance.json
    - fetch_log.txt (if provided)

    Args:
        tarball_path: Path to the tarball to modify.
        search_config: Search configuration dict (optional).
        provenance: Provenance metadata dict.
        fetch_log: List of log lines (optional).
    """
    tarball_path = Path(tarball_path)

    # Determine compression from filename
    name_str = str(tarball_path)
    is_gz = tarball_path.suffix == ".gz" or name_str.endswith(".tar.gz")
    is_bz2 = tarball_path.suffix == ".bz2" or name_str.endswith(".tar.bz2")
    if is_gz:
        read_mode = "r:gz"
        write_mode = "w:gz"
    elif is_bz2:
        read_mode = "r:bz2"
        write_mode = "w:bz2"
    else:
        read_mode = "r"
        write_mode = "w"

    # Create a temporary file for the new tarball
    with tempfile.NamedTemporaryFile(delete=False, suffix=".tar") as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Copy existing content and add provenance
        with (
            tarfile.open(tarball_path, read_mode) as old_tar,
            tarfile.open(tmp_path, write_mode) as new_tar,
        ):
            # Copy all existing members
            for member in old_tar.getmembers():
                # Skip any existing .text-fetch/ content
                if member.name.startswith(".text-fetch/"):
                    continue
                if member.isfile():
                    f = old_tar.extractfile(member)
                    if f:
                        new_tar.addfile(member, f)
                else:
                    new_tar.addfile(member)

            # Add provenance.json
            prov_json = json.dumps(provenance, indent=2).encode("utf-8")
            prov_info = tarfile.TarInfo(name=".text-fetch/provenance.json")
            prov_info.size = len(prov_json)
            prov_info.mtime = int(time.time())
            new_tar.addfile(prov_info, io.BytesIO(prov_json))

            # Add search_config.json if provided
            if search_config is not None:
                cfg_json = json.dumps(search_config, indent=2).encode("utf-8")
                cfg_info = tarfile.TarInfo(name=".text-fetch/search_config.json")
                cfg_info.size = len(cfg_json)
                cfg_info.mtime = int(time.time())
                new_tar.addfile(cfg_info, io.BytesIO(cfg_json))

            # Add fetch_log.txt if provided
            if fetch_log:
                log_content = "\n".join(fetch_log).encode("utf-8")
                log_info = tarfile.TarInfo(name=".text-fetch/fetch_log.txt")
                log_info.size = len(log_content)
                log_info.mtime = int(time.time())
                new_tar.addfile(log_info, io.BytesIO(log_content))

        # Replace original with new tarball
        tmp_path.replace(tarball_path)
    except Exception:
        # Clean up temp file on error
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def read_tarball_provenance(
    tarball_path: Path | str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Read embedded provenance from tarball.

    Args:
        tarball_path: Path to the tarball.

    Returns:
        Tuple of (search_config, provenance), either may be None if not found.
    """
    tarball_path = Path(tarball_path)

    # Determine compression from filename
    name_str = str(tarball_path)
    if tarball_path.suffix == ".gz" or name_str.endswith(".tar.gz"):
        mode = "r:gz"
    elif tarball_path.suffix == ".bz2" or name_str.endswith(".tar.bz2"):
        mode = "r:bz2"
    else:
        mode = "r"

    search_config: dict[str, Any] | None = None
    provenance: dict[str, Any] | None = None

    with tarfile.open(tarball_path, mode) as tar:
        # Try to read search_config.json
        try:
            cfg_member = tar.getmember(".text-fetch/search_config.json")
            f = tar.extractfile(cfg_member)
            if f:
                search_config = json.loads(f.read().decode("utf-8"))
        except KeyError:
            pass  # File doesn't exist

        # Try to read provenance.json
        try:
            prov_member = tar.getmember(".text-fetch/provenance.json")
            f = tar.extractfile(prov_member)
            if f:
                provenance = json.loads(f.read().decode("utf-8"))
        except KeyError:
            pass  # File doesn't exist

    return search_config, provenance


def build_provenance(
    stats: dict[str, Any],
    command: str | None = None,
    sources_queried: list[str] | None = None,
) -> dict[str, Any]:
    """Build provenance dict for embedding in tarball.

    Args:
        stats: Statistics from fetch operation.
        command: Original command line (optional).
        sources_queried: List of sources that were queried (optional).

    Returns:
        Provenance dict suitable for embedding.
    """
    # Import here to avoid circular import
    from . import __version__

    return {
        "text_fetch_version": __version__,
        "fetch_timestamp": datetime.now(UTC).isoformat(),
        "command": command,
        "sources_queried": sources_queried or stats.get("sources", []),
        "statistics": stats,
    }
