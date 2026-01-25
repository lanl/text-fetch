# Changelog

All notable changes to text-fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-01-25

### Added
- **Europe PMC Citation Expansion** - Build comprehensive corpora by following citation relationships
  - `--expand-references` flag to follow references (papers seeds cite)
  - `--expand-citations` flag to follow citations (papers citing seeds)
  - `--expand` shorthand for both directions
  - `--expansion-depth` option for multi-hop expansion (default: 1)
  - `--max-expansion` safety cap on expanded papers (default: 5000)
  - `--dry-run` mode to preview expansion stats before proceeding
  - `--yes/-y` flag to auto-confirm dry-run prompt
  - `expansion_manifest.json` output with detailed statistics

- **Citation/Reference API Methods** - New `EuropePMCClient` methods
  - `get_citations(source, identifier)` - Get papers citing a paper
  - `get_references(source, identifier)` - Get papers a paper cites
  - `get_all_citations()` - Pagination helper for all citations
  - `get_all_references()` - Pagination helper for all references

- **Expansion Engine** - BFS-based citation graph traversal
  - `expand_papers()` function for citation/reference expansion
  - `ExpansionResult` dataclass for expansion results and metadata
  - DOI-based deduplication across expansion layers
  - Canonical key generation (DOI > PMCID > PMID priority)
  - Best-available ID strategy for API lookups
  - Seed coverage statistics tracking
  - Layer-by-layer expansion tracking

### CLI
```bash
# Expand by following references (papers seeds cite)
text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand-references --out ./output

# Expand by following citations (papers citing seeds)
text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand-citations --out ./output

# Both directions
text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --out ./output

# Preview expansion (dry-run)
text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --dry-run --out ./output

# With custom options
text-fetch europepmc fetch --keyword "ebolavirus vaccine" \
  --expand --expansion-depth 2 --max-expansion 10000 --out ./output
```

### Expansion Manifest
The `expansion_manifest.json` includes:
- `expansion_config` - Options used for expansion
- `seed_coverage` - Statistics about seed paper citation/reference availability
- `expansion_stats` - Total references/citations found, duplicates skipped
- `layers` - Summary of papers at each expansion depth

### Tests
- Added 8 new tests for `expand_papers()` function
- Added 4 tests for citation/reference API methods
- Total test count: 556 (all passing)

### Motivation
Keyword search finds papers that **say** the right words. Citation expansion finds papers that **matter** to a field:
- **References:** Foundational papers (methods, prior work, reviews)
- **Citations:** Recent papers building on your seeds (follow-up studies, applications)

## [0.2.6] - 2026-01-23

### Changed
- **CLI Refactoring** - Split monolithic cli.py (~1,900 lines) into maintainable submodules
  - New `cli/` package structure with 12 focused modules
  - Each module handles a single command group (pdf, pmc, arxiv, etc.)
  - All 534 tests pass unchanged (100% backward compatible)
  - CLI help output and behavior identical to v0.2.5
  - Module structure:
    - `cli/__init__.py` - Main CLI group + config command (~70 lines)
    - `cli/_common.py` - Shared helpers (~70 lines)
    - `cli/pdf.py` - PDF batch commands (~150 lines)
    - `cli/pmc.py` - PMC commands (~500 lines)
    - `cli/arxiv.py` - arXiv commands (~150 lines)
    - `cli/biorxiv.py` - bioRxiv commands (~190 lines)
    - `cli/medrxiv.py` - medRxiv commands (~190 lines)
    - `cli/chemrxiv.py` - ChemRxiv commands (~200 lines)
    - `cli/europepmc.py` - Europe PMC commands (~220 lines)
    - `cli/fetch.py` - Unified fetch command (~270 lines)
    - `cli/workspace.py` - Workspace commands (~440 lines)
    - `cli/tarball.py` - Tarball commands (~220 lines)

### Fixed
- **EuropePMC Checkpoint Fix** - Failed IDs are now properly recorded in checkpoint
  - When `get_full_text_xml()` returns `None`, `mark_failed()` is now called
  - Failed items will be retried on `--resume` (previously they were silently skipped)
  - Checkpoint now correctly tracks both completed and failed IDs

- **Update Mode Error Handling** - Workspace timestamp only advances on successful fetches
  - `update_source_record()` is now only called when `errors == 0`
  - Affects all 5 fetcher modules: europepmc, pmc, biorxiv, arxiv, chemrxiv
  - Prevents `--update` from skipping failed items on subsequent runs

- **Checkpoint Docstring** - Fixed misleading docstring for `should_skip()` method
  - Clarified that only completed papers are skipped (not failed ones)
  - Failed papers are intentionally retried for transient errors

### Tests
- Added 4 new tests for checkpoint/resume bug fixes (`test_europepmc.py`)
  - `test_mark_failed_called_on_fetch_none`
  - `test_checkpoint_contains_failed_ids`
  - `test_update_source_record_not_called_on_errors`
  - `test_update_source_record_called_on_success`

## [0.2.5] - 2026-01-23

### Added
- **Standalone Tarball Command** - Create tarballs from existing JATS files without re-running a fetch
  - `text-fetch tarball create` command for packaging existing files
  - `--xml-dir` option (repeatable) for specifying source directories
  - `--out` option for output tarball path
  - `--csv` option to include metadata CSV in tarball
  - `--recursive` flag for recursive directory scanning
  - `--pattern` option for custom glob patterns (default: `*.xml`)
  - `--include-incomplete` flag to include incomplete/ subdirectories
  - `--validate/--no-validate` toggle for JATS validation (default: validate)
  - `--compression` option for compression type (gz, bz2, none)
  - `find_jats_files()` function for file discovery
  - `validate_and_collect_stats()` function for file validation
  - `create_tarball_from_files()` function for tarball creation
  - `embed_validation_summary()` function for validation metadata

### User Stories Implemented
1. **Post-Processing Tarball** - "I processed 235 PDFs through GROBID but forgot to use `--tarball`. I don't want to re-run the entire batch—just create the tarball from existing files."
2. **Combine Multiple Sources** - "I ran separate fetches to different directories. Now I want to combine them into a single tarball for litkit."
3. **Custom Collection** - "I manually curated a collection of JATS files from various sources. I need to package them with proper provenance metadata."
4. **Exclude Incomplete** - "I want a tarball with only valid files, excluding incomplete ones, without re-processing."

### Output Tarball Structure
```
corpus.tar.gz
├── .text-fetch/
│   ├── provenance.json           # Creation metadata
│   └── validation_summary.json   # Files included/excluded
├── metadata.csv                  # If --csv provided
└── *.jats.xml                   # JATS files (flat structure)
```

### CLI Examples
```bash
# Create tarball from single directory
text-fetch tarball create --xml-dir ./output/valid --out ./corpus.tar.gz

# Combine multiple directories
text-fetch tarball create \
  --xml-dir ./pmc/valid \
  --xml-dir ./europepmc/valid \
  --out ./combined_corpus.tar.gz

# Recursive search with custom pattern
text-fetch tarball create \
  --xml-dir ./output \
  --recursive \
  --pattern "*.jats.xml" \
  --out ./corpus.tar.gz

# Skip validation (faster)
text-fetch tarball create \
  --xml-dir ./output \
  --no-validate \
  --out ./unvalidated.tar.gz
```

### Tests
- Added 21 new tests for tarball command functions
- Total test count: 517 (all passing)

## [0.2.4] - 2026-01-23

### Added
- **Resume & Update for All Sources** - Extended checkpoint/resume and update mode to all sources
  - `--resume` flag on all source fetch commands (biorxiv, medrxiv, arxiv, chemrxiv, pmc)
  - `--update` flag on all source fetch commands
  - `--resume` and `--update` flags on unified `text-fetch fetch` command
  - Per-source checkpoint coordination for multi-source fetches

- **bioRxiv/medRxiv Resume & Update**
  - Resume support with DOI-based checkpoint tracking
  - Update mode using `start_date` parameter
  - Workspace source record updates

- **arXiv Resume & Update**
  - Resume support with arXiv ID tracking
  - Update mode using `submittedDate:[YYYYMMDD TO *]` query syntax
  - Workspace source record updates

- **ChemRxiv Resume & Update**
  - Resume support with item_id tracking
  - Update mode using `date_from` parameter
  - Workspace source record updates

- **PMC Resume & Update**
  - Resume support with PMCID tracking
  - Update mode using PubMed date qualifier `[dp]`
  - Workspace source record updates

- **Unified Fetch Integration**
  - `--resume` flag passes to all source fetches
  - `--update` flag passes to all source fetches
  - Per-source checkpoint files maintained separately

- **Enhanced Workspace Update Command**
  - `text-fetch workspace update` now supports all sources
  - Per-source update summaries (fetched, valid, errors)
  - `--grobid-url`, `--email`, `--api-key` options for source requirements
  - Source-specific error handling (GROBID for arxiv/chemrxiv, email for pmc)

### CLI
- `--resume` flag on biorxiv, medrxiv, arxiv, chemrxiv, pmc fetch commands
- `--update` flag on biorxiv, medrxiv, arxiv, chemrxiv, pmc fetch commands
- `--resume` and `--update` flags on unified `text-fetch fetch` command
- Enhanced `workspace update` with per-source results display

### Tests
- All 496 tests passing

### User Stories Implemented
1. **Resume Any Source** - "My bioRxiv fetch was downloading 300 papers when my laptop went to sleep. I want to resume where I left off."
2. **Update Any Source** - "I built a corpus using arXiv 3 months ago. I want to fetch only papers published since then."
3. **Unified Fetch Resume** - "My multi-source fetch was interrupted. I want to resume from where each source left off."
4. **Complete Workspace Update** - "I have a workspace with papers from 5 sources. I want to update all of them with new papers."

## [0.2.3] - 2026-01-23

### Added
- **Resume Interrupted Fetches** - Continue large fetches after interruption
  - `--resume` flag on `text-fetch europepmc fetch` command
  - `FetchCheckpoint` dataclass for tracking progress (`checkpoint.py`)
  - Checkpoint tracks completed/failed paper IDs
  - Config hash validation to detect changed configs
  - Periodic checkpoint saves (every 10 papers or 30 seconds)
  - Helper functions: `get_checkpoint_path()`, `load_checkpoint_if_exists()`, `clear_checkpoint()`

- **Update Mode for Incremental Corpus Updates** - Fetch only new papers since last fetch
  - `--update` flag on `text-fetch europepmc fetch` command
  - `SourceFetchRecord` dataclass for tracking per-source fetch timestamps
  - `source_records` field in `WorkspaceManifest` for update tracking
  - `update_source_record()` method to record fetch timestamps
  - `get_source_record()` and `get_last_fetch_date()` helpers
  - Automatic date filtering based on last fetch timestamp

- **Workspace Update Command** - Re-run all workspace searches to get new papers
  - `text-fetch workspace update` command
  - `--dry-run` flag to preview what would be fetched
  - `--source` option to update specific source only
  - Shows papers since last fetch per source

### CLI
- `--resume` flag for resuming interrupted Europe PMC fetches
- `--update` flag for incremental updates (requires `--workspace`)
- `--update requires --workspace` validation
- Summary shows "Resumed from: X completed" when resuming

### Tests
- Added 23 new tests for checkpoint system (`test_checkpoint.py`)
- Total test count: 496 (all passing)

### User Stories Implemented
1. **Resume Interrupted Fetch** - "My fetch was downloading 500 papers when my laptop went to sleep. I want to resume where I left off."
2. **Update Existing Corpus** - "I built a corpus 3 months ago. I want to fetch only papers published since then."
3. **Workspace Refresh** - "I have a workspace with 5 searches. I want to re-run all of them to get new papers."

## [0.2.2] - 2026-01-23

### Added
- **PMC OA Incremental Sync** - Maintain local PMC Open Access mirrors with easy updates
  - `text-fetch pmc sync` now dry-run by default (shows what would be downloaded)
  - `--download` flag to actually fetch files
  - `--verify` flag to check local files match expected sizes
  - `text-fetch pmc status` command to show local mirror statistics
  - `text-fetch pmc import` command to register existing .tar.gz files
  - `import_existing()` function for scanning and matching local files to PMC entries
  - `verify_files()` method for file integrity checking
  - `get_status()` method for mirror statistics

### Changed
- `pmc sync` is now dry-run by default - use `--download` to fetch files
- Removed `--update` flag (sync is always incremental when manifest exists)

### Tests
- Added 9 new tests for PMC OA verify, status, and import functionality
- Total test count: 473 (all passing)

### Documentation
- Updated README with PMC OA sync workflow documentation
- Added `pmc status` and `pmc import` command examples
- Added incremental update workflow guide

## [0.2.1] - 2026-01-22

### Added
- **Workspace Integration for All Fetch Commands** - Seamless `--workspace` option for building deduplicated corpora
  - `--workspace` option on `text-fetch europepmc fetch`
  - `--workspace` option on `text-fetch biorxiv fetch`
  - `--workspace` option on `text-fetch medrxiv fetch`
  - `--workspace` option on `text-fetch arxiv fetch`
  - `--workspace` option on `text-fetch chemrxiv fetch`
  - `--workspace` option on `text-fetch pmc fetch`
  - `--workspace` option on `text-fetch fetch` (unified)
  - `--workspace` option on `text-fetch pdf batch`
  - Automatic DOI deduplication across searches
  - Search history recording with statistics
  
- **From-Tarball Reproducibility** - Re-run fetches from existing tarballs
  - `--from-tarball` option on `text-fetch fetch`
  - `extract_search_config_from_tarball()` function in `common.py`
  - Extract and re-use search configuration from embedded provenance

### Enhanced
- `unified_fetch()` now accepts optional `workspace` parameter
- `process_pdf_batch()` now accepts optional `workspace` parameter
- All per-source fetch functions support workspace integration:
  - `fetch_europepmc(workspace=...)`
  - `fetch_biorxiv(workspace=...)`
  - `fetch_medrxiv(workspace=...)`
  - `fetch_arxiv(workspace=...)`
  - `fetch_chemrxiv(workspace=...)`
  - `fetch_pmc(workspace=...)`

### Tests
- Added 7 new tests for from-tarball and PDF batch workspace features
- Total test count: 464 (all passing)

### Documentation
- Updated README with Workflow 5 (Workspace Corpus) CLI examples
- Added Workflow 6 (Reproducible Fetch from Tarball)
- Updated API_REFERENCE.md with workspace parameter documentation

## [0.2.0] - 2026-01-22

### Added
- **Corpus Workspace** - Workspace-based corpus management with cross-search deduplication
  - `text-fetch workspace init` - Initialize new workspace directory
  - `text-fetch workspace status` - Show workspace statistics and search history
  - `text-fetch workspace build` - Create tarball from workspace contents
  - `text-fetch workspace list-searches` - Display all recorded search history
  - `text-fetch workspace clear` - Reset workspace with optional history preservation
  - `Workspace` class for managing corpus directories (`workspace.py`)
  - `DOIIndex` class for fast DOI lookup with case-insensitive comparison
  - `WorkspaceManifest` dataclass for workspace metadata
  - `SearchRecord` dataclass for tracking search history
  - Automatic DOI deduplication across multiple searches
  - Search history tracking with statistics
  - Provenance embedding in built tarballs

### Workspace Features
- **Cross-search deduplication** - Same DOI from different searches stored only once
- **Search history** - Track which searches contributed to the corpus
- **Unified tarball output** - Build final corpus with embedded provenance
- **Flexible clearing** - Clear files while preserving search history

### Workspace Directory Structure
```
workspace/
├── .text-fetch/
│   ├── workspace.json     # Workspace manifest
│   ├── searches/          # Search history
│   │   ├── search_001.json
│   │   └── ...
│   └── doi_index.json     # DOI → location mapping
├── valid/                 # Complete JATS files
├── incomplete/            # Incomplete JATS files
└── manifest.json          # Standard manifest
```

### Tests
- Added 51 new tests for workspace functionality (`test_workspace.py`)
- DOIIndex unit tests (10 tests)
- WorkspaceManifest/SearchRecord tests (5 tests)
- Workspace class tests (22 tests)
- Integration tests (3 tests)
- CLI integration tests (11 tests)

## [0.1.9] - 2026-01-22

### Added
- **Tarball Output for litkit** - Create tarballs directly usable by litkit RAG pipeline
  - `--tarball` flag on all fetch commands (pmc, europepmc, biorxiv, medrxiv, arxiv, chemrxiv)
  - `--tarball-name` option for custom output filename (default: `{source}_corpus.tar.gz`)
  - `--tarball` flag on `text-fetch fetch` unified command
  - `--tarball` flag on `pdf batch` command
  - `create_jats_tarball()` function for creating tarballs from output directories
  - `embed_provenance()` function for embedding provenance data in tarballs
  - `read_tarball_provenance()` function for reading embedded provenance
  - `build_provenance()` helper for constructing provenance metadata
  - Tarballs include `.text-fetch/` directory with:
    - `provenance.json` - fetch metadata (version, timestamp, command, statistics)
    - `search_config.json` - original search configuration (when available)

### Key Features
- **litkit Compatibility** - Tarballs ready for direct use with litkit RAG pipeline
- **Provenance Tracking** - Full reproducibility with embedded search configs
- **Flexible Compression** - Supports gzip (.tar.gz), bzip2 (.tar.bz2), or uncompressed (.tar)

### Tests
- Added 21 new tests for tarball functions (`test_tarball.py`)
- Tests for `create_jats_tarball()`, `embed_provenance()`, `read_tarball_provenance()`, `build_provenance()`

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
