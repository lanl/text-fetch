# text-fetch Developer Guide

This guide covers development setup, code conventions, and contribution workflow for text-fetch.

## Development Environment Setup

### Prerequisites

- Python 3.9+ (3.12+ recommended)
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

# Create virtual environment and sync dependencies
uv venv                   # Creates .venv/
uv sync --all-extras      # Installs all dependencies into .venv

# Install pre-commit hooks
uv run pre-commit install

# Verify setup
uv run text-fetch --version
```

### Running Commands

We use `uv run` to execute commands within the project's virtual environment.
This automatically uses `.venv/` without requiring manual activation:

```bash
uv run text-fetch --help          # Run the CLI
uv run pre-commit run --all-files # Run linting
uv run pytest                     # Run tests
uv run mypy src/                  # Type check
```

Alternatively, you can activate the venv traditionally:

```bash
source .venv/bin/activate         # Activate venv
text-fetch --help                 # Commands work directly
deactivate                        # When done
```

### Running GROBID

GROBID is required for PDF processing and integration tests.

**Quick start (recommended):**

```bash
./scripts/start_grobid.sh
```

**Manual startup:**

```bash
# Start GROBID (clean startup, runs in background)
docker rm -f grobid 2>/dev/null || true
docker run -d --name grobid --restart unless-stopped --init --ulimit core=0 \
  -p 8070:8070 -p 8071:8071 \
  grobid/grobid:0.8.2-crf

# Wait for GROBID to be ready (~30 seconds on first startup)
until curl -sS http://localhost:8070/api/isalive 2>/dev/null; do
  echo "Waiting for GROBID..."; sleep 2
done
echo "GROBID ready"
```

To stop GROBID:

```bash
docker stop grobid
```

To check GROBID status:

```bash
docker ps | grep grobid
curl http://localhost:8070/api/isalive
```

## Project Structure

```
text-fetch/
├── src/
│   └── text_fetch/
│       ├── __init__.py       # Package init with version
│       ├── cli.py            # Entry point (thin dispatcher)
│       ├── pdf.py            # PDF processing via GROBID
│       ├── pmc.py            # PubMed Central fetching
│       ├── ncbi.py           # NCBI E-utilities wrapper
│       ├── query.py          # JSON config → query builder
│       └── common.py         # Shared utilities
├── tei2jats.xsl              # TEI→JATS XSLT stylesheet
├── pyproject.toml            # Project metadata and dependencies
├── requirements.txt          # Pip-compatible dependencies
├── .pre-commit-config.yaml   # Pre-commit hook configuration
├── CHANGELOG.md              # Version history
├── README.md                 # User documentation
├── docs/
│   ├── ROADMAP.md            # Development roadmap
│   ├── ARCHITECTURE.md       # System design
│   ├── DEVELOPER_GUIDE.md    # This file
│   └── v0.1.1-plan.md        # Implementation plan
├── tests/                    # Test suite
│   ├── conftest.py           # Pytest fixtures
│   └── test_*.py             # Test modules
├── input/                    # Search configs (gitignored)
├── tei_cache/                # TEI cache (gitignored)
└── jats_cache/               # JATS cache (gitignored)
```

### CLI Architecture Directive

> **`src/text_fetch/cli.py` must remain a thin dispatcher.** It handles:
> - Argument parsing via click decorators
> - Subcommand routing to appropriate modules
> - Error handling and exit codes
> - User-facing output (progress bars, messages)
>
> **Business logic lives in modules** (`pmc.py`, `pdf.py`, `query.py`, etc.).
>
> **Rule of thumb:** If a function in `cli.py` exceeds 20 lines, it belongs in a module.

This separation ensures:
1. Testability: Module functions can be tested without CLI overhead
2. Reusability: Modules can be imported by other tools
3. Maintainability: Clear separation of concerns

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

## Development Discipline

### Task-Commit Cadence

> **Rule:** Implement one ~30-minute task → run pre-commit → commit.

This disciplined approach ensures:
- **Small, reviewable commits** with clear intent
- **Lint/type errors caught immediately**, not accumulated
- **Easy git bisect** if bugs are introduced
- **Clean history** for archaeology and blame

### Workflow

1. **Pick a task** from the implementation plan (~30 min scope)
2. **Implement** the task
3. **Run pre-commit** to verify quality:
   ```bash
   pre-commit run --all-files
   ```
4. **Commit** with a descriptive message:
   ```bash
   git add -p  # Stage changes interactively
   git commit -m "feat: add PMC search configuration parsing"
   ```
5. **Repeat** with the next task

### Commit Hygiene

- Each commit **must pass** all pre-commit hooks
- Each commit should be **atomic** (one logical change)
- **Never** use `git commit --no-verify`
- Commit frequently — small commits are better than large ones

### Code Quality Standards

1. **Type hints** on all public functions — mypy catches bugs before runtime
2. **Docstrings** on all public functions — Google style for consistency
3. **Tests alongside code** — not deferred to "later"
4. **No orphan TODOs** — use `# TODO(#issue): description` with issue reference
5. **Imports sorted** — ruff handles this automatically

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

When releasing a new version, update the following files:

| File | What to Update |
|------|----------------|
| `pyproject.toml` | `version = "X.Y.Z"` in `[project]` section |
| `src/text_fetch/__init__.py` | `__version__ = "X.Y.Z"` |
| `CHANGELOG.md` | Add release notes under `## [X.Y.Z] - YYYY-MM-DD` |
| `docs/ROADMAP.md` | Mark completed features, update timeline |

**Steps:**

1. **Update `pyproject.toml`**:
   ```toml
   [project]
   version = "0.1.1"
   ```

2. **Update `src/text_fetch/__init__.py`**:
   ```python
   __version__ = "0.1.1"
   ```

3. **Update `CHANGELOG.md`**:
   ```markdown
   ## [0.1.1] - 2026-01-21
   
   ### Added
   - PubMed Central search and fetch via `text-fetch pmc` command
   
   ### Changed
   - Refactored to package structure
   ```

4. **Update `docs/ROADMAP.md`** to mark milestone complete

5. **Run pre-commit** to verify:
   ```bash
   uv run pre-commit run --all-files
   ```

6. **Commit and tag**:
   ```bash
   git add pyproject.toml src/text_fetch/__init__.py CHANGELOG.md docs/ROADMAP.md
   git commit -m "chore: release v0.1.1"
   git tag v0.1.1
   git push && git push --tags
   ```

7. **Verify** the CLI shows the new version:
   ```bash
   uv run text-fetch --version
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
