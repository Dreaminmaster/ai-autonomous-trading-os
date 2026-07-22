#!/usr/bin/env python3
"""Validate the final C6A authoritative execution-entrypoint contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping

from atos.c6a_contract import C6AError
from atos.c6a_execution_contract_v2 import validate_execution_contract_v2
from atos.c6a_evidence import write_json_atomic

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = IMPL / "config/c6a_execution_contract_v2.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_execution_guard_v2.json"


class C6AExecutionGuardV2Error(RuntimeError):
    pass


def verify(path: Path = DEFAULT_CONTRACT) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AExecutionGuardV2Error(
            f"invalid C6A execution contract V2: {exc}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise C6AExecutionGuardV2Error(
            "C6A execution contract V2 must be an object"
        )
    try:
        digest = validate_execution_contract_v2(
            payload, implementation_root=IMPL
        )
    except C6AError as exc:
        raise C6AExecutionGuardV2Error(str(exc)) from exc
    return {
        "schema_version": 2,
        "stage": "C6A",
        "status": "PASS",
        "execution_contract_canonical_sha256": digest,
        "authoritative_entrypoint_count": len(payload["authoritative_entrypoints"]),
        "required_order": payload["required_order"],
        "non_authoritative_scaffolds": payload["non_authoritative_scaffolds"],
        "economic_result_run": False,
        "confirmation_opened": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = verify(args.contract)
    write_json_atomic(args.output, report)
    print(
        "C6A execution guard V2 PASS: "
        f"{report['authoritative_entrypoint_count']} frozen steps"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
