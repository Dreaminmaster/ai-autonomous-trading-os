"""C0C validation shortlist selection and gated development orchestration."""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c0c_walk_forward import (
    C0CWalkForwardError,
    build_development_report,
    write_report_files,
)

COSTS = {1.0, 1.5, 2.0}
GATE = {
    "require_positive_expected_net": True,
    "require_nonnegative_1_5x_net": True,
    "minimum_profit_factor": 1.10,
    "maximum_drawdown_ratio": 0.15,
}
RANKING_POLICY = [
    "validation_return_drawdown_desc",
    "validation_1_5x_return_desc",
    "validation_profit_factor_desc",
    "validation_drawdown_asc",
    "training_loss_asc",
    "training_epoch_asc",
    "candidate_id_asc",
]


def _num(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise C0CWalkForwardError(f"{label} must be numeric")
    result = float(value)
    if not float("-inf") < result < float("inf"):
        raise C0CWalkForwardError(f"{label} must be finite")
    return result


def _candidate_rows(
    rows: Sequence[Mapping[str, Any]], *, fold_id: str, candidate_id: str
) -> dict[float, Mapping[str, Any]]:
    by_cost: dict[float, Mapping[str, Any]] = {}
    hashes: set[str] = set()
    epochs: set[int] = set()
    losses: set[float] = set()
    for row in rows:
        if str(row.get("fold_id")) != fold_id or row.get("role") != "validation":
            raise C0CWalkForwardError("validation row identity mismatch")
        if str(row.get("candidate_id")) != candidate_id:
            raise C0CWalkForwardError("validation candidate identity mismatch")
        if row.get("fee_binding", {}).get("verified") is not True:
            raise C0CWalkForwardError("validation fee binding missing")
        cost = _num(row.get("cost_multiplier"), "cost_multiplier")
        if cost in by_cost:
            raise C0CWalkForwardError(f"duplicate validation cost: {cost}")
        by_cost[cost] = row
        digest = row.get("params_sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise C0CWalkForwardError("validation parameter hash invalid")
        hashes.add(digest)
        epochs.add(int(row.get("training_epoch")))
        losses.add(_num(row.get("training_loss"), "training_loss"))
    if set(by_cost) != COSTS:
        raise C0CWalkForwardError(f"validation cost coverage mismatch: {sorted(by_cost)}")
    if len(hashes) != 1 or len(epochs) != 1 or len(losses) != 1:
        raise C0CWalkForwardError("validation parameter lineage mismatch")
    return by_cost


def evaluate_candidate_validation(
    *, rows: Sequence[Mapping[str, Any]], config: Mapping[str, Any], fold_id: str,
    candidate_id: str
) -> dict[str, Any]:
    if not fold_id or not candidate_id:
        raise C0CWalkForwardError("fold_id and candidate_id must be non-empty")
    if config.get("validation_gate") != GATE:
        raise C0CWalkForwardError("validation_gate drift")
    by_cost = _candidate_rows(rows, fold_id=fold_id, candidate_id=candidate_id)
    expected, stress = by_cost[1.0], by_cost[1.5]
    reasons: list[str] = []
    if _num(expected.get("net_profit_abs"), "expected net") <= 0:
        reasons.append("VALIDATION_NET_RETURN_NOT_POSITIVE")
    if _num(stress.get("net_profit_abs"), "1.5x net") < 0:
        reasons.append("VALIDATION_NEGATIVE_AT_1_5X_COST")
    if _num(expected.get("profit_factor"), "expected PF") < 1.10:
        reasons.append("VALIDATION_PROFIT_FACTOR_BELOW_1_10")
    if _num(expected.get("max_drawdown_ratio"), "expected DD") > 0.15:
        reasons.append("VALIDATION_DRAWDOWN_ABOVE_15_PERCENT")
    drawdown = max(_num(expected.get("max_drawdown_ratio"), "expected DD"), 1e-12)
    return {
        "schema_version": 2,
        "fold_id": fold_id,
        "candidate_id": candidate_id,
        "eligible": not reasons,
        "rejection_reasons": reasons,
        "params_sha256": str(expected["params_sha256"]),
        "training_epoch": int(expected["training_epoch"]),
        "training_loss": _num(expected["training_loss"], "training_loss"),
        "metrics": {
            "expected_net_profit_abs": _num(expected.get("net_profit_abs"), "expected net"),
            "expected_net_return_ratio": _num(expected.get("net_return_ratio"), "expected return"),
            "expected_profit_factor": _num(expected.get("profit_factor"), "expected PF"),
            "expected_max_drawdown_ratio": _num(expected.get("max_drawdown_ratio"), "expected DD"),
            "expected_return_drawdown_ratio": _num(expected.get("net_return_ratio"), "expected return") / drawdown,
            "stress_1_5x_net_profit_abs": _num(stress.get("net_profit_abs"), "1.5x net"),
            "stress_1_5x_net_return_ratio": _num(stress.get("net_return_ratio"), "1.5x return"),
        },
    }


def _ranking_key(decision: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = decision["metrics"]
    return (
        -_num(metrics["expected_return_drawdown_ratio"], "return/drawdown"),
        -_num(metrics["stress_1_5x_net_return_ratio"], "1.5x return"),
        -_num(metrics["expected_profit_factor"], "profit factor"),
        _num(metrics["expected_max_drawdown_ratio"], "drawdown"),
        _num(decision["training_loss"], "training loss"),
        int(decision["training_epoch"]),
        str(decision["candidate_id"]),
    )


def select_fold_candidate(
    *, decisions: Sequence[Mapping[str, Any]], config: Mapping[str, Any], fold_id: str
) -> dict[str, Any]:
    if config.get("hyperopt", {}).get("selection_policy") != "top_loss_shortlist_validation_rank_v1":
        raise C0CWalkForwardError("selection policy drift")
    expected_size = int(config.get("hyperopt", {}).get("shortlist_size", 0))
    if len(decisions) != expected_size:
        raise C0CWalkForwardError(
            f"fold {fold_id} shortlist decision count {len(decisions)} != {expected_size}"
        )
    ids = {str(item.get("candidate_id")) for item in decisions}
    if len(ids) != len(decisions) or any(str(item.get("fold_id")) != fold_id for item in decisions):
        raise C0CWalkForwardError("fold shortlist identity mismatch")
    eligible = [dict(item) for item in decisions if item.get("eligible") is True]
    selected = min(eligible, key=_ranking_key) if eligible else None
    rejection_reasons = [] if selected else [
        f"{item['candidate_id']}:{reason}"
        for item in sorted(decisions, key=lambda row: str(row["candidate_id"]))
        for reason in item["rejection_reasons"]
    ]
    return {
        "schema_version": 2,
        "fold_id": fold_id,
        "selection_policy": "top_loss_shortlist_validation_rank_v1",
        "ranking_policy": RANKING_POLICY,
        "selected": selected is not None,
        "selected_candidate_id": selected["candidate_id"] if selected else None,
        "selected_params_sha256": selected["params_sha256"] if selected else None,
        "selected_training_epoch": selected["training_epoch"] if selected else None,
        "selected_training_loss": selected["training_loss"] if selected else None,
        "rejection_reasons": rejection_reasons,
        "candidate_decisions": sorted(map(dict, decisions), key=lambda item: str(item["candidate_id"])),
    }


def build_validation_rejection_report(
    *, rows: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any]
) -> dict[str, Any]:
    folds = {str(item["id"]) for item in config["folds"]}
    if {str(item.get("fold_id")) for item in decisions} != folds:
        raise C0CWalkForwardError("validation decision fold coverage mismatch")
    rejected = [item for item in decisions if item.get("selected") is False]
    if not rejected:
        raise C0CWalkForwardError("validation rejection report requires rejection")
    expected_rows = len(folds) * int(config["hyperopt"]["shortlist_size"]) * len(COSTS)
    if len(rows) != expected_rows:
        raise C0CWalkForwardError(
            f"validation-only evidence row count {len(rows)} != {expected_rows}"
        )
    seen: set[tuple[str, str, float]] = set()
    for row in rows:
        key = (str(row.get("fold_id")), str(row.get("candidate_id")), float(row.get("cost_multiplier")))
        if row.get("role") != "validation" or key in seen:
            raise C0CWalkForwardError("validation-only evidence coverage mismatch")
        seen.add(key)
    return {
        "schema_version": 2,
        "candidate_id": config["candidate_id"],
        "live": "FORBIDDEN",
        "holdout_state": "HOLDOUT_CLOSED",
        "development_test_opened": False,
        "development_economic_pass": False,
        "status": "REJECTED",
        "next_required": None,
        "rejection_reasons": [
            f"FOLD_{item['fold_id']}:{reason}"
            for item in rejected for reason in item["rejection_reasons"]
        ],
        "validation_decisions": sorted(map(dict, decisions), key=lambda item: item["fold_id"]),
        "rows": sorted(
            map(dict, rows),
            key=lambda row: (row["fold_id"], row["candidate_id"], row["cost_multiplier"]),
        ),
    }


def write_validation_rejection_files(
    report: Mapping[str, Any], *, json_path: str | Path, markdown_path: str | Path
) -> None:
    target = Path(json_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(target)
    lines = [
        "# C0C Validation Gate", "", "- Status: `REJECTED`",
        "- Development test: `NOT OPENED`", "- Holdout: `HOLDOUT_CLOSED`",
        "- LIVE: `FORBIDDEN`", "", "| Fold | Selected | Candidate | Reasons |", "|---|---|---|---|",
    ]
    for item in report["validation_decisions"]:
        lines.append(
            f"| {item['fold_id']} | {item['selected']} | "
            f"{item['selected_candidate_id'] or 'none'} | "
            f"{', '.join(item['rejection_reasons']) or 'none'} |"
        )
    Path(markdown_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _manifest(
    core: Any, config: dict[str, Any], runtime: Path, report: Path,
    artifacts: list[dict[str, Any]], decisions: list[dict[str, Any]],
    *, version: Mapping[str, Any], startup: Mapping[str, Any], all_validation_rows: Sequence[Mapping[str, Any]],
) -> None:
    files = sorted(path for path in core.DATA_DIR.rglob("*") if path.is_file())
    source_sha = os.environ.get("C0C_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
    payload = {
        "schema_version": 3,
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "workflow_sha": os.environ.get("GITHUB_SHA", "local"),
        "source_head_sha": source_sha,
        "generated_at": datetime.now(UTC).isoformat(),
        "candidate_id": config["candidate_id"],
        "live": "FORBIDDEN",
        "holdout_state": "HOLDOUT_CLOSED",
        "development_test_opened": all(item["selected"] for item in decisions),
        "freqtrade_version": dict(version),
        "startup_analysis": dict(startup),
        "config": {"path": str(core.CONFIG_PATH), "sha256": core.sha256_file(core.CONFIG_PATH)},
        "runtime_config": {"path": str(runtime), "sha256": core.sha256_file(runtime)},
        "strategy": {"path": str(core.STRATEGY_PATH), "sha256": core.sha256_file(core.STRATEGY_PATH)},
        "source_files": [
            {"path": str(path), "sha256": core.sha256_file(path)}
            for path in [
                Path("../.github/workflows/c0c-cost-aware-ema.yml"),
                core.CONFIG_PATH,
                core.STRATEGY_PATH,
                Path("pyproject.toml"),
                Path("scripts/c0c_development_core.py"),
                Path("scripts/run_c0c_development.py"),
                Path("src/atos/c0c_validation_gate.py"),
                Path("src/atos/c0c_walk_forward.py"),
                Path("tests/test_c0c_strategy_contract.py"),
                Path("tests/test_c0c_validation_gate.py"),
                Path("tests/test_c0c_walk_forward.py"),
            ]
        ],
        "plan": {
            "path": "../docs/architecture/phase-c/C0C_COST_AWARE_EMA_PLAN_V1.md",
            "sha256": core.sha256_file("../docs/architecture/phase-c/C0C_COST_AWARE_EMA_PLAN_V1.md"),
        },
        "fold_artifacts": artifacts,
        "validation_decisions": decisions,
        "all_validation_rows": list(map(dict, all_validation_rows)),
        "data_files": [{"path": str(path), "sha256": core.sha256_file(path)} for path in files],
        "report": {"path": str(report), "sha256": core.sha256_file(report)},
    }
    (core.RESULTS / "c0c_development_manifest.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )


def run_gated_development(core: Any) -> int:
    config = json.loads(core.CONFIG_PATH.read_text(encoding="utf-8"))
    core.validate_config(config)
    if core.RESULTS.exists():
        core.shutil.rmtree(core.RESULTS)
    core.RESULTS.mkdir(parents=True)
    runtime = core.prepare_runtime_config(config["pairs"])
    version = core.capture_freqtrade_version()
    startup = core.run_startup_analysis(config=config, runtime_config=runtime)

    all_validation_rows: list[dict[str, Any]] = []
    fold_decisions: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    selected_by_fold: dict[str, tuple[dict[str, Any], Path, dict[str, Any], list[dict[str, Any]]]] = {}

    for fold in config["folds"]:
        fid = fold["id"]
        folder = core.RESULTS / f"fold_{fid}"
        folder.mkdir()
        candidates, hyperopt_evidence = core.run_hyperopt(
            fold=fold, config=config, runtime_config=runtime, fold_dir=folder
        )
        candidate_decisions: list[dict[str, Any]] = []
        rows_by_candidate: dict[str, list[dict[str, Any]]] = {}
        for candidate in candidates:
            current = [
                core.run_backtest(
                    fold_id=fid, role="validation",
                    start=fold["validation_start"], end=fold["validation_end"],
                    multiplier=float(cost), config=config, runtime_config=runtime,
                    fold_dir=folder, candidate=candidate,
                )
                for cost in config["fee_multipliers"]
            ]
            all_validation_rows.extend(current)
            rows_by_candidate[str(candidate["candidate_id"])] = current
            candidate_decisions.append(evaluate_candidate_validation(
                rows=current, config=config, fold_id=fid,
                candidate_id=str(candidate["candidate_id"]),
            ))
        fold_decision = select_fold_candidate(
            decisions=candidate_decisions, config=config, fold_id=fid
        )
        decision_path = folder / "validation_selection.json"
        decision_path.write_text(json.dumps(fold_decision, indent=2, sort_keys=True), encoding="utf-8")
        fold_decisions.append(fold_decision)
        if fold_decision["selected"]:
            selected_id = str(fold_decision["selected_candidate_id"])
            selected_candidate = next(item for item in candidates if str(item["candidate_id"]) == selected_id)
            selected_by_fold[fid] = (
                fold, folder, selected_candidate, rows_by_candidate[selected_id]
            )
        artifacts.append({
            **hyperopt_evidence,
            "fold_id": fid,
            "validation_selection": str(decision_path),
            "validation_selection_sha256": core.sha256_file(decision_path),
            "candidate_decisions": candidate_decisions,
        })

    report_path = core.RESULTS / "c0c_development_report.json"
    markdown_path = core.RESULTS / "c0c_development_report.md"
    if all(item["selected"] for item in fold_decisions):
        rows: list[dict[str, Any]] = []
        buy_hold: dict[str, dict[str, Any]] = {}
        for fid in sorted(selected_by_fold):
            fold, folder, candidate, selected_validation_rows = selected_by_fold[fid]
            rows.extend(selected_validation_rows)
            rows.extend(
                core.run_backtest(
                    fold_id=fid, role="development_test",
                    start=fold["test_start"], end=fold["test_end"],
                    multiplier=float(cost), config=config, runtime_config=runtime,
                    fold_dir=folder, candidate=candidate,
                )
                for cost in config["fee_multipliers"]
            )
            buy_hold[fid] = core.fold_buy_hold(
                start=fold["test_start"], end=fold["test_end"],
                pairs=config["pairs"], timeframe=config["timeframe"],
            )
        report = build_development_report(
            rows=rows, config=config, buy_hold_by_fold=buy_hold,
            analysis_status={"lookahead": "NOT_RUN", "recursive": "PASS"},
        )
        write_report_files(report, json_path=report_path, markdown_path=markdown_path)
    else:
        report = build_validation_rejection_report(
            rows=all_validation_rows, decisions=fold_decisions, config=config
        )
        write_validation_rejection_files(
            report, json_path=report_path, markdown_path=markdown_path
        )

    core.PARAM_PATH.unlink(missing_ok=True)
    _manifest(
        core, config, runtime, report_path, artifacts, fold_decisions,
        version=version, startup=startup, all_validation_rows=all_validation_rows,
    )
    net = report.get("aggregate", {}).get("net_return_ratio")
    net_text = f"{float(net):.2%}" if isinstance(net, (int, float)) else "not-opened"
    print(
        f"C0C development complete: status={report['status']} net={net_text} "
        f"reasons={report['rejection_reasons']} HOLDOUT_CLOSED"
    )
    return 0
