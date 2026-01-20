# Changelog

All notable changes to text-fetch will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Documentation: ROADMAP.md, ARCHITECTURE.md, DEVELOPER_GUIDE.md

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
