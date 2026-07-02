from __future__ import annotations

from dataclasses import dataclass, asdict

from atos.ledger import Ledger


@dataclass
class SystemStateView:
    mode: str
    event_count: int
    components: list[str]
    notices: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class StateService:
    def __init__(self, policy: dict, ledger: Ledger | None = None):
        self.policy = policy
        self.ledger = ledger or Ledger()

    def current(self) -> SystemStateView:
        return SystemStateView(
            mode=self.policy.get("mode", "paper"),
            event_count=self.ledger.count(),
            components=["market", "strategies", "providers", "risk", "execution", "ledger", "history", "scoring", "runtime", "dashboard"],
            notices=[],
        )
