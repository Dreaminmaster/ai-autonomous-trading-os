from __future__ import annotations

import ast
from pathlib import Path


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "freqtrade_data"
    / "strategies"
    / "c0b_baselines.py"
)


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _classes() -> dict[str, ast.ClassDef]:
    return {
        node.name: node
        for node in _tree().body
        if isinstance(node, ast.ClassDef)
    }


def _assigned_names(node: ast.ClassDef) -> dict[str, ast.expr]:
    result: dict[str, ast.expr] = {}
    for child in node.body:
        if isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = child.value
    return result


def test_exact_baseline_classes_exist() -> None:
    classes = _classes()
    assert {
        "C0BEMATrend",
        "C0BDonchianBreakout",
        "C0BMeanReversion",
    }.issubset(classes)


def test_every_baseline_uses_freqtrade_stoploss_attribute() -> None:
    for name in ("C0BEMATrend", "C0BDonchianBreakout", "C0BMeanReversion"):
        assignments = _assigned_names(_classes()[name])
        assert "stoploss" in assignments
        assert "stop_loss" not in assignments
        value = ast.literal_eval(assignments["stoploss"])
        assert -0.10 < value < 0


def test_signal_methods_are_vectorized() -> None:
    for class_node in _classes().values():
        for function in [
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef)
            and node.name.startswith("populate_")
        ]:
            forbidden = [
                node
                for node in ast.walk(function)
                if isinstance(node, (ast.For, ast.While))
            ]
            assert forbidden == [], f"{class_node.name}.{function.name} contains a loop"


def test_mean_reversion_has_higher_timeframe_guard() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert '{"5m": "1h", "15m": "4h", "1h": "4h"}' in source
    assert "merge_informative_pair" in source
    assert "htf_trend_ok" in source


def test_baselines_do_not_import_atos_provider_or_live_execution() -> None:
    source = SOURCE.read_text(encoding="utf-8").lower()
    assert "providermanager" not in source
    assert "private okx" not in source
    assert "dry_run = false" not in source
    assert "requests." not in source
