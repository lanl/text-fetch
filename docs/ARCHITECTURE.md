# text-fetch Architecture

This document describes the architecture and design of text-fetch, a tool for acquiring and converting scientific literature to JATS XML format.

## Overview

text-fetch is a data acquisition utility that sits upstream of [litkit](https://github.com/lanl/litkit) in the RAG pipeline. It fetches scientific papers from various sources, converts them to a standard JATS XML format, and packages them for downstream processing.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              text-fetch                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │  User PDFs   │   │    PubMed    │   │    arXiv     │   │   Preprint   │  │
│  │              │   │   Central    │   │  (v0.1.2)    │   │   Archives   │  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘  │
│         │                  │                  │                  │          │
│         ▼                  ▼                  ▼                  ▼          │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │    GROBID    │   │  Direct XML  │   │    GROBID    │   │ GROBID/XML   │  │
│  │   (Docker)   │   │   Download   │   │   Pipeline   │   │   Hybrid     │  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘   └──────┬───────┘  │
│         │                  │                  │                  │          │
│         ▼                  │                  ▼                  │          │
│  ┌──────────────┐          │           ┌──────────────┐          │          │
│  │   TEI XML    │          │           │   TEI XML    │          │          │
│  └──────┬───────┘          │           └──────┬───────┘          │          │
│         │                  │                  │                  │          │
│         ▼                  │                  ▼                  │          │
│  ┌──────────────┐          │           ┌──────────────┐          │          │
│  │ XSLT Transform│         │           │ XSLT Transform│         │          │
│  │ (tei2jats.xsl)│         │           │ (tei2jats.xsl)│         │          │
│  └──────┬───────┘          │           └──────┬───────┘          │          │
│         │                  │                  │                  │          │
│         └──────────────────┴──────────────────┴──────────────────┘          │
│                            │                                                 │
│                            ▼                                                 │
│                     ┌──────────────┐                                         │
│                     │   JATS XML   │                                         │
│                     │  Validation  │                                         │
│                     └──────┬───────┘                                         │
│                            │                                                 │
│                            ▼                                                 │
│               ┌────────────┴────────────┐                                    │
│               ▼                         ▼                                    │
│        ┌──────────────┐          ┌──────────────┐                            │
│        │    valid/    │          │  incomplete/ │                            │
│        └──────────────┘          └──────────────┘                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │       litkit         │
                        │  (Vector Indexing)   │
                        └──────────────────────┘
                                    │
                                    ▼
                        ┌──────────────────────┐
                        │       chatty         │
                        │   (RAG Queries)      │
                        └──────────────────────┘
```

## Package Structure

```
text-fetch/
├── src/text_fetch/
│   ├── __init__.py       # Package exports
│   ├── cli/              # CLI package (v0.2.6 - refactored from cli.py)
│   │   ├── __init__.py   # Main CLI group + config command (~70 lines)
│   │   ├── _common.py    # Shared helpers (handle_tarball_creation)
│   │   ├── pdf.py        # PDF batch commands (~150 lines)
│   │   ├── pmc.py        # PMC commands (~500 lines)
│   │   ├── arxiv.py      # arXiv commands (~150 lines)
│   │   ├── biorxiv.py    # bioRxiv commands (~190 lines)
│   │   ├── medrxiv.py    # medRxiv commands (~190 lines)
│   │   ├── chemrxiv.py   # ChemRxiv commands (~200 lines)
│   │   ├── europepmc.py  # Europe PMC commands (~220 lines)
│   │   ├── fetch.py      # Unified fetch command (~270 lines)
│   │   ├── workspace.py  # Workspace commands (~440 lines)
│   │   └── tarball.py    # Tarball commands (~220 lines)
│   ├── config.py         # TOML configuration handling
│   ├── common.py         # Shared utilities (RateLimiter, clean, sha1_of_file)
│   ├── fetch.py          # Unified multi-source fetch orchestrator (v0.1.6)
│   ├── query.py          # SearchConfig and query builders
│   ├── checkpoint.py     # Resume checkpoint handling (v0.2.3)
│   ├── workspace.py      # Workspace corpus management (v0.2.0)
│   ├── grobid.py         # GROBIDClient for PDF→TEI→JATS
│   ├── ncbi.py           # NCBIClient for E-utilities
│   ├── pmc.py            # PMC fetching and JATS validation
│   ├── pmc_oa.py         # PMC Open Access corpus sync
│   ├── europepmc.py      # EuropePMCClient for Europe PMC (v0.1.5)
│   ├── arxiv.py          # ArxivClient and fetch_arxiv orchestrator
│   ├── biorxiv.py        # BiorxivClient for bioRxiv/medRxiv (v0.1.3)
│   ├── chemrxiv.py       # ChemrxivClient for ChemRxiv (v0.1.4)
│   ├── pdf.py            # PDF batch processing via GROBID
│   └── data/
│       └── tei2jats.xsl  # TEI→JATS XSLT stylesheet
├── scripts/
│   ├── start_grobid.sh   # GROBID Docker startup script
│   └── legacy/           # Archived legacy scripts
├── tests/                # Test suite
└── docs/                 # Documentation
```

## Data Sources

### 1. User PDFs (v0.1.0)

Local PDF files are processed through the GROBID pipeline:

```
PDF → GROBID → TEI XML → XSLT → JATS XML
```

**Components:**
- **GROBIDClient** (`grobid.py`): Sends PDFs to GROBID, handles TEI→JATS conversion
- **TEI XML**: Intermediate format produced by GROBID
- **XSLT Stylesheet**: `tei2jats.xsl` transforms TEI to JATS

### 2. PubMed Central (v0.1.1)

PMC provides JATS/NXML directly for open-access content:

```
JSON Search Config → NCBI E-utilities → PMID List → PMC ID Converter → JATS/NXML
```

**Components:**
- **SearchConfig** (`query.py`): JSON/dict configuration for searches
- **NCBIClient** (`ncbi.py`): E-utilities API wrapper
- **JATSValidator** (`pmc.py`): Validates and sorts downloaded articles
- **PMCOAClient** (`pmc_oa.py`): Bulk download of OA corpus

### 3. arXiv (v0.1.2)

arXiv preprints are downloaded as PDFs and converted via GROBID:

```
arXiv Query → ArxivClient → PDF Download → GROBID → TEI → XSLT → JATS
```

**Components:**
- **ArxivClient** (`arxiv.py`): Searches arXiv API, downloads PDFs
- **GROBIDClient** (`grobid.py`): Converts PDFs to JATS
- **fetch_arxiv()**: Orchestrates the full pipeline

### 4. bioRxiv/medRxiv (v0.1.3)

Direct JATS download with PDF fallback:

```
bioRxiv API → BiorxivClient → Direct JATS or PDF → GROBID → JATS
```

**Components:**
- **BiorxivClient** (`biorxiv.py`): Date-based search, DOI lookup, JATS/PDF download
- **fetch_biorxiv()** / **fetch_medrxiv()**: Orchestrators for each server

### 5. ChemRxiv (v0.1.4)

PDF-only source requiring GROBID:

```
ChemRxiv API → ChemrxivClient → PDF Download → GROBID → TEI → XSLT → JATS
```

**Components:**
- **ChemrxivClient** (`chemrxiv.py`): Search, item lookup, PDF download
- **fetch_chemrxiv()**: Orchestrates the full pipeline

### 6. Europe PMC (v0.1.5)

Native JATS access without GROBID:

```
Europe PMC REST API → EuropePMCClient → JATS/NXML
```

**Components:**
- **EuropePMCClient** (`europepmc.py`): Lucene query syntax, cursor pagination
- **fetch_europepmc()**: Orchestrates search and download

### 7. Unified Multi-Source Fetch (v0.1.6)

Single command to fetch from multiple sources:

```
JSON Config → unified_fetch() → [per-source fetchers] → deduplicate_by_doi() → Output
```

**Components:**
- **unified_fetch()** (`fetch.py`): Orchestrates fetching from multiple sources
- **deduplicate_by_doi()** (`fetch.py`): Removes duplicate DOIs across sources

| Source | Full-text Format | Strategy |
|--------|------------------|----------|
| PMC | JATS XML | Direct download |
| Europe PMC | JATS XML | Direct download |
| bioRxiv | JATS XML | Direct (PDF fallback) |
| medRxiv | JATS XML | Direct (PDF fallback) |
| arXiv | PDF | PDF → GROBID → JATS |
| ChemRxiv | PDF | PDF → GROBID → JATS |

## Core Modules

### CLI (`cli.py`)

The main entry point using Click framework:

```python
# Command groups
text-fetch pmc fetch     # Fetch from PMC via E-utilities
text-fetch pmc sync      # Sync PMC OA corpus
text-fetch arxiv fetch   # Fetch from arXiv
text-fetch pdf           # Process local PDFs
text-fetch config        # Show configuration
```

### Configuration (`config.py`)

TOML-based configuration with priority resolution:

```python
# Priority: CLI > env vars > config file > defaults
config = load_config()
email = get_ncbi_email(cli_value=None, config=config)
```

**Config locations:**
1. `./text-fetch.toml` (project directory)
2. `~/.config/text-fetch/config.toml` (user config)

### GROBID Client (`grobid.py`)

Handles all GROBID interactions:

```python
class GROBIDClient:
    def is_available(self) -> bool: ...
    def process_pdf(self, pdf_bytes, header_only=False) -> str | None: ...
    def tei_to_jats(self, tei_xml, xslt_path) -> str | None: ...
    def pdf_to_jats(self, pdf_bytes, xslt_path) -> str | None: ...
```

### arXiv Client (`arxiv.py`)

Searches and downloads from arXiv:

```python
@dataclass
class ArxivArticle:
    arxiv_id: str
    title: str
    authors: list[str]
    abstract: str
    categories: list[str]
    published: datetime
    pdf_url: str | None

class ArxivClient:
    def search(self, query, max_results=100) -> list[ArxivArticle]: ...
    def download_pdf(self, article) -> bytes | None: ...

def build_query(author=None, categories=None, ...) -> str: ...
def fetch_arxiv(config=None, query=None, ...) -> dict[str, Any]: ...
```

### NCBI Client (`ncbi.py`)

Wraps NCBI E-utilities API:

```python
class NCBIClient:
    def esearch(self, query, db="pubmed") -> dict: ...
    def esearch_ids(self, query) -> list[str]: ...
    def get_pmcids(self, pmids) -> dict[str, str]: ...
    def fetch_pmc_xml(self, pmcid) -> str | None: ...
```

### PMC Module (`pmc.py`)

JATS validation and article saving:

```python
class JATSValidator:
    def validate(self, xml_content) -> ValidationResult: ...

def save_pmc_article(pmcid, xml_content, output_dir, ...) -> tuple: ...
def fetch_pmc(config=None, query=None, ...) -> dict[str, Any]: ...
```

### Query Builder (`query.py`)

Search configuration with multi-database support:

```python
@dataclass
class SearchConfig:
    author: str | None
    keywords: list[str]
    date_range: DateRange | None
    arxiv_categories: list[str]  # For arXiv searches
    sources: list[str]           # For unified fetch (v0.1.6)
    source_options: dict[str, SourceOptions]  # Per-source config
    
    def to_pubmed_query(self) -> str: ...
    def to_arxiv_query(self) -> str: ...
    def to_europepmc_query(self) -> str: ...  # v0.1.6
    def to_biorxiv_params(self) -> dict: ...  # v0.1.6
    def to_chemrxiv_params(self) -> dict: ... # v0.1.6
```

### Unified Fetch (`fetch.py`)

Multi-source orchestrator (v0.1.6):

```python
def unified_fetch(config, output_dir, ...) -> dict[str, Any]:
    """Fetch from multiple sources using unified config."""
    ...

def deduplicate_by_doi(output_dir) -> dict[str, Any]:
    """Remove duplicate DOIs across sources."""
    ...
```

### Workspace (`workspace.py`)

Corpus workspace management with cross-search deduplication (v0.2.0):

```python
@dataclass
class WorkspaceManifest:
    """Workspace metadata."""
    version: str = "1.0"
    created: str = ""
    updated: str = ""
    name: str = ""
    statistics: dict[str, int] = field(default_factory=dict)

class DOIIndex:
    """Fast DOI lookup for deduplication."""
    def contains(self, doi: str) -> bool: ...
    def add(self, doi: str, file_path: str, source: str, search_id: str) -> None: ...
    def remove(self, doi: str) -> None: ...

class Workspace:
    """Manages a corpus workspace directory."""
    @classmethod
    def init(cls, path: Path, name: str | None = None) -> "Workspace": ...
    @classmethod
    def load(cls, path: Path) -> "Workspace": ...
    @classmethod
    def load_or_init(cls, path: Path, name: str | None = None) -> "Workspace": ...
    
    def has_doi(self, doi: str) -> bool: ...
    def add_file(self, jats_content: str, doi: str | None, source: str, 
                 search_id: str, is_valid: bool) -> Path | None: ...
    def record_search(self, config: dict, command: str, stats: dict) -> str: ...
    def build_tarball(self, output_path: Path, include_incomplete: bool = False) -> dict: ...
```

**Workspace directory structure:**
```
my-corpus/
├── .text-fetch/
│   ├── workspace.json     # Workspace manifest
│   ├── searches/          # Search history
│   │   ├── search_001.json
│   │   └── search_002.json
│   └── doi_index.json     # DOI → location mapping
├── valid/                 # Complete JATS files
├── incomplete/            # Incomplete JATS files
└── manifest.json          # Standard manifest
```

## JATS Validation

Downloaded articles are automatically sorted by completeness:

```
output/
├── valid/           # Complete JATS (title + abstract + body≥1000 chars)
│   ├── PMC123456.xml
│   ├── arxiv:2301.12345v1.xml
│   └── ...
├── incomplete/      # Missing required parts
│   ├── PMC789012.xml
│   └── ...
└── manifest.json    # Tracks contents + validation results
```

**Validation criteria for "valid":**
- ✅ Has `<article-title>` (non-empty)
- ✅ Has `<abstract>` (non-empty)
- ✅ Has `<body>` with ≥1000 characters of content

## External Services

| Service | Purpose | Rate Limit | Module |
|---------|---------|------------|--------|
| GROBID | PDF → TEI extraction | Local (unlimited) | `grobid.py` |
| NCBI E-utilities | PubMed search, PMC download | 3-9 req/sec | `ncbi.py` |
| arXiv API | Preprint search | 1 req/3 sec | `arxiv.py` |
| arXiv PDF | PDF download | 1 req/3 sec | `arxiv.py` |
| bioRxiv API | Preprint search | None documented | `biorxiv.py` |
| ChemRxiv API | Preprint search | None documented | `chemrxiv.py` |
| Europe PMC | Article search | None documented | `europepmc.py` |

Rate limiting is handled by the `RateLimiter` class in `common.py`.

## Output Formats

### JATS XML

Standard [JATS](https://jats.nlm.nih.gov/) format compatible with litkit:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE article PUBLIC "-//NLM//DTD JATS (Z39.96) Journal Archiving and Interchange DTD v1.2 20190208//EN"
  "JATS-archivearticle1.dtd">
<article>
  <front>
    <article-meta>
      <title-group><article-title>...</article-title></title-group>
      <contrib-group>...</contrib-group>
      <abstract>...</abstract>
    </article-meta>
  </front>
  <body>
    <sec><p>...</p></sec>
  </body>
</article>
```

### Manifest JSON

Tracks downloaded articles with validation results:

```json
{
  "version": "1.0",
  "updated_at": "2026-01-21T12:00:00Z",
  "statistics": {
    "total": 100,
    "valid": 85,
    "incomplete": 15
  },
  "articles": [
    {
      "pmcid": "PMC123456",
      "filename": "valid/PMC123456.xml",
      "status": "valid",
      "has_title": true,
      "has_abstract": true,
      "has_body": true,
      "body_chars": 25000,
      "saved_at": "2026-01-21T12:00:00Z",
      "sha256": "abc123..."
    }
  ]
}
```

## Integration with litkit

litkit expects directories containing JATS/NXML files:

```bash
# text-fetch produces
text-fetch pmc fetch --query "hlavacek ws[au]" --out ./corpus

# litkit consumes
litkit --build-only --faiss-writer --jats-dir ./corpus/valid
```

**Key requirements:**
- JATS XML with `<front>` (metadata) and `<body>` (full text)
- Abstract in `<abstract>` element for Stage 1 indexing
- Body paragraphs in `<p>` elements for Stage 2 chunking
- No duplicate papers (text-fetch handles deduplication via SHA256)

## Error Handling

| Error Type | Handling |
|------------|----------|
| GROBID unavailable | Raise RuntimeError (arXiv), log warning (PDF) |
| GROBID parse error | Return None, count as error in stats |
| NCBI API error | Retry with exponential backoff, then raise |
| arXiv API error | Log error, return empty list |
| arXiv rate limit | Wait 3 seconds between requests |
| Invalid JATS | Sort to `incomplete/` folder |
| Network timeout | Retry with backoff |

## Dependencies

### Python Packages

| Package | Purpose |
|---------|---------|
| click | CLI framework |
| requests | HTTP client |
| lxml | XML parsing and XSLT |
| tomli | TOML parsing (Python < 3.11) |
| pdfminer-six | Fallback DOI extraction |
| unidecode | Unicode normalization |

### External Services

| Service | Requirement |
|---------|-------------|
| GROBID | Docker container (`lfoppiano/grobid:0.7.2`) |
| NCBI E-utilities | Internet access, optional API key |
| arXiv API | Internet access |

## Security Considerations

- API keys stored in config files should have restricted permissions
- GROBID runs locally, no data leaves the machine for PDF processing
- NCBI requests include email for identification per their guidelines
- No authentication data in manifest or logs
