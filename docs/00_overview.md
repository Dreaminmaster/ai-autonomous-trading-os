# 00 Overview

## What this system is

The OKX AI Autonomous Trading OS is a controlled-autonomy trading platform. It is designed to let AI act as a trader, strategist, reviewer, and strategy allocator, while deterministic software enforces risk and execution discipline.

It is not a single strategy bot. It is a layered system.

## Core idea

```text
AI thinks. Python verifies. Risk manager decides whether execution is allowed. Ledger records everything.
```

The AI should never be the final safety authority.

## Why not direct LLM trading only?

Direct LLM trading experiments are useful, but public experiments and research show common failure modes:

- unstable performance across regimes,
- high turnover and fee drag,
- overconcentration,
- vulnerability to bad or perturbed inputs,
- weak execution semantics,
- unclear reproducibility,
- look-ahead and evaluation bias.

Therefore, the system includes AI autonomy but constrains it through schemas, evaluation, deterministic risk, and audit logs.

## Included design lines

This specification combines:

1. LLM direct trading experiments.
2. Alpha Arena / real-money AI trading competition style tests.
3. Claude / ChatGPT assisted trading bot workflows.
4. Chain-data and smart-money AI trading assistants.
5. Multi-agent trading teams.
6. Traditional quant systems.
7. Walk-forward, out-of-sample, paper trading, anti-overfitting, and anti-look-ahead validation.

## Main layers

1. Data Layer
2. Memory Layer
3. Strategy Layer
4. AI Decision Layer
5. Risk Layer
6. Execution Layer
7. Evaluation Layer
8. Review Layer
9. Governance Layer

## Default rollout

The rollout must be:

```text
design -> backtest -> paper -> shadow -> tiny live spot -> larger live only after evidence
```

Do not skip directly to live trading.

## Success definition

The system is successful only if it can show:

- reproducible backtests,
- walk-forward validation,
- realistic fees and slippage,
- stable paper trading,
- clear risk behavior,
- full auditability,
- strategy weight evolution,
- and no unsafe permissions.

Profit alone is not enough. A system that made money by overfitting, luck, excessive leverage, or hidden future information is a failed system.
