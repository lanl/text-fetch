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

## ebola.json

Example search configuration used with `pubmed_access.py`. The text-fetch JSON format differs slightly.

**Migration:** See `docs/ROADMAP.md` for the text-fetch SearchConfig format.
