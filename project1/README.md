# Project 1 data: US presidential disaster declarations, 1989-2026

This folder holds every input dataset for Project 1. Each one was downloaded from its original source by one script, is recorded with a checksum in a manifest, and was checked against the acceptance tests in the brief. The unit of analysis is a governor's request for a major disaster declaration, approved or denied. This folder covers **data acquisition only**. Nothing here is cleaned, merged or modelled yet.

**Snapshot:** 4-5 October 2026 (UTC). The download time of every file is in `data/manifest.csv`.

---

## 1. Getting started (5 minutes)

```bash
# 1. Clone the repo
git clone https://github.com/hussey17/Johnny_Football.git
cd Johnny_Football

# 2. Restore Storm Events (too large for git; stored as a release asset)
gh release download project1-data-2026-10-05 -R hussey17/Johnny_Football -p storm_events.zip -D project1/data/raw
unzip project1/data/raw/storm_events.zip -d project1/data/raw && rm project1/data/raw/storm_events.zip
```

Without the GitHub CLI (`gh`), download `storm_events.zip` from the [release page](https://github.com/hussey17/Johnny_Football/releases/tag/project1-data-2026-10-05) and unzip it into `project1/data/raw/`.

Nothing else needs downloading. You only need Python if you want to re-run or extend the fetch:

```bash
python3 -m venv .venv
.venv/bin/pip install -r project1/code/requirements.txt
```

**What to open first:**
- [`data/FETCH_REPORT.md`](data/FETCH_REPORT.md): what was fetched, the acceptance checks, known problems and open items.
- [`data/manual/`](data/manual/): the four hand-coding tables, which are ready to merge.
- [`docs/DATA_FETCH_BRIEF.md`](docs/DATA_FETCH_BRIEF.md): the specification this data was built against.

---

## 2. Folder map

```
project1/
├── README.md                  ← this file
├── docs/
│   └── DATA_FETCH_BRIEF.md    the data specification (dataset IDs D1-D22 come from here)
├── code/
│   ├── fetch_data.py          downloads every source, builds the manual tables, runs the checks, writes the report
│   ├── build_governors.py     compiles data/manual/governors_template.csv (called by fetch_data.py)
│   ├── report_notes.md        hand-written notes appended to FETCH_REPORT.md
│   └── requirements.txt       pinned Python packages
└── data/
    ├── manifest.csv           one row per file: source URL, local path, bytes, sha256, UTC download time, status
    ├── FETCH_REPORT.md        source table, failures, acceptance checks, decisions, open items
    ├── acceptance_checks.json the same checks, machine-readable
    ├── raw/                   source files exactly as served; never edit these
    └── manual/                hand-coding tables built from the raw files (see section 4)
```

---

## 3. Raw data (`data/raw/`)

The files are exactly as the source served them. If you need a cleaned version, write it somewhere else (for example `data/clean/`) and never overwrite a raw file. The ID column refers to the brief.

| Folder | ID | What it is | Key files | Use in the project |
|---|---|---|---|---|
| `openfema/` | D1 | FEMA declaration **denials**, 1,303 requests | `DeclarationDenials.csv` | Denied requests: half of the dependent variable |
| | D2 | FEMA disaster declaration summaries, one row per declared county | `DisasterDeclarationsSummaries.csv` | Approved declarations; join to D1 on `declarationRequestNumber` |
| | D3 | FEMA web declarations, one row per disaster | `FemaWebDisasterDeclarations.csv` | Declaration dates, incident types, programmes declared |
| | D4 | FEMA web disaster summaries | `FemaWebDisasterSummaries.csv` | Obligated amounts per disaster |
| `storm_events/` | D6 | NOAA Storm Events details, one file per year 1988-2026 (latest revision) | `StormEvents_details-ftp_v1.0_dYYYY_c*.csv.gz` | Need and damage measures (deaths, injuries, property and crop damage). **From the release zip.** |
| `fedreg/` | D8 | Federal Register notices setting FEMA's per capita impact indicator | `fedreg_notices.csv` (index), `text/*.htm` (notice text), `search_*.json` (API responses) | Source of `manual/tau_series.csv` |
| `bea/` | D9 | BEA state personal income (`SAINC`), GDP (`SAGDP`, `SAGDP_SIC` for pre-1997) | `*.zip` | State income, GDP and population controls |
| | D11 | BEA county income and population (`CAINC1`) | `CAINC1.zip` | County population, for per capita damage |
| `bls_laus/` | D10 | BLS Local Area Unemployment Statistics, states | `la.data.3.AllStatesS` + lookup files `la.series`, `la.area`, `la.measure` | State unemployment rate (tab-separated; join through `series_id`) |
| `fred/` | D12 | CPI-U, monthly: `CPIAUCSL` (seasonally adjusted), `CPIAUCNS` (not adjusted) | `*.csv` | Deflating dollar values. `CPIAUCNS` is the index FEMA uses. |
| `treasury_ttr/` | D13 | Treasury Total Taxable Resources by state, 1999-2025 (2004 never published) | `YYYYest.xls`, `tables-2011.xls`, `TTR-tables-YYYY.xlsx` | State fiscal capacity |
| `dataverse/mit_president/` | D15 | MIT Election Lab presidential returns by state, 1976-2024 | `1976-2024-president.csv` | Swing-state and electoral-competitiveness measures |
| `dataverse/klarner_partisan_balance/` | D16 | Klarner state partisan balance, to 2011 | `Partisan_Balance_For_Use2011_06_09b.xlsx` + codebook | Legislative and governor partisanship |
| `dataverse/klarner_governors/` | D16 | Klarner gubernatorial elections panel, to 2011 | `StateElections_Gub_..._Public_Version.xlsx` + codebook | Cross-check for the governors table |
| `dataverse/shor_mccarty/` | D22 | Shor-McCarty state legislature ideology, 1993-2022 (Jan 2025 release) | `... state aggregate data January 2025 release.dta` + codebook | Legislative polarisation |
| `census_apportionment/` | D19 | House seats by state, 1990-2020 censuses (Census Table C1) | `apportionment-2020-tableC1.xlsx` / `.pdf` | Electoral votes (seats + 2) |
| `voteview/` | D20, D21 | Voteview members and party DW-NOMINATE means | `HSall_members.csv`, `HSall_parties.csv` | Congressional polarisation |
| `governors/` | D17, D18 | Wikipedia gubernatorial election pages, 1976-2028 (parse-API JSON) and Wikidata governor tenures | `wikipedia/*.json`, `wikidata/governor_tenures.csv` | Source of `manual/governors_template.csv` |
| `nasbo/` | D14 | NASBO Rainy Day Fund Balances and State Expenditure Report historical datasets (downloaded by hand; NASBO account) | `nasbo_rainy_day.xlsx`, `nasbo_state_expenditure.xlsm` | Source of `manual/rainy_day_template.csv` |

Each `dataverse/*/` folder also holds `_dataverse_files.json`, the file listing from the Dataverse API, which records the exact dataset version.

---

## 4. Hand-coding tables (`data/manual/`)

These are ready to merge. Every row says where it came from in `source` and whether it is corroborated in `verified`, and has caveats in `notes`.

### `governors_template.csv`: one row per governor per term, 1989-2026 (581 rows)

| Column | Meaning |
|---|---|
| `state`, `governor`, `party` | Full state name; governor; D, R, I or the state party label (for example DFL) |
| `term_start`, `term_end` | Dates of this term in office (`term_end` is blank for current governors). A re-elected governor starts a new row on the new term's inauguration day. |
| `term_limited` | 1 if the governor could **not** run at `next_election_date` |
| `eligible_next_election` | 1 if they could run (the complement of `term_limited`) |
| `next_election_date` | The election that decides the end of this term |
| `source`, `verified`, `notes` | `verified = 1` (523 rows) means two independent sources agree; it does not mean a person checked the row |

**How to use it:** for a request made on date *t* in state *s*, take the row where `term_start ≤ t < term_end`. Lame-duck status is `term_limited`, and time to the next election is `next_election_date − t`.

**Caveats:**
- Acting governors who served for days have blank term-limit fields, because the fields do not apply to them.
- Some `term_start` dates are inferred inauguration days; `notes` says which.
- Corrections to the source data are in `governors_overrides.csv`, with citations.
- Each state's term-limit rules over time are in `term_limit_rules.csv`.

### `tau_series.csv`: FEMA statewide per capita impact indicator (τ), FY1989-FY2026

| Column | Meaning |
|---|---|
| `fiscal_year`, `statewide_indicator_usd` | Federal fiscal year (1 Oct to 30 Sep) and τ in dollars per resident |
| `effective_from`, `applies_by` | Start date, and whether τ applies by **declaration date** (to FY2023) or **incident start date** (FY2024 on) |
| `amount_is_guess`, `verified` | 0/1 and 1/0 for values taken from a notice; 1/0 and 0/1 for imputed values |

- **FY2001-FY2026** come from the Federal Register notices, and each was checked against the notice text.
- **FY1989-FY2000 are imputed** by running FEMA's CPI rule backwards from FY2001. They are not FEMA figures, so say so wherever they are used.

### `rainy_day_template.csv`: state fiscal reserves, 50 states × FY1992-2026 (1,750 rows)

| Column | Meaning |
|---|---|
| `state`, `fiscal_year` | Postal code; state fiscal year |
| `rainy_day_balance_usd_m` | Rainy day fund balance, $ millions (NASBO Fiscal Survey; negative balances are reported as 0) |
| `rdf_pct_gf_spending` | Balance as a share of general fund spending (NASBO) |
| `general_fund_expenditure_usd_m` | Fiscal Survey general fund spending (balance ÷ share). Blank when the balance is 0. |
| `ser_gf_spending_usd_m` | General fund spending from NASBO's State Expenditure Report. A **different survey**, available 1991-2025. Do not mix it with the column above. |
| `notes` | Survey edition; FY2026 values are estimates |

### `pda_review_queue.csv`

This file is empty because D7 (FEMA Preliminary Damage Assessments) is blocked. See section 6.

---

## 5. Re-running or extending the fetch

```bash
.venv/bin/python project1/code/fetch_data.py --email you@example.com              # everything; existing files are skipped
.venv/bin/python project1/code/fetch_data.py --email you@example.com --only bls D3 # selected steps or dataset IDs
.venv/bin/python project1/code/fetch_data.py --email you@example.com --only templates report  # rebuild tables, checks, report
```

- The email goes in the HTTP User-Agent header, which BLS and other federal sites require.
- Files already on disk are never downloaded again unless you pass `--force`.
- A failed source is recorded and the run continues.
- On a Mac, put `caffeinate -i` before the command for long runs. If the machine sleeps, downloads stall.
- The NASBO files (D14) cannot be fetched by script. To update them, save new downloads from NASBO's store as `data/raw/nasbo/nasbo_rainy_day.xlsx` and `data/raw/nasbo/nasbo_state_expenditure.xlsm`, then rerun `--only templates report`.

After any change, commit the updated `manifest.csv`, `FETCH_REPORT.md` and `manual/*.csv` together, so the manifest always matches the files.

---

## 6. Still missing

| Item | Status | What to do |
|---|---|---|
| **D7: FEMA Preliminary Damage Assessment reports** | Blocked: `www.fema.gov` web pages refuse the network these data were fetched from (the OpenFEMA API is unaffected) | From a network where fema.gov pages load (VPN, campus), run `fetch_data.py --only pda`. It downloads the PDFs and, if R is installed, extracts draft figures into `pda_review_queue.csv` for checking. |
| **D5: SHELDUS** | Out of scope: paid licence | Handled separately |
