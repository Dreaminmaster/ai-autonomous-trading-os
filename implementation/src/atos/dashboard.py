from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from atos.ledger import Ledger
from atos.reporting import ReportBuilder


class DashboardHandler(BaseHTTPRequestHandler):
    ledger_path = "runtime/atos.sqlite"
    policy = {"mode": "paper"}

    def _send(self, code: int, body: str, content_type: str = "text/html") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))

    def do_GET(self) -> None:
        ledger = Ledger(self.ledger_path)
        if self.path.startswith("/api/events"):
            events = ledger.list_events(limit=100)
            self._send(200, json.dumps({"events": events}, ensure_ascii=False, indent=2), "application/json")
            return
        if self.path.startswith("/api/report"):
            report = ReportBuilder(self.policy, ledger).build(limit=50).to_dict()
            self._send(200, json.dumps(report, ensure_ascii=False, indent=2), "application/json")
            return
        if self.path == "/" or self.path.startswith("/index"):
            html = """
            <html>
              <head><title>AI Autonomous Trading OS</title></head>
              <body>
                <h1>AI Autonomous Trading OS</h1>
                <p>Local read-only dashboard.</p>
                <ul>
                  <li><a href='/api/events'>Recent ledger events</a></li>
                  <li><a href='/api/report'>System report</a></li>
                </ul>
              </body>
            </html>
            """
            self._send(200, html)
            return
        self._send(404, "not found", "text/plain")


def run_dashboard(host: str = "127.0.0.1", port: int = 8787, ledger_path: str = "runtime/atos.sqlite", policy: dict | None = None) -> None:
    DashboardHandler.ledger_path = ledger_path
    DashboardHandler.policy = policy or {"mode": "paper"}
    server = HTTPServer((host, port), DashboardHandler)
    print(f"Dashboard running at http://{host}:{port}")
    server.serve_forever()
