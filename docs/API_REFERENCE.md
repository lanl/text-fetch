# text-fetch API Reference

This document provides comprehensive API documentation for text-fetch's Python library.

## Table of Contents

1. [SearchConfig](#searchconfig)
2. [Unified Fetch](#unified-fetch)
3. [Source Clients](#source-clients)
   - [NCBIClient](#ncbiclient)
   - [EuropePMCClient](#europepmcclient)
   - [BiorxivClient](#biorxivclient)
   - [ChemrxivClient](#chemrxivclient)
4. [GROBID Client](#grobid-client)
5. [PDF Processing](#pdf-processing)
6. [Corpus Workspace](#corpus-workspace)
7. [Corpus Comparison](#corpus-comparison)
8. [Utilities](#utilities)

---

## SearchConfig

The `SearchConfig` class is the central configuration object for multi-source searches.

### Import

```python
from text_fetch import SearchConfig, SearchConfigError
```

### Class Definition

```python
@dataclass
class SearchConfig:
    """Search configuration for multi-source queries."""
    
    name: str | None = None
    author: str | None = None
    keywords: list[str] | None = None
    mesh_terms: list[str] | None = None
    date_range: DateRange | None = None
    sources: list[str] | None = None
    source_options: dict[str, SourceOptions] | None = None
    max_results_per_source: int = 100
    deduplicate_by_doi: bool = True
    arxiv_categories: list[str] | None = None
```

### Creating a SearchConfig

**From Python:**

```python
from text_fetch import SearchConfig

config = SearchConfig(
    author="hlavacek ws",
    keywords=["systems biology", "rule-based modeling"],
    sources=["pmc", "europepmc", "biorxiv"],
    max_results_per_source=100,
    deduplicate_by_doi=True,
)
```

**From JSON file:**

```python
config = SearchConfig.from_json("input/search.json")
```

**JSON format:**

```json
{
  "name": "my_corpus",
  "author": "hlavacek ws",
  "keywords": ["systems biology", "rule-based modeling"],
  "date_range": {
    "start": "2020/01/01",
    "end": "2024/12/31"
  },
  "sources": ["pmc", "europepmc", "biorxiv"],
  "source_options": {
    "arxiv": {"categories": ["q-bio.MN", "q-bio.QM"]},
    "biorxiv": {"categories": ["systems_biology"]}
  },
  "max_results_per_source": 100,
  "deduplicate_by_doi": true
}
```

### Query Builders

SearchConfig provides methods to generate source-specific query strings:

```python
config = SearchConfig(author="hlavacek ws", keywords=["systems biology"])

# PubMed/PMC query (E-utilities syntax)
pubmed_query = config.to_pubmed_query()
# → 'hlavacek ws[au] AND systems biology[tiab]'

# Europe PMC query (Lucene syntax)
europepmc_query = config.to_europepmc_query()
# → 'AUTH:"hlavacek ws" AND "systems biology"'

# arXiv query
arxiv_query = config.to_arxiv_query()
# → 'au:"hlavacek ws" AND (ti:"systems biology" OR abs:"systems biology")'
```

### Validation

```python
config = SearchConfig()  # Empty config

# Validate before use
if not config.validate():
    print("Invalid config: need at least author, keywords, or other criteria")

# Or let it raise
try:
    config.to_pubmed_query()  # Raises SearchConfigError if invalid
except SearchConfigError as e:
    print(f"Config error: {e}")
```

---

## Unified Fetch

The `unified_fetch()` function orchestrates fetching from multiple sources.

### Import

```python
from text_fetch import unified_fetch, deduplicate_by_doi
```

### Function Signature

```python
def unified_fetch(
    config: SearchConfig,
    output_dir: str | Path,
    workspace: Workspace | None = None,
    email: str | None = None,
    api_key: str | None = None,
    grobid_url: str | None = None,
    verbose: bool = False,
    progress_callback: Callable[[str, str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Fetch articles from multiple sources based on SearchConfig.
    
    Args:
        config: SearchConfig with sources and query parameters.
        output_dir: Base directory for output files (used if workspace is None).
        workspace: Optional Workspace for deduplication and file management.
        email: Email for NCBI API (required for pmc source).
        api_key: NCBI API key (optional, for higher rate limits).
        grobid_url: GROBID service URL (required for arxiv, chemrxiv).
        verbose: Enable verbose logging.
        progress_callback: Optional callback(source, article_id, current, total).
    
    Returns:
        Dictionary with statistics:
        {
            "total_fetched": int,
            "total_valid": int,
            "total_incomplete": int,
            "total_errors": int,
            "duplicates_removed": int,
            "duplicates_skipped": int,  # When using workspace
            "per_source": {
                "pmc": {"fetched": int, "valid": int, ...},
                "europepmc": {...},
                ...
            }
        }
    """
```

### Example Usage

```python
from text_fetch import SearchConfig, unified_fetch

config = SearchConfig(
    author="hlavacek ws",
    sources=["pmc", "europepmc"],
    max_results_per_source=50,
)

stats = unified_fetch(
    config=config,
    output_dir="./output",
    email="user@example.com",
    verbose=True,
)

print(f"Fetched {stats['total_fetched']} articles")
print(f"Valid: {stats['total_valid']}, Incomplete: {stats['total_incomplete']}")
print(f"Duplicates removed: {stats['duplicates_removed']}")
```

### Deduplication

```python
from text_fetch import deduplicate_by_doi

# Deduplicate across source directories
result = deduplicate_by_doi(
    output_dir="./output",
    priority=["pmc", "europepmc", "biorxiv", "medrxiv", "arxiv", "chemrxiv"],
)

print(f"Removed {result['removed']} duplicates")
print(f"Unique DOIs: {len(result['unique_dois'])}")
```

---

## Source Clients

### NCBIClient

Client for NCBI E-utilities (PubMed, PMC).

```python
from text_fetch.ncbi import NCBIClient

with NCBIClient(email="user@example.com", api_key="optional") as client:
    # Search PubMed
    pmids = client.esearch_ids("hlavacek ws[au]", db="pubmed", max_results=100)
    
    # Convert PMIDs to PMCIDs
    pmcid_map = client.get_pmcids(pmids)  # {pmid: pmcid}
    
    # Fetch PMC article XML
    xml = client.fetch_pmc_xml("PMC12345")
```

**Methods:**

| Method | Description |
|--------|-------------|
| `esearch_ids(query, db, max_results)` | Search and return ID list |
| `get_pmcids(pmids)` | Convert PMIDs to PMCIDs |
| `fetch_pmc_xml(pmcid)` | Fetch JATS XML for a PMC article |
| `convert_ids(ids, id_type)` | Convert between ID types (doi, pmid, pmcid) |

### EuropePMCClient

Client for Europe PMC REST API.

```python
from text_fetch.europepmc import EuropePMCClient, EuropePMCArticle

client = EuropePMCClient()

# Search
articles = client.search(
    query='AUTH:"hlavacek ws"',
    max_results=100,
    open_access_only=True,
)

# Get by ID
article = client.get_by_pmcid("PMC12345")
article = client.get_by_doi("10.1234/example")

# Download full text
xml = client.get_full_text_xml("PMC12345")
```

**Methods:**

| Method | Description |
|--------|-------------|
| `search(query, max_results, open_access_only)` | Search with Lucene query |
| `get_by_pmcid(pmcid)` | Get article by PMC ID |
| `get_by_pmid(pmid)` | Get article by PubMed ID |
| `get_by_doi(doi)` | Get article by DOI |
| `get_full_text_xml(pmcid)` | Download JATS XML |
| `get_citations(source, identifier)` | Get papers citing this paper |
| `get_references(source, identifier)` | Get papers this paper cites |
| `get_all_citations(source, identifier)` | Get all citations with pagination |
| `get_all_references(source, identifier)` | Get all references with pagination |

### Citation/Reference API (v0.3.0)

Get papers that cite a paper or papers it references:

```python
from text_fetch.europepmc import EuropePMCClient

client = EuropePMCClient()

# Get citations (papers citing this paper)
citations, total = client.get_citations("MED", "32487503")
print(f"Found {total} papers citing this article")
for cite in citations:
    print(f"  - {cite.get('title')} ({cite.get('pubYear')})")

# Get references (papers this paper cites)
references, total = client.get_references("MED", "32487503")
print(f"This paper cites {total} papers")

# Get all with pagination (handles >1000 results)
all_citations = client.get_all_citations("PMC", "PMC7343657", max_results=5000)
all_references = client.get_all_references("PMC", "PMC7343657")
```

**API Parameters:**

| Parameter | Description |
|-----------|-------------|
| `source` | Source database: "MED" (PubMed), "PMC", "PPR" (preprints), etc. |
| `identifier` | Paper ID: PMID for MED, PMCID for PMC (with or without "PMC" prefix) |
| `page` | Page number (1-indexed) |
| `page_size` | Results per page (max 1000) |
| `max_results` | For pagination helpers: limit total results |

### Citation Expansion (v0.3.0)

Expand a corpus by following citation relationships:

```python
from text_fetch.europepmc import (
    EuropePMCClient,
    EuropePMCArticle,
    expand_papers,
    ExpansionResult,
)

client = EuropePMCClient()

# Get seed papers from search
seeds = list(client.iter_search('AUTH:"hlavacek ws"', max_results=50))

# Expand by following both references and citations
result = expand_papers(
    client=client,
    seeds=seeds,
    expand_references=True,
    expand_citations=True,
    depth=1,              # Number of hops (1 = direct only)
    max_expansion=5000,   # Safety cap (0 = unlimited)
)

print(f"Total expanded: {result.total_expanded}")
print(f"References found: {result.expansion_stats['references_found']}")
print(f"Citations found: {result.expansion_stats['citations_found']}")
print(f"Duplicates skipped: {result.expansion_stats['duplicates_skipped']}")

# Access expanded papers by depth
for depth, papers in result.expanded_papers.items():
    print(f"Depth {depth}: {len(papers)} papers")

# Get all papers as flat list
all_papers = result.all_papers
```

**expand_papers() Function:**

```python
def expand_papers(
    client: EuropePMCClient,
    seeds: list[EuropePMCArticle],
    expand_references: bool = False,
    expand_citations: bool = False,
    depth: int = 1,
    max_expansion: int | None = None,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> ExpansionResult:
    """
    Expand seed papers by following citation relationships.
    
    Args:
        client: Europe PMC client instance
        seeds: List of seed papers to expand from
        expand_references: If True, follow references (papers seeds cite)
        expand_citations: If True, follow citations (papers citing seeds)
        depth: Number of expansion hops (1 = direct only)
        max_expansion: Optional cap on total expanded papers
        progress_callback: Optional callback(message, current, total)
        
    Returns:
        ExpansionResult with expanded papers and metadata
    """
```

**ExpansionResult Dataclass:**

```python
@dataclass
class ExpansionResult:
    """Result of citation/reference expansion."""
    
    expanded_papers: dict[int, list[dict]]  # {depth: [paper_dicts]}
    config: dict                            # Expansion options used
    seed_coverage: dict                     # Stats on seeds
    expansion_stats: dict                   # Expansion statistics
    id_issues: dict                         # ID problems encountered
    layers: list[dict]                      # Per-layer summaries
    
    @property
    def total_expanded(self) -> int:
        """Total unique papers found."""
        return sum(len(papers) for papers in self.expanded_papers.values())
    
    @property
    def all_papers(self) -> list[dict]:
        """Flat list of all expanded papers."""
        return [p for papers in self.expanded_papers.values() for p in papers]
    
    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
```

**Seed Coverage (from result.seed_coverage):**

```python
{
    "total_seeds": 127,
    "seeds_with_citations": 98,
    "seeds_with_references": 115,
    "seeds_with_both": 95,
    "seeds_with_neither": 8,
    "citation_coverage_pct": 77.2,
    "reference_coverage_pct": 90.6,
}
```

**Expansion Stats (from result.expansion_stats):**

```python
{
    "references_found": 5234,
    "citations_found": 2156,
    "total_unique": 6890,
    "duplicates_skipped": 500,
}
```

**Query Builder:**

```python
from text_fetch.europepmc import build_query

query = build_query(
    author="hlavacek ws",
    keywords=["systems biology"],
    date_from="2020-01-01",
)
# → 'AUTH:"hlavacek ws" AND ("systems biology") AND FIRST_PDATE:[2020-01-01 TO *]'
```

### BiorxivClient

Client for bioRxiv/medRxiv API.

```python
from text_fetch.biorxiv import BiorxivClient, BiorxivArticle

# bioRxiv
client = BiorxivClient(server="biorxiv")

# medRxiv
client = BiorxivClient(server="medrxiv")

# Search by date range
articles = client.search_by_dates(
    start_date="2024-01-01",
    end_date="2024-01-31",
    max_results=100,
)

# Get by DOI
article = client.get_by_doi("10.1101/2024.01.15.123456")

# Download JATS (if available)
jats_xml = client.download_jats(article)

# Download PDF (fallback)
pdf_bytes = client.download_pdf(article)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `search_by_dates(start_date, end_date, ...)` | Search by date range |
| `get_by_doi(doi)` | Get article by DOI |
| `download_jats(article)` | Download JATS XML |
| `download_pdf(article)` | Download PDF |

**Fetch Functions:**

```python
from text_fetch import fetch_biorxiv, fetch_medrxiv

# Fetch with orchestration
stats = fetch_biorxiv(
    output_dir="./output",
    start_date="2024-01-01",
    end_date="2024-01-31",
    category="systems_biology",
    max_results=100,
    grobid_url="http://localhost:8070",  # For PDF fallback
)

stats = fetch_medrxiv(
    output_dir="./output",
    days=30,  # Recent 30 days
    category="epidemiology",
)
```

### ChemrxivClient

Client for ChemRxiv API.

```python
from text_fetch.chemrxiv import ChemrxivClient, ChemrxivArticle

client = ChemrxivClient()

# Search
articles = client.search(
    term="catalysis",
    category_ids=[123, 456],  # Use get_category_id() for names
    date_from="2024-01-01",
    max_results=50,
)

# Get by item ID
article = client.get_by_item_id("item_2024-abc123")

# Download PDF (no native JATS)
pdf_bytes = client.download_pdf(article)
```

**Category Helpers:**

```python
from text_fetch import get_category_id, get_category_ids, CHEMRXIV_CATEGORIES

# Get single category ID
cat_id = get_category_id("organic_chemistry")

# Get multiple
cat_ids = get_category_ids(["organic_chemistry", "inorganic_chemistry"])

# List all categories
print(CHEMRXIV_CATEGORIES)
```

**Fetch Function:**

```python
from text_fetch import fetch_chemrxiv

stats = fetch_chemrxiv(
    output_dir="./output",
    term="metal organic framework",
    category_ids=get_category_ids(["inorganic_chemistry"]),
    grobid_url="http://localhost:8070",  # Required
    max_results=100,
)
```

---

## GROBID Client

Client for GROBID PDF-to-XML conversion.

### Import

```python
from text_fetch import GROBIDClient, get_default_xslt_path
```

### Usage

```python
from text_fetch import GROBIDClient, get_default_xslt_path

client = GROBIDClient(url="http://localhost:8070")

# Check availability
if not client.is_available():
    print("GROBID is not running!")

# Process PDF to TEI
with open("paper.pdf", "rb") as f:
    tei_xml = client.process_pdf(f.read(), full_text=True)

# Convert TEI to JATS
xslt_path = get_default_xslt_path()  # Bundled stylesheet
jats_xml = client.tei_to_jats(tei_xml, xslt_path)

# Full pipeline
with open("paper.pdf", "rb") as f:
    jats_xml = client.pdf_to_jats(f.read(), xslt_path)
```

**Methods:**

| Method | Description |
|--------|-------------|
| `is_available()` | Check if GROBID service is running |
| `process_pdf(pdf_bytes, full_text)` | Convert PDF to TEI XML |
| `tei_to_jats(tei_xml, xslt_path)` | Convert TEI to JATS via XSLT |
| `pdf_to_jats(pdf_bytes, xslt_path)` | Full pipeline: PDF → TEI → JATS |

---

## PDF Processing

Batch processing of local PDF directories.

### Import

```python
from text_fetch import (
    find_pdfs,
    process_pdf,
    process_pdf_batch,
    PDFProcessingResult,
)
```

### Find PDFs

```python
from text_fetch import find_pdfs

pdfs = find_pdfs("./Manuscripts")
print(f"Found {len(pdfs)} PDF files")
```

### Batch Processing

```python
from text_fetch import process_pdf_batch
from pathlib import Path

def progress(name: str, current: int, total: int) -> None:
    print(f"[{current}/{total}] {name}")

result = process_pdf_batch(
    pdf_dir=Path("./Manuscripts"),
    output_dir=Path("./output"),
    grobid_url="http://localhost:8070",
    prefer_fulltext=True,
    save_tei=True,  # Cache TEI files
    resolve_ncbi=True,  # Lookup PMID/PMCID from DOI
    email="user@example.com",
    progress_callback=progress,
)

print(f"Total: {result['total']}")
print(f"Valid: {result['valid']}")
print(f"Incomplete: {result['incomplete']}")
print(f"Errors: {result['errors']}")
```

### Batch Processing with Workspace

```python
from text_fetch import process_pdf_batch, Workspace
from pathlib import Path

# Load or create workspace
ws = Workspace.load_or_init(Path("./my-corpus"))

result = process_pdf_batch(
    pdf_dir=Path("./Manuscripts"),
    output_dir=Path("./output"),  # Fallback, not used when workspace provided
    workspace=ws,  # Enables DOI deduplication
    grobid_url="http://localhost:8070",
    prefer_fulltext=True,
)

print(f"Total: {result['total']}")
print(f"Valid: {result['valid']}")
print(f"Duplicates skipped: {result.get('duplicates_skipped', 0)}")
```

### Processing Result

```python
from text_fetch import PDFProcessingResult
from text_fetch.pmc import ValidationStatus

result = PDFProcessingResult(
    pdf_path="/path/to/paper.pdf",
    sha1="abc123...",
    tei_path="/path/to/cache/paper.tei.xml",
    jats_path="/path/to/output/paper.jats.xml",
    source="grobid-fulltext",
    validation=ValidationStatus.VALID,
    metadata={"DOI": "10.1234/example", "title": "Paper Title"},
    notes=[],
)

# Convert to dict for JSON serialization
d = result.to_dict()
```

---

## Corpus Workspace

The workspace module provides workspace-based corpus management with cross-search deduplication.

### Import

```python
from text_fetch import (
    Workspace,
    WorkspaceError,
    WorkspaceManifest,
    SearchRecord,
    DOIIndex,
)
```

### Workspace Class

The `Workspace` class manages a corpus directory with DOI deduplication.

**Creating a workspace:**

```python
from text_fetch import Workspace
from pathlib import Path

# Initialize new workspace
ws = Workspace.init(Path("./my-corpus"), name="My Research Corpus")

# Load existing workspace
ws = Workspace.load(Path("./my-corpus"))

# Load or initialize (convenient for scripts)
ws = Workspace.load_or_init(Path("./my-corpus"), name="My Research Corpus")
```

**Adding files:**

```python
# Add a valid JATS file
path = ws.add_file(
    jats_content="<article>...</article>",
    doi="10.1234/example",
    source="europepmc",
    search_id="search_001",
    is_valid=True,
)

if path is None:
    print("Duplicate DOI - skipped")
else:
    print(f"Saved to: {path}")

# Add an incomplete file
ws.add_file(
    jats_content="<article>...</article>",
    doi="10.5678/incomplete",
    source="pmc",
    search_id="search_001",
    is_valid=False,
)
```

**Recording searches:**

```python
# Record a search execution
search_id = ws.record_search(
    config={"author": "hlavacek ws", "source": "europepmc"},
    command="text-fetch europepmc fetch --author 'hlavacek ws'",
    stats={"fetched": 10, "valid": 8, "incomplete": 2},
)
print(f"Recorded as: {search_id}")  # "search_001"
```

**Checking DOIs:**

```python
# Check if DOI exists (case-insensitive)
if ws.has_doi("10.1234/example"):
    print("Already in workspace")
```

**Getting statistics:**

```python
stats = ws.get_statistics()
print(f"Name: {stats['name']}")
print(f"Total searches: {stats['total_searches']}")
print(f"Valid files: {stats['total_valid']}")
print(f"Incomplete files: {stats['total_incomplete']}")
print(f"Unique DOIs: {stats['unique_dois']}")
print(f"Duplicates skipped: {stats['duplicates_skipped']}")
```

**Getting search history:**

```python
searches = ws.get_searches()
for search in searches:
    print(f"{search.id}: {search.command}")
    print(f"  Fetched: {search.statistics.get('fetched', 0)}")
```

**Building tarball:**

```python
from pathlib import Path

stats = ws.build_tarball(
    output_path=Path("./corpus.tar.gz"),
    include_incomplete=False,
)

print(f"Files included: {stats['files_included']}")
print(f"Bytes: {stats['bytes']}")
```

**Clearing workspace:**

```python
# Clear files but keep search history
ws.clear(keep_history=True)

# Full reset
ws.clear(keep_history=False)
```

### DOIIndex Class

Fast DOI lookup for deduplication.

```python
from text_fetch import DOIIndex
from pathlib import Path

# Create or load index
index = DOIIndex(Path(".text-fetch/doi_index.json"))

# Add DOI
index.add(
    doi="10.1234/example",
    file_path="valid/pmc_10.1234_example.xml",
    source="pmc",
    search_id="search_001",
)

# Check existence (case-insensitive)
if index.contains("10.1234/EXAMPLE"):
    print("Found!")

# Get metadata
info = index.get("10.1234/example")
if info:
    print(f"File: {info['file']}")
    print(f"Source: {info['source']}")
    print(f"Added: {info['added']}")

# Remove
index.remove("10.1234/example")

# Iterate
for doi in index:
    print(doi)

# Clear all
index.clear()
```

### WorkspaceManifest Dataclass

Workspace metadata stored in `.text-fetch/workspace.json`.

```python
from text_fetch import WorkspaceManifest

manifest = WorkspaceManifest(
    version="1.0",
    created="2025-01-22T12:00:00",
    updated="2025-01-22T14:30:00",
    name="my-corpus",
    statistics={
        "total_searches": 3,
        "total_valid": 100,
        "total_incomplete": 5,
    },
)

# Convert to/from dict
data = manifest.to_dict()
manifest = WorkspaceManifest.from_dict(data)
```

### SearchRecord Dataclass

Individual search execution record.

```python
from text_fetch import SearchRecord

record = SearchRecord(
    id="search_001",
    timestamp="2025-01-22T12:00:00",
    config={"author": "hlavacek ws"},
    command="text-fetch europepmc fetch --author 'hlavacek ws'",
    statistics={"fetched": 10, "valid": 8},
)

# Convert to/from dict
data = record.to_dict()
record = SearchRecord.from_dict(data)
```

### Workspace Directory Structure

```
my-corpus/
├── .text-fetch/
│   ├── workspace.json     # Workspace manifest
│   ├── searches/          # Search history
│   │   ├── search_001.json
│   │   └── search_002.json
│   └── doi_index.json     # DOI → location mapping
├── valid/
│   ├── pmc_10.1234_example.xml
│   └── europepmc_PMC123456.xml
├── incomplete/
│   └── biorxiv_10.1101_2024.01.xml
└── manifest.json          # Standard manifest
```

### Error Handling

```python
from text_fetch import Workspace, WorkspaceError

try:
    ws = Workspace.load(Path("./not-a-workspace"))
except WorkspaceError as e:
    print(f"Error: {e}")  # "Not a workspace: ./not-a-workspace"

try:
    Workspace.init(Path("./existing-workspace"))
except WorkspaceError as e:
    print(f"Error: {e}")  # "Workspace already exists: ./existing-workspace"
```

---

## Utilities

### JATS Validation

```python
from text_fetch.pmc import JATSValidator, ValidationStatus

validator = JATSValidator(body_min_chars=1000)

# Validate XML string
result = validator.validate(xml_content)

print(f"Status: {result.status}")  # VALID, INCOMPLETE, or INVALID
print(f"Has title: {result.has_title}")
print(f"Has abstract: {result.has_abstract}")
print(f"Has body: {result.has_body}")
print(f"Body chars: {result.body_chars}")
print(f"Errors: {result.errors}")

# Validate file
result = validator.validate_file("article.xml")
```

### Common Utilities

```python
from text_fetch.common import (
    clean,
    sha1_of_file,
    sha1_of_bytes,
    create_tarball,
    extract_doi_from_text,
    extract_search_config_from_tarball,
    RateLimiter,
)

# Clean text
text = clean("  Multiple   spaces  \n\n  ", normalize_unicode=True)

# Hash files
hash_str = sha1_of_file("/path/to/file.pdf")
hash_str = sha1_of_bytes(b"content")

# Create tarball
create_tarball("./output", "corpus.tar.gz")

# Extract DOI from text
doi = extract_doi_from_text("See https://doi.org/10.1234/example for details")

# Extract search config from existing tarball (for reproducibility)
from pathlib import Path
config_data = extract_search_config_from_tarball(Path("corpus.tar.gz"))
if config_data:
    print(f"Author: {config_data.get('author')}")
    print(f"Sources: {config_data.get('sources')}")
    # Use with SearchConfig.from_dict() to re-run the fetch

# Rate limiting
limiter = RateLimiter(max_per_sec=3.0)
limiter.wait()  # Blocks if called too frequently
```

### Configuration

```python
from text_fetch.config import (
    load_config,
    get_ncbi_email,
    get_ncbi_api_key,
    get_grobid_url,
)

# Load from text-fetch.toml
config = load_config()

# Resolve with priority (CLI > env > config)
email = get_ncbi_email(cli_value=None, config=config)
api_key = get_ncbi_api_key(cli_value=None, config=config)
grobid = get_grobid_url(cli_value=None, config=config)
```

---

## Available Sources

| Source | Constant | Native JATS? | Requires GROBID? |
|--------|----------|--------------|------------------|
| PMC | `"pmc"` | ✅ Yes | No |
| Europe PMC | `"europepmc"` | ✅ Yes | No |
| bioRxiv | `"biorxiv"` | ✅ Yes (mostly) | Fallback |
| medRxiv | `"medrxiv"` | ✅ Yes (mostly) | Fallback |
| arXiv | `"arxiv"` | ❌ No | Yes |
| ChemRxiv | `"chemrxiv"` | ❌ No | Yes |

```python
from text_fetch import ALL_SOURCES

print(ALL_SOURCES)
# ['pmc', 'europepmc', 'biorxiv', 'medrxiv', 'arxiv', 'chemrxiv']
```

---

## Error Handling

```python
from text_fetch import SearchConfigError

try:
    config = SearchConfig.from_json("invalid.json")
except SearchConfigError as e:
    print(f"Config error: {e}")

# Source-specific errors are typically logged, not raised
# Check stats['errors'] in return values
```

---

## Corpus Comparison

Compare two corpora to measure overlap and evaluate coverage (v0.3.1).

### Import

```python
from text_fetch.compare import (
    compare_corpora,
    ComparisonResult,
    detect_id_type,
    normalize_id,
    parse_id_list,
    extract_ids_from_tarball,
    load_corpus_ids,
)
```

### compare_corpora()

Compare two corpora and compute overlap metrics.

```python
from text_fetch.compare import compare_corpora
from pathlib import Path

result = compare_corpora(
    reference_path=Path("expert_corpus.txt"),
    candidate_path=Path("auto_corpus.tar.gz"),
    reference_label="Expert (2024)",
    candidate_label="Auto-generated",
)

# Access metrics
print(f"Jaccard similarity: {result.jaccard:.2f}")
print(f"Recall: {result.recall:.2f}")
print(f"Precision: {result.precision:.2f}")

# Access paper counts
print(f"Reference papers: {len(result.reference_ids)}")
print(f"Candidate papers: {len(result.candidate_ids)}")
print(f"Overlap: {len(result.overlap)}")

# Papers unique to each corpus
print(f"Reference only: {len(result.reference_only)}")
print(f"Candidate only: {len(result.candidate_only)}")

# Export to JSON
output_dict = result.to_dict()
```

**Function Signature:**

```python
def compare_corpora(
    reference_path: Path,
    candidate_path: Path,
    reference_label: str | None = None,
    candidate_label: str | None = None,
) -> ComparisonResult:
    """Compare two corpora and compute overlap metrics.
    
    Args:
        reference_path: Path to reference corpus (tarball or ID list)
        candidate_path: Path to candidate corpus (tarball or ID list)
        reference_label: Optional label for reference corpus (default: filename)
        candidate_label: Optional label for candidate corpus (default: filename)
    
    Returns:
        ComparisonResult with metrics and ID sets
    """
```

### ComparisonResult

Dataclass containing comparison results.

```python
from text_fetch.compare import ComparisonResult

# Fields
result.reference_label      # Display label for reference corpus
result.reference_source     # Path to reference file
result.reference_ids        # Set of normalized IDs from reference
result.reference_id_types   # Dict of ID type counts {"pmcid": N, "doi": N, ...}

result.candidate_label      # Display label for candidate corpus
result.candidate_source     # Path to candidate file
result.candidate_ids        # Set of normalized IDs from candidate
result.candidate_id_types   # Dict of ID type counts

result.overlap              # Set of IDs in both corpora
result.reference_only       # Set of IDs only in reference
result.candidate_only       # Set of IDs only in candidate
result.normalized           # Whether NCBI ID normalization was applied

# Computed properties
result.jaccard              # |A ∩ B| / |A ∪ B|
result.recall               # |A ∩ B| / |Reference|
result.precision            # |A ∩ B| / |Candidate|

# Serialization
output_dict = result.to_dict()
```

**to_dict() output format:**

```python
{
    "metadata": {
        "text_fetch_version": "0.3.1",
        "timestamp": "2026-01-25T10:30:00Z",
        "normalized": False,
    },
    "reference": {
        "label": "Expert (2024)",
        "source": "expert_corpus.txt",
        "count": 312,
        "id_types": {"pmcid": 280, "doi": 30, "pmid": 2, "unknown": 0},
    },
    "candidate": {
        "label": "Auto-generated",
        "source": "auto_corpus.tar.gz",
        "count": 2847,
        "id_types": {"pmcid": 2500, "doi": 347, "pmid": 0, "unknown": 0},
    },
    "overlap": {
        "count": 287,
        "jaccard": 0.10,
        "recall": 0.92,
        "precision": 0.10,
    },
    "reference_only": ["PMC111111", "PMC222222"],
    "candidate_only": ["PMC333333", "PMC444444"],
}
```

### ID Detection and Normalization

```python
from text_fetch.compare import detect_id_type, normalize_id

# Detect ID type
detect_id_type("PMC123456")        # → "pmcid"
detect_id_type("pmc123456")        # → "pmcid" (case-insensitive)
detect_id_type("10.1234/example")  # → "doi"
detect_id_type("32847729")         # → "pmid" (7+ digits)
detect_id_type("abc123")           # → "unknown"

# Normalize IDs for comparison
normalize_id("pmc123456")          # → "PMC123456" (uppercase)
normalize_id("10.1234/EXAMPLE")    # → "10.1234/example" (lowercase)
normalize_id("32847729")           # → "32847729" (unchanged)
```

### Loading Corpus IDs

```python
from text_fetch.compare import (
    load_corpus_ids,
    parse_id_list,
    extract_ids_from_tarball,
)
from pathlib import Path

# Auto-detect format and load
ids, type_counts = load_corpus_ids(Path("corpus.tar.gz"))
ids, type_counts = load_corpus_ids(Path("ids.txt"))

# Load from text file explicitly
ids, type_counts = parse_id_list(Path("ids.txt"))
# type_counts = {"pmcid": 50, "doi": 30, "pmid": 5, "unknown": 2}

# Extract from tarball explicitly
ids, type_counts = extract_ids_from_tarball(Path("corpus.tar.gz"))
```

**ID List File Format:**

```
# corpus_ids.txt
PMC123456
PMC789012
10.1016/j.cell.2020.01.001
32847729
# Comments (lines starting with #) are ignored
# Blank lines are ignored
```

**Tarball ID Extraction:**

IDs are extracted from `manifest.json` inside the tarball with priority:
1. PMCID (if present in manifest entry)
2. DOI (if no PMCID)
3. Filename parsing (fallback if no manifest or IDs)

### Metrics Interpretation

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **Jaccard** | \|A ∩ B\| / \|A ∪ B\| | Overall similarity (0-1), accounts for corpus size differences |
| **Recall** | \|A ∩ B\| / \|Reference\| | Fraction of reference found in candidate |
| **Precision** | \|A ∩ B\| / \|Candidate\| | Fraction of candidate that is in reference |

**Typical auto vs expert comparison:**
- High recall (~0.9) = Auto found most expert papers ✓
- Low precision (~0.1) = Auto found many additional papers (expected for expansion)
- Low Jaccard = Corpus sizes differ significantly

### CLI Usage

```bash
# Basic comparison with JSON output
text-fetch compare \
  -r expert_corpus.txt \
  -c auto_corpus.tar.gz \
  -o comparison.json

# Pretty-print to stdout
text-fetch compare \
  -r corpus_a.tar.gz \
  -c corpus_b.tar.gz

# With custom labels
text-fetch compare \
  -r snowball_d1.tar.gz \
  -c snowball_d2.tar.gz \
  --ref-label "Depth 1" \
  --cand-label "Depth 2"
```

---

## See Also

- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — Development setup and conventions
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture overview
