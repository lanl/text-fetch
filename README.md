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

### PDF Processing

Process PDFs via GROBID and convert to JATS XML:

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
