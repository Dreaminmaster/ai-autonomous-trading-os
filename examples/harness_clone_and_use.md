# Harness Clone and Use Guide

## Step 1: Clone

```bash
git clone https://github.com/Dreaminmaster/ai-autonomous-trading-os.git
cd ai-autonomous-trading-os
```

## Step 2: Read in order

Harness should read:

1. `AGENTS.md`
2. `README.md`
3. `docs/00_overview.md`
4. `docs/09_mvp_plan.md`
5. `tests/safety_tests.md`

Do not load all files into long-term prompt. Load relevant files for the current task.

## Step 3: Produce implementation plan

Harness should output:

- intended implementation repository path,
- file structure,
- phase plan,
- safety assumptions,
- no-live-trading confirmation,
- tests to run.

## Step 4: First implementation task

Recommended first task:

```text
Implement the project scaffold, schema validation, risk policy loader, and paper execution skeleton. Do not implement live OKX order placement yet.
```

## Step 5: Provider setup

If model providers are needed, implement a provider manager. Do not hard-code providers into trading scripts.

Minimum natural language provider switching can be supported later:

- "use DeepSeek Pro for this task"
- "switch back to Anges"
- "use Anges by default"

## Step 6: Secret handling

Never paste secrets into Harness chat.

Use local environment variables or a local secret file outside Git:

```bash
export DEEPSEEK_API_KEY="..."
export OKX_API_KEY="..."
export OKX_API_SECRET="..."
export OKX_API_PASSPHRASE="..."
```

Implementation should also support a local ignored file such as:

```text
~/.hermes/secrets/.env
```

## Step 7: Completion report

Every implementation phase should end with:

- files changed,
- tests run,
- safety checks,
- known limitations,
- next recommended step.
