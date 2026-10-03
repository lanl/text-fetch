"""text-fetch: Acquire scientific literature for RAG pipelines."""

__version__ = "0.3.2"

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
from .common import (
    build_provenance,
    create_jats_tarball,
    create_tarball_from_files,
    embed_provenance,
    embed_validation_summary,
    find_jats_files,
    read_tarball_provenance,
    validate_and_collect_stats,
)
from .europepmc import (
    EuropePMCArticle,
    EuropePMCClient,
    IncompleteListError,
    fetch_europepmc,
)
from .fetch import (
    ExpansionPlan,
    deduplicate_by_doi,
    unified_fetch,
)
from .grobid import GROBIDClient, GROBIDOCRError, get_default_xslt_path
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
from .workspace import (
    DOIIndex,
    SearchRecord,
    Workspace,
    WorkspaceError,
    WorkspaceManifest,
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
    "ExpansionPlan",
    "GROBIDClient",
    "GROBIDOCRError",
    "IncompleteListError",
    "MEDRXIV_CATEGORIES",
    "PDFProcessingResult",
    "SearchConfig",
    "SearchConfigError",
    "SourceOptions",
    "build_provenance",
    "create_jats_tarball",
    "create_tarball_from_files",
    "deduplicate_by_doi",
    "embed_provenance",
    "embed_validation_summary",
    "find_jats_files",
    "fetch_biorxiv",
    "fetch_chemrxiv",
    "fetch_europepmc",
    "fetch_medrxiv",
    "find_pdfs",
    "get_category_id",
    "get_category_ids",
    "get_default_xslt_path",
    "process_pdf",
    "process_pdf_batch",
    "read_tarball_provenance",
    "unified_fetch",
    "validate_and_collect_stats",
    # Workspace
    "DOIIndex",
    "SearchRecord",
    "Workspace",
    "WorkspaceError",
    "WorkspaceManifest",
]
