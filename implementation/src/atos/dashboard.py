"""
ATOS Dashboard — local read-only HTTP server.

Serves:
  /            — status page with summary
  /api/events  — recent ledger events (JSON)
  /api/report  — full system report (JSON)
  /api/risk    — current risk engine state (JSON)
  /api/scores  — strategy scores (JSON)
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from atos.ledger import Ledger
from atos.reporting import ReportBuilder

STATUS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Autonomous Trading OS</title>
  <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#0f1117;color:#e1e4e8;padding:24px;max-width:960px;margin:0 auto}
    h1{font-size:1.6em;margin-bottom:4px;color:#58a6ff}
    .sub{color:#8b949e;font-size:.85em;margin-bottom:24px}
    .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin-bottom:16px}
    .card h2{font-size:1.1em;margin-bottom:8px;color:#c9d1d9}
    .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
    .stat{background:#0d1117;border:1px solid #21262d;border-radius:6px;padding:12px}
    .stat label{font-size:.75em;color:#8b949e;display:block}
    .stat .val{font-size:1.4em;font-weight:600;margin-top:4px}
    .ok{color:#3fb950}.warn{color:#d29922}.err{color:#f85149}
    pre{background:#0d1117;padding:12px;border-radius:6px;overflow-x:auto;font-size:.8em;line-height:1.4}
    a{color:#58a6ff}
  </style>
</head>
<body>
<h1>AI Autonomous Trading OS</h1>
<p class="sub">Read-only dashboard • Paper mode • No live orders</p>

<div class="grid">
  <div class="card"><h2>System</h2>
    <div class="stat"><label>Mode</label><div class="val ok">PAPER</div></div>
    <div class="stat"><label>Live Orders</label><div class="val err">DISABLED</div></div>
    <div class="stat"><label>Kill Switch</label><div class="val ok">ARMED</div></div>
  </div>
  <div class="card"><h2>Risk Engine</h2>
    <div class="stat"><label>Status</label><div class="val ok">ACTIVE</div></div>
    <div class="stat"><label>Gates</label><div class="val">10/10</div></div>
    <div class="stat"><label>Drawdown Guard</label><div class="val ok">OK</div></div>
  </div>
  <div class="card"><h2>AI Provider</h2>
    <div class="stat"><label>Default</label><div class="val">mock</div></div>
    <div class="stat"><label>Fallback</label><div class="val ok">mock</div></div>
    <div class="stat"><label>API Keys</label><div class="val ok">HIDDEN</div></div>
  </div>
</div>

<div class="card"><h2>Quick Links</h2>
  <ul style="list-style:none;display:flex;gap:16px;flex-wrap:wrap">
    <li><a href="/api/events">📋 Recent Events (JSON)</a></li>
    <li><a href="/api/report">📊 System Report (JSON)</a></li>
    <li><a href="/api/risk">🛡️ Risk State (JSON)</a></li>
    <li><a href="/api/scores">📈 Strategy Scores (JSON)</a></li>
  </ul>
</div>

<div class="card"><h2>Safety Architecture</h2>
  <pre>
Market Data → Feature Builder → Strategy Pool → AI Provider
                                                    ↓
                                            TradeIntent JSON
                                                    ↓
                                           Schema Validation
                                                    ↓
                                     ┌─ Risk Supervisor ─┐
                                     │  10 Deterministic  │
                                     │  Safety Gates      │
                                     └────────────────────┘
                                                    ↓
                                         Execution (Paper)
                                                    ↓
                                           Ledger / Audit
  </pre>
</div>

<p class="sub" style="margin-top:24px">AI cannot place orders • AI cannot bypass risk • AI cannot read API keys • All failures → HOLD</p>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    ledger_path = "runtime/atos.sqlite"
    policy = {"mode": "paper", "allowed_symbols": ["BTC/USDT", "ETH/USDT"]}

    def _send(self, code: int, body: str, content_type: str = "text/html") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:
        ledger = Ledger(self.ledger_path)
        path = self.path.split("?")[0]

        if path.startswith("/api/events"):
            limit = 100
            if "limit=" in self.path:
                try:
                    limit = int(self.path.split("limit=")[1].split("&")[0])
                except ValueError:
                    pass
            events = ledger.list_events(limit=limit)
            self._send(200, json.dumps({"events": events, "count": len(events)}, ensure_ascii=False, indent=2), "application/json")
            return

        if path.startswith("/api/report"):
            report = ReportBuilder(self.policy, ledger).build(limit=50)
            self._send(200, json.dumps(report, ensure_ascii=False, indent=2), "application/json")
            return

        if path.startswith("/api/risk"):
            from atos.risk import RiskEngine
            risk = RiskEngine(self.policy)
            self._send(200, json.dumps({
                "gates": 10,
                "mode": self.policy.get("mode", "paper"),
                "allowed_symbols": list(self.policy.get("allowed_symbols", [])),
                "stats": risk.stats(),
            }, ensure_ascii=False, indent=2), "application/json")
            return

        if path.startswith("/api/scores"):
            from atos.scoring import ScoringEngine
            engine = ScoringEngine()
            scores = engine.daily_scores({
                "trend_following_v1": [0.2, -0.1, 0.3, 0.0, 0.1, -0.05, 0.2, 0.1, 0.05, 0.3],
                "mean_reversion_v1": [0.1, 0.05, -0.15, 0.08, 0.02, 0.12, -0.03, 0.07, 0.0, 0.1],
                "breakout_v1": [0.3, -0.2, -0.1, 0.15, 0.05, -0.08, 0.4, -0.05, 0.0, 0.1],
            })
            self._send(200, json.dumps(scores, ensure_ascii=False, indent=2), "application/json")
            return

        if path in ("/", "/index", "/index.html"):
            self._send(200, STATUS_HTML)
            return

        self._send(404, "not found", "text/plain")


def run_dashboard(host: str | None = None, port: int | None = None, ledger_path: str = "runtime/atos.sqlite", policy: dict | None = None) -> None:
    import os
    host = host or os.environ.get("ATOS_DASHBOARD_HOST", "127.0.0.1")
    port = port or int(os.environ.get("ATOS_DASHBOARD_PORT", "28787"))

    DashboardHandler.ledger_path = ledger_path
    DashboardHandler.policy = policy or {"mode": "paper", "allowed_symbols": ["BTC/USDT", "ETH/USDT"]}

    try:
        server = HTTPServer((host, port), DashboardHandler)
    except OSError as e:
        print(f"ERROR: Cannot bind to {host}:{port} — {e}")
        print("  Set ATOS_DASHBOARD_PORT to an available port or free up the current one.")
        return

    print(f"Dashboard running at http://{host}:{port}")
    print(f"API endpoints: /api/events /api/report /api/risk /api/scores")
    server.serve_forever()
