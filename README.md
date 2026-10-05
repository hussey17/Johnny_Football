# Johnny_Football

Master repo for the Advanced Econometrics (ECON 438) projects 1 and 2.

| Folder | Contents |
|---|---|
| [`project1/`](project1/) | Project 1, US presidential disaster declarations, 1989-2026: raw data acquisition (code, raw files, manifest, fetch report, hand-coding templates) |

## Layout

```
project1/
  code/fetch_data.py        one-command downloader for every raw source
  code/requirements.txt     pinned dependencies
  code/report_notes.md      hand-written notes merged into FETCH_REPORT.md
  data/raw/<source>/        raw files exactly as served (never edited)
  data/manual/*.csv         templates for hand-coded variables
  data/manifest.csv         one row per file: URL, sha256, bytes, UTC download time, status
  data/FETCH_REPORT.md      snapshot date, source table, failures, acceptance checks, open items
```

Start with [`project1/data/FETCH_REPORT.md`](project1/data/FETCH_REPORT.md) for what was fetched, what failed and which manual items remain.

Storm Events (`project1/data/raw/storm_events/`, about 310 MB) is too large for git. It is attached as `storm_events.zip` to the [`project1-data-2026-10-05` release](https://github.com/hussey17/Johnny_Football/releases/tag/project1-data-2026-10-05).

## Reproduce

```bash
python3 -m venv .venv
.venv/bin/pip install -r project1/code/requirements.txt
.venv/bin/python project1/code/fetch_data.py --email you@example.com
```

Files that already exist are skipped, so a rerun only fetches what is missing. Use `--force` to download everything again, and `--only <step|Dxx>` to run single sources. Run `python project1/code/fetch_data.py -h` for the list of steps.

To restore Storm Events from the release instead of from NOAA:

```bash
gh release download project1-data-2026-10-05 -R hussey17/Johnny_Football -p storm_events.zip -D project1/data/raw
unzip project1/data/raw/storm_events.zip -d project1/data/raw && rm project1/data/raw/storm_events.zip
```
