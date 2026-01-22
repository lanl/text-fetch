# Legacy Scripts

Scripts in this directory are archived for historical reference. They have been superseded by text-fetch commands.

## pubmed_access.py

**Status:** Archived  
**Replaced by:** `text-fetch pmc fetch` and `text-fetch fetch`

Original script for PubMed/PMC access using Biopython Entrez. Features included:
- PubMed search via Biopython `Bio.Entrez`
- PDF downloads from PMC (including PoW challenge handling)
- PDF text extraction via pdfplumber
- LangChain Document objects

**Why text-fetch is superior:**
- Downloads **native JATS/NXML** instead of PDFs (structured XML, no extraction needed)
- Multi-source support (PMC, Europe PMC, bioRxiv, arXiv, ChemRxiv)
- Proper rate limiting via `NCBIClient`
- JATS validation (valid vs incomplete)
- JSON config-driven searches
- Unified CLI interface

## pdf_to_jats.py

**Status:** Archived (v0.1.8)  
**Replaced by:** `text-fetch pdf batch`

Original standalone script for PDF→JATS conversion via GROBID. Features included:
- Recursive PDF directory scanning
- GROBID processing (fulltext or header mode)
- TEI → JATS conversion via XSLT
- TEI caching with SHA1-based filenames
- CSV metadata output
- NCBI ID resolution (DOI → PMID/PMCID)
- Tarball creation

**Migration:**
```bash
# Old command
python pdf_to_jats.py --pdf-root ./Manuscripts --out metadata.csv

# New command
text-fetch pdf batch --dir ./Manuscripts --out ./output --csv metadata.csv
```

## ebola.json

Example search configuration used with `pubmed_access.py`. The text-fetch JSON format differs slightly.

**Migration:** See `docs/ROADMAP.md` for the text-fetch SearchConfig format.
