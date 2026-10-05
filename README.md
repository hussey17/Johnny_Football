# Johnny_Football

Master repo for the Advanced Econometrics (ECON 438) projects.

| Folder | Contents | Start here |
|---|---|---|
| [`project1/`](project1/) | Project 1, US presidential disaster declarations, 1989-2026: all raw data, the scripts that fetched them, the manifest and fetch report, and the hand-coded tables (governors, FEMA's per capita indicator, state rainy-day funds) | [`project1/README.md`](project1/README.md) |
| `project2/` | (to come) | |

## Quick start

```bash
git clone https://github.com/hussey17/Johnny_Football.git
cd Johnny_Football
gh release download project1-data-2026-10-05 -R hussey17/Johnny_Football -p storm_events.zip -D project1/data/raw
unzip project1/data/raw/storm_events.zip -d project1/data/raw && rm project1/data/raw/storm_events.zip
```

The second-to-last command restores NOAA Storm Events (about 310 MB), which is too large for git and is stored on the [`project1-data-2026-10-05` release](https://github.com/hussey17/Johnny_Football/releases/tag/project1-data-2026-10-05). Everything else is in the repo. [`project1/README.md`](project1/README.md) describes every folder, file and column.

## Conventions

- `data/raw/` files are kept exactly as their source served them. Put cleaned or derived data somewhere else.
- `data/manifest.csv` records the URL, sha256 and UTC download time of every file. Cite those times in the paper.
- Commit code, manifest, report and tables together, so they always match.
