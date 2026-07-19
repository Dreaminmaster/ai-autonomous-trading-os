# C4A DSR Units and Universe-Scope Clarification V1

## 1. Status and precedence

- Stage: `C4A`
- Parent contract: `C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_CONTRACT_V1.md`
- Parent addendum: `C4A_UNIVERSE_AND_MULTIPLE_TESTING_ADDENDUM_V1.md`
- Weekly clarification: `C4A_WEEKLY_BOUNDARY_CLARIFICATION_V1.md`
- Required base SHA: `72f35dd715874dc2e7c355511675dec29642b430`
- Clarification status: `DESIGN_ONLY`
- C4B: `CLOSED`
- Holdout: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This clarification is normative. It corrects the unit convention used inside the Probabilistic/Deflated Sharpe inference and narrows what a C4A result may claim about the fixed candidate universe and the broader sequential research program. Where prior C4A wording refers to an annualized weekly Sharpe inside the DSR equation, this clarification controls.

## 2. Sharpe unit used inside DSR

The Deflated Sharpe Ratio formula must use a Sharpe ratio expressed at the same frequency as the return observations used to estimate skewness, kurtosis, and sample length.

C4A uses exactly `39` non-overlapping weekly return observations per policy. Therefore define:

`SR_weekly_raw = mean(weekly_returns) / sample_std(weekly_returns, ddof=1)`

The following quantities are all expressed in the same raw weekly unit:

- each policy's observed `SR_weekly_raw`;
- the three-trial sample standard deviation `sigma_SR_raw`;
- the expected maximum Sharpe threshold `SR_star_raw`;
- the difference `SR_weekly_raw - SR_star_raw` inside the DSR z-score.

The frozen DSR equation is:

`DSR = Phi((SR_weekly_raw - SR_star_raw) * sqrt(T - 1) / sqrt(1 - skew * SR_weekly_raw + ((kurtosis - 1) / 4) * SR_weekly_raw^2))`

where:

- `T = 39`;
- `skew` and ordinary `kurtosis` are estimated from the same 39 weekly returns;
- `Phi` is the standard-normal CDF;
- `SR_star_raw` is computed from the three raw weekly Sharpe values using the frozen expected-maximum formula.

Annualization is not applied to any Sharpe quantity inside this DSR equation.

## 3. Annualized Sharpe is a report-only transform

For human-readable reporting only:

`SR_weekly_annualized = SR_weekly_raw * sqrt(52)`

Rules:

- the annualized value must be retained as a separate field;
- it may not replace `SR_weekly_raw` in `sigma_SR_raw`, `SR_star_raw`, the non-normality denominator, or the DSR z-score;
- eligibility uses the final DSR probability and the separately frozen four-hour aggregate-Sharpe gate, not the report-only annualized weekly Sharpe;
- production and reference implementations must independently retain and compare both raw and annualized values.

This separation prevents mixing an annualized numerator with weekly-frequency sampling variance and higher moments.

## 4. Zero-variance and numerical semantics

For each policy's 39 weekly returns:

- sample standard deviation uses `ddof=1`;
- if sample standard deviation is zero and the arithmetic mean is zero:
  - `SR_weekly_raw = 0`;
  - `SR_weekly_annualized = 0`;
  - that policy's DSR probability is frozen to `0`;
- if sample standard deviation is zero and the mean is nonzero, the run is `EVIDENCE_FAILURE`;
- non-finite return, mean, standard deviation, skewness, kurtosis, Sharpe, threshold, denominator, z-score, or probability is `EVIDENCE_FAILURE`.

Across the three raw weekly policy Sharpes:

- `sigma_SR_raw` uses sample standard deviation with `ddof=1`;
- if all three raw weekly Sharpes are exactly equal, set `SR_star_raw = 0` as already frozen;
- otherwise compute `SR_star_raw` from `sigma_SR_raw` and exactly `N = 3` trials.

Production/reference comparison tolerances remain:

- absolute tolerance `1e-10`;
- relative tolerance `1e-10`.

## 5. Required retained DSR fields

For every policy, the final evidence must retain:

- the exact 39 weekly returns;
- weekly arithmetic mean;
- weekly sample standard deviation;
- `SR_weekly_raw`;
- `SR_weekly_annualized`;
- bias-corrected sample skewness;
- bias-corrected ordinary sample kurtosis;
- complete three-policy raw-Sharpe trial vector;
- `sigma_SR_raw`;
- `SR_star_raw`;
- denominator radicand;
- DSR z-score;
- DSR probability;
- DSR gate pass/fail.

Field names or a documented schema mapping must make the raw-versus-annualized unit distinction explicit. A single ambiguous `sharpe` field is insufficient.

## 6. Fixed-incumbent-universe scope

C4A is a fixed-incumbent-universe experiment. The twelve candidate pairs were preregistered as established OKX USDT spot assets before C4A implementation, but the contract does not reconstruct the complete historical set of all OKX listings as of `2023-09-01`.

Consequently:

- the liquidity formation rule prevents screen-period return leakage within the fixed twelve-pair pool;
- it does not eliminate universe-selection or survivorship limitations outside that pool;
- a positive C4A result may support only the statement that the frozen policy worked within this exact preregistered twelve-pair incumbent pool and its formation-selected top eight;
- it may not be generalized to all coins, all historical OKX listings, delisted assets, newly listed assets, or an investable production universe;
- C4B or any later paper/shadow proposal would require a separate universe-validity design before execution could be considered;
- a negative C4A result remains a valid rejection of this exact fixed-pool thesis.

No pair may be substituted after formation coverage or economic results are observed. Missing coverage remains `EVIDENCE_FAILURE`.

## 7. Within-stage versus program-level selection bias

The frozen `N = 3` DSR trial set corrects only for selection among the three preregistered C4A policies.

It does not mathematically correct for:

- the earlier C1A, C2A, and C3A candidate families;
- the human choice to investigate cross-sectional momentum after those stages were rejected;
- unpublished ideas that were considered but never preregistered;
- the fixed-incumbent-universe choice described above.

Therefore:

- the C4A DSR field must be labelled `within_stage_dsr_probability` or an equally explicit schema name;
- reports may not call it a program-wide, global, or all-research DSR;
- a C4A `SELECTED` result would remain a development-screen candidate, not confirmed edge and not authorization to trade;
- any later C4B design must treat C1-C3 as untouched confirmation data and must explicitly address the accumulated sequential-research selection problem before defining its own statistical acceptance rule;
- paper, shadow, private exchange access, and live remain unavailable even when every C4A gate passes.

The within-stage DSR gate remains `>= 0.90`; this clarification changes only the interpretation and required field naming, not the threshold.

## 8. Independent-review requirements

Before C4A design can be frozen, review must verify:

- every DSR input uses raw weekly Sharpe units inside the inference equation;
- annualization appears only as an explicit report-only transform;
- the trial vector contains exactly all three policies, including weak or cash-heavy policies;
- `T` is exactly 39 and uses the cost-inclusive boundary convention in the weekly clarification;
- the result language preserves the fixed-incumbent-universe limitation;
- the result language labels DSR as within-stage and does not imply correction for prior research stages;
- no wording implies C4B, holdout, paper, shadow, private API, leverage, derivatives, shorts, or live authorization.

## 9. Safety state

This clarification changes no market data boundary, policy signal, cost, gate probability, execution authorization, or reserved-window state.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
