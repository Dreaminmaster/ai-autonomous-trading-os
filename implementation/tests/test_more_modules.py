from atos.evaluator import Evaluator
from atos.timer import FixedTimer
from atos.state_service import StateService
from atos.account_view import EmptyAccountView


def test_evaluator_summary():
    report = Evaluator().summarize([0.1, -0.2, 0.3])
    assert report.samples == 3
    assert report.positive == 2
    assert report.negative == 1


def test_walk_forward_windows():
    windows = Evaluator().walk_forward_windows([0.1, 0.2, -0.1, 0.0, 0.3], train=2, test=1)
    assert len(windows) >= 1


def test_timer_runs():
    count = {"x": 0}
    def inc():
        count["x"] += 1
    result = FixedTimer().run(inc, runs=2)
    assert result.completed is True
    assert count["x"] == 2


def test_state_service():
    state = StateService({"mode": "paper"}).current()
    assert state.mode == "paper"


def test_empty_account_view():
    view = EmptyAccountView()
    assert view.balances() == []
    assert view.positions() == []
