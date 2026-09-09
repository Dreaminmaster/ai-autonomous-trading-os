from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from typing import Any

import pytest

from atos import cli
from atos.shadow_campaign_server import CampaignHTTPServer


class StubManager:
    def __init__(self) -> None:
        self.actions: list[str] = []

    def _result(self, action: str) -> dict[str, Any]:
        self.actions.append(action)
        return {"campaign_id": "campaign_test", "state": "PAUSED", "action": action, "live": "FORBIDDEN"}

    def status(self) -> dict[str, Any]:
        return self._result("status")

    def create(self, *, start: bool) -> dict[str, Any]:
        assert start is True
        return self._result("new")

    def resume(self) -> dict[str, Any]:
        return self._result("resume")

    def pause(self) -> dict[str, Any]:
        return self._result("pause")

    def freeze(self) -> dict[str, Any]:
        return self._result("freeze")


def _request(url: str, *, method: str = "GET", token: str | None = None) -> tuple[int, str]:
    headers = {}
    data = None
    if method == "POST":
        headers["Content-Type"] = "application/json"
        if token:
            headers["X-ATOS-Control-Token"] = token
        data = b"{}"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8")


def test_local_ui_and_all_control_buttons_require_ephemeral_token() -> None:
    manager = StubManager()
    server = CampaignHTTPServer(("127.0.0.1", 0), manager)  # type: ignore[arg-type]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, html = _request(base + "/")
        assert status == 200
        assert "开始新 Campaign" in html
        assert "继续运行" in html
        assert "暂停" in html
        assert "结束并冻结 Campaign" in html
        assert server.control_token in html
        status, _ = _request(base + "/api/pause", method="POST")
        assert status == 403
        for action in ("new", "resume", "pause", "freeze"):
            status, body = _request(
                base + "/api/" + action,
                method="POST",
                token=server.control_token,
            )
            assert status == 200
            assert json.loads(body)["action"] == action
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_campaign_ui_is_a_real_cli_command(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, Any] = {}
    monkeypatch.setattr(
        cli,
        "ShadowCampaignManager",
        lambda *args, **kwargs: called.update(
            {"manager_args": args, "manager_kwargs": kwargs}
        )
        or object(),
    )
    monkeypatch.setattr(
        cli,
        "run_campaign_server",
        lambda manager, **kwargs: called.update(
            {"manager": manager, "server_kwargs": kwargs}
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["atos", "campaign-ui", "--policy", "config/policy.json", "--no-open"],
    )

    cli.main()

    assert called["server_kwargs"] == {"port": 28788, "open_browser": False}
