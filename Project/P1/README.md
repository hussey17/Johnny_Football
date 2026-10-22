# CES and COVI data for ECON 438 Project 1

This package contains extracts from the vote-validated CES Common Content releases for 2016, 2020 and 2024, original COVI workbooks, source guides, and reproducible preparation scripts for the nonvoter-preferences study. Sources were collected on 20 October 2026. The large original CES microdata remain in the collection workspace and can be downloaded with the collector. The separately fitted 2016 and 2024 analysis is now executed in the notebook linked below; 2020 remains available as data.

**Latest analysis:** [executed notebook](notebooks/nonvoters_selection_2016_2024.ipynb), [concise findings PDF](results/findings_2016_2024.pdf), [findings in Markdown](results/findings_2016_2024.md), and [all outputs and reproduction commands](results/README.md). The notebook uses the supplied Lecture 10 notation and explains the binary-outcome extension.

The [one-page study brief](nonvoter_study_brief.pdf) summarizes the research question, model and limitations.

**Start with `data/prepared/ces_covi_2016_2020_2024.dta` in Stata, or the adjacent `.csv.gz` in Python/R.** The combined file has **185,600 respondents and 65 variables**. Every source respondent is retained, including nonvoters, unmatched records and D.C. residents. A candidate-sample flag is provided; filtering is an explicit modelling decision.

## Contents

```text
P1/
  README.md
  .gitignore
  code/
    collect_data.py                 Public downloads, ZIP import, raw-file inventory
    prepare_data.py                 Annual harmonization, COVI extraction, checked merge
    requirements.txt
  data/
    manifest.csv                   Raw-source sizes and local SHA256/MD5 hashes
    CES/
      2016/                        CES extract, metadata and corrected guide
      2020/                        Extract, guide, questionnaires and NC error materials
      2024/                        Extract, validation guide and questionnaires
      archives/                    Original ZIP bundles when collected locally; ignored by Git
    COVI/
      raw/                         Original index, policy workbook and codebook
      2016/                        Year-specific index and policy CSVs
      2020/                        Year-specific index, policies and COVID policies
      2024/                        Year-specific index and policy CSVs
      covi_state_year_2016_2020_2024.csv
    prepared/
      ces_covi_2016_2020_2024.csv.gz
      ces_covi_2016_2020_2024.dta    Recreated locally; ignored by Git
  docs/
    source_catalog.json            Pinned releases, source URLs and acquisition notes
    variable_crosswalk.csv         Actual annual variable names and roles
    harmonized_variable_notes.json Recoding definitions
    sample_counts.csv              Counts and exclusions by year
    unmatched_state_years.csv      D.C. records without COVI
    validation_report.json         Merge, category, row-count and export checks
```

Each annual CES folder also contains `ces_core_YEAR.csv.gz` and `metadata/` with the source variable dictionary, value labels, and annual checks. The original files are never edited.

## Sources and what they provide

| Source | Pinned release | Role |
|---|---|---|
| [2016 CES](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/GDF6Z0&version=5.0) | V5; February 2018 corrected validation data, guide updated January 2025 | 64,600 respondents; demographics, party/ideology, candidate preference and choice, Catalist turnout and explicit match flag. |
| [2020 CES](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/E9N6PH&version=4.0) | V4 | 61,000 respondents; corresponding survey items, adult/registered-voter weights and Catalist validation. The NC district-error memo and affected case list are retained. |
| [2024 CES](https://dataverse.harvard.edu/dataset.xhtml?persistentId=doi:10.7910/DVN/X11EP6&version=9.0) | V9; validated files published September 2025 | 60,000 respondents; corresponding survey items, gender4, population weights and TargetSmart validation. |
| [COVI](https://costofvotingindex.com/data) | Website snapshot; original 1996–2024 workbooks retained | Revised FinalCOVI, initial scores, ranks, 2020 COVIDCOVI and raw voting-law components. All 150 requested state-election records have FinalCOVI. |

CES is released under CC0 1.0; cite the dataset authors and pinned versions in `docs/source_catalog.json`. For COVI, cite the authors' relevant Election Law Journal papers, including Li, Pomante and Schraufnagel (2018) and Pomante (2025), DOI [10.1089/elj.2024.0037](https://doi.org/10.1089/elj.2024.0037). Do not assume that the CES license also applies to COVI. Hashes in `manifest.csv` are computed locally; they are not a claim that every checksum has been compared with a publisher checksum. Imported CES files were checked against the downloaded ZIP members' CRCs.

## Verified counts

Counts below precede citizenship, complete-case, weighting and 50-state restrictions.

| Year | All respondents | File matched | Validated voters | Matched nonvoters | Validated voters with usable post choice |
|---|---:|---:|---:|---:|---:|
| 2016 | 64,600 | 45,117 | 35,829 | 9,288 | 31,244 |
| 2020 | 61,000 | 48,180 | 39,198 | 8,982 | 35,779 |
| 2024 | 60,000 | 39,800 | 36,448 | 3,352 | 32,941 |

The COVI join matches **185,041 respondents**. Its **559 unmatched rows are all D.C.**: 192 in 2016, 197 in 2020, and 170 in 2024. They are retained with `covi_merge_ok = 0`. The master policy workbook's 2024 sheet contains three additional non-state rows; they are excluded from the derived policy CSV, and the original workbook is preserved.

## Actual annual variables

| Purpose | 2016 | 2020 | 2024 |
|---|---|---|---|
| Respondent ID | `V101` | `caseid` | `caseid` |
| Pre/post residence | `inputstate`, `inputstate_post` | Same | Same |
| Matching/status | `CL_matched`, `CL_voterstatus` | `CL_voter_status` | `TS_voterstatus` |
| Validated turnout | `CL_E2016GVM` | `CL_2020gvm` | `TS_g2024` |
| Post-election choice | `CC16_410a` | `CC20_410` | `CC24_410` |
| Pre-wave early vote / preference | `CC16_364b` / `CC16_364c` | `CC20_364a` / `CC20_364b` | `CC24_364a` / `CC24_364b` |
| Hypothetical post preference of self-reported nonvoters | `CC16_410a_nv` | `CC20_410a_nv` | `CC24_410_nv` |
| Adult pre/post weights | `commonweight_vv` / `commonweight_vv_post` | `commonweight` / `commonpostweight` | Same as 2020 |
| Sex/gender and income | `gender`, `faminc` | `gender`, `faminc_new` | `gender4`, `faminc_new` |

Other controls use `birthyr`, `educ`, `race`, `hispanic`, `pid7`, `ideo5` and `immstat`. Full source labels and codes are in each annual `metadata/variable_labels.json`. The codebook frequencies can predate source corrections: use the counts computed from the downloaded Stata files.

## How one combined observation is formed

One row is a respondent in a particular election year. **Append CES years; do not join respondents across years.** The unique key is `(year, case_id)`. A case ID alone is not a panel identifier.

The source `inputstate` is a Census FIPS code. It is mapped to `state_postal`; pre-election residence is the primary COVI exposure. `state_post_fips`, the later voter-file state, and a pre/post mover flag are retained for sensitivity checks. **COVI `statenu` is an alphabetical ordinal, not a FIPS code. Never merge it directly with CES `inputstate`.**

Join CES **many-to-one** to COVI using `(state_postal, year)`. The build additionally checks the mapped FIPS code. Every state-election score is repeated across that cell's respondents, which is why inference should account for clustering by state.

```python
from pathlib import Path
import pandas as pd

root = Path('.')  # Run from P1
ces = pd.concat([
    pd.read_csv(root / f'data/CES/{y}/ces_core_{y}.csv.gz',
                dtype={'turnout_raw': str}, low_memory=False)
    for y in (2016, 2020, 2024)
], ignore_index=True)
covi = pd.read_csv(root / 'data/COVI/covi_state_year_2016_2020_2024.csv')
assert not ces.duplicated(['year', 'case_id']).any()
assert not covi.duplicated(['state_postal', 'year']).any()
joined = ces.merge(covi, on=['state_postal', 'state_fips', 'year'],
                   how='left', validate='many_to_one', indicator=True)
assert len(joined) == len(ces) == 185600
```

## Variables for modelling

- `turnout_matched`: 1 for a validated voter, 0 for a matched nonvoter, missing for unmatched respondents. In 2016, the explicit match flag distinguishes a blank voting history from a failed match; in 2020, nonmissing registration status identifies a match. In 2024, codes 1–6 of `TS_g2024` mean voted, **7 means did not vote**, and missing means unmatched. An unknown voting METHOD still indicates a vote.
- `turnout_unmatched_zero`: sensitivity definition treating every unvalidated person, including unmatched people, as a nonvoter.
- `republican_any`: 1 Republican, 0 other reported candidate (including the response Other), observed only for validated voters with usable post-election choice. **It remains missing for nonvoters.** It is not Republican two-party share.
- `republican_2party`: 1 Republican, 0 Democrat, missing for third-party/Other and unknown choice. A two-party analysis adds selection into major-party voting; using this variable does not automatically correct that selection.
- `pre_republican_any`: coalesces usable pre-wave early-vote and preference responses. Code 1 means Trump in the 2020 PRE question but Biden in the POST question; coding is handled separately. Keep this variable out of the predictor set if using it as a validation benchmark.
- `post_nonvoter_pref_raw` and its label: a second benchmark based on hypothetical post-election preference. It is routed by **self-reported** nonvoting, so it is available for only a subset of validated nonvoters and is not an actual ballot outcome.
- `age`, `gender_group`, `education`, `race_h`, `income_group`, `pid7`, `ideology5`: cleaned controls. Nonanswers become missing; raw codes are retained. `age` is election year minus birth year. `race_h` identifies Hispanic respondents if either race or Hispanic-origin reports indicate Hispanic. Income is grouped as <30k, 30–49,999, 50–99,999, 100–149,999 and >=150k nominal dollars, accommodating 2016's top-coded category.
- `weight_adult_pre` and `weight_adult_post`: year-appropriate adult population weights. `weight_reg_pre/post` preserve the 2020/2024 registered-adult weights separately; they are missing by design in the 2016 extract. Do not splice registered-only weights into an all-adult analysis.
- `covi_final`: the proposed turnout exclusion. `covi_covid` is an alternative published score available only in 2020; missing values in other years are intentional. Initial scores, ranks and policies remain available for sensitivity checks.

`sample_candidate = 1` is a transparent convenience flag for matched adult citizens in the 50 states who completed the post-wave, have positive adult post weights, all seven controls, and usable choice if a validated voter. It retains nonvoters with missing outcomes. It selects **32,453 / 36,513 / 31,484** rows in 2016 / 2020 / 2024, including **5,539 / 5,257 / 2,185** nonvoters. It is not the finalized model sample: the team should decide its target population, treatment of unknown party/ideology and income, and approach to attrition first.

For a selection probit, use `turnout_matched` as the selection outcome and `republican_any` as the observed choice outcome. For pooled specifications, state and year effects can coexist with COVI variation across state-years. The executed analysis instead fits each election separately: its joint model uses individual controls in both equations and COVI only in selection; full state indicators would absorb single-year COVI. Separate state-FE baselines and region-control robustness fits expose that tradeoff. Use probability weights and state-clustered inference. Test error correlation using a robust Wald test rather than an ordinary LR test after weighted/clustered estimation. Do not let Stata silently drop voters with unknown choice without documenting that extra selection.

## Rebuild or obtain sources

From this folder, install dependencies in a project environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r code/requirements.txt
python code/collect_data.py
python code/prepare_data.py
```

The collector uses pinned Dataverse versions and `format=original`. During this collection, API requests returned HTTP 403 while public browser downloads worked. If the API refuses a later run, open the pinned dataset page, choose **Access Dataset > Original Format ZIP** (2024 offers Download ZIP), then import the archive:

```sh
python code/collect_data.py --import-ces-zip 2016 /path/to/2016.zip
python code/collect_data.py --import-ces-zip 2020 /path/to/2020.zip
python code/collect_data.py --import-ces-zip 2024 /path/to/2024.zip
python code/collect_data.py --only covi
python code/prepare_data.py
```

The importer checks ZIP paths and existing raw files against member CRCs. Existing raw files are retained; a differing pinned file raises an error instead of being overwritten. To inventory all current raw files again, use `python code/collect_data.py --only inventory`.

Partners who only need the combined observations can recreate the local Stata file from the versioned 9 MB staged extract without fetching raw data:

```sh
python code/prepare_data.py --restore-stata
```

Then, from P1 in Stata:

```stata
use "data/prepared/ces_covi_2016_2020_2024.dta", clear
isid year case_id
tab year turnout_matched, missing
tab year sample_candidate, missing
```

## Caveats to settle before estimation

1. **The exclusion is an assumption.** Voting laws may reflect changing state politics or influence mobilization/preferences. State effects do not remove time-varying confounding. Scores change in all 50 states, but this is not evidence of a strong or valid turnout exclusion. There are only 150 state-election cells and 50 state clusters.
2. **Index comparability needs scrutiny.** Policy coverage and construction change across years. The raw policies and COVID measure are retained so the team can assess a common definition and alternative 2020 exposure; they were not automatically combined or restandardized.
3. **Matching changes the target population.** Unmatched respondents include unregistered citizens and failed matches. 2024 matched status is reported only as Active, whereas earlier releases include other statuses. Compare the common active-status subset, using `active_file`, as well as alternative turnout definitions. The 2024 guide specifically cautions that Utah's private-registration rules reduce match rates; a Utah-excluded sensitivity check is warranted.
4. **Outcome missingness is separate from abstention.** Post-wave attrition and choice nonresponse leave 4,585 / 3,419 / 3,507 validated voters without usable choice. Weighting and complete cases do not prove that this missingness is ignorable. Survey choice is self-reported; only turnout is validated.
5. **Controls are not perfectly comparable.** 2024 gender identity has four categories while 2016/2020 use a binary gender item. Income bins are nominal, and birth-year age is approximate. Nonanswers to party ID/ideology should not be treated as numerical positions on those scales.
6. **Predicted preferences are conditional on the model.** For nonvoters, use the probability conditional on selection being zero, not simply the unconditioned probit probability. Functional-form and bivariate-normality assumptions matter; a full-turnout interpretation also assumes stable preferences and campaign conditions.

## Git handoff

This package is published at `Project/P1` on branch `p1_nonvoters` of [hussey17/Johnny_Football](https://github.com/hussey17/Johnny_Football/tree/p1_nonvoters/Project/P1). After cloning, switch to that branch and run the commands above from `Project/P1`:

```sh
git switch p1_nonvoters
cd Project/P1
```

The full original CES microdata and archives remain in the collection workspace at `ECONO II/Project/P1/data/CES`; they are not copied into ordinary Git history. A new clone can use the versioned compact extracts directly, restore the Stata file with `--restore-stata`, or obtain all original sources with the collector.

The local raw CES Stata files are approximately 573 MB, 850 MB and 993 MB, and two original CSVs are also large. `.gitignore` excludes those microdata, original ZIP archives and the reproducible 95 MB Stata export. It retains the compressed annual extracts, 9 MB combined CSV.gz, source metadata, checks, guides, COVI workbooks, code and this README. If full raw files must be shared through GitHub, choose Git LFS or release assets rather than accidentally adding them to ordinary Git history. [GitHub blocks ordinary files larger than 100 MiB](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github). The sources remain locally available in the requested CES folders.
