# Project 2 data: presidential approval, the economy and polarisation, 1978-2025

This folder holds everything needed to estimate the Project 2 models: the raw downloads, the two scripts that fetch and clean them, and a **model-ready monthly file**. Every variable in the proposal (`Project2_Proposal.tex`) is already built, so you can load one file and start estimating.

**Snapshot:** 13 November 2026 (UTC). The exact download time of every file is in `data/manifest.csv`.
**Quality checks:** 28 of 28 pass. See [`data/QC_REPORT.md`](data/QC_REPORT.md).

---

## 1. Getting started

**Just want the data?** Open [`data/clean/analysis_monthly.csv`](data/clean/analysis_monthly.csv) (or `.dta` for Stata). One row per month, 1977m1-2025m12. Keep the 1977 rows until you have built your lags, then restrict to `in_sample == 1`.

```stata
use "project2/data/clean/analysis_monthly.dta", clear
tsset tm, monthly
gen d_a = D.a                  // build lags and differences first...
keep if in_sample == 1         // ...then keep 1978m1-2025m12 (T = 576)
```

```r
d <- read.csv("project2/data/clean/analysis_monthly.csv")
d$d_a <- c(NA, diff(d$a))      # lags first, then subset(d, in_sample == 1)
```

**Want to rebuild it from scratch?** (about 1 minute)

```bash
python3 -m venv .venv
.venv/bin/pip install -r project2/code/requirements.txt
.venv/bin/python project2/code/fetch_data.py      # downloads raw files (skips ones already present)
.venv/bin/python project2/code/build_dataset.py   # cleans, merges, checks, writes data/clean/
```

`fetch_data.py --force` downloads fresh copies. FRED and Voteview revise their data over time, so a fresh download can change values slightly. If you do, commit the new manifest with the new outputs.

---

## 2. Folder map

```
project2/
├── README.md                     ← this file: sources and the step-by-step procedure
├── code/
│   ├── fetch_data.py             step 1: downloads every raw file, writes data/manifest.csv
│   ├── build_dataset.py          steps 2-9: cleaning, merging, variable construction, checks
│   └── requirements.txt          pinned Python packages
└── data/
    ├── manifest.csv              one row per raw file: URL, bytes, sha256, UTC download time
    ├── QC_REPORT.md              every quality check and every change made to a source value
    ├── qc_checks.json            the same, machine-readable
    ├── raw/                      files exactly as the source served them; never edit
    │   ├── ucsb_approval/        10 presidents' Gallup approval pages (HTML) + index page
    │   ├── fred/                 UMCSENT, CPIAUCSL, UNRATE, AHETPI, USREC (CSV)
    │   └── voteview/             HSall_parties.csv
    └── clean/
        ├── analysis_monthly.csv  ★ THE MODEL FILE: one row per month, 51 columns
        ├── analysis_monthly.dta  the same for Stata (monthly date variable `tm`)
        ├── approval_polls.csv    poll-level Gallup data after cleaning (1,530 rows)
        ├── data_dictionary.csv   every column: description, unit, source
        └── figures/overview.png  all main series on one page
```

---

## 3. Sources

All sources are free and need no registration.

| ID | Source | Series | Use in the model |
|---|---|---|---|
| P2-A | [American Presidency Project, UCSB](https://www.presidency.ucsb.edu/statistics/data/presidential-job-approval-all-data) | Gallup job approval, overall and by party ID, one page per president (Ford to Trump 2nd term) | $A_t$, $a_t$, $G_t$ |
| P2-B | [FRED](https://fred.stlouisfed.org) | `UMCSENT` consumer sentiment | $S_t$ |
| | | `CPIAUCSL` CPI-U, SA | $\pi_t$, deflator for $W_t$ |
| | | `UNRATE` unemployment rate, SA | $U_t$ |
| | | `AHETPI` average hourly earnings, production and nonsupervisory, SA | $W_t$ |
| | | `USREC` NBER recession indicator | control in $\mathbf{D}_t$ |
| P2-C | [Voteview](https://voteview.com/data) | `HSall_parties.csv`, DW-NOMINATE party means by Congress and chamber | $P_t$, eras |

---

## 4. Step-by-step procedure

Each step below is a function in `code/build_dataset.py`, so you can check any decision against the code.

### Step 1. Download the raw data (`fetch_data.py`)

1. Download each president's UCSB approval page (Ford to Trump 2nd term) and the index page. Ford's page covers the 1977 lead-in year.
2. Download the five FRED series as CSV from `fredgraph.csv?id=<series>`.
3. Download `HSall_parties.csv` from Voteview.
4. Record the URL, size, sha256 and UTC time of each file in `data/manifest.csv`. Raw files are never edited after download.

### Step 2. Parse and clean the Gallup polls (`parse_page`, `build_polls`)

Each UCSB page is an HTML table with one row per Gallup poll: start date, end date, % approve, % disapprove, % unsure, and % approving among Democrats, Independents and Republicans. The column names and their order differ across pages, so columns are matched by keyword ("start", "democrat", and so on), never by position.

Cleaning rules, applied in this order. Every row each rule affects is listed in `QC_REPORT.md` §2.

| # | Problem found | Rule | Rows |
|---|---|---|---|
| 2.1 | UCSB marks some rows on the G.H.W. Bush page as "interpolated" (they are not polls) | Drop them. Missing months are filled by our own rule in step 3. | 3 |
| 2.2 | Trump 2nd term page mixes Gallup with other pollsters after Gallup stopped (AP-NORC, CNN, Ipsos, ...) | Keep `Source == gallup` only, so the series has one pollster throughout | 47 dropped |
| 2.3 | Trump 1st term page lists the party breakdown in a separate block with its own dates (2017 values are Gallup monthly averages) | Read the two blocks separately and merge them on (start, end). Partisan polls without a matching overall poll stay as their own rows. | 48 |
| 2.4 | Typo year in an end date: Biden `2/20/224` | Take the year from the start date | 1 |
| 2.5 | Two Trump rows with a wrong year (end before start, or a 13-month field period) | Try moving one date's year to match the other. Keep the candidate with a 0-45 day field period that lies closest to the neighbouring rows of the table. | 2 |
| 2.6 | Two Reagan polls (Feb and Mar 1981) report Democrats at 78-87% and Republicans at 39-41%, which are clearly swapped columns | Set only those partisan values to missing. Overall approval is kept. | 2 |
| 2.7 | Duplicate polls, or polls dated outside the president's tenure | Drop. None were found. | 0 |

Each poll's **midpoint** = start + (end − start)/2 decides which month it belongs to. Field periods run from 1 to 35 days (median 4).

Output: `data/clean/approval_polls.csv`, with 1,530 rows: 1,491 polls with overall approval plus 39 Trump partisan-only rows from rule 2.3.

### Step 3. Monthly approval $A_t$ (`build_monthly_approval`)

1. **Who owns a month.** Each month belongs to the president in office on its **15th**. So every January of an inauguration year (1977, 1981, ..., 2025) belongs to the *outgoing* president, who holds 19 of its 31 days. A month uses only polls of its own president. Ten polls of incoming presidents in late January are therefore set aside. The dummy `inaug_month` marks these Januaries.
2. **Aggregate.** $A_t$ is the mean of all of that president's polls whose midpoint falls in the month. `n_polls` records how many.
3. **Fill months with no poll** (12 of 576, 2.1%, never more than 2 in a row). Interior gaps are interpolated linearly within the same administration. A gap at the start or end of an administration takes the nearest month of that same administration (3 cases: 1981m1, 1989m1, 1989m2). Values are **never** carried across presidents. `A_fill` records `observed`, `interpolated` or `nearest` for every month.
4. **Logit:** $a_t = \ln(A_t/(100-A_t))$.

| Filled months | Why |
|---|---|
| 1980m10, 1986m2, 1986m11, 1987m2, 1987m5, 1987m9, 1987m11, 1988m2, 2022m12 | Gallup did not poll that month (interpolated) |
| 1981m1, 1989m1 | Outgoing president not polled in his last January (nearest) |
| 1989m2 | G.H.W. Bush's first poll has its midpoint on 1 March (nearest) |

### Step 4. Mass polarisation $G_t$ (`build_monthly_approval`)

1. **In-party approval** is approval among Democrats if the president is a Democrat, and among Republicans otherwise. **Out-party approval** is the other one.
2. Take monthly means as in step 3, and fill the same way (`G_fill`). 560 of 576 months are observed.
3. $G_t$ = in-party − out-party approval, in percentage points. It rises from about 30 in 1978 to about 85 by 2025.
4. `G_lag12` is $G_{t-12}$, the moderator used in the model. The 1977 lead-in (including Ford's December 1976 poll) gives it a value at 1978m1.

### Step 5. Economic indicators $S_t, U_t, \pi_t, W_t$ (`build_fred`)

| Variable | Construction |
|---|---|
| $S_t$ | `UMCSENT` as published |
| $U_t$ | `UNRATE` as published |
| $\pi_t$ | $100 \times \ln(\mathrm{CPI}_t / \mathrm{CPI}_{t-12})$ |
| $W_t$ | $100 \times \ln(\mathrm{rw}_t / \mathrm{rw}_{t-12})$ with $\mathrm{rw}_t = \texttt{AHETPI}_t / \mathrm{CPI}_t$ |
| `rec` | `USREC` as published |

Source gaps:
- **2025m10:** BLS published no CPI and no unemployment rate because of the October-November 2025 federal government shutdown. FRED shows both as blank. CPI is filled with the geometric mean of 2025m9 and 2025m11, and $U$ with the arithmetic mean. Both are flagged in `CPI_filled` and `U_filled`. This month also feeds $\pi_t$ and $W_t$ through 2026m10, but only 2025m10 and 2025m11 lie in our sample.
- **Before 1978**, `UMCSENT` is quarterly. This only affects the 1977 lead-in, where $S$ is left missing. The sample itself starts in 1978m1, when the monthly series begins.

### Step 6. Elite polarisation $P_t$ and eras (`build_polarisation`, `assemble`)

1. Voteview stores `party_code` as `100`/`200` up to the 114th Congress and as `100.0`/`200.0` after that. Convert to integers before filtering, or later Congresses silently drop out.
2. For each Congress and chamber, take the Republican (200) mean minus the Democratic (100) mean of `nominate_dim1_mean`. $P_t$ is the average of the House and Senate gaps (`P_house` and `P_senate` are kept too).
3. Congress $n$ opens on 3 January of year $1789 + 2(n-1)$, so every month belongs to the Congress in session on its 15th. $P_t$ is constant within a Congress.
4. **Eras** are the terciles of $P_t$ over the 576 sample months. Because $P_t$ rises almost every Congress, they come out as three continuous blocks:

| Era | Months | Congresses | Mean $P$ |
|---|---|---|---|
| 1 | 1978m1-1992m12 (180) | 95th-102nd | 0.619 |
| 2 | 1993m1-2008m12 (192) | 103rd-110th | 0.721 |
| 3 | 2009m1-2025m12 (204) | 111th-119th | 0.843 |

### Step 7. Controls $\mathbf{D}_t$ and the president (`assemble`)

| Column | Definition |
|---|---|
| `honeymoon` | First six months of each new administration, counted from the first month whose 15th falls in the tenure (Feb-Jul of each inauguration year) |
| `rally_gulf`, `rally_911`, `rally_iraq`, `covid` | 1991m1-m3, 2001m9-2002m3, 2003m3-m4, 2020m3-m5 (as in the proposal) |
| `rec` | NBER recession |
| `admin` | Administration id for fixed effects (`carter`, `reagan`, `bush41`, `clinton`, `bush43`, `obama`, `trump1`, `biden`, `trump2`; `ford` appears in 1977 only) |
| `pres_dem`, `second_term`, `admin_month`, `inaug_month` | Party, second-term indicator, months in office, January transition month |

### Step 8. Assemble the panel (`assemble`)

Merge steps 3-7 on the month. Add `t` (1..576), the trend `s` $= t/T$ used in the trend interactions, era dummies `E1`-`E3`, and `in_sample` (1 for 1978m1-2025m12). The 1977 rows are kept so that $a_{t-1}$, $\Delta a_{t-1}$, $\mathbf{x}_{t-1}$ and $G_{t-12}$ exist at 1978m1. Over the sample, no model variable has a missing value (check M2).

### Step 9. Quality checks (`run_checks`)

All 28 pass. Full detail is in [`data/QC_REPORT.md`](data/QC_REPORT.md).

| Group | What is checked |
|---|---|
| P1-P7 polls | every page parsed; valid dates and field periods; percentages in [0,100]; approve + disapprove + unsure within 97-103; in-party approval above out-party approval in all 1,396 partisan polls; overall approval inside the party range in all 1,357 polls with both; no duplicates or out-of-tenure polls |
| M1-M7 panel | 576 contiguous months; no missing model variable; logit finite; ≤10% filled months (actual 2.1%); no fill run longer than 3 (actual 2); G observed in ≥85% of months (actual 97%); G > 0 every month |
| V1-V3 polarisation | both parties in both chambers for every Congress; P rises over time; eras are continuous blocks |
| B1-B10 benchmarks | built values reproduce known history: post-9/11 approval 88, Gulf War 85.6, Carter low 28.7, G.W. Bush low 27, unemployment 10.8 (1982) and 14.8 (Apr 2020), inflation peaks 13.6 (1980) and 8.6 (2022), sentiment low 50.0 (Jun 2022), NBER dates |

On top of the automated checks, five monthly approval values were recomputed by hand from the raw HTML (2001m9, 2012m11, 1998m12, 1986m12, 2025m6), along with $P$ for 1998 and $\pi$ for 2022m6. All match the built file exactly. The largest month-on-month approval changes (`QC_REPORT.md` §4) line up with known events: 9/11, the Iran hostage crisis (1979m12), the 1990 budget fight, the Gulf War and the invasion of Kuwait.

---

## 5. From proposal notation to columns

| Proposal | Column | Proposal | Column |
|---|---|---|---|
| $A_t$ | `A` | $P_t$ | `P` |
| $a_t$ | `a` | $G_t$, $G_{t-12}$ | `G`, `G_lag12` |
| $S_t$ | `S` | $E_{e,t}$ | `E1`, `E2`, `E3` (or `era`) |
| $U_t$ | `U` | $s_t = t/T$ | `s` |
| $\pi_t$ | `pi` | $\mathbf{D}_t$ | `honeymoon`, `rally_gulf`, `rally_911`, `rally_iraq`, `covid`, `rec` |
| $W_t$ | `W` | administration fixed effects | `admin` |

Differences, lags and interactions are left for you to build in your estimation code, so the file stays small and nothing is precomputed under assumptions you might change.

---

## 6. Things to keep in mind when modelling

1. **Polls per month vary by era**: on average 1.4 in the 1980s, 4.1 in the 2010s (Gallup's weekly tracking) and 1.1 since 2018. Monthly $A_t$ is noisier when it rests on one poll. This is one more reason for the Newey-West errors and ARCH-LM test in the proposal. `n_polls` is in the file if you want to weight observations or test this directly.
2. **$G_t$ moves with approval itself.** When the economy improves, out-party approval rises and $G_t$ falls. Use `G_lag12` as the moderator, as the proposal does, and not the contemporaneous `G`.
3. **$P_t$ for the 119th Congress (2025) is provisional.** Voteview updates the scores as votes accumulate, so a later download may differ slightly in the last 12 months.
4. **January transition months** belong to the outgoing president (step 3). If a result looks sensitive to these months, add `inaug_month` as a control.
5. **Filled values are flagged** (`A_fill`, `G_fill`, `CPI_filled`, `U_filled`). A robustness check that drops the 12 filled approval months is one line of code.
6. **Data vintage.** FRED values are the November 2026 vintage. Revisions are small for these series, but cite the snapshot date from `manifest.csv`.
