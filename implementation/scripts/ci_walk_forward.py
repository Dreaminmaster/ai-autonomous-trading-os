#!/usr/bin/env python3
import json
from pathlib import Path
from atos.evaluator import Evaluator

pnl = [0.15,-0.05,0.22,-0.08,0.31,0.12,-0.15,0.18,-0.04,0.27,
       -0.09,0.14,0.33,-0.12,0.19,-0.06,0.25,0.11,-0.18,0.29]
ev = Evaluator()
wf = ev.walk_forward(pnl, train=10, test=5)
mc = ev.monte_carlo(pnl, 200)
ov = ev.summarize(pnl)
report = {"overall": ov.to_dict(), "walk_forward": wf.to_dict(), "monte_carlo": mc.to_dict()}
Path("freqtrade_data/backtest_results/walk_forward_report.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
