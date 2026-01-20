# text-fetch Developer Guide

This guide covers development setup, code conventions, and contribution workflow for text-fetch.

## Development Environment Setup

### Prerequisites

- Python 3.8+ (3.11+ recommended)
- [uv](https://github.com/astral-sh/uv) package manager
- Docker (for GROBID)
- Git

### Initial Setup

```bash
# Clone the repository
git clone https://github.com/lanl/text-fetch.git
cd text-fetch

# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # or `.venv/Scripts/activate` on Windows
uv pip install -e ".[dev]"

# Install pre-commit hooks
pre-commit install
```

### Running GROBID

GROBID is required for PDF processing:

```bash
# Pull and run GROBID (keep this terminal open)
docker pull lfoppiano/grobid:0.7.2
docker run -t --rm -p 8070:8070 lfoppiano/grobid:0.7.2

# Verify GROBID is running
curl http://localhost:8070/api/isalive
```

## Project Structure

```
text-fetch/
├── pdf_to_jats.py       # Main CLI script
├── tei2jats.xsl         # TEI→JATS XSLT stylesheet
├── pyproject.toml       # Project metadata and dependencies
├── requirements.txt     # Pip-compatible dependencies
├── .pre-commit-config.yaml  # Pre-commit hook configuration
├── CHANGELOG.md         # Version history
├── README.md            # User documentation
├── docs/
│   ├── ROADMAP.md       # Development roadmap
│   ├── ARCHITECTURE.md  # System design
│   └── DEVELOPER_GUIDE.md  # This file
├── tests/               # Test suite
│   ├── conftest.py      # Pytest fixtures
│   └── test_*.py        # Test modules
├── input/               # Search configs (gitignored)
├── tei_cache/           # TEI cache (gitignored)
└── jats_cache/          # JATS cache (gitignored)
```

## Code Style

### Tools

We use the following tools for code quality:

| Tool | Purpose | Configuration |
|------|---------|---------------|
| [ruff](https://github.com/astral-sh/ruff) | Linting and formatting | `pyproject.toml` |
| [mypy](https://mypy.readthedocs.io/) | Static type checking | `pyproject.toml` |
| [pytest](https://pytest.org/) | Testing | `pyproject.toml` |

### Pre-commit Hooks

Pre-commit runs automatically on `git commit`. To run manually:

```bash
# Run all hooks on staged files
pre-commit run

# Run all hooks on all files
pre-commit run --all-files

# Run a specific hook
pre-commit run ruff --all-files
pre-commit run mypy --all-files
```

### Style Guidelines

- **Line length**: 88 characters (ruff default)
- **Imports**: Sorted by ruff (isort rules)
- **Quotes**: Double quotes preferred
- **Type hints**: Required for public functions
- **Docstrings**: Google style

Example:

```python
def parse_tei_fields(tei_xml: str, normalize_unicode: bool = False) -> dict[str, str]:
    """Parse TEI XML and extract bibliographic metadata.

    Args:
        tei_xml: TEI XML content as string.
        normalize_unicode: If True, convert Unicode to ASCII.

    Returns:
        Dictionary with keys: first_author, year, title, journal, DOI, PMID, PMCID.

    Raises:
        XMLSyntaxError: If TEI XML is malformed.
    """
    ...
```

## Testing

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific test file
pytest tests/test_tei_parsing.py

# Run specific test
pytest tests/test_tei_parsing.py::test_parse_author_surname -v

# Run tests matching a pattern
pytest -k "tei" -v
```

### Writing Tests

Tests should be placed in the `tests/` directory:

```python
# tests/test_tei_parsing.py
import pytest
from pdf_to_jats import parse_tei_fields, clean

class TestClean:
    def test_normalizes_whitespace(self):
        assert clean("  hello   world  ") == "hello world"
    
    def test_removes_zero_width_space(self):
        assert clean("hello\u200bworld") == "helloworld"
    
    def test_unicode_normalization(self):
        assert clean("naïve", normalize_unicode=True) == "naive"

class TestParseTeiFields:
    def test_extracts_doi(self, sample_tei_xml):
        result = parse_tei_fields(sample_tei_xml)
        assert result["DOI"] == "10.1234/example"
    
    def test_handles_missing_fields(self):
        minimal_tei = '<?xml version="1.0"?><TEI xmlns="http://www.tei-c.org/ns/1.0"/>'
        result = parse_tei_fields(minimal_tei)
        assert result["first_author"] == ""
```

### Test Fixtures

Common fixtures go in `tests/conftest.py`:

```python
# tests/conftest.py
import pytest

@pytest.fixture
def sample_tei_xml():
    return '''<?xml version="1.0" encoding="UTF-8"?>
    <TEI xmlns="http://www.tei-c.org/ns/1.0">
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title>Sample Paper</title>
          </titleStmt>
        </fileDesc>
      </teiHeader>
    </TEI>'''

@pytest.fixture
def temp_pdf(tmp_path):
    """Create a minimal PDF for testing."""
    pdf_path = tmp_path / "test.pdf"
    # ... create minimal PDF ...
    return pdf_path
```

## Development Workflow

### Feature Development

1. **Create a branch**
   ```bash
   git checkout -b feature/pmc-integration
   ```

2. **Make changes** with frequent commits
   ```bash
   git add -p  # Stage changes interactively
   git commit -m "Add PMC search configuration parsing"
   ```

3. **Run checks locally**
   ```bash
   pre-commit run --all-files
   pytest
   ```

4. **Push and create merge request**
   ```bash
   git push -u origin feature/pmc-integration
   # Create MR in GitLab
   ```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add PubMed Central search support
fix: handle missing DOI in TEI parsing
docs: update ROADMAP with preprint support
refactor: extract rate limiter to separate module
test: add tests for NCBI ID conversion
chore: update dependencies
```

### Version Bumping

1. Update version in `pyproject.toml`:
   ```toml
   [project]
   version = "0.1.1"
   ```

2. Update `CHANGELOG.md`:
   ```markdown
   ## [0.1.1] - 2025-02-01
   
   ### Added
   - PubMed Central search and fetch
   ```

3. Commit and tag:
   ```bash
   git add pyproject.toml CHANGELOG.md
   git commit -m "chore: bump version to 0.1.1"
   git tag v0.1.1
   git push && git push --tags
   ```

## Adding New Features

### Adding a New Data Source

To add a new data source (e.g., arXiv):

1. **Create a new module** (or add to existing file for small features):
   ```python
   # arxiv_fetch.py
   def search_arxiv(query: str, max_results: int = 100) -> list[dict]:
       """Search arXiv and return paper metadata."""
       ...
   
   def fetch_arxiv_pdf(arxiv_id: str, output_dir: str) -> str:
       """Download PDF and return local path."""
       ...
   ```

2. **Add tests**:
   ```python
   # tests/test_arxiv.py
   def test_search_arxiv_by_author():
       results = search_arxiv("au:hlavacek")
       assert len(results) > 0
   ```

3. **Update CLI** (if adding new commands):
   ```python
   # In main() or new entry point
   ap.add_argument("--arxiv-query", help="arXiv search query")
   ```

4. **Update documentation**:
   - Add to README.md usage section
   - Update ARCHITECTURE.md with data flow
   - Update ROADMAP.md to mark feature complete

### Modifying the XSLT Stylesheet

The `tei2jats.xsl` stylesheet transforms TEI to JATS:

1. **Test changes** with a sample TEI file:
   ```bash
   xsltproc tei2jats.xsl sample.tei.xml > output.jats.xml
   ```

2. **Validate output** against JATS DTD (optional):
   ```bash
   xmllint --dtdvalid JATS-archivearticle1.dtd output.jats.xml
   ```

3. **Test with litkit** to ensure compatibility:
   ```bash
   # Create a test tar with modified JATS
   tar -cf test.tar output.jats.xml
   litkit --build-only --tar-dir .
   ```

## Dependencies

### Adding Dependencies

```bash
# Add runtime dependency
uv add requests

# Add dev dependency
uv add --dev pytest-cov

# Update requirements.txt for pip users
uv pip compile pyproject.toml -o requirements.txt
```

### Updating Dependencies

```bash
# Update all dependencies
uv pip compile pyproject.toml -o requirements.txt --upgrade

# Update specific package
uv add requests@latest
```

## Troubleshooting

### Common Issues

**Pre-commit fails on first run:**
```bash
pre-commit install --install-hooks
```

**GROBID connection refused:**
```bash
# Check if GROBID is running
docker ps | grep grobid

# Check if port is available
lsof -i :8070
```

**mypy import errors:**
```bash
# Ensure stubs are installed
uv add --dev types-requests types-lxml
```

**Tests fail with missing fixtures:**
```bash
# Ensure conftest.py is in tests/
touch tests/__init__.py tests/conftest.py
```

## Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design and data flow
- [ROADMAP.md](ROADMAP.md) — Planned features and versions
- [litkit Developer Guide](https://github.com/lanl/litkit) — Downstream project conventions
