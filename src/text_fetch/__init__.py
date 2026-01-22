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
from .grobid import GROBIDClient, get_default_xslt_path
from .pdf import (
    PDFProcessingResult,
    find_pdfs,
    process_pdf,
    process_pdf_batch,
)
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
    "get_default_xslt_path",
    "PDFProcessingResult",
    "SearchConfig",
    "SearchConfigError",
    "SourceOptions",
    "deduplicate_by_doi",
    "fetch_biorxiv",
    "fetch_chemrxiv",
    "fetch_europepmc",
    "fetch_medrxiv",
    "find_pdfs",
    "get_category_id",
    "get_category_ids",
    "process_pdf",
    "process_pdf_batch",
    "unified_fetch",
]
