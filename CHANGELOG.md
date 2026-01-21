# Changelog

All notable changes to text-fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
