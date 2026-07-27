# C7A synthetic evidence review V1

## Scope

This change completes the current synthetic-only C7A implementation boundary with a physically separate aggregate reviewer and a deterministic retained-evidence package builder.

It authorizes no real OKX data, network access, partial prospective performance, economic run, C7B read, account access, paper, shadow, private API, or live execution.

## Physically separate reviewer

The reviewer imports neither the C7A producer nor the C7A contract module. It independently freezes and recomputes:

- the exact 26-week Monday decision grid;
- all three cost labels and one-side cost rates;
- all three non-selectable comparator identities;
- candidate weekly accounting, funding receipts/payments, traded notional, costs, turnover, activity, orientation, completeness, and 169-point hourly equity paths;
- comparator weekly equity and hourly paths;
- first-half, second-half, and aggregate returns;
- hourly-path maximum drawdown;
- weekly Sharpe, probabilistic Sharpe ratio, and BTC beta;
- carry attribution, carry-only stress, turnover, activity, and concentration;
- every frozen C7A selection gate.

It then compares its complete candidate aggregates, comparator aggregates, and decision with the producer outputs using exact key-set checks and bounded numeric equality. Producer or retained-evidence tampering returns reviewer `FAIL`.

## Evidence package

The package builder requires the exact synthetic metadata boundary, all three candidate cost streams, and all three comparator streams. It creates a new output directory only once and retains:

- synthetic metadata;
- candidate rows for `1.0x`, `1.5x`, and `2.0x` costs;
- rows for cash, always-on funding rank, and equal-notional funding rank comparators;
- producer candidate aggregates;
- producer comparator aggregates;
- producer decision;
- physically separate independent review;
- a complete SHA-256 and byte-size manifest covering every non-manifest file.

Existing output is rejected rather than overwritten.

## Validation

Focused deterministic tests verify:

- producer and independent reviewer agreement on a complete synthetic package;
- detection of a tampered producer aggregate;
- exact manifest path, size, and SHA-256 coverage;
- rejection of real-data boundary drift;
- rejection of an incomplete comparator set;
- rejection of output-directory reuse.

Applicable merge gate is ordinary CI. Freqtrade Validation is not applicable because no Freqtrade strategy, real market-data path, or execution runtime is changed.

The next boundary is planning for prospective data custody. No data collection or economic execution is authorized by this change.

`C7A_SYNTHETIC_IMPLEMENTATION_COMPLETE` / `INDEPENDENT_REVIEW_PRESENT` / `NO_REAL_DATA` / `NO_ECONOMIC_RUN` / `C7B_CLOSED` / `PAPER_CLOSED` / `SHADOW_CLOSED` / `LIVE_FORBIDDEN`
