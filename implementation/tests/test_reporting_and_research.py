from atos.account_file import FileAccountView
from atos.domain import Candle
from atos.reporting import ReportBuilder
from atos.research_loop import ResearchLoop


def candles():
    return [Candle(100+i, 102+i, 99+i, 101+i, 1000+i) for i in range(40)]


def policy():
    return {"mode": "paper", "allowed_symbols": ["BTC-USDT"], "position_limits": {"max_position_pct_per_trade": 1.0}, "ai_output_limits": {"min_confidence_for_trade": 0.6}}


def test_file_account_view_empty():
    view = FileAccountView("runtime/missing_account_view.json")
    assert view.balances() == []
    assert view.positions() == []


def test_report_builder():
    report = ReportBuilder(policy()).build()
    assert report.state["mode"] == "paper"
    assert isinstance(report.recent_events, list)


def test_research_loop():
    report = ResearchLoop(policy()).run_windows("BTC-USDT", [candles(), candles()])
    assert report.windows == 2
    assert report.ledger_events >= 4
