#!/usr/bin/env python3
"""Run C0C with fail-closed adapters for current Freqtrade research output."""
from __future__ import annotations

import csv
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Sequence

from atos.c0c_walk_forward import C0CWalkForwardError


def _finite(value: Any, label: str) -> float:
    try:
        result = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError) as exc:
        raise C0CWalkForwardError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C0CWalkForwardError(f"{label} must be finite")
    return result


def _integer(value: Any, label: str) -> int:
    text = str(value).strip()
    match = re.fullmatch(r"([0-9]+)(?:\.0+)?", text)
    if not match:
        raise C0CWalkForwardError(f"{label} must be an integer")
    return int(match.group(1))


def parse_hyperopt_csv_output(
    path: str | Path, *, shortlist_size: int, min_trades: int
) -> list[dict[str, Any]]:
    """Select the deterministic top-loss shortlist from Freqtrade's official CSV export.

    Freqtrade leaves ``Objective`` blank for epochs rejected by ``--min-trades``.
    Parse and apply the frozen trade-count eligibility rule before requiring a
    numeric objective; eligible epochs still fail closed on blank/malformed loss.
    """
    source = Path(path)
    try:
        with source.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            required = {"Epoch", "Trades", "Objective"}
            if not required.issubset(fieldnames):
                raise C0CWalkForwardError(
                    f"hyperopt CSV missing columns: {sorted(required - fieldnames)}"
                )
            records: dict[int, dict[str, Any]] = {}
            for row_number, row in enumerate(reader, start=2):
                epoch = _integer(row.get("Epoch"), f"hyperopt CSV row {row_number} Epoch")
                trades = _integer(row.get("Trades"), f"hyperopt CSV row {row_number} Trades")
                if trades < min_trades:
                    continue
                loss = _finite(row.get("Objective"), f"hyperopt CSV row {row_number} Objective")
                if loss >= 100000:
                    continue
                candidate = {"epoch": epoch, "loss": loss}
                existing = records.get(epoch)
                if existing is not None and existing != candidate:
                    raise C0CWalkForwardError(f"conflicting hyperopt epoch {epoch}")
                records[epoch] = candidate
    except OSError as exc:
        raise C0CWalkForwardError(f"unable to read hyperopt CSV: {exc}") from exc

    if len(records) < shortlist_size:
        raise C0CWalkForwardError(
            f"hyperopt shortlist requires {shortlist_size} eligible epochs, found {len(records)}"
        )
    return sorted(records.values(), key=lambda item: (item["loss"], item["epoch"]))[
        :shortlist_size
    ]


def discover_official_hyperopt_result_file(directory: str | Path) -> Path:
    """Resolve the single authoritative Freqtrade result via its official pointer.

    Freqtrade 2026.6 writes both a ``strategy_*.fthypt`` result and the
    non-authoritative ``hyperopt_tickerdata.pkl`` cache. The official
    ``.last_result.json`` pointer identifies the result that downstream
    ``hyperopt-list`` and ``hyperopt-show`` must consume.
    """
    result_dir = Path(directory)
    pointer = result_dir / ".last_result.json"
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C0CWalkForwardError(
            f"unable to read official hyperopt result pointer {pointer}: {exc}"
        ) from exc

    latest = payload.get("latest_hyperopt")
    if not isinstance(latest, str) or not latest.strip():
        raise C0CWalkForwardError("official hyperopt result pointer missing latest_hyperopt")
    latest = latest.strip()
    latest_path = Path(latest)
    if latest_path.name != latest or latest_path.suffix.lower() != ".fthypt":
        raise C0CWalkForwardError(
            f"official hyperopt result pointer is unsafe or unsupported: {latest!r}"
        )

    result_file = result_dir / latest
    if not result_file.is_file():
        raise C0CWalkForwardError(
            f"official hyperopt result pointer target is missing: {result_file}"
        )

    result_files = sorted(path for path in result_dir.glob("*.fthypt") if path.is_file())
    if result_files != [result_file]:
        raise C0CWalkForwardError(
            "expected exactly one authoritative .fthypt result matching the official "
            f"pointer, found {[path.name for path in result_files]}"
        )
    return result_file


def _rich_cells(line: str) -> list[str]:
    normalized = line.replace("┃", "|").replace("│", "|")
    if "|" not in normalized:
        return []
    return [cell.strip() for cell in normalized.strip().strip("|").split("|")]


def validate_recursive_analysis_log(
    path: str | Path,
    *,
    startup_count: int,
    required_indicators: Sequence[str],
    max_variance_pct: float,
) -> dict[str, Any]:
    """Parse Freqtrade 2026.6 Rich recursive output using its emission semantics.

    Freqtrade only emits indicators present in ``DataFrame.compare()``. Therefore
    a required indicator omitted from the table, or represented by ``-`` at the
    selected startup column, is explicit zero observed recursive variance rather
    than missing evidence. The exact selected startup column and the no-lookahead
    marker remain mandatory, and malformed or excessive numeric values fail closed.
    """
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise C0CWalkForwardError(f"unable to read recursive analysis log: {exc}") from exc

    if any("=> found lookahead in indicator" in line for line in lines):
        raise C0CWalkForwardError("recursive analysis reported indicator lookahead")
    if not any("No lookahead bias on indicators found." in line for line in lines):
        raise C0CWalkForwardError("recursive analysis missing no-lookahead proof")

    header_index: int | None = None
    startup_column: int | None = None
    for index, line in enumerate(lines):
        cells = _rich_cells(line)
        if not cells or cells[0].lower() != "indicators":
            continue
        for column, cell in enumerate(cells):
            if re.match(rf"^{re.escape(str(startup_count))}(?:\s|\(|$)", cell):
                header_index = index
                startup_column = column
                break
        if header_index is not None:
            break
    if header_index is None or startup_column is None:
        raise C0CWalkForwardError(
            f"recursive analysis table/header missing startup column {startup_count}"
        )

    table_values: dict[str, str] = {}
    for line in lines[header_index + 1 :]:
        cells = _rich_cells(line)
        if not cells:
            if table_values:
                break
            continue
        if len(cells) <= startup_column:
            continue
        indicator = cells[0]
        if not indicator or indicator.lower() == "indicators":
            continue
        raw = cells[startup_column].strip()
        existing = table_values.get(indicator)
        if existing is not None and existing != raw:
            raise C0CWalkForwardError(
                f"conflicting recursive rows for indicator {indicator}"
            )
        table_values[indicator] = raw

    required = list(dict.fromkeys(str(item) for item in required_indicators))
    if not required:
        raise C0CWalkForwardError("recursive analysis required indicators are empty")

    observed: dict[str, float] = {}
    evidence_basis: dict[str, str] = {}
    omitted_as_zero: list[str] = []
    dashed_as_zero: list[str] = []

    for indicator in required:
        if indicator not in table_values:
            observed[indicator] = 0.0
            evidence_basis[indicator] = "NOT_EMITTED_BY_FREQTRADE_NO_RECURSIVE_DIFFERENCE"
            omitted_as_zero.append(indicator)
            continue

        raw = table_values[indicator]
        if not raw or "nan" in raw.lower():
            raise C0CWalkForwardError(
                f"recursive analysis {indicator} is not calculable at {startup_count}"
            )
        if raw == "-":
            variance = 0.0
            evidence_basis[indicator] = "DASH_NO_RECORDED_DIFFERENCE_AT_SELECTED_STARTUP"
            dashed_as_zero.append(indicator)
        else:
            try:
                variance = abs(float(raw.rstrip("%").replace(",", "")))
            except ValueError as exc:
                raise C0CWalkForwardError(
                    f"invalid recursive variance for {indicator}: {raw!r}"
                ) from exc
            evidence_basis[indicator] = "NUMERIC_RICH_TABLE_VALUE"

        if variance > max_variance_pct:
            raise C0CWalkForwardError(
                f"recursive variance {indicator}={variance}% exceeds {max_variance_pct}%"
            )
        observed[indicator] = variance

    return {
        "status": "PASS",
        "startup_candle_count": startup_count,
        "max_variance_pct": max_variance_pct,
        "output_semantics": "FREQTRADE_2026_6_ONLY_DIFFERING_INDICATORS_EMITTED",
        "lookahead_status": "PASS",
        "indicator_variance_pct": dict(sorted(observed.items())),
        "indicator_evidence_basis": dict(sorted(evidence_basis.items())),
        "omitted_as_zero_variance": sorted(omitted_as_zero),
        "dash_as_zero_variance": sorted(dashed_as_zero),
    }


def _run_startup_analysis(
    core: Any, *, config: dict[str, Any], runtime_config: Path
) -> dict[str, Any]:
    startup = config["startup_analysis"]
    pair_reports: list[dict[str, Any]] = []
    for pair in startup["pairs"]:
        slug = pair.replace("/", "_")
        log_path = core.RESULTS / f"recursive_analysis_{slug}.log"
        command_path = core.RESULTS / f"recursive_analysis_{slug}.command.json"
        command = [
            "freqtrade",
            "recursive-analysis",
            "--config",
            str(runtime_config),
            "--userdir",
            "freqtrade_data",
            "--datadir",
            str(core.DATA_DIR),
            "--strategy-path",
            "freqtrade_data/strategies",
            "--strategy",
            config["strategy"],
            "--pairs",
            pair,
            "--timeframe",
            config["timeframe"],
            "--timerange",
            startup["timerange"],
            "--startup-candle",
            *[str(value) for value in startup["startup_candidates"]],
            "--no-color",
        ]
        core.run(command, log_path, command_path)
        parsed = validate_recursive_analysis_log(
            log_path,
            startup_count=int(startup["selected_startup_candles"]),
            required_indicators=startup["required_indicators"],
            max_variance_pct=float(startup["max_variance_pct"]),
        )
        parsed["pair"] = pair
        pair_reports.append(
            {
                "pair": pair,
                "log_path": str(log_path),
                "log_sha256": core.sha256_file(log_path),
                "command_path": str(command_path),
                "command_sha256": core.sha256_file(command_path),
                "result": parsed,
            }
        )
    report = {
        "status": "PASS",
        "startup_candle_count": int(startup["selected_startup_candles"]),
        "max_variance_pct": float(startup["max_variance_pct"]),
        "pairs": pair_reports,
    }
    report_path = core.RESULTS / "recursive_analysis_report.json"
    core._write_json(report_path, report)
    return {
        "report_path": str(report_path),
        "report_sha256": core.sha256_file(report_path),
        "result": report,
    }


def _run_hyperopt(
    core: Any,
    *,
    fold: dict[str, Any],
    config: dict[str, Any],
    runtime_config: Path,
    fold_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    core.clean_hyperopt_outputs()
    hyper = config["hyperopt"]
    log_path = fold_dir / "hyperopt.log"
    command_path = fold_dir / "hyperopt.command.json"
    command = [
        "freqtrade",
        "hyperopt",
        "--config",
        str(runtime_config),
        "--userdir",
        "freqtrade_data",
        "--datadir",
        str(core.DATA_DIR),
        "--strategy-path",
        "freqtrade_data/strategies",
        "--strategy",
        config["strategy"],
        "--pairs",
        *config["pairs"],
        "--timeframe",
        config["timeframe"],
        "--timerange",
        core.timerange(fold["train_start"], fold["train_end"]),
        "--fee",
        str(hyper["fee_rate"]),
        "--spaces",
        hyper["space"],
        "--epochs",
        str(hyper["epochs"]),
        "--random-state",
        str(hyper["random_state"]),
        "--min-trades",
        str(hyper["min_trades"]),
        "--hyperopt-loss",
        hyper["loss"],
        "--job-workers",
        str(hyper["workers"]),
        "--disable-param-export",
        "--no-color",
    ]
    core.run(command, log_path, command_path)
    result_file = discover_official_hyperopt_result_file(core.HYPEROPT_RESULTS)

    list_log = fold_dir / "hyperopt_list.log"
    list_csv = fold_dir / "hyperopt_epochs.csv"
    list_command = fold_dir / "hyperopt_list.command.json"
    core.run(
        [
            "freqtrade",
            "hyperopt-list",
            "--config",
            str(runtime_config),
            "--userdir",
            "freqtrade_data",
            "--hyperopt-filename",
            result_file.name,
            "--export-csv",
            str(list_csv),
            "--no-details",
            "--no-color",
        ],
        list_log,
        list_command,
    )
    shortlist = parse_hyperopt_csv_output(
        list_csv,
        shortlist_size=int(hyper["shortlist_size"]),
        min_trades=int(hyper["min_trades"]),
    )

    shortlist_dir = fold_dir / "shortlist"
    shortlist_dir.mkdir()
    candidates: list[dict[str, Any]] = []
    for rank, item in enumerate(shortlist, start=1):
        epoch = int(item["epoch"])
        candidate_id = f"rank_{rank:02d}_epoch_{epoch}"
        show_log = shortlist_dir / f"{candidate_id}.hyperopt_show.json"
        show_command = shortlist_dir / f"{candidate_id}.hyperopt_show.command.json"
        core.PARAM_PATH.unlink(missing_ok=True)
        core.run(
            [
                "freqtrade",
                "hyperopt-show",
                "--config",
                str(runtime_config),
                "--userdir",
                "freqtrade_data",
                "--hyperopt-filename",
                result_file.name,
                "--index",
                str(epoch),
                "--print-json",
                "--no-header",
                "--no-color",
            ],
            show_log,
            show_command,
        )
        if not core.PARAM_PATH.is_file():
            raise SystemExit(
                f"hyperopt-show epoch {epoch} did not export {core.PARAM_PATH}"
            )
        core.validate_parameter_file(core.PARAM_PATH)
        params_copy = shortlist_dir / f"{candidate_id}.params.json"
        shutil.copy2(core.PARAM_PATH, params_copy)
        candidates.append(
            {
                "candidate_id": candidate_id,
                "rank": rank,
                "training_epoch": epoch,
                "training_loss": float(item["loss"]),
                "params_path": params_copy,
                "params_sha256": core.sha256_file(params_copy),
                "show_log_path": str(show_log),
                "show_log_sha256": core.sha256_file(show_log),
                "show_command_path": str(show_command),
                "show_command_sha256": core.sha256_file(show_command),
            }
        )

    hyper_copy = fold_dir / "hyperopt_results"
    shutil.copytree(core.HYPEROPT_RESULTS, hyper_copy)
    official_files = [
        {"path": str(path), "sha256": core.sha256_file(path)}
        for path in sorted(hyper_copy.rglob("*"))
        if path.is_file()
    ]
    shortlist_path = fold_dir / "shortlist.json"
    core._write_json(
        shortlist_path,
        [
            {
                key: (str(value) if isinstance(value, Path) else value)
                for key, value in item.items()
            }
            for item in candidates
        ],
    )
    evidence = {
        "fold_id": fold["id"],
        "hyperopt_log": str(log_path),
        "hyperopt_log_sha256": core.sha256_file(log_path),
        "hyperopt_command": str(command_path),
        "hyperopt_command_sha256": core.sha256_file(command_path),
        "hyperopt_list_log": str(list_log),
        "hyperopt_list_log_sha256": core.sha256_file(list_log),
        "hyperopt_list_csv": str(list_csv),
        "hyperopt_list_csv_sha256": core.sha256_file(list_csv),
        "hyperopt_list_command": str(list_command),
        "hyperopt_list_command_sha256": core.sha256_file(list_command),
        "shortlist": str(shortlist_path),
        "shortlist_sha256": core.sha256_file(shortlist_path),
        "official_hyperopt_result_files": official_files,
    }
    return candidates, evidence


def install_freqtrade_output_compat(core: Any) -> None:
    """Bind the authoritative runner to parsers matching current Freqtrade output."""
    core.run_startup_analysis = lambda **kwargs: _run_startup_analysis(core, **kwargs)
    core.run_hyperopt = lambda **kwargs: _run_hyperopt(core, **kwargs)


def main() -> int:
    import c0c_development_core as core
    from atos.c0c_validation_gate import run_gated_development

    install_freqtrade_output_compat(core)
    return run_gated_development(core)


if __name__ == "__main__":
    raise SystemExit(main())
