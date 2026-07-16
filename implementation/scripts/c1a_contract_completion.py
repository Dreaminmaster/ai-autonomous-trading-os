#!/usr/bin/env python3
"""Complete and independently verify the frozen C1A evidence contract."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
os.chdir(IMPL)
RESULTS = Path("freqtrade_data/backtest_results/c1a_family_screen")
REPORT_JSON = RESULTS / "c1a_family_screen_report.json"
REPORT_MD = RESULTS / "c1a_family_screen_report.md"
MANIFEST_PATH = RESULTS / "c1a_family_screen_manifest.json"
FINAL_PATH = RESULTS / "c1a_final_evidence.json"
SOURCE_INVENTORY_PATH = RESULTS / "c1a_source_inventory.json"
COMPLETION_INVENTORY_PATH = RESULTS / "c1a_contract_completion_inventory.json"
RUNTIME_CONFIG_PATH = Path("freqtrade_data/c1a_runtime/config.c1a.json")
C0C_RESULT_PATH = Path("../docs/architecture/phase-c/c0c/C0C_COST_AWARE_EMA_RESULT_V1.md")

C0C_CONTEXT = {
    "candidate": "c0c-cost-aware-ema-v1",
    "strategy": "C0CCostAwareEMA",
    "status": "REJECTED",
    "candidate_source_sha": "c93c548ed7d22c90fbc729dbb3022ee9e7c579c1",
    "merge_commit": "ba9b02d63ae8fb67b99307191b9e58cd014d8dd6",
    "workflow_run": "29472584256",
    "artifact_id": "8365664976",
    "artifact_digest": "sha256:8a88f7b2644406f84188a34184395b2c7d66a79c733b76db622c210591ad36c5",
    "selectable": False,
    "development_test_opened": False,
    "holdout_state": "HOLDOUT_CLOSED",
    "live": "FORBIDDEN",
}

SOURCE_PATHS = [
    Path("../.github/workflows/c1a-strategy-family-screen.yml"),
    Path("../docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_CONTRACT_V1.md"),
    C0C_RESULT_PATH,
    Path("pyproject.toml"),
    Path("config/c1a_strategy_family_screen.json"),
    Path("config/policy.validation.json"),
    Path("freqtrade_data/config.dryrun.json"),
    RUNTIME_CONFIG_PATH,
    Path("freqtrade_data/strategies/c1a_common.py"),
    Path("scripts/c0c_development_core.py"),
    Path("scripts/c1a_contract_completion.py"),
    Path("scripts/c1a_data_guard.py"),
    Path("scripts/c1a_evidence.py"),
    Path("scripts/c1a_source_inventory.py"),
    Path("scripts/finalize_c1a_evidence.py"),
    Path("scripts/run_c0c_development.py"),
    Path("scripts/setup_freqtrade.sh"),
    Path("scripts/validate_no_secrets.sh"),
    Path("src/atos/c0b_export.py"),
    Path("src/atos/c0c_walk_forward.py"),
    Path("src/atos/c1a_family_screen.py"),
    Path("src/atos/profitability_diagnostics.py"),
    Path("tests/test_c1a_contract_completion.py"),
    Path("tests/test_c1a_data_guard.py"),
    Path("tests/test_c1a_evidence_contract.py"),
    Path("tests/test_c1a_family_screen.py"),
    Path("tests/test_c1a_strategy_contract.py"),
]


class C1AContractCompletionError(RuntimeError):
    """Raised when the frozen comparator or effective source set is incomplete."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise C1AContractCompletionError(f"unreadable file {path}: {exc}") from exc


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C1AContractCompletionError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C1AContractCompletionError(f"{label} must contain an object")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def exact_source_sha() -> str:
    value = os.environ.get("C1A_SOURCE_SHA", "")
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise C1AContractCompletionError("C1A_SOURCE_SHA must be an exact lowercase commit SHA")
    return value


def frozen_c0c_context() -> dict[str, Any]:
    try:
        text = C0C_RESULT_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise C1AContractCompletionError(f"unable to read frozen C0C result: {exc}") from exc
    required_markers = (
        "Status: `REJECTED`",
        C0C_CONTEXT["candidate_source_sha"],
        C0C_CONTEXT["merge_commit"],
        C0C_CONTEXT["workflow_run"],
        C0C_CONTEXT["artifact_id"],
        C0C_CONTEXT["artifact_digest"],
        "development_test_opened = false",
        "holdout_state = HOLDOUT_CLOSED",
        "live = FORBIDDEN",
    )
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise C1AContractCompletionError(f"frozen C0C result marker mismatch: {missing}")
    return {
        **C0C_CONTEXT,
        "result_document_path": str(C0C_RESULT_PATH),
        "result_document_sha256": sha256_file(C0C_RESULT_PATH),
        "basis": "FROZEN_RESULT_DOCUMENT_NO_RERUN",
    }


def validate_runtime_config_payload(payload: Mapping[str, Any]) -> None:
    exchange = payload.get("exchange")
    api_server = payload.get("api_server")
    if payload.get("dry_run") is not True or payload.get("trading_mode") != "spot":
        raise C1AContractCompletionError("effective runtime config must remain spot dry-run")
    if not isinstance(exchange, Mapping) or exchange.get("name") != "okx":
        raise C1AContractCompletionError("effective runtime exchange drift")
    if exchange.get("pair_whitelist") != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C1AContractCompletionError("effective runtime pair universe drift")
    if any(exchange.get(key) not in ("", None) for key in ("key", "secret", "password")):
        raise C1AContractCompletionError("effective runtime config contains private credentials")
    if payload.get("max_open_trades") != 3:
        raise C1AContractCompletionError("effective runtime max_open_trades drift")
    if payload.get("stake_currency") != "USDT" or float(payload.get("stake_amount", -1)) != 300.0:
        raise C1AContractCompletionError("effective runtime stake drift")
    if float(payload.get("dry_run_wallet", -1)) != 1000.0:
        raise C1AContractCompletionError("effective runtime wallet drift")
    if float(payload.get("tradable_balance_ratio", -1)) != 1.0:
        raise C1AContractCompletionError("effective runtime balance ratio drift")
    if not isinstance(api_server, Mapping) or api_server.get("enabled") is not False:
        raise C1AContractCompletionError("effective runtime API server must remain disabled")
    if payload.get("force_entry_enable") is not False or payload.get("initial_state") != "stopped":
        raise C1AContractCompletionError("effective runtime execution state drift")


def source_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in SOURCE_PATHS:
        if not path.is_file():
            raise C1AContractCompletionError(f"effective source missing: {path}")
        rows.append({"path": str(path), "sha256": sha256_file(path)})
    return rows


def retained_rows() -> list[dict[str, str]]:
    return [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in sorted(RESULTS.rglob("*"))
        if path.is_file() and path != MANIFEST_PATH
    ]


def apply_completion() -> dict[str, Any]:
    source_sha = exact_source_sha()
    report = read_json(REPORT_JSON, "C1A report")
    manifest = read_json(MANIFEST_PATH, "C1A manifest")
    for payload, label in ((report, "report"), (manifest, "manifest")):
        if payload.get("source_head_sha") != source_sha:
            raise C1AContractCompletionError(f"{label} exact source binding mismatch")
        if payload.get("status") not in {"SELECTED", "REJECTED"}:
            raise C1AContractCompletionError(f"{label} lacks a valid economic classification")
        if payload.get("confirmation_opened") is not False:
            raise C1AContractCompletionError(f"{label} opened confirmation")
        if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
            raise C1AContractCompletionError(f"{label} safety state drift")

    runtime = read_json(RUNTIME_CONFIG_PATH, "effective C1A runtime config")
    validate_runtime_config_payload(runtime)
    c0c = frozen_c0c_context()
    comparators = report.get("comparators")
    if not isinstance(comparators, dict) or "hold_cash" not in comparators or "windows" not in comparators:
        raise C1AContractCompletionError("existing non-selectable comparators are incomplete")
    comparators["frozen_c0c"] = c0c
    report["comparators"] = comparators
    report["contract_completion_status"] = "PASS"
    write_json(REPORT_JSON, report)

    markdown = REPORT_MD.read_text(encoding="utf-8")
    marker = "## Frozen C0C historical comparator"
    if marker not in markdown:
        markdown += (
            "\n## Frozen C0C historical comparator\n\n"
            "- Candidate: `c0c-cost-aware-ema-v1`\n"
            "- Status: `REJECTED`\n"
            "- Selectable: `false`\n"
            "- Basis: frozen result document only; no rerun and no stale-SHA reuse.\n"
            "- Development-test opened: `false`\n"
            "- Holdout: `HOLDOUT_CLOSED`\n"
            "- Live: `FORBIDDEN`\n"
        )
    REPORT_MD.write_text(markdown, encoding="utf-8")

    sources = source_rows()
    completion_inventory = {
        "schema_version": 1,
        "status": "PASS",
        "stage": "C1A",
        "source_head_sha": source_sha,
        "frozen_c0c_context": c0c,
        "effective_runtime_config": {
            "path": str(RUNTIME_CONFIG_PATH),
            "sha256": sha256_file(RUNTIME_CONFIG_PATH),
            "validated": True,
        },
        "source_files": sources,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    write_json(COMPLETION_INVENTORY_PATH, completion_inventory)

    manifest["report_sha256"] = sha256_file(REPORT_JSON)
    manifest["report_markdown_sha256"] = sha256_file(REPORT_MD)
    manifest["source_files"] = sources
    manifest["effective_runtime_config"] = completion_inventory["effective_runtime_config"]
    manifest["frozen_c0c_context"] = c0c
    manifest["contract_completion_inventory"] = {
        "path": str(COMPLETION_INVENTORY_PATH),
        "sha256": sha256_file(COMPLETION_INVENTORY_PATH),
    }
    manifest["retained_result_files"] = retained_rows()
    write_json(MANIFEST_PATH, manifest)
    print("C1A contract completion apply PASS: frozen C0C comparator and effective sources bound")
    return manifest


def verify_hash_rows(rows: Any, label: str) -> int:
    if not isinstance(rows, list) or not rows:
        raise C1AContractCompletionError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise C1AContractCompletionError(f"{label}[{index}] must be an object")
        path = row.get("path")
        digest = row.get("sha256")
        if not isinstance(path, str) or path in seen:
            raise C1AContractCompletionError(f"{label}[{index}] path invalid or duplicated")
        seen.add(path)
        if not isinstance(digest, str) or sha256_file(path) != digest:
            raise C1AContractCompletionError(f"{label}[{index}] hash mismatch: {path}")
    return len(rows)


def verify_source_inventory(source_sha: str) -> dict[str, Any]:
    inventory = read_json(SOURCE_INVENTORY_PATH, "C1A source inventory")
    if inventory.get("status") != "PASS" or inventory.get("source_head_sha") != source_sha:
        raise C1AContractCompletionError("source inventory status/source mismatch")
    if inventory.get("holdout_state") != "HOLDOUT_CLOSED" or inventory.get("live") != "FORBIDDEN":
        raise C1AContractCompletionError("source inventory safety state mismatch")
    rows = inventory.get("files")
    if not isinstance(rows, list) or not rows:
        raise C1AContractCompletionError("source inventory files missing")
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise C1AContractCompletionError(f"source inventory row {index} invalid")
        source = ROOT / str(row.get("path", ""))
        snapshot = IMPL / str(row.get("snapshot_path", ""))
        digest = sha256_file(source)
        if digest != row.get("source_sha256"):
            raise C1AContractCompletionError(f"source inventory source hash mismatch: {source}")
        if sha256_file(snapshot) != row.get("snapshot_sha256") or sha256_file(snapshot) != digest:
            raise C1AContractCompletionError(f"source inventory snapshot mismatch: {snapshot}")
    return inventory


def verify_completion() -> dict[str, Any]:
    source_sha = exact_source_sha()
    report = read_json(REPORT_JSON, "C1A report")
    manifest = read_json(MANIFEST_PATH, "C1A manifest")
    final = read_json(FINAL_PATH, "C1A final evidence")
    completion = read_json(COMPLETION_INVENTORY_PATH, "C1A completion inventory")
    expected_c0c = frozen_c0c_context()

    if report.get("source_head_sha") != source_sha or manifest.get("source_head_sha") != source_sha:
        raise C1AContractCompletionError("report/manifest exact source mismatch")
    if report.get("comparators", {}).get("frozen_c0c") != expected_c0c:
        raise C1AContractCompletionError("frozen C0C comparator mismatch")
    if manifest.get("frozen_c0c_context") != expected_c0c:
        raise C1AContractCompletionError("manifest frozen C0C context mismatch")
    runtime = read_json(RUNTIME_CONFIG_PATH, "effective C1A runtime config")
    validate_runtime_config_payload(runtime)
    runtime_binding = manifest.get("effective_runtime_config")
    if not isinstance(runtime_binding, Mapping) or runtime_binding.get("path") != str(RUNTIME_CONFIG_PATH):
        raise C1AContractCompletionError("effective runtime config binding missing")
    if runtime_binding.get("sha256") != sha256_file(RUNTIME_CONFIG_PATH):
        raise C1AContractCompletionError("effective runtime config hash mismatch")

    expected_sources = source_rows()
    if manifest.get("source_files") != expected_sources or completion.get("source_files") != expected_sources:
        raise C1AContractCompletionError("effective source inventory mismatch")
    source_count = verify_hash_rows(expected_sources, "effective source files")
    if completion.get("source_head_sha") != source_sha or completion.get("status") != "PASS":
        raise C1AContractCompletionError("completion inventory status/source mismatch")
    if completion.get("holdout_state") != "HOLDOUT_CLOSED" or completion.get("live") != "FORBIDDEN":
        raise C1AContractCompletionError("completion inventory safety state mismatch")
    if manifest.get("contract_completion_inventory", {}).get("sha256") != sha256_file(COMPLETION_INVENTORY_PATH):
        raise C1AContractCompletionError("completion inventory hash is not bound")

    source_inventory = verify_source_inventory(source_sha)
    if final.get("status") != "PASS" or final.get("source_head_sha") != source_sha:
        raise C1AContractCompletionError("final evidence status/source mismatch")
    if final.get("economic_status") != report.get("status"):
        raise C1AContractCompletionError("final economic classification mismatch")
    if final.get("manifest_sha256") != sha256_file(MANIFEST_PATH):
        raise C1AContractCompletionError("final manifest hash mismatch")
    if final.get("report_sha256") != sha256_file(REPORT_JSON):
        raise C1AContractCompletionError("final report hash mismatch")
    if final.get("holdout_state") != "HOLDOUT_CLOSED" or final.get("live") != "FORBIDDEN":
        raise C1AContractCompletionError("final evidence safety state mismatch")
    if final.get("errors") not in ([], None):
        raise C1AContractCompletionError("final evidence contains errors")

    checks = list(final.get("checks", []))
    additions = [
        "contract:frozen_c0c_comparator_bound",
        "contract:effective_runtime_config_bound",
        f"contract:effective_sources_{source_count}_bound",
        "contract:source_inventory_snapshot_verified",
        "contract:completion_inventory_bound",
    ]
    for item in additions:
        if item not in checks:
            checks.append(item)
    final.update(
        {
            "contract_completion_status": "PASS",
            "frozen_c0c_context": expected_c0c,
            "effective_runtime_config": dict(runtime_binding),
            "source_inventory_path": str(SOURCE_INVENTORY_PATH),
            "source_inventory_sha256": sha256_file(SOURCE_INVENTORY_PATH),
            "source_inventory_files": len(source_inventory["files"]),
            "contract_completion_inventory_path": str(COMPLETION_INVENTORY_PATH),
            "contract_completion_inventory_sha256": sha256_file(COMPLETION_INVENTORY_PATH),
            "checks": checks,
            "checks_passed": len(checks),
            "errors": [],
        }
    )
    write_json(FINAL_PATH, final)
    print(
        "C1A contract completion verify PASS: frozen comparator, runtime config, "
        f"{source_count} effective sources, and source snapshots bound"
    )
    return final


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("apply", "verify"))
    args = parser.parse_args()
    if args.mode == "apply":
        apply_completion()
    else:
        verify_completion()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
