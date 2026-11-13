#!/usr/bin/env python3
"""ECON 438 Project 2: raw data acquisition.

Downloads every raw source used in Project 2 into data/raw/ and records each
file (URL, bytes, sha256, UTC time) in data/manifest.csv.

Usage:
    python project2/code/fetch_data.py [--force]

Raw files are never rewritten unless --force is given.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

CODE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = CODE_DIR.parent
RAW_DIR = PROJECT_DIR / "data" / "raw"
MANIFEST_PATH = PROJECT_DIR / "data" / "manifest.csv"

HEADERS = {"User-Agent": "Mozilla/5.0 (academic research; ECON 438 data fetch)"}
TIMEOUT = (20, 120)
ATTEMPTS = 3

UCSB = "https://www.presidency.ucsb.edu/statistics/data"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"

# (dataset_id, source, url, local path relative to data/raw, note)
SOURCES: list[tuple[str, str, str, str, str]] = []

# P2-A: Gallup approval, one page per president (Ford to Trump 2nd term; Ford covers the 1977 lead-in)
PRESIDENT_PAGES = [
    "gerald-r-ford", "jimmy-carter", "ronald-reagan", "george-bush", "william-j-clinton",
    "george-w-bush", "barack-obama", "donald-j-trump", "joseph-r-biden",
    "donald-j-trump-2nd-term",
]
for slug in PRESIDENT_PAGES:
    SOURCES.append((
        "P2-A", "American Presidency Project (UCSB)",
        f"{UCSB}/{slug}-public-approval",
        f"ucsb_approval/{slug}.html",
        "Gallup job approval with partisan breakdown, HTML table",
    ))
SOURCES.append((
    "P2-A", "American Presidency Project (UCSB)",
    f"{UCSB}/presidential-job-approval-all-data",
    "ucsb_approval/index.html",
    "index page; documents that all rows to Jan 2026 are Gallup",
))

# P2-B: FRED economic series
FRED_SERIES = {
    "UMCSENT": "University of Michigan consumer sentiment (monthly from 1978)",
    "CPIAUCSL": "CPI-U all items, seasonally adjusted",
    "UNRATE": "Civilian unemployment rate, seasonally adjusted",
    "AHETPI": "Avg hourly earnings, production and nonsupervisory, SA",
    "USREC": "NBER recession indicator",
}
for sid, note in FRED_SERIES.items():
    SOURCES.append(("P2-B", "FRED", FRED.format(sid), f"fred/{sid}.csv", note))

# P2-C: Voteview party means
SOURCES.append((
    "P2-C", "Voteview",
    "https://voteview.com/static/data/out/parties/HSall_parties.csv",
    "voteview/HSall_parties.csv",
    "DW-NOMINATE party means by Congress and chamber",
))

FIELDS = ["dataset_id", "source", "url", "local_path", "bytes", "sha256",
          "http_status", "downloaded_at_utc", "status", "note"]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest() -> dict[str, dict]:
    if not MANIFEST_PATH.exists():
        return {}
    with open(MANIFEST_PATH, newline="") as f:
        return {r["local_path"]: r for r in csv.DictReader(f)}


def save_manifest(rows: dict[str, dict]) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_PATH, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])


def fetch(url: str) -> requests.Response:
    last = None
    for attempt in range(1, ATTEMPTS + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200 and r.content:
                return r
            last = RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException as e:  # network hiccup: retry
            last = e
        time.sleep(2 * attempt)
    raise RuntimeError(f"{url}: {last}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="re-download existing files")
    args = ap.parse_args()

    manifest = load_manifest()
    for did, source, url, local, note in SOURCES:
        path = RAW_DIR / local
        key = f"data/raw/{local}"
        if path.exists() and not args.force and key in manifest:
            print(f"skip  {key}")
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        r = fetch(url)
        path.write_bytes(r.content)
        manifest[key] = {
            "dataset_id": did, "source": source, "url": url, "local_path": key,
            "bytes": path.stat().st_size, "sha256": sha256_of(path),
            "http_status": r.status_code, "downloaded_at_utc": utc_now(),
            "status": "ok", "note": note,
        }
        print(f"ok    {key}  ({path.stat().st_size:,} bytes)")
        time.sleep(0.5)
    save_manifest(manifest)
    print(f"manifest: {MANIFEST_PATH.relative_to(PROJECT_DIR)} ({len(manifest)} files)")


if __name__ == "__main__":
    main()
