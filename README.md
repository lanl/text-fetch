# text-fetch

**Acquire scientific literature for RAG pipelines.**

text-fetch provides a unified interface for acquiring full-text scientific literature from multiple sources and converting it to JATS XML format for downstream RAG (Retrieval-Augmented Generation) pipelines. The output is designed for use with [litkit](https://github.com/lanl/litkit) and [chatty](https://github.com/lanl/chatty).

## Installation

### Prerequisites

- Python 3.9+
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

- [ROADMAP.md](docs/ROADMAP.md) - Development roadmap and feature status
- [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) - Contributing guidelines
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture
- [README_pdf_to_jats.md](docs/README_pdf_to_jats.md) - Legacy `pdf_to_jats.py` script documentation

## Related Projects

- **[litkit](https://github.com/lanl/litkit)** - Two-stage RAG pipeline for scientific literature
- **[chatty](https://github.com/lanl/chatty)** - Terminal UI chatbot with RAG integration

## License

[Insert license information here]
