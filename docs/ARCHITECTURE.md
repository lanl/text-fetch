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
│   ├── cli.py            # Click-based CLI (main entry point)
│   ├── config.py         # TOML configuration handling
│   ├── common.py         # Shared utilities (RateLimiter, clean, sha1_of_file)
│   ├── grobid.py         # GROBIDClient for PDF→TEI→JATS
│   ├── arxiv.py          # ArxivClient and fetch_arxiv orchestrator
│   ├── ncbi.py           # NCBIClient for E-utilities
│   ├── pmc.py            # PMC fetching and JATS validation
│   ├── pmc_oa.py         # PMC Open Access corpus sync
│   ├── query.py          # SearchConfig and query builders
│   └── pdf.py            # Legacy PDF processing functions
├── pdf_to_jats.py        # Legacy standalone script
├── tei2jats.xsl          # XSLT stylesheet
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

### 4. bioRxiv/medRxiv (v0.1.3 — Planned)

Mixed approach depending on source:

| Source | Full-text Format | Strategy |
|--------|------------------|----------|
| bioRxiv | JATS XML | Direct download (with PDF fallback) |
| medRxiv | JATS XML | Direct download (with PDF fallback) |
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
    
    def to_pubmed_query(self) -> str: ...
    def to_arxiv_query(self) -> str: ...
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
