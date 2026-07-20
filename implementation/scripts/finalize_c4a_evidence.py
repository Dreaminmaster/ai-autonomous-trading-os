#!/usr/bin/env python3
"""Execute the independently recomputed C4A evidence finalizer."""
from __future__ import annotations

import sys

try:
    from scripts.c4a_finalizer_core import C4AFinalizerError, main
except ModuleNotFoundError:  # pragma: no cover
    from c4a_finalizer_core import C4AFinalizerError, main  # type: ignore


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"C4A finalizer failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
