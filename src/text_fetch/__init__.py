"""text-fetch: Acquire scientific literature for RAG pipelines."""

__version__ = "0.1.1"

from .grobid import GROBIDClient

__all__ = ["GROBIDClient"]
