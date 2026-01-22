# Changelog

All notable changes to text-fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.6] - 2026-01-21

### Added
- **Unified Multi-Source Fetch** - Single command to fetch from multiple sources
  - `text-fetch fetch` command with `--config-file` option
  - JSON config with `sources` array and `source_options` per-source config
  - DOI-based deduplication across sources (keeps first by priority)
  - Unified `manifest.json` with per-source statistics
  - `unified_fetch()` orchestrator function (`fetch.py`)
  - `deduplicate_by_doi()` utility function for DOI-based deduplication
  - `SourceOptions` dataclass for per-source configuration
  - `ALL_SOURCES` constant listing available sources

### Enhanced
- Extended `SearchConfig` with multi-source support (`query.py`)
  - `name` and `description` metadata fields
  - `sources` field to specify which sources to search
  - `source_options` for per-source category filters
  - `max_results_per_source` limit (default: 100)
  - `open_access_only` flag (default: True)
  - `deduplicate_by_doi` flag (default: True)
  - `to_europepmc_query()` method for Europe PMC queries
  - `to_biorxiv_params()` method for bioRxiv/medRxiv params
  - `to_chemrxiv_params()` method for ChemRxiv params

### CLI
- `--sources` option to override config sources
- `--no-dedupe` flag to disable deduplication
- Per-source progress bars with source name labels
- Summary showing per-source statistics

### Tests
- Added tests for multi-source SearchConfig extensions
- Added tests for SourceOptions dataclass
- Added tests for DOI-based deduplication
- Added tests for callback wrapper helper

## [0.1.5] - 2026-01-21

### Added
- **Europe PMC Integration** - Fetch articles from Europe PMC with native JATS XML
  - `text-fetch europepmc fetch` command for Europe PMC articles
  - `EuropePMCClient` class for Europe PMC REST API (`europepmc.py`)
  - `EuropePMCArticle` dataclass for article metadata
  - Native JATS XML download (no GROBID required)
  - Lucene query syntax support (`AUTH:`, `TITLE:`, `DOI:`, etc.)
  - Cursor-based pagination for efficient deep queries
  - Search by author (`--author`)
  - Search by keywords (`--keyword`)
  - Date range filtering (`--date-from`, `--date-to`)
  - Raw query support (`--query` for Lucene syntax)
  - PMC ID lookup (`--pmcid`)
  - Open access filtering (`--include-non-oa` to disable)
  - `build_query()` helper for constructing Lucene queries
  - `fetch_europepmc()` orchestrator function
  - ID lookup methods: `get_by_pmcid()`, `get_by_pmid()`, `get_by_doi()`
  - `normalize_pmcid()` utility for ID format normalization

### Key Advantages
- **No GROBID required** - Europe PMC provides native JATS XML
- **Faster pagination** - Cursor-based vs offset-based
- **Simpler query syntax** - Lucene instead of E-utilities
- **European content** - Access to Horizon 2020/Europe funded research

### Tests
- Added 30 new tests for Europe PMC client (`test_europepmc.py`)

## [0.1.4] - 2026-01-21

### Added
- **ChemRxiv Integration** - Fetch preprints from ChemRxiv chemistry server
  - `text-fetch chemrxiv fetch` command for ChemRxiv preprints
  - `ChemrxivClient` class for ChemRxiv public API (`chemrxiv.py`)
  - `ChemrxivArticle` dataclass for article metadata
  - PDF→GROBID→JATS pipeline (ChemRxiv has no native JATS XML)
  - Search by term (`--term` for title/abstract/authors)
  - Date range filtering (`--date-from`, `--date-to`)
  - Category filtering (`--category`)
  - Item ID lookup (`--item-id`)
  - Pagination via skip/limit (automatic iteration)
  - `CHEMRXIV_CATEGORIES` constant (22 categories)
  - `get_category_id()` and `get_category_ids()` helper functions
  - `fetch_chemrxiv()` orchestrator function

### Tests
- Added 25 new tests for ChemRxiv client (`test_chemrxiv.py`)
- Total test count: 277 (all passing)

## [0.1.3] - 2026-01-21

### Added
- **bioRxiv/medRxiv Integration** - Fetch preprints with direct JATS XML download
  - `text-fetch biorxiv fetch` command for bioRxiv preprints
  - `text-fetch medrxiv fetch` command for medRxiv preprints
  - `BiorxivClient` class for api.biorxiv.org API (`biorxiv.py`)
  - `BiorxivArticle` dataclass for article metadata
  - Direct JATS XML download from `jatsxml` field (preferred)
  - PDF→GROBID→JATS fallback when JATS not available
  - Date-based search (`--start-date`, `--end-date`, `--days`)
  - DOI-based lookup (`--doi`)
  - Category filtering (`--category`)
  - Pagination iterator for large result sets
  - `BIORXIV_CATEGORIES` constant (27 categories)
  - `MEDRXIV_CATEGORIES` constant (52 categories)
  - `fetch_biorxiv()` and `fetch_medrxiv()` orchestrator functions

### Tests
- Added 21 new tests for bioRxiv client (`test_biorxiv.py`)
- Total test count: 252 (all passing)

## [0.1.2] - 2026-01-21

### Added
- **arXiv Integration** - Fetch preprints from arXiv via PDF→GROBID→JATS pipeline
  - `text-fetch arxiv fetch` command for searching and downloading preprints
  - `ArxivClient` class with search and download methods (`arxiv.py`)
  - `ArxivArticle` dataclass for article metadata
  - `build_query()` helper for constructing arXiv query syntax
  - `fetch_arxiv()` orchestrator function (search → download → convert → validate)
  - Support for arXiv query syntax (au:, ti:, abs:, all:, cat:)
  - Category-based filtering (e.g., q-bio.MN, cs.AI)
  - Rate limiting (3-second delay per arXiv guidelines)
- **GROBID Client Module** - Extracted and enhanced GROBID integration
  - `GROBIDClient` class with is_available(), process_pdf(), tei_to_jats() methods (`grobid.py`)
  - Combined `pdf_to_jats()` convenience method
  - Configurable timeout and URL
  - Proper error handling and logging
- **Extended SearchConfig** - arXiv support in query builder (`query.py`)
  - New `arxiv_categories` field for category filtering
  - New `to_arxiv_query()` method for arXiv query syntax generation

### Changed
- Extracted GROBID client from `pdf.py` into dedicated `grobid.py` module
- Added `GROBIDClient` to package exports in `__init__.py`

### Tests
- Added 13 new tests for GROBID client (`test_grobid.py`)
- Added 18 new tests for arXiv client (`test_arxiv.py`)
- Total test count: 236 (all passing)

## [0.1.1] - 2026-01-21

### Added
- **PubMed Central Integration** - Full PMC article fetching via E-utilities
  - `text-fetch pmc fetch` command for searching and downloading articles
  - JSON-based search configuration (`SearchConfig` class in `query.py`)
  - Author-based searches (e.g., `"hlavacek ws[au]"`)
  - Keyword and title/abstract searches with `[tiab]` qualifier
  - Date range filtering with `[dp]` qualifier
  - Support for ebola.json-style multi-category keyword configs
- **NCBI E-utilities Infrastructure** (`NCBIClient` class in `ncbi.py`)
  - ESearch for PubMed queries with pagination
  - PMID → PMCID conversion via ID converter API
  - PMC article download via efetch endpoint
  - Rate limiting (3 req/sec without key, 9 req/sec with API key)
  - Retry logic with exponential backoff
- **JATS Validation** (`JATSValidator` class in `pmc.py`)
  - Validates articles for title, abstract, and body content
  - Sorts into `valid/` vs `incomplete/` folders
  - Minimum body character threshold (default: 1000 chars)
  - SHA256 content hashing for deduplication
- **PMC OA Corpus Sync** (`pmc_oa.py`)
  - `text-fetch pmc sync` command for bulk download
  - Incremental updates via manifest tracking
  - Progress reporting and resume support
- **TOML Configuration** (`config.py`)
  - `text-fetch.toml` configuration file support
  - Priority-based resolution: CLI > env vars > config file
  - Settings for NCBI email, API key, and GROBID URL
- **Click-based CLI** (`cli.py`)
  - Unified CLI with subcommands: `pdf`, `pmc fetch`, `pmc sync`, `config`
  - Progress bars for long-running operations
  - Verbose mode with detailed logging

### Changed
- Refactored to package structure (`src/text_fetch/`)
- Extracted shared utilities to `common.py` (RateLimiter, clean, sha1_of_file)
- Improved documentation (ROADMAP.md, ARCHITECTURE.md, DEVELOPER_GUIDE.md)

### Dependencies
- click >= 8.1.0 (new)
- tomli >= 2.0.0 for Python < 3.11 (new)

## [0.1.0] - 2025-01-20

### Added
- Initial release of text-fetch
- PDF to JATS XML conversion pipeline via GROBID
- TEI XML intermediate format with XSLT transformation to JATS
- SHA1-based content-addressable caching for TEI and JATS files
- NCBI E-utilities integration for PMID/PMCID resolution from DOIs
- OCR support via GROBID service
- Unicode normalization using unidecode library
- CSV index generation with bibliographic metadata
- Tar.gz archive creation for downstream processing
- Fallback DOI extraction via pdfminer when GROBID fails
- Rate limiting for external API requests
- Configurable processing options:
  - `--prefer-fulltext` for full document processing
  - `--resolve-ncbi` for PubMed ID resolution
  - `--normalize-unicode` for ASCII conversion
  - `--create-tarball` for archive generation

### Dependencies
- requests >= 2.31.0
- lxml >= 4.9.0
- pdfminer-six >= 20221105
- unidecode >= 1.3.0
- GROBID 0.7.2 (Docker container)

[Unreleased]: https://github.com/lanl/text-fetch/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/lanl/text-fetch/releases/tag/v0.1.0
