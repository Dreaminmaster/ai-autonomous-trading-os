from __future__ import annotations

from copy import deepcopy

import pytest

from atos.c0c_validation_gate import (
    build_validation_rejection_report,
    evaluate_candidate_validation,
    select_fold_candidate,
)
from atos.c0c_walk_forward import C0CWalkForwardError


def _config():
    return {
        "candidate_id": "c0c-cost-aware-ema-v1",
        "folds": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
        "hyperopt": {
            "shortlist_size": 3,
            "selection_policy": "top_loss_shortlist_validation_rank_v1",
        },
        "validation_gate": {
            "require_positive_expected_net": True,
            "require_nonnegative_1_5x_net": True,
            "minimum_profit_factor": 1.10,
            "maximum_drawdown_ratio": 0.15,
        },
    }


def _rows(
    fold="1", candidate="rank_01_epoch_1", epoch=1, loss=0.2,
    expected=10.0, stress=1.0, pf=1.2, dd=0.1,
):
    result = []
    for cost in (1.0, 1.5, 2.0):
        net = expected if cost == 1.0 else (stress if cost == 1.5 else stress - 1.0)
        result.append({
            "fold_id": fold,
            "role": "validation",
            "candidate_id": candidate,
            "cost_multiplier": cost,
            "params_sha256": str(epoch) * 64,
            "training_epoch": epoch,
            "training_loss": loss,
            "fee_binding": {"verified": True},
            "net_profit_abs": net,
            "net_return_ratio": net / 1000,
            "profit_factor": pf if cost == 1.0 else max(0.0, pf - 0.1),
            "max_drawdown_ratio": dd,
        })
    return result


def _candidate_decision(**kwargs):
    rows=_rows(**kwargs)
    return evaluate_candidate_validation(
        rows=rows,config=_config(),fold_id=str(kwargs.get("fold","1")),
        candidate_id=str(kwargs.get("candidate","rank_01_epoch_1")),
    )


def test_candidate_gate_accepts_only_cost_surviving_candidate():
    decision = _candidate_decision()
    assert decision["eligible"] is True
    assert decision["rejection_reasons"] == []


@pytest.mark.parametrize(
    "kwargs, reason",
    [
        ({"expected": -1.0}, "VALIDATION_NET_RETURN_NOT_POSITIVE"),
        ({"stress": -1.0}, "VALIDATION_NEGATIVE_AT_1_5X_COST"),
        ({"pf": 1.09}, "VALIDATION_PROFIT_FACTOR_BELOW_1_10"),
        ({"dd": 0.151}, "VALIDATION_DRAWDOWN_ABOVE_15_PERCENT"),
    ],
)
def test_candidate_gate_rejects_before_development_test(kwargs, reason):
    decision = _candidate_decision(**kwargs)
    assert decision["eligible"] is False
    assert reason in decision["rejection_reasons"]


def test_candidate_gate_requires_exact_cost_fee_and_parameter_lineage():
    rows = _rows()[:-1]
    with pytest.raises(C0CWalkForwardError, match="cost coverage"):
        evaluate_candidate_validation(rows=rows, config=_config(), fold_id="1", candidate_id="rank_01_epoch_1")
    rows = _rows()
    rows[-1]["params_sha256"] = "x" * 64
    with pytest.raises(C0CWalkForwardError, match="lineage"):
        evaluate_candidate_validation(rows=rows, config=_config(), fold_id="1", candidate_id="rank_01_epoch_1")
    rows = _rows()
    rows[-1]["fee_binding"]["verified"] = False
    with pytest.raises(C0CWalkForwardError, match="fee binding"):
        evaluate_candidate_validation(rows=rows, config=_config(), fold_id="1", candidate_id="rank_01_epoch_1")


def test_validation_gate_contract_drift_fails_closed():
    config = deepcopy(_config())
    config["validation_gate"]["minimum_profit_factor"] = 1.0
    with pytest.raises(C0CWalkForwardError, match="validation_gate drift"):
        evaluate_candidate_validation(
            rows=_rows(), config=config, fold_id="1", candidate_id="rank_01_epoch_1"
        )


def test_fold_selection_uses_validation_ranking_not_training_best():
    training_best=_candidate_decision(candidate="rank_01_epoch_1",epoch=1,loss=0.01,expected=10,stress=1,pf=1.2,dd=0.10)
    validation_best=_candidate_decision(candidate="rank_02_epoch_2",epoch=2,loss=0.02,expected=12,stress=2,pf=1.2,dd=0.08)
    third=_candidate_decision(candidate="rank_03_epoch_3",epoch=3,loss=0.03,expected=11,stress=1.5,pf=1.2,dd=0.09)
    selected=select_fold_candidate(decisions=[training_best,validation_best,third],config=_config(),fold_id="1")
    assert selected["selected"] is True
    assert selected["selected_candidate_id"] == "rank_02_epoch_2"
    assert selected["ranking_policy"][0] == "validation_return_drawdown_desc"


def test_fold_selection_rejects_when_no_shortlist_candidate_survives():
    decisions=[
        _candidate_decision(candidate=f"rank_0{i}_epoch_{i}",epoch=i,loss=float(i),expected=-1.0)
        for i in (1,2,3)
    ]
    selected=select_fold_candidate(decisions=decisions,config=_config(),fold_id="1")
    assert selected["selected"] is False
    assert selected["selected_candidate_id"] is None
    assert len(selected["rejection_reasons"]) == 3


def _fold_decision(fold: str, rejected: bool):
    decisions=[]
    for i in (1,2,3):
        candidate=f"rank_0{i}_epoch_{i}"
        decisions.append(_candidate_decision(
            fold=fold,candidate=candidate,epoch=i,loss=float(i),
            expected=-1.0 if rejected else 10.0+i,
            stress=1.0+i/10,dd=0.1,
        ))
    return select_fold_candidate(decisions=decisions,config=_config(),fold_id=fold)


def test_rejection_report_contains_all_shortlist_validation_and_keeps_test_closed():
    decisions=[_fold_decision(str(fold),rejected=(fold==2)) for fold in (1,2,3)]
    rows=[]
    for fold in (1,2,3):
        for i in (1,2,3):
            rows.extend(_rows(
                fold=str(fold),candidate=f"rank_0{i}_epoch_{i}",epoch=i,loss=float(i),
                expected=-1.0 if fold==2 else 10.0+i,
                stress=1.0,
            ))
    report=build_validation_rejection_report(rows=rows,decisions=decisions,config=_config())
    assert report["status"] == "REJECTED"
    assert report["development_test_opened"] is False
    assert report["holdout_state"] == "HOLDOUT_CLOSED"
    assert len(report["rows"]) == 27
    assert all(row["role"] == "validation" for row in report["rows"])
    assert any(reason.startswith("FOLD_2:") for reason in report["rejection_reasons"])


def test_rejection_report_refuses_all_selected_state():
    decisions=[_fold_decision(str(fold),rejected=False) for fold in (1,2,3)]
    rows=[]
    for fold in (1,2,3):
        for i in (1,2,3):
            rows.extend(_rows(fold=str(fold),candidate=f"rank_0{i}_epoch_{i}",epoch=i,loss=float(i)))
    with pytest.raises(C0CWalkForwardError,match="requires rejection"):
        build_validation_rejection_report(rows=rows,decisions=decisions,config=_config())
