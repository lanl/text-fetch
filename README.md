# text-fetch

**Acquire scientific literature for RAG pipelines.**

text-fetch provides a unified interface for acquiring full-text scientific literature from multiple sources and converting it to JATS XML format for downstream RAG (Retrieval-Augmented Generation) pipelines. The output is designed for use with [litkit](https://github.com/lanl/litkit) and [chatty](https://github.com/lanl/chatty).

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) package manager (recommended)
- Docker (for GROBID-based PDF processing)

### Install with uv

```bash
# Clone the repository
git clone https://github.com/lanl/text-fetch.git
cd text-fetch

# Install with uv (includes dev dependencies)
uv sync --all-extras

# Verify installation
uv run text-fetch --version
```

## Configuration

text-fetch uses a TOML configuration file. Create `text-fetch.toml` in your project directory or `~/.config/text-fetch/config.toml` for global settings.

```toml
# text-fetch.toml
[ncbi]
email = "your.email@example.com"  # Required for NCBI API
api_key = "your_api_key"          # Optional: higher rate limits

[grobid]
url = "http://localhost:8070"     # GROBID service URL
```

See `text-fetch.example.toml` for a complete example.

Configuration can also be set via environment variables:
- `NCBI_EMAIL` - Email for NCBI API
- `NCBI_API_KEY` - NCBI API key

Priority: CLI options > environment variables > config file

## Commands

### Show Configuration

```bash
text-fetch config
```

### PubMed Central

#### Fetch Articles via E-utilities

Fetch articles by PubMed query:

```bash
text-fetch pmc fetch --query "hlavacek ws[author]" --out ./output
```

#### Sync PMC Open Access Corpus

Download and maintain a local mirror of the PMC Open Access subset:

```bash
# Initial sync (warning: full corpus is ~400GB)
text-fetch pmc sync --storage /Volumes/External/pmc-oa

# Incremental update (only new/modified articles)
text-fetch pmc sync --storage /Volumes/External/pmc-oa --update

# Sync specific subset (oa_comm, oa_noncomm, oa_other)
text-fetch pmc sync --storage ./pmc-oa --subset oa_comm

# Test with limited files
text-fetch pmc sync --storage ./test-pmc --max-files 10 -y
```

**Subsets:**
- `oa_comm` - Commercial use allowed (CC BY, CC0)
- `oa_noncomm` - Non-commercial use only (CC BY-NC)
- `oa_other` - Other open access licenses

### arXiv

Fetch preprints from arXiv (converts PDFs via GROBID):

```bash
# Start GROBID (requires Docker)
./scripts/start_grobid.sh

# Search by author
text-fetch arxiv fetch --query 'au:"hlavacek ws"' --out ./output

# Search by category
text-fetch arxiv fetch --categories q-bio.MN --out ./output

# Search with multiple categories
text-fetch arxiv fetch --categories q-bio.MN --categories cs.AI --out ./output

# Using JSON config
text-fetch arxiv fetch --config-file input/search.json --out ./output
```

### bioRxiv

Fetch preprints from bioRxiv (direct JATS XML when available, falls back to PDF→GROBID):

```bash
# Recent preprints by category
text-fetch biorxiv fetch --days 30 --category systems_biology --out ./output

# Date range
text-fetch biorxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

# Specific DOIs
text-fetch biorxiv fetch --doi 10.1101/2024.01.15.123456 --out ./output

# Multiple DOIs
text-fetch biorxiv fetch --doi 10.1101/2024.01.15.111111 --doi 10.1101/2024.01.15.222222 --out ./output
```

**Categories:** See `BIORXIV_CATEGORIES` in the code for all 27 supported categories (e.g., `systems_biology`, `bioinformatics`, `genomics`).

### medRxiv

Fetch preprints from medRxiv (direct JATS XML when available, falls back to PDF→GROBID):

```bash
# Recent epidemiology preprints
text-fetch medrxiv fetch --days 30 --category epidemiology --out ./output

# Date range
text-fetch medrxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

# Specific DOIs
text-fetch medrxiv fetch --doi 10.1101/2024.01.15.123456 --out ./output
```

**Categories:** See `MEDRXIV_CATEGORIES` in the code for all 52 supported categories (e.g., `epidemiology`, `infectious_diseases`, `public_and_global_health`).

### ChemRxiv

Fetch preprints from ChemRxiv (requires GROBID - no native JATS available):

```bash
# Start GROBID (requires Docker)
./scripts/start_grobid.sh

# Search by term
text-fetch chemrxiv fetch --term "catalysis" --out ./output

# Filter by category
text-fetch chemrxiv fetch --category organic_chemistry --out ./output

# Date range
text-fetch chemrxiv fetch --date-from 2024-01-01 --date-to 2024-12-31 --out ./output

# Specific item IDs
text-fetch chemrxiv fetch --item-id item_2024-abc123 --out ./output

# Combined filters
text-fetch chemrxiv fetch --term "synthesis" --category organic_chemistry --max-results 50 --out ./output
```

**Categories:** See `CHEMRXIV_CATEGORIES` in the code for all 22 supported categories (e.g., `organic_chemistry`, `inorganic_chemistry`, `biochemistry`, `catalysis`).

### Europe PMC

Fetch articles from Europe PMC (native JATS XML - no GROBID required):

```bash
# Search by author
text-fetch europepmc fetch --author "hlavacek ws" --out ./output

# Search with keywords
text-fetch europepmc fetch --keyword "systems biology" --out ./output

# Date range
text-fetch europepmc fetch --author "perelson" --date-from 2020-01-01 --out ./output

# Raw Lucene query
text-fetch europepmc fetch --query 'AUTH:"hlavacek" AND TITLE:modeling' --out ./output

# Specific PMC IDs
text-fetch europepmc fetch --pmcid PMC123456 --pmcid PMC789012 --out ./output

# Include non-open-access results
text-fetch europepmc fetch --author "smith" --include-non-oa --out ./output
```

**Key advantages:**
- **No GROBID required** - Europe PMC provides native JATS XML
- **Lucene query syntax** - Familiar, powerful query language
- **Cursor-based pagination** - Fast for deep result sets
- **European content** - Access to Horizon 2020/Europe funded research

**Query syntax:** Uses Lucene syntax (`AUTH:`, `TITLE:`, `DOI:`, `KEYWORD:`, `FIRST_PDATE:`, etc.). See [Europe PMC documentation](https://europepmc.org/RestfulWebService).

### Corpus Workspace (v0.2.0)

Build a deduplicated corpus across multiple searches:

```bash
# Initialize workspace
text-fetch workspace init ./my-corpus

# Check workspace status
text-fetch workspace status ./my-corpus

# Build final tarball
text-fetch workspace build ./my-corpus

# List search history
text-fetch workspace list-searches ./my-corpus

# Clear workspace (keep search history)
text-fetch workspace clear ./my-corpus --keep-history

# Full reset
text-fetch workspace clear ./my-corpus --force
```

**Workspace directory structure:**
```
my-corpus/
├── .text-fetch/           # Metadata directory
│   ├── workspace.json     # Workspace manifest
│   ├── searches/          # Search history
│   │   ├── search_001.json
│   │   └── ...
│   └── doi_index.json     # DOI deduplication index
├── valid/                 # Complete JATS files
│   └── *.xml
├── incomplete/            # Incomplete JATS files
│   └── *.xml
└── manifest.json          # Standard manifest
```

### Unified Multi-Source Fetch

Fetch articles from multiple sources with a single JSON config file:

```bash
# Create a search config file
cat > input/hlavacek.json << 'EOF'
{
  "name": "hlavacek_corpus",
  "description": "Publications by William S. Hlavacek",
  "author": "hlavacek ws",
  "keywords": ["systems biology", "rule-based modeling"],
  "sources": ["pmc", "europepmc", "biorxiv"],
  "source_options": {
    "biorxiv": {"categories": ["systems_biology"]}
  },
  "max_results_per_source": 100,
  "deduplicate_by_doi": true
}
EOF

# Fetch from all sources in config
text-fetch fetch --config-file input/hlavacek.json --out ./output

# Override sources from command line
text-fetch fetch --config-file input/hlavacek.json --sources pmc,europepmc --out ./output

# Disable DOI deduplication
text-fetch fetch --config-file input/hlavacek.json --no-dedupe --out ./output
```

**Config options:**
- `name` / `description` - Metadata for the search
- `author` - Author name to search
- `keywords` - Keywords to search in title/abstract
- `sources` - Array of sources: `pmc`, `europepmc`, `arxiv`, `biorxiv`, `medrxiv`, `chemrxiv`
- `source_options` - Per-source configuration (categories, etc.)
- `max_results_per_source` - Limit per source (default: 100)
- `open_access_only` - Only fetch open access articles (default: true)
- `deduplicate_by_doi` - Remove duplicates across sources (default: true)

**Output structure:**
```
output/
├── pmc/
│   ├── valid/
│   └── incomplete/
├── europepmc/
│   ├── valid/
│   └── incomplete/
├── biorxiv/
│   ├── valid/
│   └── incomplete/
├── _duplicates/      # Removed duplicates
├── duplicates.json   # Deduplication log
└── manifest.json     # Unified manifest with stats
```

**Deduplication priority:** PMC > Europe PMC > bioRxiv > medRxiv > arXiv > ChemRxiv

### PDF Processing

Process local PDFs via GROBID and convert to JATS XML:

```bash
# Start GROBID (requires Docker)
./scripts/start_grobid.sh

# Process PDFs
text-fetch pdf ./Manuscripts --out ./output
```

## JATS Validation

Downloaded articles are automatically sorted by completeness:

```
output/
├── valid/           # Complete JATS (title + abstract + body≥1000 chars)
│   ├── PMC123456.xml
│   └── ...
├── incomplete/      # Missing required parts
│   ├── PMC789012.xml
│   └── ...
└── manifest.json    # Tracks contents + validation results
```

## Quick Start

### 1. Configure NCBI Access

```bash
# Create config file
cat > text-fetch.toml << EOF
[ncbi]
email = "your.email@example.com"
EOF
```

### 2. Fetch Articles by Author

```bash
uv run text-fetch pmc fetch --query "perelson as[author]" --out ./perelson
```

### 3. Sync PMC Open Access (Test)

```bash
uv run text-fetch pmc sync --storage ./pmc-test --subset oa_comm --max-files 5 -y
```

## Workflows

### Workflow 1: Author Corpus

Build a comprehensive corpus of publications by a specific author.

```bash
# Create search config
cat > input/hlavacek.json << 'EOF'
{
  "name": "hlavacek_corpus",
  "author": "hlavacek ws",
  "sources": ["pmc", "europepmc", "biorxiv"],
  "max_results_per_source": 100,
  "deduplicate_by_doi": true
}
EOF

# Run unified fetch
text-fetch fetch \
  --config-file input/hlavacek.json \
  --email your.email@example.com \
  --out ./output/hlavacek

# Results structure
ls -la output/hlavacek/
# pmc/
#   valid/
#   incomplete/
# europepmc/
#   valid/
#   incomplete/
# biorxiv/
#   valid/
#   incomplete/
# manifest.json
# duplicates.json (if duplicates found)
```

### Workflow 2: Preprint-Only Corpus

Build a corpus from preprint servers only (no peer-reviewed journals).

```bash
# Create preprint-focused config
cat > input/preprints.json << 'EOF'
{
  "name": "preprint_corpus",
  "keywords": ["systems biology", "rule-based modeling"],
  "sources": ["biorxiv", "medrxiv", "arxiv"],
  "source_options": {
    "arxiv": {"categories": ["q-bio.MN", "q-bio.QM"]},
    "biorxiv": {"categories": ["systems_biology", "bioinformatics"]}
  },
  "max_results_per_source": 50
}
EOF

# Start GROBID for arXiv PDFs
./scripts/start_grobid.sh

# Fetch preprints
text-fetch fetch \
  --config-file input/preprints.json \
  --grobid-url http://localhost:8070 \
  --out ./output/preprints
```

### Workflow 3: Date-Limited Search

Search for recent publications within a specific time window.

```bash
# Create date-limited config
cat > input/recent.json << 'EOF'
{
  "author": "perelson as",
  "date_range": {
    "start": "2024/01/01",
    "end": "2025/01/01"
  },
  "sources": ["pmc", "europepmc"],
  "max_results_per_source": 200
}
EOF

# Fetch recent articles
text-fetch fetch \
  --config-file input/recent.json \
  --email your.email@example.com \
  --out ./output/recent

# Check stats
cat output/recent/manifest.json | jq '.statistics'
```

### Workflow 4: PDF Directory Processing

Process a local directory of PDFs (e.g., downloaded papers, grants).

```bash
# Start GROBID
./scripts/start_grobid.sh

# Process PDF directory
text-fetch pdf batch \
  --dir ./Manuscripts \
  --out ./output/pdfs \
  --csv metadata.csv \
  --resolve-ncbi \
  --email your.email@example.com \
  --verbose

# Results
ls output/pdfs/
# valid/           - Complete JATS
# incomplete/      - Missing title/abstract/body
# tei_cache/       - Cached TEI from GROBID

cat metadata.csv  # CSV with extracted metadata
```

### Workflow 5: Workspace Corpus

Build a deduplicated corpus from multiple author searches:

```bash
# Initialize workspace
text-fetch workspace init ./systems-biology-corpus --name "Systems Biology"

# Add papers from multiple author searches (--workspace option)
text-fetch europepmc fetch --author "hlavacek ws" \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 45 articles (45 valid, 0 incomplete)

text-fetch europepmc fetch --author "perelson as" \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 52 articles (38 valid, 2 incomplete, 12 duplicates skipped)

text-fetch biorxiv fetch --days 30 --category systems_biology \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 23 articles (21 valid, 2 incomplete, 0 duplicates skipped)

# Process local PDFs into workspace
text-fetch pdf batch --dir ./Manuscripts \
  --workspace ./systems-biology-corpus --out ./tmp
# Processed 10 PDFs (8 valid, 2 incomplete, 0 duplicates skipped)

# Check status
text-fetch workspace status ./systems-biology-corpus
# Workspace: Systems Biology
# Valid articles: 112
# Incomplete articles: 6
# Unique DOIs: 112
# Duplicates skipped: 12
# Searches: 4

# Build final tarball when done
text-fetch workspace build ./systems-biology-corpus --tarball corpus.tar.gz
```

**Key benefits:**
- **Cross-search deduplication** - Same DOI from different searches is only stored once
- **Search history** - Track which searches contributed to the corpus
- **Provenance** - Built tarballs include search metadata

### Workflow 6: Reproducible Fetch from Tarball

Re-run a fetch from an existing tarball's embedded configuration:

```bash
# First, create a tarball with embedded config
text-fetch fetch --config-file input/hlavacek.json --out ./output --tarball

# Later, reproduce the same fetch (e.g., for updates)
text-fetch fetch --from-tarball ./output/unified_corpus.tar.gz \
  --out ./updated --tarball
```

This is useful for:
- **Reproducing previous fetches** - Run the same search criteria again
- **Updating corpora** - Re-fetch with the same config to get new articles
- **Sharing search configs** - Tarball contains the exact search parameters used

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run pre-commit run --all-files
```

## Documentation

- [API_REFERENCE.md](docs/API_REFERENCE.md) - Python API documentation
- [ROADMAP.md](docs/ROADMAP.md) - Development roadmap and feature status
- [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) - Contributing guidelines
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture

## Related Projects

- **[litkit](https://github.com/lanl/litkit)** - Two-stage RAG pipeline for scientific literature
- **[chatty](https://github.com/lanl/chatty)** - Terminal UI chatbot with RAG integration

## License

[Insert license information here]
