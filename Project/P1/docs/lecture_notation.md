# Lecture notation and binary-outcome adaptation

Teaching source: *Lecture_10_Limited_Dependent_Variable_Models_Part_8_Notes.pdf*, supplied locally by the user. Relevant material: selection equations (pp. 5-7), joint normality (p. 9), inverse Mills ratio (pp. 10-12), two-step estimation (pp. 13-15), exclusion restrictions (pp. 15-17), and generated-regressor inference (p. 18). The lecture PDF is not redistributed.

| Lecture symbol | Study meaning | Notebook object / code |
|---|---|---|
| S | Validated turnout: 1 voter; 0 matched nonvoter | `turnout_matched`, `S` |
| Z | Selection regressors | `Z`: individual controls plus COVI |
| gamma | Turnout coefficients | `gamma:` entries in joint coefficient tables |
| v | Unobserved turnout determinant | Standard normal selection disturbance |
| Y | Observed substantive outcome, when S=1 | `republican_any`, `Y` |
| X | Preference regressors | `X`: individual controls |
| beta | Preference coefficients | `beta:` entries in joint coefficient tables |
| u | Unobserved outcome determinant | Standard normal latent-preference disturbance |
| rho | Correlation of u and v | `tanh(atanh_rho)` |
| lambda(Z gamma) | Selected inverse Mills ratio | `imr(Z @ gamma)` |
| delta = rho sigma_u | Lecture's continuous-outcome correction coefficient | `delta` in the teaching two-step diagnostic only |

The lecture's Y is continuous and its second step is an augmented OLS regression. Here, preference is binary. The main model therefore uses `Y*=X beta+u`, `Y=1(Y*>0)` and a joint binary sample-selection likelihood. Both latent variances are normalized to one. A probit with an added inverse Mills ratio is not used as an exact binary correction.

The notebook separately implements the literal two-step linear-probability diagnostic to explain the lecture's logic. Its variance is calculated from stacked first- and second-step estimating equations; a naive second-stage OLS variance would omit generated-regressor uncertainty. Unbounded diagnostic predictions are not used as electoral probabilities.

For the main joint estimator, the nonvoter target is `Phi2(-Z gamma, X beta; -rho) / Phi(-Z gamma)`. The marginal `Phi(X beta)` is exported as a different target. The exclusion is COVI; it cannot coexist with full state indicators in a single-year selection equation. Baselines with state indicators and joint models with region controls are reported to expose the identification tradeoff.

Binary-likelihood reference: [Stata, Probit model with sample selection by mlexp](https://blog.stata.com/2015/10/22/probit-model-with-sample-selection-by-mlexp/). [SciPy's Owen's T function](https://docs.scipy.org/doc/scipy/reference/generated/scipy.special.owens_t.html) supports the deterministic bivariate CDF implementation, independently checked against conditional-normal quadrature.
