# References and Design Influences

This file summarizes public ideas that influenced this specification. It is not an endorsement of any particular trading result.

## Public AI autonomous trading directions

### 1. Direct LLM trading experiments

Public experiments where LLM agents receive market information and emit trading decisions are useful for observing behavior, but they frequently expose weaknesses:

- inconsistent performance,
- excessive turnover,
- weak risk control,
- fragile decision loops,
- possible overconfidence,
- poor reproducibility.

Design implication: direct LLM trading should be a controlled module, not the whole system.

### 2. Alpha Arena / Nof1-style real-money competitions

These experiments show what happens when multiple AI models trade with real or competition capital. The important lesson is not simply who won a short contest; it is that model choice, leverage, turnover, fees, and risk discipline dominate outcomes.

Design implication: the system needs fee modeling, leverage restrictions, risk limits, and audit logs.

### 3. Claude / ChatGPT-assisted trading bots

Some traders use LLMs to build and improve bots, reduce emotional execution, and generate code. In most serious examples, the LLM is not the unrestricted exchange controller; it is inside a toolchain.

Design implication: use AI for reasoning, coding, review, and strategy selection; use deterministic code for execution discipline.

### 4. Crypto-native AI assistants such as Nansen AI

Crypto has special data advantages: on-chain flows, smart-money behavior, funding rates, open interest, orderbook data, and social signals.

Design implication: the Data Layer should eventually include chain and sentiment signals, not only OHLCV.

### 5. Multi-agent trading architectures

A trading system can separate roles:

- market analyst,
- strategy selector,
- risk critic,
- execution planner,
- review agent.

Design implication: the AI Decision Layer should support multiple agents, but all decisions still pass deterministic risk controls.

### 6. Traditional quant validation

Backtesting alone is insufficient. The system should support:

- chronological replay,
- out-of-sample validation,
- walk-forward validation,
- parameter perturbation,
- Monte Carlo,
- fee/slippage stress testing,
- regime analysis.

Design implication: Evaluation Layer is mandatory, not optional.

### 7. Finance LLM bias and look-ahead risk

General LLMs may know historical events or accidentally reason with future information. Financial LLM evaluation must consider look-ahead, survivorship, objective, narrative, and cost biases.

Design implication: historical replay must feed only point-in-time packets, and model outputs must be compared against baselines.

## Useful URLs to review manually

- https://www.reuters.com/commentary/breakingviews/early-ai-investor-returns-earn-average-human-grade-2025-11-07/
- https://www.axios.com/2025/09/25/nansen-ai-crypto-trading-chatbot
- https://arxiv.org/abs/2512.02261
- https://arxiv.org/abs/2601.13770
- https://arxiv.org/abs/2602.14233
- https://arxiv.org/abs/2605.19337
- https://www.reuters.com/world/agentic-ai-may-require-regulatory-reform-boes-breeden-says-2026-06-30/

## Warning

Short-term public examples of AI trading profits do not prove durable edge. This system is designed to test, audit, and control autonomy before scaling capital.
