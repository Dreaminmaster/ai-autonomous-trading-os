from __future__ import annotations

from dataclasses import dataclass, asdict

from atos.ledger import Ledger
from atos.state_service import StateService


@dataclass
class ProductReport:
    state: dict
    recent_events: list[dict]
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class ReportBuilder:
    def __init__(self, policy: dict, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()
        self.policy = policy

    def build(self, limit: int = 20) -> ProductReport:
        state = StateService(self.policy, self.ledger).current().to_dict()
        events = self.ledger.list_events(limit=limit)
        notes = []
        if state.get("mode") == "paper":
            notes.append("paper mode active")
        if not events:
            notes.append("no ledger events yet")
        return ProductReport(state=state, recent_events=events, notes=notes)
