#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from Bio import Entrez, Medline
import requests
import os
import time
import json
from bs4 import BeautifulSoup
import pdfplumber
from langchain.docstore.document import Document
import re
import shlex
import subprocess
from urllib.parse import urljoin
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import hashlib

# --------------------
# Config
# --------------------
Entrez.email = "hlavacek@lanl.gov"  # NCBI requirement

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
      "AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/129.0.0.0 Safari/537.36")

HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
PDF_ACCEPT = "application/pdf,application/octet-stream;q=0.9,*/*;q=0.7"
ACCEPT_LANG = "en-US,en;q=0.9"

# Reuseable browser-y headers (also for PoW HTTP path)
HEADERS = {
    "User-Agent": UA,
    "Accept": PDF_ACCEPT,
    "Accept-Language": ACCEPT_LANG,
    "Referer": "https://pmc.ncbi.nlm.nih.gov/",
}

# --------------------
# Query helpers
# --------------------
def build_pubmed_query(json_filename: str) -> str:
    with open(json_filename, 'r', encoding='utf-8') as f:
        data = json.load(f)

    def format_terms(terms):
        return " OR ".join([f"\"{term}\"[tiab]" for term in terms if term.strip()])

    virus_terms = format_terms(data.get("virus_keywords", []))
    disease_terms = format_terms(data.get("disease_keywords", []))
    vaccine_terms = format_terms(data.get("vaccine_keywords", []))

    combined_virus_disease = f"({virus_terms} OR {disease_terms})"

    date_range = data.get("date_range", {})
    start_date = date_range.get("start", "")
    end_date = date_range.get("end", "")
    date_query = f"\"{start_date}\"[PDAT]:\"{end_date}\"[PDAT]"

    query = f"({combined_virus_disease}) AND ({vaccine_terms}) AND ({date_query})"
    return query

def get_output_directory(json_filename: str) -> str:
    base = os.path.basename(json_filename)
    prefix = base.split("_")[0]
    with open(json_filename, "r", encoding="utf-8") as f:
        data = json.load(f)
    date_range = data.get("date_range", {})
    start_clean = date_range.get("start", "start").replace("/", "_")
    end_clean = date_range.get("end", "end").replace("/", "_")
    return f"{prefix}_PDF_files_{start_clean}_{end_clean}"

# --------------------
# PubMed / PMC lookups
# --------------------
def search_pubmed(query, retmax=128):
    handle = Entrez.esearch(db="pubmed", term=query, retmax=retmax)
    record = Entrez.read(handle)
    handle.close()
    return record["IdList"]

def fetch_pubmed_records(pmids):
    handle = Entrez.efetch(db="pubmed", id=",".join(pmids), rettype="medline", retmode="text")
    records = list(Medline.parse(handle))
    handle.close()
    return records

def get_pmcid(pmid):
    handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid)
    record = Entrez.read(handle)
    handle.close()
    try:
        return record[0]["LinkSetDb"][0]["Link"][0]["Id"]
    except (IndexError, KeyError):
        return None

# --------------------
# PDF text extraction
# --------------------
def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception as e:
        print(f"Error processing {pdf_path}: {e}")
    return text

def load_documents(pdf_directory: str, pubmed_records) -> (list, dict):
    documents = []
    count_pdf = 0
    count_abstract = 0

    if isinstance(pubmed_records, dict):
        pubmed_records = list(pubmed_records.values())

    for record in pubmed_records:
        pmid = record.get("PMID", "")
        pmc_id = record.get("PMCID") or (get_pmcid(pmid) if pmid else None)

        if pmc_id:
            pmcid_norm = pmc_id if str(pmc_id).startswith("PMC") else f"PMC{pmc_id}"
            pdf_filename = f"{pmcid_norm}.pdf"
            pdf_path = os.path.join(pdf_directory, pdf_filename)
            if os.path.exists(pdf_path):
                print(f"Found PDF for PMID {pmid} ({pmcid_norm}). Extracting full text.")
                full_text = extract_text_from_pdf(pdf_path)
                source = pdf_filename
                count_pdf += 1
            else:
                print(f"No PDF file found for {pmcid_norm} (PMID {pmid}). Using title and abstract.")
                full_text = f"{record.get('TI', '')}\n{record.get('AB', '')}"
                source = "PubMed abstract"
                count_abstract += 1
        else:
            print(f"No PMC ID for PMID {pmid}. Using title and abstract.")
            full_text = f"{record.get('TI', '')}\n{record.get('AB', '')}"
            source = "PubMed abstract"
            count_abstract += 1

        documents.append(Document(page_content=full_text, metadata={"PMID": pmid, "source": source}))

    report = {"from_pdf": count_pdf, "from_abstract": count_abstract}
    return documents, report

# --------------------
# Interstitial/redirect helpers for PMC
# --------------------
_PDF_HREF_RE = re.compile(
    r'href=["\']([^"\']+?\.pdf(?:\?[^"\']*)?)["\']',
    re.I
)

def _extract_pdf_hrefs(html: str, base_url: str) -> list[str]:
    urls = []
    for m in _PDF_HREF_RE.finditer(html or ""):
        urls.append(urljoin(base_url, m.group(1)))
    return urls

def _resolve_pdf_redirect(html_text: str, base_url: str) -> str | None:
    m = re.search(r'<meta[^>]+http-equiv=["\']?refresh["\']?[^>]+content=["\']?[^;]+;\s*url=([^"\'>\s]+)', html_text, re.I)
    if m:
        return urljoin(base_url, m.group(1).strip())

    m = re.search(r'(?:window\.location|location\.href|document\.location)\s*=\s*["\']([^"\']+)["\']', html_text, re.I)
    if m:
        return urljoin(base_url, m.group(1).strip())

    m = re.search(r'<a[^>]+href=["\']([^"\']+?(?:\.pdf|/oa/oa\.fcgi[^"\']*))["\']', html_text, re.I)
    if m:
        return urljoin(base_url, m.group(1).strip())

    return None

def get_pmc_oa_pdf_urls(pmc_id: str) -> list[str]:
    pmcid = pmc_id if str(pmc_id).startswith("PMC") else f"PMC{pmc_id}"
    oa_url = f"https://pmc.ncbi.nlm.nih.gov/utils/oa/oa.fcgi?id={pmcid}"
    try:
        r = requests.get(
            oa_url,
            timeout=30,
            headers={
                "User-Agent": UA,
                "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": ACCEPT_LANG,
            },
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)
        urls = []
        for link in root.findall(".//link"):
            href = link.get("href", "")
            fmt = link.get("format", "")
            if fmt and fmt.lower() == "pdf" and href:
                urls.append(urljoin("https://pmc.ncbi.nlm.nih.gov/", href))
        return urls
    except Exception as e:
        print(f"OA lookup failed for {pmcid}: {e}")
        return []

# --------------------
# (A) cURL-based downloading (existing)
# --------------------
def _prep_pmc_url(url: str) -> tuple[str, str | None, str | None]:
    referer = None
    article_url = None
    m = re.search(r"(https://pmc\.ncbi\.nlm\.nih\.gov)/articles/(PMC\d+)/pdf/", url, re.I)
    if m:
        base, pmcid = m.group(1), m.group(2)
        article_url = f"{base}/articles/{pmcid}/"
        referer = article_url
        if "download=1" not in url:
            url = url + ("&download=1" if "?" in url else "?download=1")
    return url, referer, article_url

def _derive_filename(url: str) -> str:
    pmc = re.search(r"/articles/(PMC\d+)/pdf/([^/?#]+)", url, re.I)
    if pmc:
        pmcid, tail = pmc.group(1), pmc.group(2)
        return f"{pmcid}_{tail}"
    return os.path.basename(url.split("?")[0]) or "download.pdf"

def _curl_warmup(article_url: str, cookiejar_path: str) -> None:
    cmd = [
        "curl","-fL","--connect-timeout","15","--max-time","60","--compressed",
        "-H", f"Accept: {HTML_ACCEPT}",
        "-H", f"Accept-Language: {ACCEPT_LANG}",
        "-A", UA,
        "-c", cookiejar_path,   # save cookies here
        "-o", os.devnull,       # discard HTML
        article_url,
    ]
    print(" ".join(shlex.quote(c) for c in cmd))
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Warmup curl failed ({e.returncode}) for {article_url}")

def _curl_once(url: str, out_path: str, referer: str | None, cookiejar_path: str | None) -> tuple[bool, bytes | None]:
    cmd = [
        "curl","-fL","--retry","5","--retry-all-errors","--connect-timeout","15","--max-time","600","--compressed",
        "-H", f"Accept: {PDF_ACCEPT}",
        "-H", f"Accept-Language: {ACCEPT_LANG}",
        "-A", UA,
        "-o", out_path,
    ]
    if referer:
        cmd += ["-e", referer]
    if cookiejar_path:
        cmd += ["-b", cookiejar_path]
    cmd.append(url)

    print(" ".join(shlex.quote(c) for c in cmd))
    try:
        subprocess.run(cmd, check=True)
        with open(out_path, "rb") as f:
            head = f.read(5)
        if head == b"%PDF-":
            print(f"✔ Saved {out_path}")
            return True, None
        else:
            with open(out_path, "rb") as f:
                body = f.read()
            try:
                os.remove(out_path)
            except Exception:
                pass
            return False, body
    except subprocess.CalledProcessError as e:
        print(f"curl failed ({e.returncode}) for {url}")
    except Exception as e:
        print(f"Download failed for {url}: {e}")

    return False, None

def _curl_fetch_html(url: str, referer: str | None, cookiejar_path: str | None) -> str | None:
    cmd = [
        "curl","-fL","--connect-timeout","15","--max-time","60","--compressed",
        "-H", f"Accept: {HTML_ACCEPT}",
        "-H", f"Accept-Language: {ACCEPT_LANG}",
        "-A", UA,
        "-sS",
    ]
    if referer:
        cmd += ["-e", referer]
    if cookiejar_path:
        cmd += ["-b", cookiejar_path]
    cmd.append(url)

    print(" ".join(shlex.quote(c) for c in cmd))
    try:
        p = subprocess.run(cmd, check=True, capture_output=True)
        return p.stdout.decode("latin-1", errors="ignore")
    except subprocess.CalledProcessError as e:
        print(f"curl html fetch failed ({e.returncode}) for {url}")
        return None

def curl_download_direct(url: str, out_dir: str, explicit_name: str | None = None) -> bool:
    """
    For PMC URLs: skip cURL entirely and use the PoW-aware Python downloader right away.
    For non-PMC URLs: keep the original cURL flow as a fallback.
    """
    os.makedirs(out_dir, exist_ok=True)

    # If it's a PMC host, use the working PoW-aware method immediately.
    if _is_pmc_host(url):
        url_prepped, referer, _ = _prep_pmc_url(url)
        filename = explicit_name or _derive_filename(url_prepped)
        out_path = os.path.join(out_dir, filename)
        try:
            print("Using PoW-aware Python downloader (direct)…")
            download_pmc_pdf(url_prepped, out_path, referer=referer or HEADERS.get("Referer"))
            print(f"✔ Saved (PoW) {out_path}")
            return True
        except Exception as e:
            print(f"PoW download failed for {url_prepped}: {e}")
            return False

    # ---- Non-PMC URLs keep the original cURL path (unchanged) ----
    url_prepped, referer, article_url = _prep_pmc_url(url)
    filename = explicit_name or _derive_filename(url_prepped)
    out_path = os.path.join(out_dir, filename)

    cookiejar_path = None
    try:
        if article_url:
            pmc = re.search(r"/articles/(PMC\d+)/", article_url)
            suffix = (pmc.group(1) if pmc else "pmc")
            cookiejar_path = os.path.join(out_dir, f".cookies_{suffix}.txt")
            _curl_warmup(article_url, cookiejar_path)

        ok, body = _curl_once(url_prepped, out_path, referer, cookiejar_path)
        if ok:
            return True

        candidates: list[str] = []
        if body:
            html = body.decode("latin-1", errors="ignore")
            resolved = _resolve_pdf_redirect(html, url_prepped)
            if resolved:
                candidates.append(resolved)

        html2 = _curl_fetch_html(url_prepped, referer, cookiejar_path)
        if html2:
            candidates.extend(_extract_pdf_hrefs(html2, url_prepped))

        m = re.search(r"^(https://pmc\.ncbi\.nlm\.nih\.gov/articles/(PMC\d+)/)pdf/", url_prepped, re.I)
        if m:
            pdf_index = m.group(1) + "pdf/"
            html3 = _curl_fetch_html(pdf_index, referer, cookiejar_path)
            if html3:
                candidates.extend(_extract_pdf_hrefs(html3, pdf_index))

        seen = set()
        uniq_candidates = []
        for u in candidates:
            if u not in seen:
                seen.add(u)
                uniq_candidates.append(u)

        for cand in uniq_candidates:
            cand_prep, cand_ref, _ = _prep_pmc_url(cand)
            tries = [cand_prep]
            if ".pdf" in cand_prep.lower() and "download=1" not in cand_prep.lower():
                tries.append(cand_prep + ("&download=1" if "?" in cand_prep else "?download=1"))
            for t in tries:
                ok2, _ = _curl_once(t, out_path, cand_ref or referer, cookiejar_path)
                if ok2:
                    return True

        print(f"Download failed for {url}: Downloaded file is not a PDF (missing %PDF- header).")
        return False
    finally:
        if cookiejar_path and os.path.exists(cookiejar_path):
            try:
                os.remove(cookiejar_path)
            except Exception:
                pass


def curl_download_batch(urls: list[str], out_dir: str) -> None:
    for u in urls:
        u = u.strip()
        if not u or u.startswith("#"):
            continue
        # This now routes PMC URLs straight to the PoW-aware path via curl_download_direct()
        curl_download_direct(u, out_dir)

# --------------------
# (B) PoW-aware Python HTTP downloader (from your first script)
# --------------------
POW_RE = re.compile(
    r'POW_CHALLENGE\s*=\s*"([^"]+)"[\s\S]*?POW_DIFFICULTY\s*=\s*"(\d+)"[\s\S]*?POW_COOKIE_NAME\s*=\s*"([^"]+)"',
    re.I
)

def _is_pmc_host(url: str) -> bool:
    return bool(re.search(r"^https://pmc\.ncbi\.nlm\.nih\.gov/", url, re.I))

def http_get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    return urllib.request.urlopen(req, timeout=60)

def is_pdf_stream(resp) -> bool:
    ctype = resp.headers.get("Content-Type", "").lower()
    return "application/pdf" in ctype or ctype.endswith("/pdf")

def solve_pow(challenge: str, difficulty: int) -> int:
    prefix = "0" * difficulty
    nonce = 0
    while True:
        h = hashlib.sha256((challenge + str(nonce)).encode("utf-8")).hexdigest()
        if h.startswith(prefix):
            return nonce
        nonce += 1

def download_pmc_pdf(url: str, out_path: str, referer: str | None = None) -> None:
    local_headers = dict(HEADERS)
    if referer:
        local_headers["Referer"] = referer

    # First attempt
    try:
        with http_get(url, local_headers) as resp:
            if is_pdf_stream(resp):
                with open(out_path, "wb") as f:
                    f.write(resp.read())
                print(f"Saved PDF to {out_path}")
                return
            html = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        if e.code == 403 and e.fp:
            html = e.fp.read().decode("utf-8", errors="ignore")
        else:
            raise

    m = POW_RE.search(html)
    if not m:
        raise SystemExit("Failed to detect PMC PoW challenge in the response (no PDF and no challenge found).")

    challenge, diff_str, cookie_name = m.groups()
    difficulty = int(diff_str)
    nonce = solve_pow(challenge, difficulty)
    cookie_value = f"{cookie_name}={challenge},{nonce}"

    headers_with_cookie = dict(local_headers)
    headers_with_cookie["Cookie"] = cookie_value

    with http_get(url, headers_with_cookie) as resp2:
        if not is_pdf_stream(resp2):
            raise SystemExit("PoW solved, but server still did not return a PDF (site behavior may have changed).")
        with open(out_path, "wb") as f:
            while True:
                chunk = resp2.read(1024 * 64)
                if not chunk:
                    break
                f.write(chunk)
    print(f"Saved PDF to {out_path}")

# --------------------
# High-level PMC URL discovery (ALL PDFs, not just main)
# --------------------
def get_pmc_main_pdf_url(pmcid_norm: str) -> str | None:
    # Keep original (used to decide the "canonical" PMCID.pdf)
    oa_urls = get_pmc_oa_pdf_urls(pmcid_norm)
    if oa_urls:
        for u in oa_urls:
            if re.search(r'/pdf/[^/]+\.pdf', u, re.I) and not re.search(r'/suppl', u, re.I):
                return u
        return oa_urls[0]

    article_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid_norm}/"
    try:
        r = requests.get(
            article_url,
            headers={"User-Agent": UA, "Accept": HTML_ACCEPT, "Accept-Language": ACCEPT_LANG},
            timeout=30,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if meta and meta.get("content"):
            return meta["content"]
    except Exception as e:
        print(f"citation_pdf_url lookup failed for {pmcid_norm}: {e}")

    return None

def get_all_pmc_pdf_urls(pmcid_norm: str) -> list[str]:
    """
    Return all plausible PDF URLs for a PMCID:
      - OA service list
      - citation_pdf_url
      - any links under /pdf/ index page
    """
    urls = []

    # OA service
    urls.extend(get_pmc_oa_pdf_urls(pmcid_norm))

    # Article meta
    article_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid_norm}/"
    try:
        r = requests.get(
            article_url,
            headers={"User-Agent": UA, "Accept": HTML_ACCEPT, "Accept-Language": ACCEPT_LANG},
            timeout=30,
        )
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        meta = soup.find("meta", attrs={"name": "citation_pdf_url"})
        if meta and meta.get("content"):
            urls.append(meta["content"])
    except Exception as e:
        print(f"Article page fetch failed for {pmcid_norm}: {e}")

    # /pdf/ index page scrape
    pdf_index = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid_norm}/pdf/"
    try:
        r2 = requests.get(
            pdf_index,
            headers={"User-Agent": UA, "Accept": HTML_ACCEPT, "Accept-Language": ACCEPT_LANG},
            timeout=30,
        )
        if r2.status_code == 200:
            urls.extend(_extract_pdf_hrefs(r2.text, pdf_index))
    except Exception as e:
        print(f"/pdf/ index fetch failed for {pmcid_norm}: {e}")

    # De-dup preserving order
    seen = set()
    uniq = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            uniq.append(u)
    return uniq

def _nice_pdf_name(pmcid_norm: str, url: str, is_primary: bool) -> str:
    """
    Produce a stable filename for a PMCID + URL.
    Primary article -> PMCID.pdf
    Others -> PMCID_<tail>.pdf
    """
    if is_primary:
        return f"{pmcid_norm}.pdf"
    m = re.search(r"/pdf/([^/?#]+\.pdf)", url, re.I)
    if m:
        tail = m.group(1)
    else:
        tail = os.path.basename(url.split("?")[0]) or "download.pdf"
    # Avoid duplicating the canonical name
    if tail.lower() in ("main.pdf", f"{pmcid_norm}.pdf".lower()):
        tail = f"{pmcid_norm}_main.pdf"
    return f"{pmcid_norm}_{tail}"

# --------------------
# MAIN
# --------------------
if __name__ == "__main__":
    # ---- Configure your input JSON here ----
    json_file = "./input/ebola.json"

    # Build query and output dir
    query_string = build_pubmed_query(json_file)
    print(query_string)

    output_directory = get_output_directory(json_file)
    print(output_directory)

    # Search & fetch records
    print("Searching PubMed...")
    pmid_list = search_pubmed(query_string, retmax=1000)
    print(f"Found {len(pmid_list)} articles.")

    records = fetch_pubmed_records(pmid_list)
    for rec in records:
        print(f"PMID: {rec.get('PMID')}, Title: {rec.get('TI', 'No title')[:100]}...")

    pmid_to_record = {r.get("PMID"): r for r in records}

    # Download loop (cURL first; falls back to PoW-aware Python HTTP when needed)
    for pmid in pmid_list:
        time.sleep(0.34)  # ~3 req/sec per NCBI guidance
        rec = pmid_to_record.get(pmid, {})
        pmc_id = rec.get("PMCID") or get_pmcid(pmid)
        if not pmc_id:
            print(f"PMID {pmid} does not have a linked PMC entry.")
            continue

        pmcid_norm = pmc_id if str(pmc_id).startswith("PMC") else f"PMC{pmc_id}"
        print(f"PMID {pmid} found in PMC as {pmcid_norm}. Resolving URLs and downloading...")

        # Get all candidates
        all_urls = get_all_pmc_pdf_urls(pmcid_norm)
        if not all_urls:
            print(f"No PDF URLs found for {pmcid_norm}.")
            continue

        # Choose a primary for canonical PMCID.pdf (prefer non-supplement main)
        primary = None
        for u in all_urls:
            if re.search(r'/pdf/[^/]+\.pdf', u, re.I) and not re.search(r'/suppl', u, re.I):
                primary = u
                break
        if primary is None:
            primary = all_urls[0]

        # Download primary as PMCID.pdf
        ok_primary = curl_download_direct(primary, output_directory, explicit_name=_nice_pdf_name(pmcid_norm, primary, is_primary=True))
        if not ok_primary:
            print(f"Primary download failed for {pmcid_norm} ({primary})")

        # Download any additional PDFs with descriptive names
        for u in all_urls:
            if u == primary:
                continue
            name = _nice_pdf_name(pmcid_norm, u, is_primary=False)
            ok_extra = curl_download_direct(u, output_directory, explicit_name=name)
            if not ok_extra:
                print(f"Supplementary download failed for {pmcid_norm} ({u})")

    # (Optional) Build Document objects from whatever PDFs were saved
    # docs, rpt = load_documents(output_directory, records)
    # print("Loaded documents:", len(docs), "Report:", rpt)
