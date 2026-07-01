# Implementation Run Guide

This directory contains the current product source implementation.

Run from repository root:

```bash
cd implementation
python -m pip install -e '.[dev]'
python python/cli.py status
python python/cli.py risk
python python/cli.py cycle
pytest
```

Expected behavior:

- default mode is paper
- strategy pool generates candidates
- decision layer emits structured intent
- risk engine approves or rejects
- paper executor simulates result
- ledger writes runtime records
- production boundary is disabled by default

Do not put real API keys into Git.
