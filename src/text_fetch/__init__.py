"""text-fetch: Acquire scientific literature for RAG pipelines."""

__version__ = "0.1.6"

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
from .fetch import (
    deduplicate_by_doi,
    unified_fetch,
)
from .grobid import GROBIDClient
from .query import (
    ALL_SOURCES,
    SearchConfig,
    SearchConfigError,
    SourceOptions,
)

__all__ = [
    "ALL_SOURCES",
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
    "SearchConfig",
    "SearchConfigError",
    "SourceOptions",
    "deduplicate_by_doi",
    "fetch_biorxiv",
    "fetch_chemrxiv",
    "fetch_europepmc",
    "fetch_medrxiv",
    "get_category_id",
    "get_category_ids",
    "unified_fetch",
]
