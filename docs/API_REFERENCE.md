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
7. [Utilities](#utilities)

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

## See Also

- [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md) — Development setup and conventions
- [ARCHITECTURE.md](ARCHITECTURE.md) — System architecture overview
- [ROADMAP.md](ROADMAP.md) — Project roadmap and future plans
