"""text-fetch: Acquire scientific literature for RAG pipelines."""

__version__ = "0.1.3"

from .biorxiv import (
    BIORXIV_CATEGORIES,
    MEDRXIV_CATEGORIES,
    BiorxivArticle,
    BiorxivClient,
    fetch_biorxiv,
    fetch_medrxiv,
)
from .grobid import GROBIDClient

__all__ = [
    "BIORXIV_CATEGORIES",
    "BiorxivArticle",
    "BiorxivClient",
    "GROBIDClient",
    "MEDRXIV_CATEGORIES",
    "fetch_biorxiv",
    "fetch_medrxiv",
]
