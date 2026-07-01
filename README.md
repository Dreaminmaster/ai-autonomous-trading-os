# OKX AI Autonomous Trading OS

> Product source + specification repository for building an engineering-grade AI autonomous trading system for OKX.

This repository now contains both:

1. a full system specification under `docs/`, `schemas/`, `configs/`, `prompts/`, and `tests/`;
2. a working Python implementation scaffold under `implementation/`.

The implementation is designed for controlled autonomy:

```text
strategy candidates
  -> decision layer
  -> structured trade intent
  -> deterministic risk engine
  -> paper executor
  -> ledger store
```

## Current runnable implementation

Run from repository root:

```bash
cd implementation
python -m pip install -e '.[dev]'
python python/cli.py status
python python/cli.py risk
python python/cli.py cycle
pytest
```

Implemented source files include:

```text
implementation/python/atos_core.py
implementation/python/models.py
implementation/python/strategy_pool.py
implementation/python/decision_layer.py
implementation/python/risk_engine.py
implementation/python/paper_executor.py
implementation/python/ledger_store.py
implementation/python/run_demo.py
implementation/python/cli.py
implementation/python/production_guard.py
implementation/config/policy.json
implementation/tests/test_core.py
```

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
  -> risk engine
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
implementation/                   # Runnable Python implementation scaffold
```

## Recommended Harness entry command

After cloning this repo, tell Harness:

```text
Clone the repo and run implementation/RUN.md.
Then run cd implementation && python python/cli.py status && python python/cli.py cycle && pytest.
Do not put API keys into code/logs/Git.
Continue implementing the remaining product modules from AGENTS.md and docs/09_mvp_plan.md.
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
