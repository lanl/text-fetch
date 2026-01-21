# text-fetch

This project provides a tool to extract metadata and full text from PDF files using GROBID, convert the extracted TEI XML to JATS XML, create a CSV index of the processed documents, and optionally generate a tar.gz archive of the JATS output.

## Prerequisites

- Python 3.9+
- Docker (for running GROBID)
- [uv](https://github.com/astral-sh/uv) package manager (recommended)

## Installation

Choose one of the following methods to install dependencies:

### Method 1: Using pip (Recommended)

```bash
pip install -r requirements.txt
```

### Method 2: Using uv (Optional - faster package management)

```bash
# Install uv
pip install uv

# Install dependencies
uv pip install -r requirements.txt
```

## GROBID Setup

GROBID is required for PDF processing. Start it with Docker:

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

To stop GROBID: `docker stop grobid`

See [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for more details.

## Usage

### Basic Example

Process all PDFs in a directory and create a CSV index with TEI and JATS XML files:

```bash
python pdf_to_jats.py Manuscripts --out pdf_index.csv --save-tei --save-jats --verbose
```

### Example with OCR, Metadata Resolution, and Tar.gz Archive

Process PDFs with OCR support, resolve PMID/PMCID from DOIs, and create a tar.gz archive of JATS files:

```bash
python pdf_to_jats.py Manuscripts --out pdf_metadata.csv \
  --grobid-url http://localhost:8070 \
  --prefer-fulltext --ocr \
  --resolve-ncbi --email your.moniker@lanl.gov \
  --save-tei --tei-out tei_cache \
  --save-jats --jats-out jats_cache \
  --create-tarball --tarball-name jats_archive.tar.gz \
  --normalize-unicode --verbose
```

### Process Specific PDFs

Process only specific PDF files:

```bash
python pdf_to_jats.py Manuscripts --out pdf_index.csv \
  --save-tei --save-jats \
  --only "paper1.pdf,paper2.pdf,paper3.pdf" \
  --verbose
```

## Options

- `--grobid-url`: GROBID service base URL (default: http://localhost:8070)
- `--prefer-fulltext`: Prefer processFulltextDocument over header
- `--ocr`: Pass ocr=true to GROBID (effective only if service supports OCR)
- `--save-tei`: Save TEI XML to --tei-out
- `--tei-out`: Directory for TEI cache (default: tei_cache)
- `--save-jats`: Save JATS XML to --jats-out
- `--jats-out`: Directory for JATS cache (default: jats_cache)
- `--xslt-path`: Path to TEI→JATS XSLT stylesheet (default: tei2jats.xsl)
- `--only`: Restrict to specific filename(s); can be given multiple times
- `--resolve-ncbi`: Resolve PMID/PMCID via NCBI idconv using DOI
- `--email`: Contact email for NCBI requests (recommended)
- `--max-req-per-sec`: Throttle for external requests (default: 2.0)
- `--verbose`: Verbose logging
- `--timeout`: HTTP timeout for GROBID (default: 60 seconds)
- `--create-tarball`: Create a tar.gz archive of the JATS output
- `--tarball-name`: Name of the tar.gz archive (default: jats_output.tar.gz)
- `--normalize-unicode`: Normalize Unicode characters to ASCII (useful for compatibility with downstream tools)

### Unicode Normalization

The `--normalize-unicode` flag uses the `unidecode` library to convert Unicode characters to their closest ASCII representation. This is particularly useful for handling author names with diacritics or special characters, ensuring better compatibility with tools that may not support Unicode fully.

Example usage:

```bash
python pdf_to_jats.py Manuscripts --out pdf_index.csv \
  --save-tei --save-jats \
  --normalize-unicode \
  --verbose
```

This will convert characters like "ğ" to "g" in the output CSV and JATS XML files.

## Output

### CSV Index

The script generates a CSV file with the following columns:

- **first_author**: Surname of the first author
- **year**: Publication year
- **title**: Article title
- **journal**: Journal name
- **DOI**: Digital Object Identifier
- **PMID**: PubMed ID (if resolved via NCBI)
- **PMCID**: PubMed Central ID (if resolved via NCBI)
- **file_path**: Relative path to the PDF file
- **tei_path**: Path to the cached TEI XML file
- **jats_path**: Path to the generated JATS XML file
- **source**: Source of metadata (grobid-fulltext, grobid-header, cache, pdfminer, or unknown)
- **notes**: Error messages or warnings (if any)

### TEI and JATS XML Files

If `--save-tei` and `--save-jats` options are used:

- **TEI files** are saved in the directory specified by `--tei-out` (default: `tei_cache/`)
- **JATS files** are saved in the directory specified by `--jats-out` (default: `jats_cache/`)
- Files are named as `<original_basename>.<sha1_hash>.{tei,jats}.xml` for content-addressable caching

## Features

- **Automatic TEI Caching**: TEI XML files are cached by SHA1 hash of PDF content, avoiding reprocessing of unchanged files
- **JATS Conversion**: Converts TEI XML to JATS XML using XSLT transformation
- **Metadata Extraction**: Extracts author, title, journal, DOI, and publication year from PDFs
- **NCBI Integration**: Optional resolution of PMID/PMCID from DOIs via NCBI E-utilities
- **OCR Support**: Processes scanned PDFs using GROBID's OCR capabilities (if enabled in GROBID service)
- **Fallback DOI Extraction**: Uses pdfminer to extract DOI from PDF text if GROBID fails
- **Rate Limiting**: Configurable throttling for external API requests
- **Flexible Processing**: Process all PDFs or filter by specific filenames

## Files in This Repository

- **pdf_to_jats.py**: Main script for processing PDFs
- **tei2jats.xsl**: XSLT stylesheet for converting TEI XML to JATS XML
- **README.md**: This file
- **build_plan.txt**: Detailed refactoring plan (for reference)
- **pyproject.toml**: Project configuration and dependencies
- **Manuscripts/**: Directory containing PDF files (example)

## Compatibility with litkit

This tool is designed to be compatible with litkit for both Stage 1 (title + abstract) and Stage 2 (body paragraphs) processing:

- The JATS XML output includes both the article metadata and full text content.
- The abstract is correctly extracted from the TEI and included in the JATS output.
- Body paragraphs are structured in a way that litkit can easily process for chunked text embeddings.

## Troubleshooting

### GROBID Connection Errors

If you see connection errors, ensure:
1. Docker Desktop is running
2. GROBID container is started (`docker ps` should show the container)
3. GROBID is accessible at `http://localhost:8070`

### XSLT Transformation Errors

If JATS conversion fails:
1. Ensure `tei2jats.xsl` is in the current directory
2. Check that the TEI XML file is valid
3. Verify that `lxml` is properly installed

### Missing Dependencies

If you get import errors, install the required packages:
```bash
pip install -r requirements.txt
```

### tar.gz Archive Creation

If you encounter issues with tar.gz archive creation:
1. Ensure you have write permissions in the output directory
2. Verify that the JATS output files were successfully generated

## License

[Insert license information here]
