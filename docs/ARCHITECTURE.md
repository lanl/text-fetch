# text-fetch Architecture

This document describes the architecture and design of text-fetch, a tool for acquiring and converting scientific literature to JATS XML format.

## Overview

text-fetch is a data acquisition utility that sits upstream of [litkit](https://github.com/lanl/litkit) in the RAG pipeline. It fetches scientific papers from various sources, converts them to a standard JATS XML format, and packages them into tar archives for downstream processing.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              text-fetch                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                     │
│  │  User PDFs   │   │    PubMed    │   │   Preprint   │                     │
│  │              │   │   Central    │   │   Archives   │                     │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                     │
│         │                  │                  │                              │
│         ▼                  ▼                  ▼                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐                     │
│  │    GROBID    │   │  Direct XML  │   │ GROBID/XML   │                     │
│  │   (Docker)   │   │   Download   │   │   Hybrid     │                     │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                     │
│         │                  │                  │                              │
│         ▼                  │                  │                              │
│  ┌──────────────┐          │                  │                              │
│  │   TEI XML    │          │                  │                              │
│  └──────┬───────┘          │                  │                              │
│         │                  │                  │                              │
│         ▼                  │                  │                              │
│  ┌──────────────┐          │                  │                              │
│  │ XSLT Transform│         │                  │                              │
│  │ (tei2jats.xsl)│         │                  │                              │
│  └──────┬───────┘          │                  │                              │
│         │                  │                  │                              │
│         └──────────────────┴──────────────────┘                              │
│                            │                                                 │
│                            ▼                                                 │
│                     ┌──────────────┐                                         │
│                     │   JATS XML   │                                         │
│                     │    Cache     │                                         │
│                     └──────┬───────┘                                         │
│                            │                                                 │
│                            ▼                                                 │
│                     ┌──────────────┐                                         │
│                     │ Tar Archive  │                                         │
│                     │   + CSV      │                                         │
│                     └──────────────┘                                         │
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

## Data Sources

### 1. User PDFs (v0.1.0)

Local PDF files are processed through the GROBID pipeline:

```
PDF → GROBID → TEI XML → XSLT → JATS XML
```

**Components:**
- **GROBID**: Machine learning library for document parsing (runs in Docker)
- **TEI XML**: Intermediate format produced by GROBID
- **XSLT Stylesheet**: `tei2jats.xsl` transforms TEI to JATS

### 2. PubMed Central (v0.1.1 — Planned)

PMC provides JATS/NXML directly for open-access content:

```
JSON Search Config → NCBI E-utilities → PMID List → PMC ID Converter → JATS/NXML
```

**Components:**
- **Search Configuration**: JSON files defining search parameters
- **E-utilities**: NCBI's web API (esearch, efetch)
- **ID Converter**: Maps PMIDs to PMCIDs
- **OA Service**: Downloads full-text XML

### 3. Preprint Archives (v0.2.x — Planned)

Mixed approach depending on source:

| Source | Full-text Format | Strategy |
|--------|------------------|----------|
| arXiv | PDF (+ LaTeX) | PDF → GROBID → JATS |
| bioRxiv | JATS XML | Direct download |
| medRxiv | JATS XML | Direct download |
| ChemRxiv | PDF | PDF → GROBID → JATS |

## Core Components

### PDF Processing (`pdf_to_jats.py`)

The main entry point for PDF processing:

```python
# Key functions
grobid_process()      # Send PDF to GROBID, get TEI
parse_tei_fields()    # Extract metadata from TEI
tei_to_jats()         # XSLT transformation
create_tarball()      # Package output
```

**Processing flow:**
1. Scan directory for PDFs
2. Compute SHA1 hash for cache key
3. Check TEI cache; call GROBID if miss
4. Parse TEI for metadata (author, title, DOI, etc.)
5. Optionally resolve PMID/PMCID via NCBI
6. Transform TEI → JATS via XSLT
7. Write to cache and CSV index
8. Create tar.gz archive

### Caching Strategy

Content-addressable caching using SHA1 hashes:

```
<basename>.<sha1>.tei.xml   # TEI cache
<basename>.<sha1>.jats.xml  # JATS cache
```

**Benefits:**
- Unchanged PDFs are never reprocessed
- Cache is portable (based on content, not path)
- Easy to identify duplicate content

### External Services

| Service | Purpose | Rate Limit |
|---------|---------|------------|
| GROBID | PDF → TEI extraction | Local (unlimited) |
| NCBI E-utilities | PubMed search, ID conversion | 3 req/sec (with API key) |
| NCBI idconv | DOI → PMID/PMCID | 3 req/sec |

Rate limiting is handled by the `RateLimiter` class.

## Directory Structure

```
text-fetch/
├── pdf_to_jats.py       # Main CLI script
├── tei2jats.xsl         # XSLT stylesheet
├── pyproject.toml       # Project configuration
├── requirements.txt     # Dependencies
├── input/               # Search configuration files (gitignored)
│   └── *.json
├── Manuscripts/         # Input PDFs (gitignored)
├── tei_cache/           # TEI XML cache
├── jats_cache/          # JATS XML cache
└── docs/
    ├── ROADMAP.md
    ├── ARCHITECTURE.md
    └── DEVELOPER_GUIDE.md
```

## Output Formats

### CSV Index

Metadata index with columns:
- `first_author`, `year`, `title`, `journal`
- `DOI`, `PMID`, `PMCID`
- `file_path`, `tei_path`, `jats_path`
- `source`, `notes`

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

### Tar Archives

Uncompressed `.tar` files (or `.tar.gz` for transfer) containing JATS XML files:

```bash
# Structure expected by litkit
archive.tar
├── paper1.jats.xml
├── paper2.jats.xml
└── ...
```

## Integration with litkit

litkit expects tar archives containing JATS/NXML files:

```bash
# text-fetch produces
python pdf_to_jats.py Manuscripts --save-jats --create-tarball

# litkit consumes
litkit --build-only --faiss-writer --tar-dir workspace/tar_shards
```

**Key requirements:**
- JATS XML with `<front>` (metadata) and `<body>` (full text)
- Abstract in `<abstract>` element for Stage 1 indexing
- Body paragraphs in `<p>` elements for Stage 2 chunking
- No duplicate papers (text-fetch is responsible for deduplication)

## Error Handling

| Error Type | Handling |
|------------|----------|
| GROBID connection failure | Retry with fallback to pdfminer for DOI |
| TEI parse error | Log to `notes` column, continue processing |
| XSLT transformation failure | Log error, skip JATS generation |
| NCBI API error | Log warning, proceed without IDs |
| Rate limit exceeded | Wait and retry |

## Configuration

### Command-line Arguments

```bash
python pdf_to_jats.py <pdf_root> \
  --out <csv_path> \
  --grobid-url http://localhost:8070 \
  --prefer-fulltext \
  --save-tei --tei-out tei_cache \
  --save-jats --jats-out jats_cache \
  --resolve-ncbi --email user@example.com \
  --create-tarball --tarball-name output.tar.gz
```

### Environment Variables (Planned)

```bash
TEXT_FETCH_GROBID_URL=http://localhost:8070
TEXT_FETCH_NCBI_EMAIL=user@example.com
TEXT_FETCH_OUTPUT_DIR=./output
```

## Dependencies

### Python Packages

| Package | Purpose |
|---------|---------|
| requests | HTTP client for GROBID and NCBI |
| lxml | XML parsing and XSLT transformation |
| pdfminer-six | Fallback DOI extraction |
| unidecode | Unicode normalization |

### External Services

| Service | Requirement |
|---------|-------------|
| GROBID | Docker container (`lfoppiano/grobid:0.7.2`) |
| NCBI E-utilities | Internet access, optional API key |

## Security Considerations

- API keys should be stored securely (environment variables or files with restricted permissions)
- GROBID runs locally, no data leaves the machine
- NCBI requests include email for identification per their guidelines
- No authentication data in CSV output or logs
