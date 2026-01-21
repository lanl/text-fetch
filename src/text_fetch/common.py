"""Shared utilities for text-fetch."""

import hashlib
import re
import tarfile
import time
import unicodedata
from typing import Optional

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
    import os

    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(directory, arcname=os.path.basename(directory))


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


def extract_doi_from_text(text: str) -> Optional[str]:
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
