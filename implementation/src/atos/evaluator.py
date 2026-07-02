from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class EvaluationReport:
    samples: int
    positive: int
    negative: int
    total_return: float
    worst_drop: float
    fees: float

    def to_dict(self) -> dict:
        return asdict(self)


class Evaluator:
    def summarize(self, values: list[float], fees: float = 0.0) -> EvaluationReport:
        positive = len([x for x in values if x > 0])
        negative = len([x for x in values if x < 0])
        total = sum(values)
        equity = 0.0
        peak = 0.0
        worst = 0.0
        for value in values:
            equity += value
            peak = max(peak, equity)
            worst = min(worst, equity - peak)
        return EvaluationReport(len(values), positive, negative, total, abs(worst), fees)

    def walk_forward_windows(self, values: list[float], train: int, test: int) -> list[dict]:
        output = []
        start = 0
        while start + train + test <= len(values):
            train_values = values[start:start + train]
            test_values = values[start + train:start + train + test]
            output.append({"train": self.summarize(train_values).to_dict(), "test": self.summarize(test_values).to_dict()})
            start += test
        return output
