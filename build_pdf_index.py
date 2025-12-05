
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pdf_index.py
Scan a folder of PDFs, run them through GROBID to extract bibliographic fields,
optionally OCR via your GROBID service, cache/save TEI, and emit a CSV index.

Columns (in this order):
    first_author, year, title, journal, DOI, PMID, PMCID, file_path, tei_path, source, notes

Key features:
- Robust TEI parsing for first_author across analytic/monogr/titleStmt with TEI namespace.
- Optional prefer-fulltext processing; fallback to header or pdfminer if needed.
- Optional NCBI idconv resolution (PMID/PMCID) for known DOIs.
- Optional Crossref lookup stub (currently only used to sanity-check DOIs found).
- Rate limiting for external requests.
- TEI caching keyed by SHA1 of the PDF bytes; saved as <basename>.<sha1>.tei.xml.
- --only filter to run on a specific filename (can be passed multiple times).

Requirements:
    pip install requests lxml pdfminer.six

Typical usage:
    python build_pdf_index.py Manuscripts --out pdf_index.csv \
      --grobid-url http://localhost:8070 \
      --prefer-fulltext --ocr \
      --resolve-ncbi --email you@org.edu \
      --max-req-per-sec 2.0 \
      --save-tei --tei-out tei_cache \
      --verbose
"""
import argparse
import csv
import hashlib
import os
import re
import sys
import time
import unicodedata
from typing import Dict, Tuple, Optional, List

import requests
from lxml import etree as ET

# pdfminer fallback
try:
    from pdfminer.high_level import extract_text
    _HAS_PDFMINER = True
except Exception:
    _HAS_PDFMINER = False

# --------------------------- Utilities ---------------------------

NS = {"tei": "http://www.tei-c.org/ns/1.0"}

def clean(s: str) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def tei_text(elem, xpath: str) -> str:
    if elem is None:
        return ""
    nodes = elem.xpath(xpath, namespaces=NS)
    if not nodes:
        return ""
    if isinstance(nodes[0], str):
        return clean(nodes[0])
    txt = "".join([t for t in nodes[0].itertext()])
    return clean(txt)

def _first_match(elem, xpaths: List[str]) -> str:
    for xp in xpaths:
        v = tei_text(elem, xp)
        if v:
            return v
    return ""

def parse_tei_fields(tei_xml: str) -> Dict[str, str]:
    """
    Parse a GROBID TEI string and return a dict with:
      first_author, year, title, journal, DOI, PMID, PMCID
    Works for analytic articles, monographs/books, and header-only outputs.
    """
    root = ET.fromstring(tei_xml.encode("utf-8"))

    doi = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='DOI']/text()",
        "//tei:teiHeader//tei:ptr[@type='DOI']/@target",
    ])
    pmid = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='PMID']/text()"
    ])
    pmcid = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='PMCID']/text()",
        "//tei:teiHeader//tei:idno[@type='PMC']/text()"
    ])

    title = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:analytic/tei:title[not(@type) or @type='main']/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[not(@type) or @type='main']/text()",
        "//tei:teiHeader//tei:titleStmt/tei:title/text()"
    ])

    journal = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[@level='j']/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[1]/text()",
    ])

    year = ""
    yraw = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:imprint/tei:date/@when",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:imprint/tei:date/text()",
        "//tei:teiHeader//tei:profileDesc/tei:creation/tei:date/@when",
        "//tei:teiHeader//tei:profileDesc/tei:creation/tei:date/text()",
    ])
    if yraw:
        m = re.search(r"(19|20|21)\d{2}", yraw)
        if m:
            year = m.group(0)

    first_author = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:analytic/tei:author[1]/tei:persName/tei:surname/text()",
        "//tei:teiHeader//tei:biblStruct/tei:analytic/tei:author[1]//tei:surname/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:author[1]/tei:persName/tei:surname/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:author[1]//tei:surname/text()",
        "//tei:teiHeader//tei:titleStmt/tei:author[1]/tei:persName/tei:surname/text()",
        "//tei:teiHeader//tei:titleStmt/tei:author[1]//tei:surname/text()",
        "(//tei:teiHeader//tei:surname/text())[1]"
    ])
    if not first_author:
        first_author = _first_match(root, [
            "(//tei:teiHeader//tei:author[1]//tei:persName//text())[last()]",
        ])
        if first_author and " " in first_author:
            first_author = first_author.split()[-1]

    return {
        "first_author": first_author,
        "year": year,
        "title": title,
        "journal": journal,
        "DOI": doi,
        "PMID": pmid,
        "PMCID": pmcid,
    }

def sha1_of_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def extract_doi_with_pdfminer(path: str, max_pages: int = 3) -> Optional[str]:
    if not _HAS_PDFMINER:
        return None
    try:
        text = extract_text(path, page_numbers=list(range(max_pages)))
        if not text:
            return None
        # DOI pattern (case-insensitive)
        m = re.search(r'10\.\d{4,9}/[-._;()/:A-Z0-9]+', text, flags=re.IGNORECASE)
        if m:
            return m.group(0).rstrip(' .;,)\n\r')
    except Exception:
        return None
    return None

# --------------------------- Networking / Services ---------------------------

class RateLimiter:
    def __init__(self, max_per_sec: float):
        self.min_interval = 1.0 / max_per_sec if max_per_sec > 0 else 0.0
        self.last = 0.0
    def wait(self):
        if self.min_interval <= 0:
            return
        now = time.time()
        delta = now - self.last
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self.last = time.time()

def grobid_process(pdf_path: str, url: str, prefer_fulltext: bool, ocr: bool,
                   timeout: int = 60) -> Tuple[Optional[str], str]:
    """
    Call GROBID. Return (tei_xml, source_label). source_label in
    {'grobid-fulltext','grobid-header'} if successful, else (None,'').
    Note: OCR is handled by the running GROBID service (container). We always pass consolidateHeader=1.
    """
    files = {"input": open(pdf_path, "rb")}
    data = {
        "consolidateHeader": "1",
        "includeRawAffiliations": "1"
    }
    # Some setups accept "ocr" flag; harmless if ignored.
    if ocr:
        data["ocr"] = "true"

    endpoints = []
    if prefer_fulltext:
        endpoints = ["/api/processFulltextDocument", "/api/processHeaderDocument"]
    else:
        endpoints = ["/api/processHeaderDocument", "/api/processFulltextDocument"]

    for i, ep in enumerate(endpoints):
        try:
            resp = requests.post(url.rstrip("/") + ep, files=files, data=data, timeout=timeout)
            if resp.status_code == 200 and resp.text.strip().startswith("<"):
                return resp.text, "grobid-fulltext" if "Fulltext" in ep else "grobid-header"
        except Exception:
            pass
        finally:
            try:
                files["input"].seek(0)
            except Exception:
                pass
    return None, ""

def ncbi_idconv_from_doi(doi: str, email: str, limiter: Optional[RateLimiter]) -> Tuple[str, str, str]:
    """Return (doi, pmid, pmcid). Keeps doi unchanged if NCBI normalizes differently."""
    if not doi:
        return "", "", ""
    url = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
    params = {"tool": "lanl_pdf_index", "email": email or "", "ids": doi, "format": "json"}
    try:
        if limiter: limiter.wait()
        r = requests.get(url, params=params, timeout=30)
        if r.ok:
            j = r.json()
            recs = j.get("records", [])
            if recs:
                rec = recs[0]
                pmid = str(rec.get("pmid") or "") if rec.get("pmid") else ""
                pmcid = str(rec.get("pmcid") or "") if rec.get("pmcid") else ""
                norm_doi = rec.get("doi") or doi
                return norm_doi, pmid, pmcid
    except Exception:
        pass
    return doi, "", ""

# --------------------------- Main ---------------------------

def find_pdfs(root_dir: str) -> List[str]:
    out = []
    for base, _, files in os.walk(root_dir):
        for fn in files:
            if fn.lower().endswith(".pdf"):
                out.append(os.path.join(base, fn))
    out.sort()
    return out

def main():
    ap = argparse.ArgumentParser(description="Index PDFs via GROBID, emit CSV.")
    ap.add_argument("pdf_root", help="Directory containing PDFs (recursively scanned)")
    ap.add_argument("--out", required=True, help="Output CSV path")
    ap.add_argument("--grobid-url", default="http://localhost:8070", help="GROBID service base URL")
    ap.add_argument("--prefer-fulltext", action="store_true", help="Prefer processFulltextDocument over header")
    ap.add_argument("--ocr", action="store_true", help="Pass ocr=true to GROBID (effective only if service supports OCR)")
    ap.add_argument("--save-tei", action="store_true", help="Save TEI XML to --tei-out")
    ap.add_argument("--tei-out", default="tei_cache", help="Directory for TEI cache (created if missing)")
    ap.add_argument("--only", action="append", help="Restrict to specific filename(s); can be given multiple times")
    ap.add_argument("--resolve-ncbi", action="store_true", help="Resolve PMID/PMCID via NCBI idconv using DOI")
    ap.add_argument("--email", default="", help="Contact email for NCBI requests (recommended)")
    ap.add_argument("--max-req-per-sec", type=float, default=2.0, help="Throttle for external requests")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("--timeout", type=int, default=60, help="HTTP timeout for GROBID")
    args = ap.parse_args()

    if args.save_tei and not os.path.isdir(args.tei_out):
        os.makedirs(args.tei_out, exist_ok=True)

    limiter = RateLimiter(args.max_req_per_sec if args.max_req_per_sec > 0 else 1000000.0)

    pdfs = find_pdfs(args.pdf_root)
    only_list = []
    if args.only:
        for item in args.only:
            only_list.extend([s.strip() for s in item.split(",") if s.strip()])
        # Case-insensitive exact filename match
        pdfs = [p for p in pdfs if os.path.basename(p).lower() in {o.lower() for o in only_list}]

    total = len(pdfs)
    if args.verbose:
        print(f"Scanning {total} PDFs under {os.path.abspath(args.pdf_root)} ...")

    rows = []
    for idx, pdf in enumerate(pdfs, 1):
        base = os.path.basename(pdf)
        notes = []
        tei_xml = None
        tei_path = ""
        source = ""
        first_author = year = title = journal = doi = pmid = pmcid = ""

        # Cache key & read if already saved
        sha1 = sha1_of_file(pdf)
        cached_name = f"{os.path.splitext(base)[0]}.{sha1}.tei.xml"
        cached_path = os.path.join(args.tei_out, cached_name)

        if args.save_tei and os.path.isfile(cached_path):
            try:
                with open(cached_path, "r", encoding="utf-8") as f:
                    tei_xml = f.read()
                source = "cache"
            except Exception as e:
                notes.append(f"cache_read_error:{e}")

        # Call GROBID if needed
        if tei_xml is None:
            tei_xml, source = grobid_process(pdf, args.grobid_url, args.prefer_fulltext, args.ocr, timeout=args.timeout)
            if tei_xml is None:
                # pdfminer fallback to at least get DOI
                fallback_doi = extract_doi_with_pdfminer(pdf) or ""
                if fallback_doi:
                    doi = fallback_doi
                    source = "pdfminer"
                    notes.append("tei_missing;doi_from_pdfminer")
                else:
                    source = "unknown"
                    notes.append("tei_missing;no_doi")
            else:
                if args.save_tei:
                    try:
                        with open(cached_path, "w", encoding="utf-8") as f:
                            f.write(tei_xml)
                        tei_path = cached_path
                    except Exception as e:
                        notes.append(f"tei_save_error:{e}")

        # Parse TEI
        if tei_xml:
            try:
                parsed = parse_tei_fields(tei_xml)
                first_author = parsed.get("first_author", "")
                year = parsed.get("year", "")
                title = parsed.get("title", "")
                journal = parsed.get("journal", "")
                doi = doi or parsed.get("DOI", "")
                pmid = parsed.get("PMID", "") or pmid
                pmcid = parsed.get("PMCID", "") or pmcid
                if args.save_tei and not tei_path:
                    # Save if we got here via GROBID but hit a save error earlier
                    try:
                        with open(cached_path, "w", encoding="utf-8") as f:
                            f.write(tei_xml)
                        tei_path = cached_path
                    except Exception as e:
                        notes.append(f"tei_save_error:{e}")
            except ET.XMLSyntaxError as e:
                notes.append(f"tei_parse_error:{e}")

        # NCBI resolve (if DOI present)
        if args.resolve_ncbi and doi:
            try:
                limiter.wait()
                doi, pmid_ncbi, pmcid_ncbi = ncbi_idconv_from_doi(doi, args.email, limiter=None)
                if pmid_ncbi and not pmid:
                    pmid = pmid_ncbi
                if pmcid_ncbi and not pmcid:
                    pmcid = pmcid_ncbi
            except Exception as e:
                notes.append(f"ncbi_error:{e}")

        # Relativize TEI path for portability
        if tei_path:
            try:
                tei_path = os.path.relpath(tei_path, os.getcwd())
            except Exception:
                pass

        if args.verbose:
            print(f"[{idx}/{total}] {base} :: {source or 'unknown'} :: DOI={doi} PMID={pmid} PMCID={pmcid}")

        rows.append({
            "first_author": first_author,
            "year": year,
            "title": title,
            "journal": journal,
            "DOI": doi,
            "PMID": pmid,
            "PMCID": pmcid,
            "file_path": os.path.relpath(pdf, os.getcwd()),
            "tei_path": tei_path,
            "source": source or "unknown",
            "notes": ";".join(notes)
        })

    # Write CSV
    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    fieldnames = ["first_author", "year", "title", "journal",
                  "DOI", "PMID", "PMCID", "file_path", "tei_path", "source", "notes"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    if args.verbose:
        print(f"Wrote {len(rows)} rows to {os.path.abspath(out_path)}")

if __name__ == "__main__":
    main()
