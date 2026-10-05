# ECON 438 Project 1: Data Fetch Brief (for a coding agent)

**Task in one line:** write and run a Python script that downloads every free raw dataset listed below, records what it got in a manifest, prepares templates for the hand-coded items, and uploads the result to a Google Drive folder.

**Project context (for orientation only):** a study of US presidential disaster declarations, 1989 to 2026. The unit is a governor's request for a major disaster declaration, approved or denied. The data feed probit, decomposition and sample selection models. You do not need to build any of that. This brief covers acquisition only.

---

## 1. Before you start: ask the user these three things, once

1. **Drive destination.** Which upload method applies (see section 6) and the target folder. Default folder name: `ECON438_Project1_Data`.
2. **Contact email** for the HTTP `User-Agent` header. BLS and some federal sites reject requests without one.
3. **Is R available?** Needed only for the PDA step (D7). If not, download the PDFs and skip extraction.

Then proceed without further questions. If something is ambiguous, pick the conservative option and note it in `FETCH_REPORT.md`.

## 2. Scope

**In scope**
- Download raw files for the sources in section 4.
- Write `manifest.csv` and `FETCH_REPORT.md`.
- Create the manual-work templates in section 5.
- Upload everything to Google Drive.

**Out of scope. Do not do these.**
- SHELDUS (paid licence, handled separately).
- Any cleaning, merging, reshaping or variable construction beyond the templates in section 5.
- Any modelling or analysis.
- Editing raw files after download.

## 3. Engineering rules

- **Starter script.** If the user supplies `fetch_data.py`, extend it. It already covers D1, D2, D6, D8, D9, D10, D12, D15, D16 (Klarner), D21 and D22. Otherwise write it from this brief.
- **One entry point:** `python fetch_data.py --email <contact> [--only <step> ...] [--force]`.
- **Raw is immutable.** Save to `data/raw/<source>/` exactly as served. Never rewrite a raw file.
- **Idempotent.** Skip files that already exist unless `--force`. Download to `*.part`, then rename.
- **Resilient.** Three attempts with backoff per file. One failed source must not stop the others.
- **Polite.** Timeout 120 s, at most 2 requests per second per host, descriptive `User-Agent` with the contact email.
- **Prefer bulk files** over paginated APIs. OpenFEMA serves the full dataset at `<endpoint>.csv`; the JSON API caps each page.
- **Blocked hosts.** If the environment cannot reach a host, record `blocked` in the manifest and move on. Do not use mirrors, caches or proxies.
- **No secrets in code.** No tokens, passwords or OAuth files in the script, the repo or the Drive folder.
- **Dependencies:** `requests` only for fetching, plus `pandas` and `openpyxl` for the templates. Pin them in `requirements.txt`.
- **Snapshot date.** OpenFEMA updates daily. Record the UTC download time of every file; the paper will cite it.

## 4. Sources to fetch

Status key: **verified** = URL or identifier confirmed working; **confirm** = follows a known pattern, check it and fall back as noted.

### A. FEMA request and declaration records

| ID | Dataset | URL | Status | Save to |
|---|---|---|---|---|
| D1 | Declaration Denials v1 | `https://www.fema.gov/api/open/v1/DeclarationDenials.csv` | verified | `raw/openfema/` |
| D2 | Disaster Declarations Summaries v2 | `https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries.csv` | verified | `raw/openfema/` |
| D3 | FEMA Web Disaster Declarations v1 | `https://www.fema.gov/api/open/v1/FemaWebDisasterDeclarations.csv` | confirm (JSON endpoint verified) | `raw/openfema/` |
| D4 | FEMA Web Disaster Summaries v1 | `https://www.fema.gov/api/open/v1/FemaWebDisasterSummaries.csv` | confirm (JSON endpoint verified) | `raw/openfema/` |

Fallback for D3 and D4: page the JSON endpoint with `$top=1000&$skip=N` until the row count equals `metadata.count` (request it with `$inlinecount=allpages`).

### B. Need and damage

| ID | Dataset | URL | Status | Save to |
|---|---|---|---|---|
| D6 | NOAA Storm Events, details files, 1988 to 2026 | Directory listing at `https://www.ncei.noaa.gov/pub/data/swdi/stormevents/csvfiles/`. Files match `StormEvents_details-ftp_v1.0_dYYYY_cYYYYMMDD.csv.gz`. Take the latest `c` date per year. | verified | `raw/storm_events/` |
| D7 | FEMA Preliminary Damage Assessment reports (PDFs) | Listing: `https://www.fema.gov/disaster/how-declared/preliminary-damage-assessments/reports` (paginated, fiscal year 2008 onward). Tool: R package `UrbanInstitute/preliminary-damage-assessments`, functions `scrape_pda_pdfs()` and `get_preliminary_damage_assessments()`. | verified | `raw/pda/pdfs/`, `raw/pda/pda_extracted_draft.csv` |
| D8 | Per-capita impact indicator notices | Federal Register API: `https://www.federalregister.gov/api/v1/documents.json` with `conditions[term]="statewide per capita impact indicator"`, `per_page=100`, `order=oldest`. Save title, publication date, document number, URL and raw text URL. | verified | `raw/fedreg/` |

D7 detail: with R, install via `remotes::install_github("UrbanInstitute/preliminary-damage-assessments")`, run the two functions and save the output as a draft. Without R, scrape the listing pages for PDF links and download the PDFs only. Either way the extracted numbers are a draft for human checking, not final data.

### C. Economic conditions and fiscal capacity

| ID | Dataset | URL | Status | Save to |
|---|---|---|---|---|
| D9 | BEA regional zips: state income, GDP, population | `https://apps.bea.gov/regional/zip/SAINC.zip`, `SAGDP.zip`, `SAGDP_SIC.zip` | verified | `raw/bea/` |
| D11 | County population, 1969 onward | `https://apps.bea.gov/regional/zip/CAINC1.zip` | confirm | `raw/bea/` |
| D10 | BLS state unemployment (LAUS) | `https://download.bls.gov/pub/time.series/la/` files `la.data.3.AllStatesS`, `la.series`, `la.area`, `la.measure` | verified | `raw/bls_laus/` |
| D12 | CPI-U | `https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL` | verified | `raw/fred/` |
| D13 | Treasury Total Taxable Resources | Scrape Excel links from `https://home.treasury.gov/policy-issues/economic-policy/total-taxable-resources`. Files sit under `https://home.treasury.gov/system/files/226/`: `TTR-tables-YYYY.xlsx` (2012 to 2025), `tables-2011.xls`, `YYYYest.xls` (1999 to 2010). | verified | `raw/treasury_ttr/` |

D13 note: the page lists no file for 2004. If it is absent, record it as missing; do not guess a URL. Fallback for D11: Census county population estimate files at `www2.census.gov/programs-surveys/popest/datasets/`.

### D. Political variables and polarization

| ID | Dataset | Identifier | Status | Save to |
|---|---|---|---|---|
| D15 | MIT Election Lab, US President 1976 to 2024 | Harvard Dataverse `doi:10.7910/DVN/42MVDX` | verified | `raw/dataverse/mit_president/` |
| D16 | Klarner state partisan balance; Klarner governors | Harvard Dataverse `hdl:1902.1/20403` and `hdl:1902.1/20408` | verified | `raw/dataverse/klarner_*/` |
| D19 | House apportionment by state, 1990 to 2020 censuses | Census Table C1: `https://www2.census.gov/programs-surveys/decennial/2020/data/apportionment/apportionment-2020-tableC1.xlsx` (PDF version at the same path) | confirm | `raw/census_apportionment/` |
| D20 | Voteview member file (optional) | `https://voteview.com/static/data/out/members/HSall_members.csv` | confirm | `raw/voteview/` |
| D21 | Voteview party means | `https://voteview.com/static/data/out/parties/HSall_parties.csv` | verified | `raw/voteview/` |
| D22 | Shor-McCarty state legislative ideology | Harvard Dataverse `doi:10.7910/DVN/WI8ERB` (check the Shor dataverse for a newer version first) | verified | `raw/dataverse/shor_mccarty/` |

Dataverse method: list files with `GET https://dataverse.harvard.edu/api/datasets/:persistentId/versions/:latest/files?persistentId=<id>`, then download each from `/api/access/datafile/<file id>`. Add `?format=original` when the file has an `originalFileName`, so tabular files arrive in their uploaded format.

Fallback for D19: the National Archives allocation table at `https://www.archives.gov/electoral-college/allocation`.

### E. Not fetchable by script (do not attempt)

| ID | Item | Why | What you do instead |
|---|---|---|---|
| D5 | SHELDUS | Paid licence | Nothing. Out of scope. |
| D14 | NASBO rainy-day fund balances | Historical dataset needs a registered NASBO account | Create the template in section 5 |
| D16 (part) | Governors after Klarner's coverage ends | openICPSR project 102000 ("United States Governors 1775-2020") needs a login; 2021 to 2026 has no bulk source | Create the template in section 5 |
| D17, D18 | Governor term limits and election calendar | Hand-coded from the Book of the States and NGA rosters | Create the template in section 5 |

## 5. Templates for manual work

Write these to `data/manual/`. They are scaffolds for humans to complete. Leave unknown cells empty. Never invent values.

1. **`governors_template.csv`**, one row per governor spell, 1989 to 2026. Columns: `state`, `governor`, `party`, `term_start`, `term_end`, `term_limited` (0/1), `eligible_next_election` (0/1), `next_election_date`, `source`, `verified` (0/1), `notes`. Pre-fill `state`, `governor`, `party` and dates from the Klarner governors file where it has them, with `source = klarner` and `verified = 0`. Leave the term-limit and election columns empty.
2. **`tau_series.csv`**, one row per fiscal year. Columns: `fiscal_year`, `statewide_indicator_usd`, `fr_document_number`, `fr_url`, `amount_is_guess` (0/1), `verified` (0/1). Pre-fill from D8 by regex on the notice text, flag every amount as a guess, set `verified = 0`.
3. **`rainy_day_template.csv`**. Columns: `state`, `fiscal_year`, `rainy_day_balance_usd_m`, `general_fund_expenditure_usd_m`, `source`, `verified`. One empty row per state and fiscal year, 1992 to 2026.
4. **`pda_review_queue.csv`**. Columns: `pdf_file`, `state`, `declaration_or_request_id`, `decision`, `pa_per_capita_draft`, `ia_estimate_draft`, `verified`. Pre-fill from the D7 draft extraction if it ran; otherwise list the PDF file names only.

## 6. Upload to Google Drive

Use the first method that applies. State in the report which one you used.

1. **Drive connector or tool** already available to you: use it.
2. **Google Colab:** `drive.mount('/content/drive')`, then write to `/content/drive/MyDrive/<folder>`.
3. **Google Drive for desktop** on the user's machine: copy into the synced folder path the user gave.
4. **rclone** with a remote the user has already configured: `rclone copy data <remote>:<folder> --progress`.
5. **None of these:** build `ECON438_Project1_Data.zip`, stop, and tell the user. Do not ask for a password and do not start an OAuth flow that stores a token in the project.

Upload notes:
- Expect roughly 2 to 3 GB in total. Storm Events and the PDA PDFs are most of it.
- Upload `raw/pda/pdfs/` and `raw/storm_events/` as one zip each. Thousands of small files are slow on Drive.
- Do not overwrite an existing Drive folder silently. If it exists, upload into a dated subfolder `snapshot_YYYY-MM-DD/`.

Target layout:

```
ECON438_Project1_Data/
  code/fetch_data.py
  code/requirements.txt
  raw/<source>/...
  manual/*.csv
  manifest.csv
  FETCH_REPORT.md
```

## 7. Manifest and report

**`manifest.csv`**, one row per file attempted: `dataset_id`, `source`, `url`, `local_path`, `bytes`, `sha256`, `http_status`, `downloaded_at_utc`, `status` (`ok`, `skipped`, `failed`, `blocked`, `manual`), `note`.

**`FETCH_REPORT.md`**, one page: snapshot date, table of sources with status and row counts, every failure with its error, every `confirm` URL and whether it worked or which fallback was used, the Drive method and folder link, and the list of manual items still open.

## 8. Acceptance checks

Run these after downloading and put the results in the report. A failed check is a finding to report, not something to patch around.

| Check | Expected |
|---|---|
| D1 rows | At least 1,300 (1,303 on 4 Oct 2026) |
| D1 rows with `declarationRequestType == "Major Disaster"` | At least 881 |
| D1 and D2 both contain `declarationRequestNumber` | Yes |
| D3 rows | At least 5,270; at least 2,943 with `declarationType == "Major Disaster"` |
| D4 rows | At least 4,000 |
| D6 | One details file for every year 1988 to 2025; 2026 if published |
| D9 | Three zips, each opens without error |
| D10 | `la.data.3.AllStatesS` has data through 2026 |
| D12 | Monthly series ending in 2026 |
| D13 | One file per year 1999 to 2025, with 2004 allowed to be missing |
| D15 | Years 1976 to 2024 present, 50 states plus DC |
| D21 | File contains a `nominate_dim1_mean` column or equivalent party mean |
| D22 | State-year coverage starting 1993 |
| Manifest | Every file on disk has a row with a sha256; no row has an empty `status` |

## 9. Definition of done

- [ ] Script runs end to end from a clean folder with one command.
- [ ] A second run downloads nothing new.
- [ ] `manifest.csv` and `FETCH_REPORT.md` exist and agree with what is on disk.
- [ ] All four templates exist in `data/manual/`.
- [ ] Everything is in the Drive folder, and the report gives the folder link.
- [ ] Final message to the user lists what failed, what was blocked and which manual items remain.
