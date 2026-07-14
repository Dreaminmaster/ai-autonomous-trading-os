# C0 Profitability Research and Edge Validation Contract V1

Status: **DESIGN CANDIDATE**  
Mode: **BACKTEST / PAPER / SHADOW ONLY**  
Live: **FORBIDDEN**

## 1. Purpose

The execution and persistence foundation is now strong enough to stop treating infrastructure completion as the product goal.

C0 establishes the minimum research protocol required to discover, reject, compare, and promote trading strategies based on honest economic evidence.

The target is not to guarantee profit. The target is to build a falsifiable process that can demonstrate whether a strategy has positive net expectancy after costs and whether AI adds value beyond simple deterministic baselines.

C0 is intentionally small. It reuses Freqtrade's existing backtesting, trade export, strategy comparison, Hyperopt, lookahead analysis, recursive analysis, and result-analysis capabilities instead of creating another custom optimization framework.

## 2. Evidence motivating C0

The last frozen canonical result for `BTC/USDT`, spot, `5m`, `2025-01-01` through `2025-07-01` was:

| Metric | Value |
|---|---:|
| Trades | 244 |
| Net profit | -16.12% |
| Win rate | 44.67% |
| Maximum drawdown | 17.85% |
| Profit factor | 0.7524 |
| Lookahead analysis | PASS |
| Buy and hold | approximately -7.4% |

The strategy underperformed buy-and-hold while trading much more frequently.

Attribution showed:

| Entry source | Trades | Result |
|---|---:|---:|
| `trend_following_v1` | 230 | -$189.53 |
| `breakout_v1` | 10 | +$1.69 |
| `mean_reversion_v1` | 4 | +$26.69 |

Exit attribution showed:

| Exit reason | Trades | Result |
|---|---:|---:|
| max holding time | 174 | -$524.74 |
| take profit | 61 | +$403.25 |
| RSI overbought | 7 | -$6.73 |
| stop loss | 1 | -$31.06 |

Round 1 changed weights and exit timing but every tested variant was worse than the canonical baseline. Variant results ranged from `-41.67%` to `-58.29%`.

This is evidence against continuing manual weight tuning.

## 3. Root diagnosis

The current `MockProvider` is not an AI research baseline. It returns the first BUY candidate whose hard-coded confidence is at least `0.60`.

The candidate list is ordered:

1. trend following;
2. mean reversion;
3. breakout;
4. HOLD.

Candidate confidences and thresholds are fixed constants. The provider does not estimate expected return, transaction cost, uncertainty, regime compatibility, or opportunity cost.

Therefore:

- strategy order acts as an implicit priority rule;
- lowering or disabling one strategy substitutes the next eligible strategy;
- a weight experiment changes routing more than edge;
- the current AI wrapper must not be treated as evidence that AI adds value;
- successful take-profit trades do not prove that entry selection is sound;
- the current five-minute frequency may amplify turnover and costs without sufficient predictive power.

## 4. Governing principles

### 4.1 Simple baselines first

A complex strategy or AI decision layer is retained only if it outperforms simpler alternatives under the same data, fees, slippage, position constraints, and evaluation protocol.

### 4.2 Export trades, do not scrape terminal tables

Research evidence must come from structured Freqtrade backtest exports and explicit manifests. Text-log parsing may be used only for diagnostics, never as the authoritative metric source.

### 4.3 Economic performance, not signal count

Optimization must target net risk-adjusted performance and robustness, not win rate, trade count, or gross return alone.

### 4.4 Costs are part of the strategy

Fees and slippage must be included in every promoted result. Turnover and cost sensitivity are first-class metrics.

### 4.5 Train, validation, and test remain separated

The final test set is evaluated once per frozen candidate. Failed test results may not be used to retune that same candidate and then be reported as untouched test evidence.

### 4.6 No moving thresholds after seeing results

Eligibility thresholds may change only through a prospective contract erratum committed before the affected test result is generated.

### 4.7 AI must prove incremental value

No LLM, FreqAI model, or learned router is promoted merely because it is more sophisticated. It must beat its deterministic parent baseline out of sample without hiding higher turnover, drawdown, or tail risk.

## 5. Reuse before build

C0 shall reuse mature Freqtrade capabilities where possible:

- `backtesting --export trades` and structured backtest result files;
- `--strategy-list` for common-data comparisons;
- `--fee` for explicit cost sensitivity;
- Hyperopt with deterministic `--random-state`;
- built-in Sharpe, Sortino, Calmar, profit/drawdown, and multi-metric loss functions;
- `lookahead-analysis`;
- `recursive-analysis`;
- backtest result analysis and enter/exit tag statistics;
- FreqAI only after deterministic baselines establish a valid target and evaluation protocol.

A custom component is justified only when the official tool cannot produce the required evidence or when the repository needs an exact machine-readable contract around that evidence.

## 6. Initial research universe

### 6.1 Trading constraints

C0 remains:

- spot;
- long-only;
- no leverage;
- no derivatives;
- no private OKX API;
- no live execution;
- one position per pair unless a later experiment explicitly declares otherwise.

### 6.2 Pairs

The minimum research universe is:

- `BTC/USDT`;
- `ETH/USDT`;
- `SOL/USDT`.

A strategy may be specialized, but specialization must be declared before test evaluation. A candidate cannot be described as general if it only survives on one pair.

### 6.3 Timeframes

Use:

- `5m` as the legacy control;
- `15m` as a medium-frequency candidate;
- `1h` as a lower-turnover candidate.

The first implementation must compare timeframes before assuming five-minute trading is desirable.

### 6.4 Historical coverage

The research dataset must cover at least eighteen months and include multiple observable market conditions. The exact pair/timeframe/date coverage and missing-data statistics must be written into the run manifest.

The protocol must support longer history without changing its schema.

## 7. Walk-forward protocol

The initial default is an anchored or rolling walk-forward with:

- training window: 6 months;
- validation window: 3 months;
- test window: 3 months;
- step: 3 months.

These durations are configuration, not hard-coded strategy assumptions.

For every fold:

1. parameters are fit or selected using training data only;
2. validation chooses among frozen candidates from that training run;
3. the selected candidate is evaluated once on the fold's test data;
4. no future fold data is available to signal generation or parameter selection;
5. all fold boundaries are stored in the manifest.

A candidate with insufficient historical coverage is reported as `INSUFFICIENT_DATA`, not silently evaluated on a different universe.

## 8. Required baselines

The first implementation must compare at least:

1. HOLD / no trade;
2. buy and hold;
3. the frozen current `AISupervisedStrategy`;
4. EMA crossover with a volatility or trend-strength guard;
5. Donchian-style breakout;
6. RSI/Bollinger mean reversion with a higher-timeframe trend guard.

The deterministic baselines should be small and readable. They are not required to use the ATOS AI/provider layer.

The purpose is to determine whether any simple, reproducible edge exists before adding AI complexity.

## 9. Authoritative trade-level evidence

Each run must export a structured trade dataset containing, when available:

- run ID and candidate ID;
- source commit and config hashes;
- pair and timeframe;
- fold and train/validation/test role;
- open and close timestamps;
- entry and exit prices;
- stake and quantity;
- enter tag and exit reason;
- gross PnL;
- fees;
- modeled slippage;
- net PnL;
- duration;
- maximum favorable excursion (MFE);
- maximum adverse excursion (MAE);
- regime labels known at entry time;
- strategy candidate or router decision identity.

The analysis pipeline must read these structured exports instead of reconstructing trades from text tables.

## 10. Required metrics

At candidate, pair, timeframe, fold, and aggregate levels, report:

- net return;
- annualized return when statistically meaningful;
- maximum drawdown;
- return / drawdown ratio;
- Sharpe;
- Sortino;
- Calmar;
- profit factor;
- expectancy;
- mean-trade uncertainty or confidence interval;
- number of trades;
- turnover;
- average and distribution of duration;
- win rate;
- fee total;
- slippage total;
- contribution by pair;
- contribution by regime;
- contribution by enter tag;
- contribution by exit reason;
- MFE/MAE distributions;
- concentration of profit in the best fold, pair, day, and trade.

Buy-and-hold maximum drawdown must be computed from the equity path. Absolute return is not a drawdown proxy.

## 11. Cost and robustness matrix

Every promoted candidate must be evaluated under:

- expected fee and slippage assumptions;
- 1.5x expected total trading cost;
- 2x expected total trading cost.

Also require:

- lookahead analysis PASS;
- recursive analysis with no material startup-period instability;
- exact static pair universe per run;
- no result cache for authoritative runs;
- deterministic seeds for Hyperopt or model training;
- complete config and data manifests.

A strategy that is profitable only at zero or unrealistically low cost is rejected.

## 12. Hyperparameter optimization rules

Hyperopt is permitted only after the candidate's economic hypothesis and parameter space are documented.

Rules:

- optimize on training data only;
- use a deterministic random state;
- use a minimum-trade requirement;
- use a risk-aware loss such as multi-metric, profit/drawdown, Sharpe, Sortino, or Calmar;
- prohibit optimization directly against the final test set;
- store the complete search space and selected parameters;
- compare the optimized candidate with its default-parameter version;
- reject isolated optimum points with no stable neighboring region;
- cap epochs and search-space size prospectively to control compute cost.

Hyperopt is a search tool, not evidence of out-of-sample profitability.

## 13. Initial paper-eligibility thresholds

These thresholds determine whether a candidate may proceed to sustained Paper/Shadow evaluation. They do not authorize Live.

A candidate must satisfy all of the following on aggregated untouched test folds:

1. net return after expected costs is positive;
2. median fold net return is positive;
3. profit factor is at least `1.10`;
4. maximum drawdown is no greater than `15%` and is not worse than the relevant buy-and-hold control;
5. return/drawdown is better than buy-and-hold;
6. the candidate remains non-negative under `1.5x` costs;
7. no single pair contributes more than `70%` of total profit unless the strategy was prospectively declared pair-specific;
8. no single fold contributes more than `60%` of total profit;
9. at least two pairs or two distinct market regimes produce positive net contribution;
10. lookahead and recursive analyses pass;
11. the result has enough trades for the selected statistical method and does not rely on one outlier trade.

A candidate failing any condition remains a research candidate. It may be redesigned, but its failed test evidence remains preserved.

## 14. AI incremental-value protocol

AI evaluation begins only after at least one deterministic candidate reaches paper eligibility.

The deterministic candidate is the parent baseline. The AI layer may initially perform only one narrowly defined role:

- regime routing;
- abstention / cost-aware trade filtering;
- position sizing within frozen risk limits; or
- candidate ranking.

For the same underlying candidate signals, compare:

1. deterministic parent;
2. AI-disabled control;
3. AI-enabled candidate;
4. randomized or naive router control where useful.

AI is retained only if untouched out-of-sample evidence shows a meaningful improvement in risk-adjusted net performance without unacceptable increases in turnover, drawdown, concentration, or operational failure.

The current `MockProvider` remains a plumbing test, not an AI performance baseline.

## 15. Work packages

### C0A — Trade-level diagnostic foundation

Deliver:

- authoritative Freqtrade trade export ingestion;
- correct buy-and-hold equity and drawdown calculation;
- per-trade MFE/MAE and exit-path diagnostics;
- machine-readable run manifest;
- reproduction of the frozen `-16.12%` canonical result within declared numeric tolerance.

No new strategy optimization is permitted in C0A.

### C0B — Deterministic baseline matrix

Deliver:

- the required simple baselines;
- three pairs and three timeframes where data is available;
- expected, 1.5x, and 2x cost cases;
- structured comparison report;
- explicit candidate rejection reasons.

### C0C — Walk-forward and train-only Hyperopt

Deliver:

- configurable folds;
- train-only optimization;
- validation selection;
- untouched test evaluation;
- reproducible seed and parameter artifacts;
- robustness and concentration analysis.

### C0D — AI incremental test

Begin only if C0C produces at least one paper-eligible deterministic candidate.

### C0E — Sustained Paper/Shadow validation

Begin only if C0D or the deterministic parent remains eligible. Paper/Shadow results must be compared with contemporaneous backtest expectations and execution-cost assumptions.

## 16. Test and CI policy

C0 must not make every code PR run the entire research universe.

Use three levels:

### Fast PR checks

- parser and schema unit tests;
- metric vector tests;
- tiny synthetic trade fixtures;
- targeted strategy smoke test;
- ordinary full Python test suite;
- secret scan.

### Candidate research run

Triggered manually or by an explicit strategy-candidate label/workflow input:

- data coverage check;
- baseline/candidate matrix;
- train/validation/test folds;
- expected-cost and stress-cost cases;
- lookahead and recursive analysis;
- structured artifacts.

### Phase freeze run

Run once for a final candidate and exact SHA. It includes the complete required research matrix and evidence summary.

Changing documentation, CI evidence helpers, persistence, or unrelated runtime code must not automatically launch the full research matrix.

## 17. Authorized implementation surface

Expected implementation areas for C0A–C0C include:

- `implementation/src/atos/evaluation/` or a comparably narrow evaluation package;
- `implementation/scripts/` research runners;
- `implementation/freqtrade_data/strategies/` deterministic research baselines;
- `implementation/tests/` targeted metric, manifest, split, and leakage tests;
- a dedicated manually triggered research workflow;
- machine-readable report schemas and artifact manifests.

Changes to B4/B5 execution, persistence, idempotency, recovery, or paper adapter contracts are forbidden unless an independently reviewed defect proves they are necessary.

## 18. Explicit non-goals

C0 does not:

- authorize Live;
- add private OKX API access;
- add leverage, futures, swaps, or options;
- claim guaranteed profitability;
- tune the final test set;
- promote a strategy based on one pair or one favorable window without a prospective specialization declaration;
- accept an LLM narrative as performance evidence;
- replace Freqtrade capabilities with custom code without a documented gap;
- preserve the current AI wrapper if a simpler strategy is superior.

## 19. Promotion decisions

At the end of every work package, the valid decisions are:

- `REJECTED` — no credible edge or invalid evidence;
- `RESEARCH_ONLY` — promising but below threshold or insufficient data;
- `PAPER_ELIGIBLE` — all C0 thresholds pass;
- `SHADOW_ELIGIBLE` — paper behavior remains consistent and operationally stable;
- `LIVE_ELIGIBLE_FOR_SEPARATE_DESIGN` — evidence justifies beginning an independent Live design review.

No C0 result can directly enable Live.

## 20. External references to reuse

Official Freqtrade documentation:

- Backtesting and structured exports: <https://www.freqtrade.io/en/stable/backtesting/>
- Hyperopt: <https://www.freqtrade.io/en/stable/hyperopt/>
- Lookahead analysis: <https://www.freqtrade.io/en/stable/lookahead-analysis/>
- Recursive analysis: <https://www.freqtrade.io/en/stable/recursive-analysis/>
- FreqAI: <https://www.freqtrade.io/en/stable/freqai-running/>

Research hypotheses, not implementation mandates:

- Bysik and Ślepaczuk, *Machine Learning-Based Bitcoin Trading Under Transaction Costs: Evidence From Walk-Forward Forecasting* (2026), emphasizing cost-aware filtering and walk-forward evaluation.
- Begušić and Kostanjčar, *Momentum and liquidity in cryptocurrencies* (2019), motivating liquidity-aware momentum tests.
- Wood, Roberts, and Zohren, *Slow Momentum with Fast Reversion* (2021), motivating explicit regime/changepoint tests rather than fixed unconditional strategy routing.

Any borrowed method must be independently reproduced on the repository's own data and cost assumptions.

## 21. Freeze condition

C0 V1 becomes frozen only after a design-only PR confirms:

- one-file design scope;
- consistency with frozen B4/B5 safety contracts;
- no Live or private API expansion;
- explicit test-cost separation;
- explicit strategy rejection rules;
- explicit evidence that AI complexity must earn its place.

**LIVE FORBIDDEN.**
