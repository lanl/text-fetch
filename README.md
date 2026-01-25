# text-fetch

**Acquire scientific literature for RAG pipelines.**

uv run text-fetch provides a unified interface for acquiring full-text scientific literature from multiple sources and converting it to JATS XML format for downstream RAG (Retrieval-Augmented Generation) pipelines. The output is designed for use with [litkit](https://github.com/lanl/litkit) and [chatty](https://github.com/lanl/chatty).

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

uv run text-fetch uses a TOML configuration file. Create `text-fetch.toml` in your project directory or `~/.config/text-fetch/config.toml` for global settings.

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

## Getting Help

Use `--help` after any command to see available options:

```bash
# List all command groups
uv run text-fetch --help

# List subcommands in a group
uv run text-fetch pmc --help

# Show options for a specific command
uv run text-fetch pmc fetch --help
uv run text-fetch workspace update --help
```

## Commands

### Show Configuration

```bash
uv run text-fetch config
```

### PubMed Central

#### Fetch Articles via E-utilities

Fetch articles by PubMed query:

```bash
uv run text-fetch pmc fetch --query "hlavacek ws[author]" --out ./output

# Resume interrupted fetch
uv run text-fetch pmc fetch --query "hlavacek ws[author]" --out ./output --resume

# Update mode: fetch only new papers since last fetch (requires workspace)
uv run text-fetch pmc fetch --query "hlavacek ws[author]" --workspace ./my-corpus --update
```

#### Sync PMC Open Access Corpus

Download and maintain a local mirror of the PMC Open Access subset:

```bash
# Check for updates (dry-run, shows what would be downloaded)
uv run text-fetch pmc sync --storage /Volumes/External/pmc-oa

# Download updates (actually fetches files)
uv run text-fetch pmc sync --storage /Volumes/External/pmc-oa --download

# Sync specific subset (oa_comm, oa_noncomm, oa_other)
uv run text-fetch pmc sync --storage ./pmc-oa --subset oa_comm --download

# Verify existing files match expected sizes
uv run text-fetch pmc sync --storage ./pmc-oa --verify

# Test with limited files
uv run text-fetch pmc sync --storage ./test-pmc --max-files 10 --download -y
```

#### Check PMC OA Mirror Status

```bash
# Show status of local mirror
uv run text-fetch pmc status --storage /Volumes/External/pmc-oa
# PMC OA Local Mirror
# ========================================
# Storage: /Volumes/External/pmc-oa
# Last sync: 2024-07-15 10:30:00
#
# Subsets:
#   oa_comm: 1,234,567 files (180.5 GB)
#   oa_noncomm: 890,123 files (95.2 GB)
#   oa_other: 1,275,310 files (125.3 GB)
#
# Total: 3,400,000 files (401.0 GB)
```

#### Import Existing Downloads

If you've manually downloaded PMC OA files, register them with the sync manifest:

```bash
# Import existing .tar.gz files into sync manifest
uv run text-fetch pmc import --storage /Volumes/External/pmc-oa
# Scanning /Volumes/External/pmc-oa for .tar.gz files...
# ==================================================
# Import complete!
#   Files scanned: 3,400,000
#   Matched: 3,399,500
#   Unmatched: 500
#   Manifest: /Volumes/External/pmc-oa/sync_manifest.json

# Import only specific subset
uv run text-fetch pmc import --storage ./pmc-oa --subset oa_comm
```

**Subsets:**
- `oa_comm` - Commercial use allowed (CC BY, CC0)
- `oa_noncomm` - Non-commercial use only (CC BY-NC)
- `oa_other` - Other open access licenses

#### PMC OA Incremental Update Workflow

```bash
# 1. If you have existing downloads, import them first
uv run text-fetch pmc import --storage /Volumes/External/pmc-oa

# 2. Check what's new (dry-run)
uv run text-fetch pmc sync --storage /Volumes/External/pmc-oa
# Shows: 56,789 new files (~278 GB)

# 3. Download updates
uv run text-fetch pmc sync --storage /Volumes/External/pmc-oa --download

# 4. Verify downloads (optional)
uv run text-fetch pmc sync --storage /Volumes/External/pmc-oa --verify
```

### arXiv

Fetch preprints from arXiv (converts PDFs via GROBID):

```bash
# Start GROBID (requires Docker)
./scripts/start_grobid.sh

# Search by author
uv run text-fetch arxiv fetch --query 'au:"hlavacek ws"' --out ./output

# Search by category
uv run text-fetch arxiv fetch --categories q-bio.MN --out ./output

# Search with multiple categories
uv run text-fetch arxiv fetch --categories q-bio.MN --categories cs.AI --out ./output

# Using JSON config
uv run text-fetch arxiv fetch --config-file input/search.json --out ./output

# Resume interrupted fetch
uv run text-fetch arxiv fetch --categories q-bio.MN --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch arxiv fetch --categories q-bio.MN --workspace ./my-corpus --update
```

### bioRxiv

Fetch preprints from bioRxiv (direct JATS XML when available, falls back to PDF→GROBID):

```bash
# Recent preprints by category
uv run text-fetch biorxiv fetch --days 30 --category systems_biology --out ./output

# Date range
uv run text-fetch biorxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

# Specific DOIs
uv run text-fetch biorxiv fetch --doi 10.1101/2024.01.15.123456 --out ./output

# Multiple DOIs
uv run text-fetch biorxiv fetch --doi 10.1101/2024.01.15.111111 --doi 10.1101/2024.01.15.222222 --out ./output

# Resume interrupted fetch
uv run text-fetch biorxiv fetch --days 30 --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch biorxiv fetch --days 30 --workspace ./my-corpus --update
```

**Categories:** See `BIORXIV_CATEGORIES` in the code for all 27 supported categories (e.g., `systems_biology`, `bioinformatics`, `genomics`).

### medRxiv

Fetch preprints from medRxiv (direct JATS XML when available, falls back to PDF→GROBID):

```bash
# Recent epidemiology preprints
uv run text-fetch medrxiv fetch --days 30 --category epidemiology --out ./output

# Date range
uv run text-fetch medrxiv fetch --start-date 2024-01-01 --end-date 2024-01-31 --out ./output

# Specific DOIs
uv run text-fetch medrxiv fetch --doi 10.1101/2024.01.15.123456 --out ./output

# Resume interrupted fetch
uv run text-fetch medrxiv fetch --days 30 --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch medrxiv fetch --days 30 --workspace ./my-corpus --update
```

**Categories:** See `MEDRXIV_CATEGORIES` in the code for all 52 supported categories (e.g., `epidemiology`, `infectious_diseases`, `public_and_global_health`).

### ChemRxiv

Fetch preprints from ChemRxiv (requires GROBID - no native JATS available):

```bash
# Start GROBID (requires Docker)
./scripts/start_grobid.sh

# Search by term
uv run text-fetch chemrxiv fetch --term "catalysis" --out ./output

# Filter by category
uv run text-fetch chemrxiv fetch --category organic_chemistry --out ./output

# Date range
uv run text-fetch chemrxiv fetch --date-from 2024-01-01 --date-to 2024-12-31 --out ./output

# Specific item IDs
uv run text-fetch chemrxiv fetch --item-id item_2024-abc123 --out ./output

# Combined filters
uv run text-fetch chemrxiv fetch --term "synthesis" --category organic_chemistry --max-results 50 --out ./output

# Resume interrupted fetch
uv run text-fetch chemrxiv fetch --term "catalysis" --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch chemrxiv fetch --term "catalysis" --workspace ./my-corpus --update
```

**Categories:** See `CHEMRXIV_CATEGORIES` in the code for all 22 supported categories (e.g., `organic_chemistry`, `inorganic_chemistry`, `biochemistry`, `catalysis`).

### Europe PMC

Fetch articles from Europe PMC (native JATS XML - no GROBID required):

```bash
# Search by author
uv run text-fetch europepmc fetch --author "hlavacek ws" --out ./output

# Search with keywords
uv run text-fetch europepmc fetch --keyword "systems biology" --out ./output

# Date range
uv run text-fetch europepmc fetch --author "perelson" --date-from 2020-01-01 --out ./output

# Raw Lucene query
uv run text-fetch europepmc fetch --query 'AUTH:"hlavacek" AND TITLE:modeling' --out ./output

# Specific PMC IDs
uv run text-fetch europepmc fetch --pmcid PMC123456 --pmcid PMC789012 --out ./output

# Include non-open-access results
uv run text-fetch europepmc fetch --author "smith" --include-non-oa --out ./output

# Resume interrupted fetch
uv run text-fetch europepmc fetch --author "hlavacek ws" --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch europepmc fetch --author "hlavacek ws" --workspace ./my-corpus --update
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
uv run text-fetch workspace init ./my-corpus

# Check workspace status
uv run text-fetch workspace status ./my-corpus

# Build final tarball
uv run text-fetch workspace build ./my-corpus

# List search history
uv run text-fetch workspace list-searches ./my-corpus

# Clear workspace (keep search history)
uv run text-fetch workspace clear ./my-corpus --keep-history

# Full reset
uv run text-fetch workspace clear ./my-corpus --force

# Update workspace: re-run searches to fetch new papers
uv run text-fetch workspace update ./my-corpus

# Preview what would be fetched
uv run text-fetch workspace update ./my-corpus --dry-run

# Update specific source only
uv run text-fetch workspace update ./my-corpus --source europepmc
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
uv run text-fetch fetch --config-file input/hlavacek.json --out ./output

# Override sources from command line
uv run text-fetch fetch --config-file input/hlavacek.json --sources pmc,europepmc --out ./output

# Disable DOI deduplication
uv run text-fetch fetch --config-file input/hlavacek.json --no-dedupe --out ./output

# Resume interrupted multi-source fetch
uv run text-fetch fetch --config-file input/hlavacek.json --out ./output --resume

# Update mode: fetch only new papers since last fetch
uv run text-fetch fetch --config-file input/hlavacek.json --workspace ./my-corpus --update
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
uv run text-fetch pdf ./Manuscripts --out ./output
```

#### OCR Support for Scanned PDFs

For scanned or image-based PDFs, you need the **full GROBID image** with Tesseract OCR:

```bash
# Start GROBID WITH OCR support (~5GB image)
./scripts/start_grobid_with_ocr.sh

# Process scanned PDFs
uv run text-fetch pdf batch --dir ./Manuscripts --out ./output --ocr
```

**Important:** The `--ocr` flag **requires** the full GROBID image (`grobid:X.X.X-full`). 
If you use `--ocr` with the standard GROBID image (`grobid:X.X.X-crf`), you will get an error:

```
Error: OCR requested but GROBID does not have OCR support.
The standard GROBID image (grobid:X.X.X-crf) does not include Tesseract.
Use the full image: ./scripts/start_grobid_with_ocr.sh
```

**When to use OCR:**
- Scanned papers (image-only PDFs)
- Older publications without embedded text
- Documents with mixed text/image content

**When standard GROBID is sufficient:**
- Modern PDFs with embedded text (most recent publications)
- Born-digital documents

The standard GROBID image is faster to start (~2GB vs ~5GB) and processes faster, 
so only use OCR when necessary.

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
uv run text-fetch fetch \
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
uv run text-fetch fetch \
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
uv run text-fetch fetch \
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
uv run text-fetch pdf batch \
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

**Note:** The `--ocr` flag enables OCR processing for scanned PDFs. This improves
extraction quality for older papers that are image-based. Without OCR, GROBID may
fail to extract titles and abstracts from scanned documents.

### Workflow 5: Workspace Corpus

Build a deduplicated corpus from multiple author searches:

```bash
# Initialize workspace
uv run text-fetch workspace init ./systems-biology-corpus --name "Systems Biology"

# Add papers from multiple author searches (--workspace option)
uv run text-fetch europepmc fetch --author "hlavacek ws" \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 45 articles (45 valid, 0 incomplete)

uv run text-fetch europepmc fetch --author "perelson as" \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 52 articles (38 valid, 2 incomplete, 12 duplicates skipped)

uv run text-fetch biorxiv fetch --days 30 --category systems_biology \
  --workspace ./systems-biology-corpus --out ./tmp
# Fetched 23 articles (21 valid, 2 incomplete, 0 duplicates skipped)

# Process local PDFs into workspace
uv run text-fetch pdf batch --dir ./Manuscripts \
  --workspace ./systems-biology-corpus --out ./tmp
# Processed 10 PDFs (8 valid, 2 incomplete, 0 duplicates skipped)

# Check status
uv run text-fetch workspace status ./systems-biology-corpus
# Workspace: Systems Biology
# Valid articles: 112
# Incomplete articles: 6
# Unique DOIs: 112
# Duplicates skipped: 12
# Searches: 4

# Build final tarball when done
uv run text-fetch workspace build ./systems-biology-corpus --tarball corpus.tar.gz
```

**Key benefits:**
- **Cross-search deduplication** - Same DOI from different searches is only stored once
- **Search history** - Track which searches contributed to the corpus
- **Provenance** - Built tarballs include search metadata

### Workflow 6: Reproducible Fetch from Tarball

Re-run a fetch from an existing tarball's embedded configuration:

```bash
# First, create a tarball with embedded config
uv run text-fetch fetch --config-file input/hlavacek.json --out ./output --tarball

# Later, reproduce the same fetch (e.g., for updates)
uv run text-fetch fetch --from-tarball ./output/unified_corpus.tar.gz \
  --out ./updated --tarball
```

This is useful for:
- **Reproducing previous fetches** - Run the same search criteria again
- **Updating corpora** - Re-fetch with the same config to get new articles
- **Sharing search configs** - Tarball contains the exact search parameters used

### Workflow 7: Incremental Corpus Updates (v0.2.4)

Resume interrupted fetches and update existing corpora with new papers:

```bash
# Scenario 1: Resume interrupted fetch
# Your laptop went to sleep during a large fetch - resume where you left off
uv run text-fetch europepmc fetch --author "hlavacek ws" --out ./output --resume
# "Resumed from: 127 completed, continuing..."

# Scenario 2: Update existing workspace
# You built a corpus 3 months ago, now want only new papers since then
uv run text-fetch europepmc fetch --author "hlavacek ws" --workspace ./my-corpus --update
# "Checking for papers since 2025-10-23..."

# Scenario 3: Update all sources in workspace
uv run text-fetch workspace update ./my-corpus
# "europepmc: 15 new papers"
# "biorxiv: 8 new papers"
# "Total: 23 new papers added"

# Preview updates without downloading
uv run text-fetch workspace update ./my-corpus --dry-run

# Update specific source only
uv run text-fetch workspace update ./my-corpus --source arxiv --grobid-url http://localhost:8070
```

**Key features:**
- **Checkpoint-based resume** - Progress saved every 10 papers or 30 seconds
- **Per-source tracking** - Each source tracks its last fetch date independently
- **Config validation** - Changing search criteria resets the checkpoint
- **Workspace integration** - `--update` requires `--workspace` for date tracking

### Workflow 8: Citation Expansion from Seed Papers (v0.3.0)

Expand a corpus by following citation relationships from seed papers:

```bash
# Basic: Expand by following both references and citations
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --out ./output
# Fetched 127 seed papers
# Expanding: 127 seeds → 2,341 references, 892 citations
# After dedup: 2,987 unique papers (456 duplicates skipped)

# Follow only references (papers that seeds cite)
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand-references --out ./output

# Follow only citations (papers citing seeds)
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand-citations --out ./output

# Dry-run: Preview expansion stats before proceeding
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --dry-run --out ./output
# ═══════════════════════════════════════════════════════════════════
# EXPANSION DRY-RUN REPORT
# ═══════════════════════════════════════════════════════════════════
# 
# SEED COVERAGE:
#   Total seeds:            127
#   Seeds with citations:    98 (77%)
#   Seeds with references:  115 (91%)
# 
# EXPANSION ESTIMATE:
#   References found:     ~2,341 papers
#   Citations found:        ~892 papers
#   Total unique:        ~2,987 papers
# 
# Continue with expansion? [y/N]

# Auto-confirm dry-run
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --dry-run --yes --out ./output

# Custom expansion options
uv run text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand \
  --expansion-depth 1 \      # Number of hops (default: 1)
  --max-expansion 10000 \    # Safety cap (default: 5000, 0=unlimited)
  --out ./output
```

**Why citation expansion?**
- **Keyword search** finds papers that *say* the right words
- **Citation expansion** finds papers that *matter* to a field:
  - **References:** Foundational papers (methods, prior work, reviews)
  - **Citations:** Recent papers building on your seeds (follow-up studies)

**Output structure with expansion:**
```
output/
├── seeds/                    # Original seed papers
│   ├── valid/
│   └── incomplete/
├── expanded/                 # Papers from expansion
│   ├── valid/
│   └── incomplete/
├── expansion_manifest.json   # Expansion metadata
└── manifest.json             # Overall manifest
```

**Expansion manifest includes:**
- `expansion_config` - Options used for expansion
- `seed_coverage` - Stats on seeds with citations/references
- `expansion_stats` - Total found, duplicates skipped
- `layers` - Papers at each expansion depth

### Workflow 9: Create Tarball from Existing Files (v0.2.5)

Create tarballs from existing JATS files without re-running a fetch:

```bash
# Scenario 1: Forgot to use --tarball during fetch
uv run text-fetch tarball create --xml-dir ./output/valid --out ./corpus.tar.gz

# Scenario 2: Combine multiple directories into one tarball
uv run text-fetch tarball create \
  --xml-dir ./pmc/valid \
  --xml-dir ./europepmc/valid \
  --xml-dir ./biorxiv/valid \
  --out ./combined_corpus.tar.gz

# Scenario 3: Include metadata CSV
uv run text-fetch tarball create \
  --xml-dir ./output/valid \
  --csv ./output/metadata.csv \
  --out ./corpus.tar.gz

# Scenario 4: Recursive search with custom pattern
uv run text-fetch tarball create \
  --xml-dir ./output \
  --recursive \
  --pattern "*.jats.xml" \
  --out ./corpus.tar.gz

# Scenario 5: Skip validation (faster)
uv run text-fetch tarball create \
  --xml-dir ./output \
  --no-validate \
  --out ./unvalidated.tar.gz

# Scenario 6: Include incomplete files
uv run text-fetch tarball create \
  --xml-dir ./output/valid \
  --xml-dir ./output/incomplete \
  --include-incomplete \
  --out ./full_corpus.tar.gz
```

**Options:**
- `--xml-dir` / `-d` - Directory containing JATS/XML files (repeatable)
- `--out` / `-o` - Output tarball path (.tar.gz)
- `--csv` - Include metadata CSV in tarball
- `--recursive` / `-r` - Recursively search directories
- `--pattern` - Glob pattern for XML files (default: `*.xml`)
- `--include-incomplete` - Include files from incomplete/ directories
- `--validate/--no-validate` - Toggle JATS validation (default: validate)
- `--compression` - Compression type: gz, bz2, none (default: gz)

**Output structure:**
```
corpus.tar.gz
├── .text-fetch/
│   ├── provenance.json           # Creation metadata
│   └── validation_summary.json   # Files included/excluded
├── metadata.csv                  # If --csv provided
└── *.xml                         # JATS files (flat structure)
```

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
