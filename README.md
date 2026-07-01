# OKX AI Autonomous Trading OS

> Specification repository for building an engineering-grade AI autonomous trading system for OKX.

This repository is **not** a live trading bot. It is a complete design/specification package for an agent such as Harness/Hermes/Codex to clone, read, and implement safely.

## Goal

Build an OKX AI Autonomous Trading OS where AI can:

- analyze markets,
- select strategies,
- generate structured trading decisions,
- review past trades,
- adjust strategy weights,
- propose new strategy candidates,
- and operate toward long-term autonomous profitability.

But the system must remain:

- engineering-grade,
- auditable,
- reproducible,
- backtestable,
- paper-tradable,
- risk-controlled,
- and impossible for the LLM to bypass deterministic safety gates.

## Non-goals

This repository does **not** authorize immediate live trading.

The system must not:

- place real orders before paper trading and validation,
- store API keys in code, Git, logs, reports, or prompts,
- use OKX API keys with withdrawal permissions,
- let an LLM call the exchange directly without a deterministic risk gate,
- auto-enable leverage, futures, swaps, or options without explicit human approval,
- claim or guarantee profits.

## Core architecture

```text
Data Layer
  -> Memory Layer
  -> Strategy Layer
  -> AI Decision Layer
  -> Deterministic Risk Layer
  -> Execution Layer
  -> Ledger / Audit Layer
  -> Evaluation Layer
  -> Review / Strategy Evolution Layer
  -> Governance Layer
```

The AI may decide what it wants to do, but every action must pass through deterministic Python controls.

```text
AI market reasoning
  -> structured trade_intent JSON
  -> schema validation
  -> risk_manager.py
  -> execution adapter
  -> ledger
  -> review loop
```

## Repository map

```text
AGENTS.md                         # Main instructions for Harness/Agent
README.md                         # This file
docs/                             # Full system design
schemas/                          # JSON schemas for agent outputs
configs/                          # Example config files without secrets
prompts/                          # Agent prompt templates
tests/                            # Acceptance and safety tests
examples/                         # How Harness should clone/read/use this spec
references/                       # External research and public examples summary
```

## Recommended Harness entry command

After cloning this repo, tell Harness:

```text
Read AGENTS.md, README.md, docs/00_overview.md, and docs/09_mvp_plan.md first.
Then produce an implementation plan for the OKX AI Autonomous Trading OS.
Do not trade. Do not use live OKX order APIs. Do not store API keys in code/logs/Git.
```

## Build philosophy

This system combines:

- LLM discretionary decision-making,
- multi-agent analysis,
- traditional quant strategy pools,
- crypto-native data such as funding/open interest/orderbook/on-chain signals,
- walk-forward and out-of-sample validation,
- paper trading,
- deterministic risk controls,
- and continuous AI review.

The intended result is not a simple script. It is a trading operating system with controlled autonomy.
