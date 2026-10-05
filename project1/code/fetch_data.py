#!/usr/bin/env python3
"""ECON 438 Project 1: raw data acquisition.

Downloads every free raw dataset listed in DATA_FETCH_BRIEF.md, records each
file in data/manifest.csv, builds the manual-work templates in data/manual/ and
writes data/FETCH_REPORT.md with the acceptance checks.

Usage:
    python fetch_data.py --email <contact> [--only <step> ...] [--force]

Steps (run in this order when --only is not given):
    openfema  D1-D4   OpenFEMA bulk CSVs
    storm     D6      NOAA Storm Events details files, 1988 onward
    pda       D7      FEMA Preliminary Damage Assessment PDFs (+ R extraction)
    fedreg    D8      Federal Register per-capita indicator notices
    bea       D9 D11  BEA regional zips
    bls       D10     BLS LAUS state unemployment
    fred      D12     CPI-U
    ttr       D13     Treasury Total Taxable Resources
    dataverse D15 D16 D22  Harvard Dataverse datasets
    census    D19     House apportionment table C1
    voteview  D20 D21 Voteview members and party means
    templates         data/manual/*.csv
    report            acceptance checks + FETCH_REPORT.md

--only also accepts dataset IDs (e.g. --only D3 D13).
Raw files are never rewritten: existing files are skipped unless --force.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import gzip
import hashlib
import html
import io
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import urllib3.util.connection

# IPv6 routes to some hosts (fema.gov's CDN) hang until the connect timeout on
# this network; urllib3 has no happy-eyeballs fallback, so resolve IPv4 only.
urllib3.util.connection.HAS_IPV6 = False

# --------------------------------------------------------------------------
# Paths and constants
# --------------------------------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CODE_DIR.parent
DATA_DIR = PROJECT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
MANUAL_DIR = DATA_DIR / "manual"
MANIFEST_PATH = DATA_DIR / "manifest.csv"
REPORT_PATH = DATA_DIR / "FETCH_REPORT.md"
CHECKS_PATH = DATA_DIR / "acceptance_checks.json"

TIMEOUT = (20, 120)  # (connect, read) seconds
ATTEMPTS = 3
MIN_INTERVAL = 0.5  # seconds between requests to the same host (2 req/s)
# Some hosts (NOAA) intermittently serve a body at a few KB/s; abort and retry
# an attempt that averages below MIN_RATE bytes/s after STALL_GRACE seconds.
MIN_RATE = 50_000
STALL_GRACE = 60
HARD_DEADLINE = 600  # seconds per download attempt

MANIFEST_FIELDS = [
    "dataset_id", "source", "url", "local_path", "bytes", "sha256",
    "http_status", "downloaded_at_utc", "status", "note",
]

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

STEPS = [
    "openfema", "storm", "pda", "fedreg", "bea", "bls", "fred", "ttr",
    "dataverse", "census", "voteview", "governors", "templates", "report",
]
ID_TO_STEP = {
    "D1": "openfema", "D2": "openfema", "D3": "openfema", "D4": "openfema",
    "D6": "storm", "D7": "pda", "D8": "fedreg", "D9": "bea", "D11": "bea",
    "D10": "bls", "D12": "fred", "D13": "ttr", "D15": "dataverse",
    "D16": "dataverse", "D22": "dataverse", "D19": "census",
    "D20": "voteview", "D21": "voteview", "D17": "governors", "D18": "governors",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_DIR).as_posix()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

class Manifest:
    """One row per file attempted, keyed by local_path (or url if no file)."""

    def __init__(self, path: Path):
        self.path = path
        self.rows: dict[str, dict] = {}
        if path.exists():
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    self.rows[self._key(row)] = row

    @staticmethod
    def _key(row: dict) -> str:
        return row.get("local_path") or f"{row['dataset_id']}|{row['url']}"

    def get(self, local_path: str) -> dict | None:
        return self.rows.get(local_path)

    def record(self, **row) -> None:
        full = {k: "" for k in MANIFEST_FIELDS}
        full.update({k: ("" if v is None else str(v)) for k, v in row.items()})
        if full["local_path"]:
            # a success supersedes an earlier failed/blocked attempt at the same URL
            self.rows.pop(f"{full['dataset_id']}|{full['url']}", None)
        self.rows[self._key(full)] = full
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".csv.part")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
            w.writeheader()
            for key in sorted(self.rows, key=lambda k: (
                    self.rows[k]["dataset_id"], self.rows[k]["local_path"],
                    self.rows[k]["url"])):
                w.writerow(self.rows[key])
        tmp.replace(self.path)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Blocked(Exception):
    """Host unreachable or refusing this client (DNS, connection, 403)."""


class DeadlineExceeded(Exception):
    """An attempt ran past HARD_DEADLINE. Deliberately not an OSError, so
    urllib3 does not swallow it as a socket error."""


@contextlib.contextmanager
def deadline(seconds: float):
    """Wall-clock limit on a block. A server that trickles a byte at a time
    never trips the socket read timeout; SIGALRM interrupts the blocked read."""
    def on_alarm(signum, frame):
        raise DeadlineExceeded(f"hard deadline {seconds:.0f} s exceeded")
    previous = signal.signal(signal.SIGALRM, on_alarm)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


class Fetcher:
    def __init__(self, email: str, manifest: Manifest, force: bool):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = (
            f"ECON438-Project1-datafetch/1.0 (academic research; contact: {email})")
        self.manifest = manifest
        self.force = force
        self._last: dict[str, float] = {}

    def _throttle(self, url: str) -> None:
        host = urlparse(url).netloc
        wait = self._last.get(host, 0) + MIN_INTERVAL - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last[host] = time.monotonic()

    def request(self, url: str, params=None, stream=False) -> requests.Response:
        """GET with throttling and three attempts. Raises Blocked or the last error."""
        last_exc: Exception | None = None
        for attempt in range(1, ATTEMPTS + 1):
            self._throttle(url)
            try:
                with deadline(HARD_DEADLINE):
                    r = self.session.get(url, params=params, timeout=TIMEOUT, stream=stream)
                if r.status_code == 403:
                    r.close()
                    raise Blocked(f"HTTP 403 from {urlparse(url).netloc}")
                if r.status_code in (429,) or r.status_code >= 500:
                    r.close()
                    raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
                return r
            except Blocked:
                if attempt == ATTEMPTS:
                    raise
                last_exc = None
            except requests.ConnectionError as e:
                last_exc = e
                if attempt == ATTEMPTS:
                    raise Blocked(f"connection error: {e}") from e
            except (requests.RequestException, DeadlineExceeded) as e:
                last_exc = e
                if attempt == ATTEMPTS:
                    raise
            time.sleep(2 ** attempt)
        raise last_exc  # pragma: no cover

    def get_json(self, url: str, params=None):
        r = self.request(url, params=params)
        r.raise_for_status()
        return r.json()

    def get_text(self, url: str, params=None) -> str:
        r = self.request(url, params=params)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _stream_to(r: requests.Response, part: Path) -> None:
        """Write the body to part; give up if it trickles in below MIN_RATE."""
        start, done = time.monotonic(), 0
        with deadline(HARD_DEADLINE), r, open(part, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                elapsed = time.monotonic() - start
                if elapsed > STALL_GRACE and done / elapsed < MIN_RATE:
                    raise TimeoutError(f"stalled: {done:,} bytes in {elapsed:.0f} s")
        expected = r.headers.get("Content-Length")
        if expected and int(expected) != done and "gzip" not in r.headers.get("Content-Encoding", ""):
            raise TimeoutError(f"truncated body: {done:,} of {int(expected):,} bytes")

    def download(self, dataset_id: str, source: str, url: str, dest: Path,
                 params=None, note: str = "", validate=None) -> str:
        """Download url to dest via dest.part. Returns the manifest status."""
        key = rel(dest)
        if dest.exists() and not self.force:
            prev = self.manifest.get(key)
            if prev and prev.get("sha256") and prev.get("status") in ("ok", "skipped"):
                log(f"  [skip] {key}")
                return "skipped"
            # file present without a manifest row: register it, do not re-fetch
            self.manifest.record(
                dataset_id=dataset_id, source=source, url=url, local_path=key,
                bytes=dest.stat().st_size, sha256=sha256_of(dest),
                downloaded_at_utc=datetime.fromtimestamp(
                    dest.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                status="skipped",
                note=(note + "; " if note else "") +
                     "file already on disk, not re-downloaded; time is file mtime")
            log(f"  [skip, registered] {key}")
            return "skipped"

        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        full_url = url
        try:
            for attempt in range(1, ATTEMPTS + 1):
                r = self.request(url, params=params, stream=True)
                full_url = r.url
                status_code = r.status_code
                if status_code != 200:
                    r.close()
                    raise requests.HTTPError(f"HTTP {status_code}", response=r)
                try:
                    self._stream_to(r, part)
                    break
                except (requests.RequestException, DeadlineExceeded, OSError, ValueError) as e:
                    part.unlink(missing_ok=True)
                    if attempt == ATTEMPTS:
                        raise
                    log(f"  body attempt {attempt} failed ({e}); retrying")
                    time.sleep(2 ** attempt)
            if validate is not None:
                problem = validate(part)
                if problem:
                    part.unlink(missing_ok=True)
                    raise ValueError(f"validation failed: {problem}")
            downloaded_at = utc_now()
            part.replace(dest)
            self.manifest.record(
                dataset_id=dataset_id, source=source, url=full_url, local_path=key,
                bytes=dest.stat().st_size, sha256=sha256_of(dest),
                http_status=status_code, downloaded_at_utc=downloaded_at,
                status="ok", note=note)
            log(f"  [ok] {key} ({dest.stat().st_size:,} bytes)")
            return "ok"
        except Blocked as e:
            part.unlink(missing_ok=True)
            self.manifest.record(dataset_id=dataset_id, source=source, url=full_url,
                                 local_path="", http_status="403" if "403" in str(e) else "",
                                 downloaded_at_utc=utc_now(), status="blocked",
                                 note=f"{e}" + (f"; {note}" if note else ""))
            log(f"  [blocked] {url}: {e}")
            return "blocked"
        except Exception as e:  # noqa: BLE001 - one failure must not stop the run
            part.unlink(missing_ok=True)
            code = getattr(getattr(e, "response", None), "status_code", "")
            self.manifest.record(dataset_id=dataset_id, source=source, url=full_url,
                                 local_path="", http_status=code,
                                 downloaded_at_utc=utc_now(), status="failed",
                                 note=f"{type(e).__name__}: {e}" + (f"; {note}" if note else ""))
            log(f"  [failed] {url}: {e}")
            return "failed"


def looks_like_csv(min_lines: int = 2):
    def check(path: Path):
        with open(path, "rb") as f:
            head = f.read(1 << 20)
        if head.lstrip().startswith((b"<", b"{")):
            return "response is HTML/JSON, not CSV"
        if head.count(b"\n") < min_lines - 1:
            return "fewer lines than expected"
        return None
    return check


def is_zip(path: Path):
    return None if zipfile.is_zipfile(path) else "not a valid zip"


def magic(prefix: bytes, label: str):
    def check(path: Path):
        with open(path, "rb") as f:
            return None if f.read(len(prefix)) == prefix else f"not a {label} file"
    return check


# --------------------------------------------------------------------------
# Steps
# --------------------------------------------------------------------------

OPENFEMA = [
    ("D1", "https://www.fema.gov/api/open/v1/DeclarationDenials"),
    ("D2", "https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries"),
    ("D3", "https://www.fema.gov/api/open/v1/FemaWebDisasterDeclarations"),
    ("D4", "https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries"),
]


def step_openfema(fx: Fetcher, only_ids: set[str] | None) -> None:
    out = RAW_DIR / "openfema"
    for did, endpoint in OPENFEMA:
        if only_ids and did not in only_ids:
            continue
        name = endpoint.rsplit("/", 1)[1]
        log(f"{did} {name}")
        status = fx.download(did, "OpenFEMA", endpoint + ".csv", out / f"{name}.csv",
                             note="bulk CSV", validate=looks_like_csv(10))
        if status in ("failed",) and did in ("D3", "D4"):
            log(f"  CSV failed; falling back to paged JSON for {did}")
            openfema_json_fallback(fx, did, endpoint, out / f"{name}.json")


def openfema_json_fallback(fx: Fetcher, did: str, endpoint: str, dest: Path) -> None:
    if dest.exists() and not fx.force:
        log(f"  [skip] {rel(dest)}")
        return
    rows, skip, total = [], 0, None
    try:
        while total is None or len(rows) < total:
            data = fx.get_json(endpoint, params={
                "$top": 1000, "$skip": skip, "$inlinecount": "allpages"})
            total = data["metadata"]["count"]
            page = data[endpoint.rsplit("/", 1)[1]]
            if not page:
                break
            rows.extend(page)
            skip += len(page)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        part.write_text(json.dumps(rows), encoding="utf-8")
        part.replace(dest)
        fx.manifest.record(dataset_id=did, source="OpenFEMA", url=endpoint + "?$top=1000&$skip=N",
                           local_path=rel(dest), bytes=dest.stat().st_size,
                           sha256=sha256_of(dest), http_status=200,
                           downloaded_at_utc=utc_now(), status="ok",
                           note=f"JSON fallback, {len(rows)} of metadata.count={total} rows")
    except Exception as e:  # noqa: BLE001
        fx.manifest.record(dataset_id=did, source="OpenFEMA", url=endpoint,
                           downloaded_at_utc=utc_now(),
                           status="blocked" if isinstance(e, Blocked) else "failed",
                           note=f"JSON fallback: {type(e).__name__}: {e}")


STORM_BASE = "https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/"
STORM_RE = re.compile(r"StormEvents_details-ftp_v1\.0_d(\d{4})_c(\d{8})\.csv\.gz")


def step_storm(fx: Fetcher, first_year: int = 1988) -> None:
    log("D6 NOAA Storm Events details")
    try:
        listing = fx.get_text(STORM_BASE)
    except Exception as e:  # noqa: BLE001
        fx.manifest.record(dataset_id="D6", source="NOAA NCEI", url=STORM_BASE,
                           downloaded_at_utc=utc_now(),
                           status="blocked" if isinstance(e, Blocked) else "failed",
                           note=f"directory listing: {e}")
        return
    latest: dict[int, tuple[str, str]] = {}
    for m in STORM_RE.finditer(listing):
        year, cdate = int(m.group(1)), m.group(2)
        if year >= first_year and (year not in latest or cdate > latest[year][0]):
            latest[year] = (cdate, m.group(0))
    for year in sorted(latest):
        cdate, fname = latest[year]
        fx.download("D6", "NOAA NCEI Storm Events", STORM_BASE + fname,
                    RAW_DIR / "storm_events" / fname,
                    note=f"year {year}, latest revision c{cdate}",
                    validate=magic(b"\x1f\x8b", "gzip"))


PDA_LISTING = "https://www.fema.gov/disaster/how-declared/preliminary-damage-assessments/reports"


def step_pda(fx: Fetcher) -> None:
    """Scrape PDA listing for PDF links; run the Urban Institute R extraction if R exists."""
    log("D7 FEMA Preliminary Damage Assessments")
    pdf_dir = RAW_DIR / "pda" / "pdfs"
    try:
        first = fx.request(PDA_LISTING)
        first.raise_for_status()
    except Exception as e:  # noqa: BLE001
        fx.manifest.record(
            dataset_id="D7", source="FEMA PDA reports", url=PDA_LISTING,
            http_status="403" if "403" in str(e) else "", downloaded_at_utc=utc_now(),
            status="blocked" if isinstance(e, Blocked) else "failed",
            note=f"listing page: {e}. PDFs and R extraction not attempted; "
                 "the www.fema.gov web pages refuse this network (OpenFEMA API is fine)")
        return

    # Listing reachable: collect PDF links page by page, then download them.
    pdf_urls: list[str] = []
    page, text = 0, first.text
    while True:
        links = re.findall(r'href="([^"]+\.pdf)"', text, flags=re.I)
        if not links:
            break
        new = [urljoin(PDA_LISTING, html.unescape(u)) for u in links]
        pdf_urls.extend(u for u in new if u not in pdf_urls)
        page += 1
        try:
            text = fx.get_text(PDA_LISTING, params={"page": page})
        except Exception as e:  # noqa: BLE001
            log(f"  listing page {page} failed: {e}")
            break
    log(f"  {len(pdf_urls)} PDF links on {page} listing pages")
    for url in pdf_urls:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(urlparse(url).path).name)
        fx.download("D7", "FEMA PDA reports", url, pdf_dir / name,
                    validate=magic(b"%PDF", "PDF"))

    if shutil.which("Rscript"):
        run_pda_r_extraction(fx, pdf_dir)
    else:
        log("  Rscript not found: PDFs only, no draft extraction")


def run_pda_r_extraction(fx: Fetcher, pdf_dir: Path) -> None:
    draft = RAW_DIR / "pda" / "pda_extracted_draft.csv"
    if draft.exists() and not fx.force:
        log(f"  [skip] {rel(draft)}")
        return
    script = f"""
    options(repos = c(CRAN = "https://cloud.r-project.org"))
    if (!requireNamespace("remotes", quietly = TRUE)) install.packages("remotes")
    if (!requireNamespace("preliminarydamageassessments", quietly = TRUE))
      remotes::install_github("UrbanInstitute/preliminary-damage-assessments", upgrade = "never")
    library(preliminarydamageassessments)
    scrape_pda_pdfs(cache_directory = {json.dumps(str(pdf_dir))})
    df <- get_preliminary_damage_assessments(
      file_path = {json.dumps(str(draft) + ".part")},
      directory_path = {json.dumps(str(pdf_dir))}, use_cache = TRUE)
    if (!file.exists({json.dumps(str(draft) + ".part")})) readr::write_csv(df, {json.dumps(str(draft) + ".part")})
    """
    try:
        subprocess.run(["Rscript", "-e", script], check=True, timeout=6 * 3600)
        Path(str(draft) + ".part").replace(draft)
        fx.manifest.record(dataset_id="D7", source="UrbanInstitute R package",
                           url="github.com/UrbanInstitute/preliminary-damage-assessments",
                           local_path=rel(draft), bytes=draft.stat().st_size,
                           sha256=sha256_of(draft), downloaded_at_utc=utc_now(),
                           status="ok", note="DRAFT extraction, needs human checking")
    except Exception as e:  # noqa: BLE001
        fx.manifest.record(dataset_id="D7", source="UrbanInstitute R package",
                           url="github.com/UrbanInstitute/preliminary-damage-assessments",
                           downloaded_at_utc=utc_now(), status="failed",
                           note=f"R extraction: {e}")


FR_API = "https://www.federalregister.gov/api/v1/documents.json"
FR_FIELDS = ["title", "publication_date", "document_number", "html_url", "pdf_url",
             "raw_text_url", "full_text_xml_url", "type", "agencies", "abstract"]
FR_QUERIES = [
    # (label, params) - the first is the query given in the brief
    ("brief", {"conditions[term]": '"statewide per capita impact indicator"'}),
    ("supplement", {"conditions[term]": '"per capita impact indicator"',
                    "conditions[agencies][]": "federal-emergency-management-agency"}),
]


def step_fedreg(fx: Fetcher) -> None:
    log("D8 Federal Register per-capita indicator notices")
    out = RAW_DIR / "fedreg"
    docs: dict[str, dict] = {}
    for label, q in FR_QUERIES:
        dest = out / f"search_{label}.json"
        params = {**q, "per_page": 100, "order": "oldest", "fields[]": FR_FIELDS}
        status = fx.download("D8", "Federal Register API", FR_API, dest, params=params,
                             note=f"search results ({label} query, page 1)",
                             validate=magic(b"{", "JSON"))
        if not dest.exists():
            continue
        data = json.loads(dest.read_text(encoding="utf-8"))
        if data.get("total_pages", 1) > 1:
            log(f"  WARNING: {label} query has {data['total_pages']} pages; only page 1 saved")
        for r in data.get("results", []):
            d = docs.setdefault(r["document_number"], {**r, "queries": []})
            d["queries"].append(label)

    # Index of notices (derived listing, not a raw file).
    index = out / "fedreg_notices.csv"
    with open(index, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["publication_date", "document_number", "title", "type", "html_url",
                    "raw_text_url", "pdf_url", "matched_queries"])
        for d in sorted(docs.values(), key=lambda d: (d["publication_date"], d["document_number"])):
            w.writerow([d["publication_date"], d["document_number"], d["title"], d.get("type"),
                        d.get("html_url"), d.get("raw_text_url"), d.get("pdf_url"),
                        ";".join(d["queries"])])
    fx.manifest.record(dataset_id="D8", source="Federal Register API (derived index)",
                       url=FR_API, local_path=rel(index), bytes=index.stat().st_size,
                       sha256=sha256_of(index), downloaded_at_utc=utc_now(), status="ok",
                       note=f"{len(docs)} notices; built from search_*.json")

    # Notice text. federalregister.gov's full_text URLs answer scripts with a
    # "Request Access" page (HTTP 200), so take the GPO govinfo edition of the
    # same notice first and use raw_text_url only as a fallback.
    for d in docs.values():
        num, note = d["document_number"], f"{d['publication_date']} {d['title'][:80]}"
        govinfo = (d.get("pdf_url") or "").replace("/pdf/", "/html/")
        govinfo = govinfo[:-4] + ".htm" if govinfo.endswith(".pdf") else ""
        status = "failed"
        if govinfo:
            status = fx.download("D8", "GPO govinfo (Federal Register)", govinfo,
                                 out / "text" / f"{num}.htm", note=note,
                                 validate=not_access_wall)
        if status not in ("ok", "skipped") and d.get("raw_text_url"):
            fx.download("D8", "Federal Register", d["raw_text_url"],
                        out / "text" / f"{num}.txt", note=note, validate=not_access_wall)


def not_access_wall(path: Path):
    with open(path, "rb") as f:
        head = f.read(4096)
    if b"Request Access" in head or b"<!DOCTYPE html" in head[:100]:
        return "bot-check page instead of the document"
    return None


def step_bea(fx: Fetcher) -> None:
    for did, name in [("D9", "SAINC"), ("D9", "SAGDP"), ("D9", "SAGDP_SIC"), ("D11", "CAINC1")]:
        log(f"{did} BEA {name}")
        fx.download(did, "BEA Regional", f"https://apps.bea.gov/regional/zip/{name}.zip",
                    RAW_DIR / "bea" / f"{name}.zip", validate=is_zip)


def step_bls(fx: Fetcher) -> None:
    log("D10 BLS LAUS")
    base = "https://download.bls.gov/pub/time.series/la/"
    for name in ["la.data.3.AllStatesS", "la.series", "la.area", "la.measure"]:
        fx.download("D10", "BLS LAUS", base + name, RAW_DIR / "bls_laus" / name,
                    validate=looks_like_csv(2))


def step_fred(fx: Fetcher) -> None:
    log("D12 FRED CPIAUCSL")
    fx.download("D12", "FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
                RAW_DIR / "fred" / "CPIAUCSL.csv", validate=looks_like_csv(10))


TTR_PAGE = "https://home.treasury.gov/policy-issues/economic-policy/total-taxable-resources"


def step_ttr(fx: Fetcher) -> None:
    log("D13 Treasury Total Taxable Resources")
    out = RAW_DIR / "treasury_ttr"
    try:
        page = fx.get_text(TTR_PAGE)
    except Exception as e:  # noqa: BLE001
        fx.manifest.record(dataset_id="D13", source="US Treasury", url=TTR_PAGE,
                           downloaded_at_utc=utc_now(),
                           status="blocked" if isinstance(e, Blocked) else "failed",
                           note=f"listing page: {e}")
        return
    # hrefs on this page are unquoted
    links = sorted(set(re.findall(r'(?:https://home\.treasury\.gov)?/system/files/226/[^"\'\s>]+\.xlsx?',
                                  page, flags=re.I)))
    for link in links:
        url = urljoin(TTR_PAGE, link)
        fx.download("D13", "US Treasury TTR", url, out / Path(urlparse(url).path).name,
                    validate=magic(b"PK", "xlsx") if url.lower().endswith(".xlsx")
                    else magic(b"\xd0\xcf\x11\xe0", "xls"))
    if not any(re.search(r"(^|/)2004est\.xls", l) for l in links):
        fx.manifest.record(dataset_id="D13", source="US Treasury TTR", url=TTR_PAGE,
                           downloaded_at_utc=utc_now(), status="failed",
                           note="2004 estimate: no file listed on the Treasury page; "
                                "URL not guessed (allowed to be missing)")


DV_API = "https://dataverse.harvard.edu/api"
DATAVERSE = [
    ("D15", "doi:10.7910/DVN/42MVDX", "mit_president"),
    ("D16", "hdl:1902.1/20403", "klarner_partisan_balance"),
    ("D16", "hdl:1902.1/20408", "klarner_governors"),
    ("D22", None, "shor_mccarty"),  # resolved at run time, see latest_shor_mccarty()
]
SHOR_DEFAULT = "doi:10.7910/DVN/WI8ERB"


def latest_shor_mccarty(fx: Fetcher) -> tuple[str, str]:
    """Newest 'Aggregate State Legislator Shor-McCarty' dataset on Dataverse."""
    try:
        data = fx.get_json(f"{DV_API}/search", params={
            "q": '"Aggregate State Legislator Shor-McCarty Ideology Data"',
            "type": "dataset", "per_page": 50})
        cands = [i for i in data["data"]["items"]
                 if i.get("name", "").startswith("Aggregate State Legislator Shor-McCarty")]
        if cands:
            best = max(cands, key=lambda i: i.get("published_at", ""))
            return best["global_id"], f"newest of {len(cands)} versions: {best['name']}"
    except Exception as e:  # noqa: BLE001
        return SHOR_DEFAULT, f"search failed ({e}); used brief's DOI"
    return SHOR_DEFAULT, "search found nothing; used brief's DOI"


def step_dataverse(fx: Fetcher, only_ids: set[str] | None) -> None:
    for did, pid, folder in DATAVERSE:
        if only_ids and did not in only_ids:
            continue
        note = ""
        if pid is None:
            pid, note = latest_shor_mccarty(fx)
        log(f"{did} Dataverse {pid} -> {folder}")
        out = RAW_DIR / "dataverse" / folder
        try:
            listing = fx.get_json(f"{DV_API}/datasets/:persistentId/versions/:latest/files",
                                  params={"persistentId": pid})
        except Exception as e:  # noqa: BLE001
            fx.manifest.record(dataset_id=did, source="Harvard Dataverse", url=pid,
                               downloaded_at_utc=utc_now(),
                               status="blocked" if isinstance(e, Blocked) else "failed",
                               note=f"file listing: {e}")
            continue
        out.mkdir(parents=True, exist_ok=True)
        meta = out / "_dataverse_files.json"
        if not meta.exists() or fx.force:
            meta.write_text(json.dumps({"persistentId": pid, "note": note,
                                        "retrieved_at_utc": utc_now(), **listing}, indent=2),
                            encoding="utf-8")
            fx.manifest.record(dataset_id=did, source="Harvard Dataverse API",
                               url=f"{DV_API}/datasets/:persistentId/versions/:latest/files?persistentId={pid}",
                               local_path=rel(meta), bytes=meta.stat().st_size,
                               sha256=sha256_of(meta), http_status=200,
                               downloaded_at_utc=utc_now(), status="ok",
                               note=("file listing; " + note).strip("; "))
        for item in listing["data"]:
            dfile = item["dataFile"]
            original = dfile.get("originalFileName")
            name = original or dfile["filename"]
            url = f"{DV_API}/access/datafile/{dfile['id']}"
            fx.download(did, "Harvard Dataverse", url + ("?format=original" if original else ""),
                        out / name, note=f"{pid} file id {dfile['id']}")


def step_census(fx: Fetcher) -> None:
    log("D19 Census apportionment Table C1")
    base = "https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/"
    ok = False
    for name, check in [("apportionment-2020-tableC1.xlsx", magic(b"PK", "xlsx")),
                        ("apportionment-2020-tableC1.pdf", magic(b"%PDF", "PDF"))]:
        status = fx.download("D19", "US Census Bureau", base + name,
                             RAW_DIR / "census_apportionment" / name, validate=check)
        ok = ok or status in ("ok", "skipped")
    if not ok:
        log("  falling back to National Archives allocation page")
        fx.download("D19", "National Archives", "https://www.archives.gov/electoral-college/allocation",
                    RAW_DIR / "census_apportionment" / "nara_allocation.html",
                    note="fallback for Census Table C1")


def step_voteview(fx: Fetcher) -> None:
    base = "https://voteview.com/static/data/out/"
    for did, path in [("D20", "members/HSall_members.csv"), ("D21", "parties/HSall_parties.csv")]:
        log(f"{did} Voteview {path}")
        fx.download(did, "Voteview", base + path, RAW_DIR / "voteview" / Path(path).name,
                    validate=looks_like_csv(10))


WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_SPARQL = "https://query.wikidata.org/sparql"
GOV_ELECTION_YEARS = range(1976, 2029)  # from 1976 so terms begun before 1989 split correctly


def step_governors(fx: Fetcher) -> None:
    """Sources for the governor template (D17 term limits, D18 election calendar).

    - Wikipedia "<year> United States gubernatorial elections", 1976-2028:
      one table per year with incumbent, party and result ("term-limited",
      "retired", "re-elected", ...). Saved as the parse-API JSON as served.
    - Wikidata: every tenure in each state's "Governor of <State>" position
      (P39 with start/end qualifiers), saved as the SPARQL CSV as served.
    These are encyclopedic secondary sources; build_governors.py cross-checks
    them against each other and against Klarner (1989-2011).
    """
    log("D17/D18 governor sources (Wikipedia election pages, Wikidata tenures)")
    out = RAW_DIR / "governors"
    for year in GOV_ELECTION_YEARS:
        page = f"{year} United States gubernatorial elections"
        fx.download("D18", "Wikipedia", WIKI_API, out / "wikipedia" / f"{year}_gubernatorial_elections.json",
                    params={"action": "parse", "page": page, "prop": "text|revid",
                            "format": "json", "formatversion": 2, "redirects": 1},
                    note=f"parse API: {page}", validate=magic(b"{", "JSON"))

    # labels are not consistently capitalised (Iowa's item is "governor of Iowa")
    labels = " ".join(f'"{g} of {s}"@en' for s in STATES.values() for g in ("Governor", "governor"))
    pos_query = f"SELECT ?pos ?label WHERE {{ VALUES ?label {{ {labels} }} ?pos rdfs:label ?label . }}"
    pos_file = out / "wikidata" / "governor_positions.csv"
    fx.session.headers["Accept"] = "text/csv"
    try:
        fx.download("D17", "Wikidata", WIKIDATA_SPARQL, pos_file, params={"query": pos_query},
                    note="Governor of <State> position items", validate=looks_like_csv(2))
        if pos_file.exists():
            with open(pos_file, encoding="utf-8") as f:
                ids = sorted({r["pos"].rsplit("/", 1)[1] for r in csv.DictReader(f)})
            tenure_query = f"""
SELECT ?pos ?posLabel ?person ?personLabel ?start ?end ?replaces ?replacesLabel ?replacedBy ?replacedByLabel ?endCauseLabel WHERE {{
  VALUES ?pos {{ {' '.join('wd:' + i for i in ids)} }}
  ?person p:P39 ?st . ?st ps:P39 ?pos .
  OPTIONAL {{ ?st pq:P580 ?start }} OPTIONAL {{ ?st pq:P582 ?end }}
  OPTIONAL {{ ?st pq:P1365 ?replaces }} OPTIONAL {{ ?st pq:P1366 ?replacedBy }}
  OPTIONAL {{ ?st pq:P1534 ?endCause }}
  FILTER(!BOUND(?end) || ?end >= "1985-01-01"^^xsd:dateTime)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?posLabel ?start"""
            fx.download("D17", "Wikidata", WIKIDATA_SPARQL, out / "wikidata" / "governor_tenures.csv",
                        params={"query": tenure_query}, note="P39 tenures ending 1985 or later",
                        validate=looks_like_csv(100))
    finally:
        fx.session.headers.pop("Accept", None)


# --------------------------------------------------------------------------
# Templates (data/manual)
# --------------------------------------------------------------------------

def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    log(f"  wrote {rel(path)} ({len(rows)} rows)")


TAU_SENTENCE = re.compile(
    r"statewide per capita (?:impact )?indicator (?:will be (?:increased|decreased) to|"
    r"will remain at|was increased to|was decreased to|to) \$\s?(\d+\.\d{2}) for all disasters "
    r"(declared|with an incident start date) on or after (October \d{1,2}, (\d{4}))", re.I)


def tau_rows_from_fedreg() -> list[list]:
    """Statewide per capita indicator by fiscal year, from the FR notice text.

    A row is marked verified (amount_is_guess = 0, verified = 1) only when the
    notice states the amount and its effective date in one sentence of the
    form "... indicator will be increased to $X for all disasters declared on
    or after October 1, YYYY"; the fiscal year is then YYYY + 1. Anything else
    falls back to a looser match and stays flagged as a guess.
    """
    index = RAW_DIR / "fedreg" / "fedreg_notices.csv"
    if not index.exists():
        return []
    loose = re.compile(r"statewide per capita (?:impact )?indicator[^$]{0,300}?\$\s?([\d,]+\.\d{2})",
                       re.I | re.S)
    rows = {}
    with open(index, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if "per capita" not in r["title"].lower() and "grant amounts" not in r["title"].lower():
                continue
            paths = [RAW_DIR / "fedreg" / "text" / f"{r['document_number']}{ext}"
                     for ext in (".htm", ".txt")]
            txt_path = next((p for p in paths if p.exists()), None)
            if txt_path is None:
                continue
            text = re.sub(r"<[^>]+>", " ", txt_path.read_text(encoding="utf-8", errors="replace"))
            text = re.sub(r"\s+", " ", html.unescape(text))
            m = TAU_SENTENCE.search(text)
            if m:
                eff = datetime.strptime(m.group(3), "%B %d, %Y").date()
                basis = "declaration date" if m.group(2).lower() == "declared" else "incident start date"
                row = [eff.year + 1, m.group(1), r["document_number"], r["html_url"], 0, 1,
                       eff.isoformat(), basis, f"published {r['publication_date']}"]
            else:
                m = loose.search(text)
                if not m:
                    continue
                row = [int(r["publication_date"][:4]) + 1, m.group(1).replace(",", ""),
                       r["document_number"], r["html_url"], 1, 0, "", "",
                       f"published {r['publication_date']}; effective date not parsed"]
            if row[0] in rows:
                raise ValueError(f"two notices for FY{row[0]}: {rows[row[0]][2]} and {row[2]}")
            rows[row[0]] = row
    if rows:  # make gaps explicit rather than silent
        for fy in range(min(rows), max(rows) + 1):
            rows.setdefault(fy, [fy, "", "", "", "", 0, "", "", "no notice found"])
    return [rows[k] for k in sorted(rows)]


def step_templates(fx: Fetcher) -> None:
    log("Templates")
    MANUAL_DIR.mkdir(parents=True, exist_ok=True)

    # governor terms are compiled from the D16-D18 sources by build_governors.py
    try:
        import build_governors
        log(f"  governors: {build_governors.write_template()}")
    except Exception as e:  # noqa: BLE001
        log(f"  governors template not rebuilt: {type(e).__name__}: {e}")

    write_csv(MANUAL_DIR / "tau_series.csv",
              ["fiscal_year", "statewide_indicator_usd", "fr_document_number", "fr_url",
               "amount_is_guess", "verified", "effective_from", "applies_by", "notes"],
              tau_rows_from_fedreg())

    write_csv(MANUAL_DIR / "rainy_day_template.csv",
              ["state", "fiscal_year", "rainy_day_balance_usd_m",
               "general_fund_expenditure_usd_m", "source", "verified"],
              [[st, y, "", "", "", ""] for st in STATES for y in range(1992, 2027)])

    draft = RAW_DIR / "pda" / "pda_extracted_draft.csv"
    pdfs = sorted((RAW_DIR / "pda" / "pdfs").glob("*.pdf"))
    header = ["pdf_file", "state", "declaration_or_request_id", "decision",
              "pa_per_capita_draft", "ia_estimate_draft", "verified"]
    if draft.exists():
        import pandas as pd
        d = pd.read_csv(draft)
        log(f"  PDA draft columns: {list(d.columns)}")
        pick = lambda *names: next((d[n] for n in names if n in d.columns), [""] * len(d))
        rows = list(zip(pick("file_name", "pdf_file", "file"), pick("state", "state_name"),
                        pick("disaster_number", "declaration_number", "request_id"),
                        pick("event_outcome", "decision", "outcome"),
                        pick("pa_per_capita_impact", "pa_per_capita"),
                        pick("ia_total_cost", "ia_cost_estimate"), [0] * len(d)))
    else:
        rows = [[p.name, "", "", "", "", "", 0] for p in pdfs]
    write_csv(MANUAL_DIR / "pda_review_queue.csv", header, [list(r) for r in rows])

    for p in sorted(MANUAL_DIR.glob("*.csv")):  # templates, overrides and rule table
        fx.manifest.record(dataset_id="manual", source="template", url="",
                           local_path=rel(p), bytes=p.stat().st_size, sha256=sha256_of(p),
                           downloaded_at_utc=utc_now(), status="manual",
                           note="scaffold for hand coding; verified=0 throughout")


# --------------------------------------------------------------------------
# Acceptance checks and report
# --------------------------------------------------------------------------

def run_checks(manifest: Manifest) -> list[dict]:
    import pandas as pd

    res: list[dict] = []

    def add(check, expected, observed, passed):
        res.append({"check": check, "expected": expected, "observed": str(observed),
                    "result": "PASS" if passed else "FAIL"})

    def guard(name, expected, fn):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            add(name, expected, f"error: {type(e).__name__}: {e}", False)

    of = RAW_DIR / "openfema"

    def d1():
        df = pd.read_csv(of / "DeclarationDenials.csv", low_memory=False)
        add("D1 rows", ">= 1,300", f"{len(df):,}", len(df) >= 1300)
        n = (df["declarationRequestType"] == "Major Disaster").sum()
        add("D1 Major Disaster rows", ">= 881", f"{n:,}", n >= 881)
        d2cols = pd.read_csv(of / "DisasterDeclarationsSummaries.csv", nrows=0).columns
        both = "declarationRequestNumber" in df.columns and "declarationRequestNumber" in d2cols
        add("D1 and D2 contain declarationRequestNumber", "Yes", "Yes" if both else "No", both)
    guard("D1/D2", "files readable", d1)

    def d3():
        df = pd.read_csv(of / "FemaWebDisasterDeclarations.csv", low_memory=False)
        n = (df["declarationType"] == "Major Disaster").sum()
        add("D3 rows", ">= 5,270; >= 2,943 Major Disaster",
            f"{len(df):,}; {n:,} Major Disaster", len(df) >= 5270 and n >= 2943)
    guard("D3 rows", ">= 5,270", d3)

    def d4():
        df = pd.read_csv(of / "FemaWebDisasterSummaries.csv", low_memory=False)
        add("D4 rows", ">= 4,000", f"{len(df):,}", len(df) >= 4000)
    guard("D4 rows", ">= 4,000", d4)

    def d6():
        years = {int(m.group(1)) for p in (RAW_DIR / "storm_events").glob("*.csv.gz")
                 if (m := STORM_RE.match(p.name))}
        missing = [y for y in range(1988, 2026) if y not in years]
        add("D6 details file per year 1988-2025 (2026 if published)", "no gaps",
            f"{min(years)}-{max(years)}, {len(years)} years; missing {missing or 'none'}; "
            f"2026 {'present' if 2026 in years else 'absent'}", not missing)
    guard("D6", "one file per year", d6)

    def d9():
        names = ["SAINC", "SAGDP", "SAGDP_SIC"]
        obs, ok = [], True
        for n in names:
            p = RAW_DIR / "bea" / f"{n}.zip"
            with zipfile.ZipFile(p) as z:
                bad = z.testzip()
                obs.append(f"{n}: {len(z.namelist())} members{' BAD ' + bad if bad else ''}")
                ok = ok and bad is None
        add("D9 three zips open", "3 valid zips", "; ".join(obs), ok)
    guard("D9 three zips open", "3 valid zips", d9)

    def d10():
        df = pd.read_csv(RAW_DIR / "bls_laus" / "la.data.3.AllStatesS", sep="\t",
                         dtype=str, skipinitialspace=True)
        df.columns = [c.strip() for c in df.columns]
        last = df["year"].astype(int).max()
        last_period = df[df["year"].astype(int) == last]["period"].str.strip().max()
        add("D10 LAUS data through 2026", "max year 2026", f"{last} {last_period}", last >= 2026)
    guard("D10 LAUS data through 2026", "max year 2026", d10)

    def d12():
        df = pd.read_csv(RAW_DIR / "fred" / "CPIAUCSL.csv")
        dates = pd.to_datetime(df.iloc[:, 0])
        monthly = dates.diff().dropna().dt.days.between(28, 31).all()
        add("D12 monthly CPI-U ending 2026", "monthly, last obs 2026",
            f"{dates.min():%Y-%m} to {dates.max():%Y-%m}, monthly={bool(monthly)}",
            monthly and dates.max().year >= 2026)
    guard("D12", "monthly, ending 2026", d12)

    def d13():
        have = set()
        for p in (RAW_DIR / "treasury_ttr").glob("*.xls*"):
            if m := re.fullmatch(r"(\d{4})est\.xls", p.name):
                have.add(int(m.group(1)))
            elif m := re.fullmatch(r"(?:TTR-)?tables-(\d{4})\.xlsx?", p.name):
                have.add(int(m.group(1)))
        missing = [y for y in range(1999, 2026) if y not in have]
        add("D13 one file per year 1999-2025 (2004 may be missing)", "missing ⊆ {2004}",
            f"{len(have)} years; missing {missing or 'none'}", set(missing) <= {2004})
    guard("D13", "one file per year", d13)

    def d15():
        df = pd.read_csv(RAW_DIR / "dataverse" / "mit_president" / "1976-2024-president.csv")
        years = sorted(df["year"].unique())
        states = df["state_po"].nunique()
        expected_years = list(range(1976, 2025, 4))
        add("D15 years 1976-2024, 50 states + DC", "13 elections, 51 units",
            f"{years[0]}-{years[-1]} ({len(years)} elections), {states} state units",
            years == expected_years and states == 51)
    guard("D15", "1976-2024, 51 units", d15)

    def d21():
        cols = pd.read_csv(RAW_DIR / "voteview" / "HSall_parties.csv", nrows=0).columns
        add("D21 party mean column", "nominate_dim1_mean or equivalent",
            "present" if "nominate_dim1_mean" in cols else f"absent; columns {list(cols)}",
            "nominate_dim1_mean" in cols)
    guard("D21", "nominate_dim1_mean", d21)

    def d22():
        folder = RAW_DIR / "dataverse" / "shor_mccarty"
        f = next(p for p in folder.iterdir() if p.suffix in (".dta", ".tab", ".csv"))
        df = pd.read_stata(f) if f.suffix == ".dta" else pd.read_csv(f, sep=None, engine="python")
        ycol = next(c for c in df.columns if c.lower() == "year")
        add("D22 state-year coverage starts 1993", "min year 1993",
            f"{f.name}: {int(df[ycol].min())}-{int(df[ycol].max())}, {len(df):,} rows",
            int(df[ycol].min()) <= 1993)
    guard("D22", "min year 1993", d22)

    def man():
        on_disk = {rel(p) for p in DATA_DIR.rglob("*")
                   if p.is_file() and p != MANIFEST_PATH and p != REPORT_PATH and p != CHECKS_PATH
                   and not p.name.endswith(".part") and p.name != ".DS_Store"}
        rows = list(manifest.rows.values())
        with_sha = {r["local_path"] for r in rows if r["local_path"] and r["sha256"]}
        missing_rows = sorted(on_disk - with_sha)
        empty_status = [r for r in rows if not r["status"]]
        stale = sorted(r["local_path"] for r in rows if r["local_path"]
                       and not (PROJECT_DIR / r["local_path"]).exists())
        sha_bad = [r["local_path"] for r in rows if r["local_path"] and r["sha256"]
                   and (PROJECT_DIR / r["local_path"]).exists()
                   and r["dataset_id"] != "manual"
                   and sha256_of(PROJECT_DIR / r["local_path"]) != r["sha256"]]
        add("Manifest: every file has a row with sha256; no empty status",
            "0 unlisted, 0 empty, 0 stale, 0 hash mismatches",
            f"{len(on_disk)} files; unlisted {len(missing_rows)} {missing_rows[:5]}; "
            f"empty status {len(empty_status)}; stale {len(stale)}; "
            f"hash mismatch {len(sha_bad)} {sha_bad[:5]}",
            not missing_rows and not empty_status and not stale and not sha_bad)
    guard("Manifest", "consistent", man)
    return res


def count_rows(path: Path) -> str:
    try:
        if path.suffix == ".zip":
            with zipfile.ZipFile(path) as z:
                return f"{len(z.namelist())} files"
        if path.name.endswith(".csv.gz"):
            with gzip.open(path, "rb") as f:
                return f"{sum(1 for _ in f) - 1:,}"
        if path.suffix in (".csv", ".tab") or path.parent.name == "bls_laus":
            with open(path, "rb") as f:
                return f"{sum(1 for _ in f) - 1:,}"
    except Exception:  # noqa: BLE001
        return "?"
    return ""


def step_report(manifest: Manifest) -> None:
    log("Acceptance checks")
    checks = run_checks(manifest)
    for c in checks:
        log(f"  {c['result']}  {c['check']}: {c['observed']}")
    CHECKS_PATH.write_text(json.dumps(checks, indent=2), encoding="utf-8")

    rows = list(manifest.rows.values())
    times = sorted(r["downloaded_at_utc"] for r in rows
                   if r["downloaded_at_utc"] and r["status"] in ("ok", "skipped")
                   and r["dataset_id"] != "manual")
    by_ds: dict[str, list[dict]] = {}
    for r in rows:
        by_ds.setdefault(r["dataset_id"], []).append(r)

    def ds_key(k):
        return (0, int(k[1:])) if re.fullmatch(r"D\d+", k) else (1, k)

    lines = [
        "# ECON 438 Project 1: Fetch Report", "",
        f"*Generated by `code/fetch_data.py` at {utc_now()}.*", "",
        f"**Snapshot:** files downloaded between {times[0] if times else '?'} and "
        f"{times[-1] if times else '?'} (UTC). OpenFEMA updates daily; cite the "
        "`downloaded_at_utc` value in `manifest.csv` for each file.", "",
        "## Sources", "",
        "| ID | Source | Files ok | Other status | Rows / members | Bytes |",
        "|---|---|---|---|---|---|",
    ]
    for ds in sorted(by_ds, key=ds_key):
        rs = by_ds[ds]
        ok = [r for r in rs if r["status"] in ("ok", "skipped", "manual")]
        other = {}
        for r in rs:
            if r["status"] not in ("ok", "skipped", "manual"):
                other[r["status"]] = other.get(r["status"], 0) + 1
        counts = []
        for r in ok:
            p = PROJECT_DIR / r["local_path"]
            c = count_rows(p) if p.exists() else ""
            if c and len(ok) <= 4:
                counts.append(f"{p.name}: {c}")
        if len(ok) > 4:
            counts = [f"{len(ok)} files"]
        total_bytes = sum(int(r["bytes"] or 0) for r in ok)
        lines.append(f"| {ds} | {rs[0]['source']} | {len(ok)} | "
                     f"{', '.join(f'{v} {k}' for k, v in other.items()) or '-'} | "
                     f"{'<br>'.join(counts) or '-'} | {total_bytes:,} |")

    problems = [r for r in rows if r["status"] in ("failed", "blocked")]
    lines += ["", "## Failures and blocked hosts", ""]
    if problems:
        lines += [f"- **{r['dataset_id']}** `{r['status']}` {r['url']}: {r['note']}" for r in problems]
    else:
        lines.append("None.")

    lines += ["", "## Acceptance checks", "", "| Check | Expected | Observed | Result |",
              "|---|---|---|---|"]
    lines += [f"| {c['check']} | {c['expected']} | {c['observed']} | **{c['result']}** |"
              for c in checks]

    notes_path = CODE_DIR / "report_notes.md"
    if notes_path.exists():
        lines += ["", notes_path.read_text(encoding="utf-8").strip()]

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"  wrote {rel(REPORT_PATH)}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--email", required=True, help="contact email for the User-Agent header")
    ap.add_argument("--only", nargs="+", metavar="STEP",
                    help=f"steps or dataset IDs to run: {', '.join(STEPS)}, or D1..D22")
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = ap.parse_args()

    steps, only_ids = list(STEPS), None
    if args.only:
        wanted, only_ids = set(), set()
        for item in args.only:
            if item in STEPS:
                wanted.add(item)
            elif item.upper() in ID_TO_STEP:
                wanted.add(ID_TO_STEP[item.upper()])
                only_ids.add(item.upper())
            else:
                ap.error(f"unknown step or dataset ID: {item}")
        steps = [s for s in STEPS if s in wanted]
        # an ID filter applies only within steps that were selected by ID
        if not only_ids or any(s in args.only for s in ("openfema", "dataverse")):
            only_ids = None

    manifest = Manifest(MANIFEST_PATH)
    fx = Fetcher(args.email, manifest, args.force)
    runners = {
        "openfema": lambda: step_openfema(fx, only_ids),
        "storm": lambda: step_storm(fx),
        "pda": lambda: step_pda(fx),
        "fedreg": lambda: step_fedreg(fx),
        "bea": lambda: step_bea(fx),
        "bls": lambda: step_bls(fx),
        "fred": lambda: step_fred(fx),
        "ttr": lambda: step_ttr(fx),
        "dataverse": lambda: step_dataverse(fx, only_ids),
        "census": lambda: step_census(fx),
        "voteview": lambda: step_voteview(fx),
        "governors": lambda: step_governors(fx),
        "templates": lambda: step_templates(fx),
        "report": lambda: step_report(manifest),
    }
    for step in steps:
        try:
            runners[step]()
        except Exception as e:  # noqa: BLE001 - keep going with other sources
            log(f"!! step {step} crashed: {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
