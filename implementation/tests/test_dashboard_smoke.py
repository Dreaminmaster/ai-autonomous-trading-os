"""Dashboard smoke tests — verify dashboard components are importable and functional."""

from atos.dashboard import run_dashboard
from atos.reporting import ReportBuilder
from atos.ledger import Ledger


def test_dashboard_handler_imports():
    """Dashboard module should be importable."""
    from atos.dashboard import DashboardHandler
    assert DashboardHandler is not None

def test_report_builder_works_with_ledger():
    """Report builder should connect to ledger."""
    ledger = Ledger(":memory:")
    report = ReportBuilder({"mode": "paper"}, ledger).build(limit=5)
    assert report.state["mode"] == "paper"
    assert isinstance(report.recent_events, list)
    assert report.notes is not None

def test_ledger_memory_mode():
    """Ledger should work in memory mode."""
    ledger = Ledger(":memory:")
    ledger.record("test_event", {"key": "value"})
    assert ledger.count() == 1
    events = ledger.list_events(limit=10)
    assert len(events) == 1
    assert events[0]["kind"] == "test_event"
