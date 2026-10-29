"""HTTP dispatch coverage for UI API actions that are otherwise exercised through services/browser flows."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from ui.server import Handler, UIServer


GET_INVALID_ROUTES = (
    "/api/studio/graph",
)

POST_INVALID_ROUTES = (
    "/api/chat/queue/drain",
    "/api/project/history/clear",
    "/api/project/message",
    "/api/project/reset",
    "/api/project/resume",
    "/api/project/stop",
    "/api/studio/graph/save",
    "/api/studio/path/test",
    "/api/studio/stage/source",
    "/api/studio/stage/test/cancel",
    "/api/studio/stage/validate",
    "/api/studio/visual/save",
    "/api/tasks/merge",
    "/api/tasks/resume",
    "/api/tasks/run",
    "/api/tasks/stop",
)


@pytest.fixture()
def api_server(tmp_path: Path):
    (tmp_path / "ui" / "data").mkdir(parents=True)
    (tmp_path / "ui" / "static").mkdir(parents=True)
    server = UIServer(tmp_path, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def _request_json(url: str, *, method: str = "GET", body: dict | None = None) -> tuple[int, dict]:
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            status = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        status = exc.code
        payload = json.loads(exc.read().decode("utf-8"))
    return status, payload


@pytest.mark.parametrize("route", GET_INVALID_ROUTES)
def test_get_api_route_dispatch_is_live_and_returns_structured_error(api_server, route: str) -> None:
    status, payload = _request_json(f"http://127.0.0.1:{api_server.port}{route}")
    assert status == 400, (route, status, payload)
    assert payload["code"] == "invalid_request"
    assert payload["message"]
    assert payload["retryable"] is False


@pytest.mark.parametrize("route", POST_INVALID_ROUTES)
def test_post_api_route_dispatch_is_live_and_returns_structured_error(api_server, route: str) -> None:
    status, payload = _request_json(
        f"http://127.0.0.1:{api_server.port}{route}",
        method="POST",
        body={"request_id": f"route-coverage-{route.rsplit('/', 1)[-1]}"},
    )
    assert status == 400, (route, status, payload)
    assert payload["code"] == "invalid_request"
    assert payload["message"]
    assert payload["retryable"] is False
    assert payload["request_id"].startswith("route-coverage-")


def test_project_picker_route_dispatches_without_opening_native_dialog(
    api_server,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []

    def fake_pick_folder(handler) -> None:
        calls.append(True)
        return handler._json({"cancelled": True})

    monkeypatch.setattr(Handler, "_pick_folder", fake_pick_folder)
    status, payload = _request_json(
        f"http://127.0.0.1:{api_server.port}/api/projects/pick",
        method="POST",
        body={"request_id": "route-coverage-project-picker"},
    )
    assert status == 200
    assert payload == {"cancelled": True}
    assert calls == [True]
