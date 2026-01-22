"""text-fetch: Acquire scientific literature for RAG pipelines."""

__version__ = "0.1.5"

from .biorxiv import (
    BIORXIV_CATEGORIES,
    MEDRXIV_CATEGORIES,
    BiorxivArticle,
    BiorxivClient,
    fetch_biorxiv,
    fetch_medrxiv,
)
from .chemrxiv import (
    CHEMRXIV_CATEGORIES,
    ChemrxivArticle,
    ChemrxivClient,
    fetch_chemrxiv,
    get_category_id,
    get_category_ids,
)
from .europepmc import (
    EuropePMCArticle,
    EuropePMCClient,
    fetch_europepmc,
)
from .grobid import GROBIDClient

__all__ = [
    "BIORXIV_CATEGORIES",
    "BiorxivArticle",
    "BiorxivClient",
    "CHEMRXIV_CATEGORIES",
    "ChemrxivArticle",
    "ChemrxivClient",
    "EuropePMCArticle",
    "EuropePMCClient",
    "GROBIDClient",
    "MEDRXIV_CATEGORIES",
    "fetch_biorxiv",
    "fetch_chemrxiv",
    "fetch_europepmc",
    "fetch_medrxiv",
    "get_category_id",
    "get_category_ids",
]
