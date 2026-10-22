# Executed results: abstention, selection and the Blue Wall

Start with [the concise findings PDF](findings_2016_2024.pdf) or [its Markdown version](findings_2016_2024.md). The full [executed notebook](../notebooks/nonvoters_selection_2016_2024.ipynb) explains every model in the notation of the supplied Lecture 10 notes. [The lecture-to-study map](../docs/lecture_notation.md) explains the continuous-to-binary extension.

## Executions completed

1. Audited the retained 2016/2024 cross sections and state nonvoter sample sizes; kept nonvoter outcomes missing during estimation.
2. Estimated weighted turnout and voter-choice probits, including baselines with full state indicators and no-state comparisons.
3. Estimated joint binary probit with sample selection and COVI excluded from the outcome, using three starting correlations per election.
4. Implemented the lecture's first-stage probit, inverse Mills ratio and augmented linear-probability second stage as a teaching diagnostic, with stacked-equation variance. This is not used as a valid binary likelihood or for election scenarios.
5. Computed score-based state-cluster covariance, rho tests/intervals, national preference intervals including observed covariate-mix uncertainty, cross-year tests clustered jointly by state, and baseline probability effects.
6. Compared predictions with available pre-election preferences and hypothetical post-election nonvoter choices on the same respondent subsets.
7. Tabulated prior Democratic/Republican/other/nonvoter reports against current choice or validated abstention; reported a separate Sanders-primary description. These are not validated longitudinal electorate flows.
8. Calculated Michigan/Wisconsin/Pennsylvania required-participation thresholds, hypothetical participation grids and non-Republican-to-Democratic allocation sensitivity. Kept actual other-candidate responses separate in descriptive tables.
9. Refit selection without COVI, excluding Utah, with region controls, and on active-status records in 2016 (2024 is already all active).
10. Checked the deterministic bivariate CDF against independent quadrature, checked the analytic likelihood gradient numerically, and recovered known parameters in a simulated sample. Numerical checks do not establish the exclusion restriction.

## Output map

| Output | Contents |
|---|---|
| `tables/sample_counts.csv`, `state_sample_counts.csv` | Sample restrictions and nonvoter/Kish counts |
| `tables/coefficients_2016.csv`, `coefficients_2024.csv` | Every main-model coefficient, state-cluster SE, t statistic, p value and interval |
| `tables/national_preferences.csv` | Baseline and conditional-selection Republican preference, allocated Democratic complement and national intervals |
| `tables/cross_year_contrasts.csv` | Formal 2024-minus-2016 tests; Republican direction is the reverse of the allocated Democratic direction |
| `tables/blue_wall_preferences.csv` | State point estimates and conditional-on-covariates parameter SEs; these are not state population CIs |
| `tables/lecture_two_step_diagnostic.csv` | IMR coefficient, generated-regressor-adjusted SE and invalid-probability diagnostics |
| `tables/baseline_average_partial_effects.csv` | Probability-scale conditional contrasts over retained nonvoter covariates |
| `tables/nonvoter_benchmarks.csv` | Stated preferences, coverage and predictions for the same subsets |
| `tables/prior_vote_transitions.csv`, `prior_vote_coverage.csv` | Prior reports versus current choice/abstention and missing-prior coverage |
| `tables/sanders_descriptive_transitions.csv` | Self-reported Sanders primary voters; exploratory description |
| `tables/blue_wall_thresholds.csv` | Required added participants at five allocation assumptions |
| `tables/participation_scenarios.csv` | Five hypothetical participation counts per threshold scenario |
| `tables/electoral_college_arithmetic.csv` | EC reallocations if all three states flip, holding other states fixed |
| `tables/selection_robustness.csv`, `robustness_coefficients.csv` | Alternative selection fits and all their coefficients |
| `model_diagnostics.json` | Multistart likelihoods, scores, Hessian diagnostics, rho and robust inference |
| `estimator_validation.json` | Independent CDF, gradient and simulated-data checks |
| `run_manifest.json` | Actual runtime versions, data/code hashes and inference conventions |
| `figures/` | National interval comparison and baseline state threshold sensitivity |

## Reproduce from this folder's parent (`Project/P1`)

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r code/requirements-analysis.txt
python code/validate_selection.py
python code/execute_notebook.py
python code/build_findings.py
```

The notebook writes tables, figures and its execution manifest. The final command builds both the Markdown findings and the PDF. An interactive Jupyter client can open the notebook directly using the same environment. The execution script provisions a temporary kernel using the exact Python interpreter running it; it does not rely on a pre-existing machine-specific kernel name.

The versioned compact data are sufficient. Original CES microdata are only required to recreate the new prior-vote supplement:

```sh
python code/prepare_analysis_inputs.py --ces-dir /path/to/original/data/CES
```

Original-variable names and source-file hashes are in `data/analysis/prior_vote_provenance.json`. State returns are in `data/analysis/official_blue_wall_returns.csv`, transcribed from the linked official FEC publications. The 2016 EC illustration uses standard state allocations before faithless electors.

## Boundaries for the presentation

- The headline allocated Democratic share is `1 - predicted Republican share`, with every non-Republican assigned to Democrats. It is an explicit optimistic allocation, not measured Democratic preference.
- The baseline cross-year decline in that share has p = 0.077; the selection-model change has p = 0.368. Neither is significant at 5%.
- Selection results depend on normality, exclusion and omitted state factors. Three starts agree numerically, but the 2016 adjusted mean is very uncertain; the 2024 adjustment disagrees sharply with stated-preference benchmarks. The 2024 likelihood Hessian has a condition number around 1.6 million, another reason to treat asymptotic inference cautiously.
- State thresholds hold existing ballots fixed and assume added participants have the predicted nonvoter mix. No CES weight sum is treated as a state population count. A population full-turnout conclusion still needs aligned nonvoter totals and justified transportability beyond the retained matched sample.
- The 2024 state nonvoter samples are small and highly concentrated in a few weights. Parameter-only state SEs do not measure uncertainty about population composition. State thresholds are point scenarios and have no population confidence intervals.
- Prior votes and primary preferences are self-reported. These data do not identify Gaza, moderation, or Sanders support as causes of abstention.
