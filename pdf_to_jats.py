
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_pdf_index.py
Scan a folder of PDFs, run them through GROBID to extract bibliographic fields,
optionally OCR via your GROBID service, cache/save TEI, convert to JATS, and emit a CSV index.

Columns (in this order):
    first_author, year, title, journal, DOI, PMID, PMCID, file_path, tei_path, jats_path, source, notes

Key features:
- Robust TEI parsing for first_author across analytic/monogr/titleStmt with TEI namespace.
- Optional prefer-fulltext processing; fallback to header or pdfminer if needed.
- Optional NCBI idconv resolution (PMID/PMCID) for known DOIs.
- Optional Crossref lookup stub (currently only used to sanity-check DOIs found).
- Rate limiting for external requests.
- TEI caching keyed by SHA1 of the PDF bytes; saved as <basename>.<sha1>.tei.xml.
- JATS conversion via XSLT (tei2jats.xsl); saved as <basename>.<sha1>.jats.xml.
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
      --save-jats --jats-out jats_cache \
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
import tarfile
from typing import Dict, Tuple, Optional, List
from unidecode import unidecode

import requests
from lxml import etree as ET

# pdfminer fallback
try:
    from pdfminer.high_level import extract_text
    _HAS_PDFMINER = True
except Exception:
    _HAS_PDFMINER = False

def create_tarball(directory: str, output_file: str):
    """
    Create a tar.gz archive of the specified directory.
    
    Args:
        directory (str): Path to the directory to be archived
        output_file (str): Name of the output tar.gz file
    """
    with tarfile.open(output_file, "w:gz") as tar:
        tar.add(directory, arcname=os.path.basename(directory))

# --------------------------- Utilities ---------------------------

NS = {"tei": "http://www.tei-c.org/ns/1.0"}

class TeiToJatsError(Exception):
    """Raised when TEI to JATS conversion fails."""
    pass

def tei_to_jats(tei_xml: str, xslt_path: str) -> str:
    """
    Transform TEI XML string to JATS XML string using the provided XSLT stylesheet.
    
    Args:
        tei_xml: TEI XML content as string
        xslt_path: Path to the tei2jats.xsl stylesheet
    
    Returns:
        JATS XML content as string
    
    Raises:
        TeiToJatsError: If transformation fails
    """
    try:
        # Load XSLT stylesheet
        with open(xslt_path, 'rb') as f:
            xslt_root = ET.XML(f.read())
        transform = ET.XSLT(xslt_root)
        
        # Parse TEI document
        tei_doc = ET.XML(tei_xml.encode("utf-8"))
        
        # Transform to JATS
        jats_doc = transform(tei_doc)
        
        # Convert to string with XML declaration
        return ET.tostring(
            jats_doc,
            encoding="utf-8",
            xml_declaration=True,
            pretty_print=True
        ).decode("utf-8")
    except Exception as e:
        raise TeiToJatsError(f"TEI→JATS transform failed: {e}") from e

def clean(s: str, normalize_unicode: bool = False) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ").replace("\u200b", "")
    s = re.sub(r"\s+", " ", s).strip()
    if normalize_unicode:
        s = unidecode(s)
    return s

def tei_text(elem, xpath: str, normalize_unicode: bool = False) -> str:
    if elem is None:
        return ""
    nodes = elem.xpath(xpath, namespaces=NS)
    if not nodes:
        return ""
    if isinstance(nodes[0], str):
        return clean(nodes[0], normalize_unicode)
    txt = "".join([t for t in nodes[0].itertext()])
    return clean(txt, normalize_unicode)

def _first_match(elem, xpaths: List[str], normalize_unicode: bool = False) -> str:
    for xp in xpaths:
        v = tei_text(elem, xp, normalize_unicode)
        if v:
            return v
    return ""

def parse_tei_fields(tei_xml: str, normalize_unicode: bool = False) -> Dict[str, str]:
    """
    Parse a GROBID TEI string and return a dict with:
      first_author, year, title, journal, DOI, PMID, PMCID
    Works for analytic articles, monographs/books, and header-only outputs.
    """
    root = ET.fromstring(tei_xml.encode("utf-8"))

    doi = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='DOI']/text()",
        "//tei:teiHeader//tei:ptr[@type='DOI']/@target",
    ], normalize_unicode)
    pmid = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='PMID']/text()"
    ], normalize_unicode)
    pmcid = _first_match(root, [
        "//tei:teiHeader//tei:idno[@type='PMCID']/text()",
        "//tei:teiHeader//tei:idno[@type='PMC']/text()"
    ], normalize_unicode)

    title = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:analytic/tei:title[not(@type) or @type='main']/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[not(@type) or @type='main']/text()",
        "//tei:teiHeader//tei:titleStmt/tei:title/text()"
    ], normalize_unicode)

    journal = _first_match(root, [
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[@level='j']/text()",
        "//tei:teiHeader//tei:biblStruct/tei:monogr/tei:title[1]/text()",
    ], normalize_unicode)

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
    ], normalize_unicode)
    if not first_author:
        first_author = _first_match(root, [
            "(//tei:teiHeader//tei:author[1]//tei:persName//text())[last()]",
        ], normalize_unicode)
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
    Note: OCR is handled by the running GROBID service (container).
    We always pass consolidateHeader=1.
    """
    with open(pdf_path, "rb") as pdf_file:
        files = {"input": pdf_file}
        data = {
            "consolidateHeader": "1",
            "includeRawAffiliations": "1"
        }
        # Some setups accept "ocr" flag; harmless if ignored.
        if ocr:
            data["ocr"] = "true"

        endpoints = []
        if prefer_fulltext:
            endpoints = ["/api/processFulltextDocument",
                         "/api/processHeaderDocument"]
        else:
            endpoints = ["/api/processHeaderDocument",
                         "/api/processFulltextDocument"]

        for i, ep in enumerate(endpoints):
            try:
                resp = requests.post(url.rstrip("/") + ep, files=files,
                                     data=data, timeout=timeout)
                if resp.status_code == 200 and resp.text.strip().startswith("<"):
                    label = ("grobid-fulltext" if "Fulltext" in ep
                             else "grobid-header")
                    return resp.text, label
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
    ap.add_argument("--save-jats", action="store_true", help="Save JATS XML to --jats-out")
    ap.add_argument("--jats-out", default="jats_cache", help="Directory for JATS cache (created if missing)")
    ap.add_argument("--xslt-path", default="tei2jats.xsl", help="Path to TEI→JATS XSLT stylesheet")
    ap.add_argument("--only", action="append", help="Restrict to specific filename(s); can be given multiple times")
    ap.add_argument("--resolve-ncbi", action="store_true", help="Resolve PMID/PMCID via NCBI idconv using DOI")
    ap.add_argument("--email", default="", help="Contact email for NCBI requests (recommended)")
    ap.add_argument("--max-req-per-sec", type=float, default=2.0, help="Throttle for external requests")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging")
    ap.add_argument("--timeout", type=int, default=60, help="HTTP timeout for GROBID")
    ap.add_argument("--create-tarball", action="store_true", help="Create a tar.gz archive of the JATS output")
    ap.add_argument("--tarball-name", default="jats_output.tar.gz", help="Name of the tar.gz archive (default: jats_output.tar.gz)")
    ap.add_argument("--normalize-unicode", action="store_true", help="Normalize Unicode characters to ASCII")
    args = ap.parse_args()

    if args.save_tei and not os.path.isdir(args.tei_out):
        os.makedirs(args.tei_out, exist_ok=True)
    
    if args.save_jats and not os.path.isdir(args.jats_out):
        os.makedirs(args.jats_out, exist_ok=True)
    
    # Verify XSLT stylesheet exists if JATS conversion is requested
    if args.save_jats and not os.path.isfile(args.xslt_path):
        print(f"ERROR: XSLT stylesheet not found at {args.xslt_path}", file=sys.stderr)
        print(f"Please ensure tei2jats.xsl exists in the current directory or specify --xslt-path", file=sys.stderr)
        sys.exit(1)

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
        jats_path = ""
        source = ""
        first_author = year = title = journal = doi = pmid = pmcid = ""

        # Cache key & construct file paths
        sha1 = sha1_of_file(pdf)
        base_name = os.path.splitext(base)[0]
        cached_tei_name = f"{base_name}.{sha1}.tei.xml"
        cached_jats_name = f"{base_name}.{sha1}.jats.xml"
        cached_tei_path = os.path.join(args.tei_out, cached_tei_name)
        cached_jats_path = os.path.join(args.jats_out, cached_jats_name)

        # Read cached TEI if available
        if args.save_tei and os.path.isfile(cached_tei_path):
            try:
                with open(cached_tei_path, "r", encoding="utf-8") as f:
                    tei_xml = f.read()
                source = "cache"
            except Exception as e:
                notes.append(f"tei_cache_read_error:{e}")

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
                        with open(cached_tei_path, "w", encoding="utf-8") as f:
                            f.write(tei_xml)
                        tei_path = cached_tei_path
                    except Exception as e:
                        notes.append(f"tei_save_error:{e}")

        # Parse TEI
        if tei_xml:
            try:
                parsed = parse_tei_fields(tei_xml, args.normalize_unicode)
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
                        with open(cached_tei_path, "w", encoding="utf-8") as f:
                            f.write(tei_xml)
                        tei_path = cached_tei_path
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

        # Convert TEI to JATS
        if args.save_jats and tei_xml:
            try:
                jats_xml = tei_to_jats(tei_xml, args.xslt_path)
                with open(cached_jats_path, "w", encoding="utf-8") as f:
                    f.write(jats_xml)
                jats_path = cached_jats_path
            except TeiToJatsError as e:
                notes.append(f"jats_conversion_error:{e}")
            except Exception as e:
                notes.append(f"jats_save_error:{e}")
        
        # Relativize paths for portability
        if tei_path:
            try:
                tei_path = os.path.relpath(tei_path, os.getcwd())
            except Exception:
                pass
        
        if jats_path:
            try:
                jats_path = os.path.relpath(jats_path, os.getcwd())
            except Exception:
                pass

        if args.verbose:
            status_parts = [f"[{idx}/{total}] {base}", f"source={source or 'unknown'}"]
            if doi:
                status_parts.append(f"DOI={doi}")
            if pmid:
                status_parts.append(f"PMID={pmid}")
            if pmcid:
                status_parts.append(f"PMCID={pmcid}")
            if jats_path:
                status_parts.append("JATS=✓")
            print(" :: ".join(status_parts))

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
            "jats_path": jats_path,
            "source": source or "unknown",
            "notes": ";".join(notes)
        })

    # Write CSV
    out_path = args.out
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.isdir(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    fieldnames = ["first_author", "year", "title", "journal",
                  "DOI", "PMID", "PMCID", "file_path", "tei_path", "jats_path", "source", "notes"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    if args.verbose:
        print(f"Wrote {len(rows)} rows to {os.path.abspath(out_path)}")

    # Create tar.gz archive if requested
    if args.create_tarball and args.save_jats:
        tarball_path = os.path.join(os.path.dirname(args.out), args.tarball_name)
        create_tarball(args.jats_out, tarball_path)
        if args.verbose:
            print(f"Created tar.gz archive: {os.path.abspath(tarball_path)}")

if __name__ == "__main__":
    main()
