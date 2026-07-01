# 07 Review and Strategy Evolution Layer

## Purpose

The Review Layer turns trade history into controlled learning.

The AI should not merely write a narrative review. Reviews must produce structured findings that can affect strategy diagnostics and weights through approved rules.

## Review cadence

Required review jobs:

- per-trade review,
- daily review,
- weekly review,
- monthly review,
- incident review after large loss,
- strategy promotion/demotion review.

## Per-trade review

After a trade closes, record:

- original thesis,
- evidence used,
- selected strategy,
- expected scenario,
- actual outcome,
- reason for exit,
- PnL,
- whether stop/take-profit worked,
- whether the thesis was correct,
- lesson learned.

## Daily review

Questions:

1. Which strategies made money?
2. Which strategies lost money?
3. Which AI reasons were valid?
4. Which AI reasons were unsupported?
5. Were losses due to strategy, execution, slippage, fees, or regime change?
6. Should any strategy be paused?
7. Should risk state change tomorrow?

## Weekly/monthly review

Questions:

- Are strategy weights improving risk-adjusted performance?
- Which market regimes are favorable?
- Which symbols are consistently poor?
- Are fees consuming too much edge?
- Is the AI overtrading?
- Are exits worse than entries?
- Are lessons repeating without improvement?

## Structured review output

Reviews should follow `schemas/trade_review.schema.json`.

Key fields:

- trade_id
- strategy_ids
- outcome
- pnl
- thesis_quality
- execution_quality
- risk_quality
- regime
- lesson
- recommended_action
- strategy_weight_delta_suggestion

## Strategy scoring

Each strategy gets scores by regime:

- return score
- drawdown penalty
- stability score
- trade-count confidence
- fee-efficiency score
- review-quality score
- recency weight

## Strategy weight updates

Weight updates should be formula-based and bounded.

Example controls:

- max weight increase per day: 5%
- max weight decrease per day: 10%
- minimum evidence trades before promotion: 30
- minimum paper-trading days before live: 14
- hard pause after max drawdown breach

## Candidate strategy generation

The AI may propose new strategies.

A new strategy proposal must include:

- hypothesis,
- data needed,
- entry rule,
- exit rule,
- risk rule,
- expected market regime,
- failure conditions,
- test plan.

It cannot become active until it passes the Evaluation Layer.

## Memory update rules

Memory entries must include:

- timestamp,
- source trade/review IDs,
- confidence,
- expiration or recency decay,
- applicable regimes,
- applicable strategies.

Bad lessons should not become permanent rules without repeated evidence.

## Avoiding self-confirmation

The AI reviewer must look for:

- cherry-picking,
- hindsight rationalization,
- overfitting explanations,
- blaming execution when strategy was wrong,
- ignoring fees,
- ignoring missed exits,
- repeating the same failed thesis.

## Output of review layer

The layer produces:

- review reports,
- strategy score table,
- strategy weight proposal,
- paused strategies,
- candidate strategy backlog,
- risk policy proposals.

Only approved non-risk weight changes may be applied automatically. Risk policy changes require human approval.
