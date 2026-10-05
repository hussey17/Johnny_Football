## Distribution (replaces the brief's Google Drive step)

Per the user's instruction the data go to GitHub instead of Google Drive.

- **Repository:** https://github.com/hussey17/Johnny_Football, folder `project1/`. Code, manifest, this report, manual templates and every raw file except Storm Events are committed directly (largest single file about 25 MB).
- **Storm Events (D6):** `project1/data/raw/storm_events/` is git-ignored and published as one zip, `storm_events.zip`, on the release `project1-data-2026-10-05`: https://github.com/hussey17/Johnny_Football/releases/tag/project1-data-2026-10-05. Unzip it into `project1/data/raw/` to restore the folder; `manifest.csv` has the sha256 of every file inside it.
- **PDA PDFs (D7):** none were downloaded (see below), so there is no PDA zip.

## `confirm` URLs and fallbacks

| ID | Result |
|---|---|
| D3 `FemaWebDisasterDeclarations.csv` | Worked. The JSON paging fallback was not needed. |
| D4 `FemaWebDisasterSummaries.csv` | Worked. |
| D11 BEA `CAINC1.zip` | Worked. The Census fallback was not needed. |
| D19 Census `apportionment-2020-tableC1.xlsx` / `.pdf` | Both worked. The National Archives fallback was not needed. |
| D20 Voteview `HSall_members.csv` | Worked. |

## Deviations from the brief and judgement calls

- **D7 PDA reports: blocked.** Every `www.fema.gov` web page, including the PDA listing, returns HTTP 403 "Access Denied" to this network. This held for the script, for curl and for an ordinary browser. The OpenFEMA API (`/api/open/...`) is unaffected. Following the brief's blocked-host rule, no PDFs were downloaded and the R extraction was not run, although R 4.5.2 is installed. The Urban Institute package also sends a spoofed mobile-browser User-Agent, which this script does not do. To recover D7, run `python code/fetch_data.py --email <you> --only pda` from a network where fema.gov pages load. The step then downloads the PDFs and runs the R package automatically.
- **D8 notice text from govinfo.** `federalregister.gov` full-text URLs return a "Request Access" bot-check page (HTTP 200) to scripts, and the API does not. The text of each notice is therefore taken from the Government Publishing Office edition at `govinfo.gov` (same document, official publisher), saved as `raw/fedreg/text/<document_number>.htm`. The `raw_text_url` of each notice is still recorded in `raw/fedreg/fedreg_notices.csv`.
- **D8 second query.** The brief's query (`"statewide per capita impact indicator"`) returns 28 notices. A supplementary query, `"per capita impact indicator"` limited to FEMA, returns 55. Both raw responses are saved, and the union of the two is indexed in `fedreg_notices.csv`, with a `matched_queries` column.
- **D13 Treasury.** All 27 Excel files linked on the page were downloaded. Among them is `research-series-2010.xls`, which is not in the brief's list. 2004 is not listed on the page and is recorded as missing. No URL was guessed.
- **D22 Shor-McCarty.** The search for a newer version found the January 2025 release (`doi:10.7910/DVN/T53FFK`, covering 1993-2022). That release is used instead of the April 2023 one named in the brief (`WI8ERB`).
- **Network workarounds (no change to content).** The script resolves hosts over IPv4 only, because IPv6 connections to fema.gov's CDN hang on this network. Each download attempt is aborted and retried if it runs past 10 minutes or averages under 50 KB/s after a minute, because NOAA intermittently sends the body a few bytes at a time.

## Manual items still open

1. **`manual/governors_template.csv`**: 254 governor spells from 1989 to 2011, pre-filled from Klarner (`verified = 0`), plus one blank reminder row per state for the 2012-2026 spells. Klarner coverage ends in 2011, and the openICPSR source (project 102000) needs a login. `term_limited`, `eligible_next_election` and `next_election_date` are empty for every row (D17, D18). Rows whose party cell is blank had a mid-year change of governor (`govparty_a` between 0 and 1).
2. **`manual/tau_series.csv`**: 26 fiscal years (FY2001-FY2025 and FY2027), extracted by regex and flagged `amount_is_guess = 1`. **FY2026 is missing:** no notice published in 2025 matched either query. Each amount needs checking against its notice.
3. **`manual/rainy_day_template.csv`**: 50 states × FY1992-2026 = 1,750 empty rows, for the NASBO data (D14), which needs a registered account.
4. **`manual/pda_review_queue.csv`**: empty (header only), because D7 is blocked.
5. **SHELDUS (D5)**: out of scope (paid licence).
