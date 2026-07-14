# C0B2 Prospective Low-Turnover Edge Reset V1

Status: **DESIGN CANDIDATE**  
Mode: **BACKTEST ONLY**  
Live: **FORBIDDEN**

## 1. Purpose

C0B produced a valid research platform and a valid negative result: none of the nine `strategy × timeframe` candidates survived. C0B2 freezes the next economic hypothesis before any further strategy code or test evaluation.

The objective is not to rescue the rejected C0B strategies by tuning the frozen test set. The objective is to test whether a sparse, low-turnover, cost-aware signal family can produce enough gross expectancy to remain positive after realistic fees.

## 2. Frozen C0B evidence

Authoritative candidate: `741f09debe11274b9af71bb1c00eda7a1ce79252`  
Matrix run: `29352209123`  
Artifact digest: `sha256:61778615a3f252dfc570c7edb94b87902bd7d423220aa1db6a1cfe72356a117b`

C0B result:

- 9 of 9 candidates rejected;
- every candidate net-negative at expected cost and 1.5x cost;
- every candidate below Profit Factor `1.10`;
- every candidate above the `15%` drawdown limit;
- no candidate had positive contribution from at least two pairs.

Best expected-cost results:

| Candidate | Net return | Profit factor | Max drawdown | Trades |
|---|---:|---:|---:|---:|
| `C0BEMATrend@5m` | -15.63% | 0.8852 | 18.01% | 538 |
| `C0BMeanReversion@1h` | -25.91% | 0.4475 | 30.07% | 107 |
| `C0BDonchianBreakout@1h` | -56.16% | 0.7736 | 63.03% | 732 |

Trade-level decomposition shows that several candidates had weak positive gross PnL but lost after turnover costs:

| Candidate | Approx. gross PnL | Fees | Net PnL |
|---|---:|---:|---:|
| `C0BEMATrend@5m` | +$329.40 | $485.72 | -$156.32 |
| `C0BMeanReversion@15m` | +$38.27 | $411.51 | -$373.24 |
| `C0BDonchianBreakout@15m` | +$92.35 | $994.90 | -$902.55 |

The evidence rejects continued five-minute and fifteen-minute high-turnover tuning. It also rejects direct promotion to C0C, Paper, Shadow, or Live.

## 3. Root hypothesis

The next candidate family shall test this falsifiable claim:

> A sparse event-driven strategy on `1h` and `4h`, with entry-time regime and volatility filters plus an explicit cost hurdle, can reduce turnover enough that gross expectancy remains positive after expected and stressed costs.

This is a new hypothesis family. It is not a parameter revision of the frozen C0B EMA, Donchian, or mean-reversion candidates.

## 4. Prospective research split

The C0B test interval remains frozen and may be used only as historical diagnosis.

C0B2 uses:

- development / training: `2023-11-01` through `2025-06-30`;
- untouched final test: `2025-07-01` through `2026-06-30`;
- warm-up data before each scored interval as required by indicators;
- pairs: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`;
- candidate timeframes: `1h`, `4h`;
- spot, long-only, no leverage, no derivatives.

The final test interval may be evaluated once per frozen candidate. A failed candidate cannot be retuned against that interval and reported as untouched evidence.

## 5. Candidate families

At most two small, readable families are permitted in the first C0B2 implementation.

### 5.1 Sparse trend continuation

Required characteristics:

- entry is a discrete event, not a continuously true sticky condition;
- higher-timeframe trend and volatility regime known at entry;
- minimum expected move or ATR distance must exceed a declared round-trip cost hurdle;
- cooldown or reset requirement prevents immediate re-entry after an exit;
- exit logic must be compatible with the entry horizon and cannot depend on a high-frequency crossover that repeatedly crystallizes small losses.

### 5.2 Volatility-compression breakout

Required characteristics:

- compression is measured before the breakout;
- breakout is based only on prior completed candles;
- volume or range expansion is optional but must be prospectively declared;
- entry is blocked when the expected move does not clear the cost hurdle;
- cooldown and one-position-per-pair remain mandatory.

Mean-reversion redesign is deferred. C0B showed that stop-loss losses dominated its positive ordinary exits, so it must not be revived in the first C0B2 implementation without a separate prospective hypothesis.

## 6. Parameter and search limits

Before any optimization, the implementation PR must declare:

- every parameter;
- its range or discrete values;
- the economic reason for the range;
- the maximum number of combinations or Hyperopt epochs;
- deterministic random state when optimization is used.

The first implementation should prefer a small deterministic grid. Hyperopt is allowed only on the development interval and only after the search space is committed.

No more than three frozen candidate specifications may be evaluated on the untouched final test in this hypothesis cycle.

## 7. Cost and turnover requirements

Every reported candidate must include:

- gross PnL before trading costs;
- fees and modeled slippage separately;
- net PnL;
- turnover;
- average gross expectancy per trade;
- average round-trip cost per trade;
- gross-expectancy-to-cost ratio;
- expected, 1.5x, and 2x cost cases.

A candidate cannot reach the final test unless its development/validation evidence shows:

1. positive gross expectancy;
2. positive net expectancy at expected cost;
3. non-negative result at 1.5x cost;
4. Profit Factor at least `1.10`;
5. maximum drawdown no greater than `15%`;
6. materially lower turnover than the rejected C0B candidates at the comparable horizon;
7. positive contribution from at least two pairs or a prospectively declared pair specialization.

## 8. Validation protocol

Reuse Freqtrade. Do not build another optimizer or backtester.

Required checks:

- structured trade export;
- exact config, data, strategy, source and result hashes;
- lookahead analysis;
- recursive analysis;
- no result cache for authoritative runs;
- development-only parameter selection;
- untouched final test evaluation;
- expected, 1.5x and 2x costs;
- pair, regime, exit-reason and trade-level attribution;
- MFE/MAE and profit concentration;
- comparison with HOLD, buy-and-hold and the frozen C0B controls.

## 9. Stop conditions

Stop this hypothesis cycle and do not keep tuning when any of the following occurs:

- all declared candidates have non-positive gross expectancy on development data;
- all candidates fail expected-cost profitability;
- the only apparent improvement comes from reducing assumed costs;
- performance depends on one pair, one short interval or one outlier trade without prospective specialization;
- neighboring parameter values collapse;
- the untouched test fails.

A stopped hypothesis is valid research output. The next action is a new economic hypothesis, not a wider parameter search on the failed test set.

## 10. Authorized implementation surface

C0B2 may change only narrow research areas:

- one C0B2 strategy file under `implementation/freqtrade_data/strategies/`;
- one prospective C0B2 configuration;
- one research runner or extension of the existing C0B runner;
- targeted metric, contract and leakage tests;
- one manually or explicit-candidate-triggered workflow;
- machine-readable artifacts.

Forbidden:

- B4/B5 execution, persistence, recovery or paper adapter changes;
- private OKX API;
- Live;
- leverage or derivatives;
- changes to the frozen C0B evidence;
- automatic full research runs for unrelated PRs.

## 11. Advancement rule

Only a C0B2 candidate satisfying the frozen C0 thresholds on the untouched final test may proceed to C0C walk-forward confirmation.

No deterministic survivor means:

- no AI incremental test;
- no Paper or Shadow promotion;
- no Live work.

**LIVE remains FORBIDDEN.**
