from __future__ import annotations

import json
import threading
import urllib.parse
import urllib.request
from pathlib import Path

from ui.chat_agent_service import ChatAgentService
from ui.chat_service import ChatService
from ui.server import UIServer


def test_project_chat_sessions_are_durable_and_separate_from_runner_history(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    legacy = project / ".ai-task-runner" / "ui" / "messages.jsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"role": "user", "content": "runner task history"}) + "\n",
        encoding="utf-8",
    )

    service = ChatService()
    first = service.sessions(project)
    first_id = first["active_session_id"]
    created = service.create_session(project, title="Design", request_id="create-1")
    second_id = created["session_id"]
    repeated = service.create_session(project, title="ignored", request_id="create-1")

    assert repeated["session_id"] == second_id
    assert len(repeated["sessions"]) == 2

    first_message = service.append_message(project, first_id, "user", "normal chat")
    second_message = service.append_message(project, second_id, "assistant", "separate session")
    assert first_message["message_id"].startswith("msg-")
    assert second_message["message_id"].startswith("msg-")
    assert [row["content"] for row in service.messages(project, first_id)["messages"]] == [
        "normal chat"
    ]
    assert [row["content"] for row in service.messages(project, second_id)["messages"]] == [
        "separate session"
    ]
    assert "runner task history" not in json.dumps(service.messages(project, first_id))
    assert "runner task history" in legacy.read_text(encoding="utf-8")

    restarted = ChatService()
    snapshot = restarted.sessions(project)
    assert snapshot["active_session_id"] == second_id
    assert len(snapshot["sessions"]) == 2
    assert restarted.messages(project, second_id)["messages"][0]["content"] == "separate session"


def test_project_chat_session_lifecycle_never_leaves_project_without_a_chat(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = ChatService()

    first_id = service.sessions(project)["active_session_id"]
    second = service.create_session(project, request_id="create-2")
    second_id = second["session_id"]
    renamed = service.rename_session(project, second_id, "Implementation")
    assert next(
        row for row in renamed["sessions"] if row["session_id"] == second_id
    )["title"] == "Implementation"

    selected = service.select_session(project, first_id)
    assert selected["active_session_id"] == first_id

    after_first_delete = service.delete_session(project, first_id)
    assert after_first_delete["active_session_id"] == second_id
    assert [row["session_id"] for row in after_first_delete["sessions"]] == [second_id]

    after_last_delete = service.delete_session(project, second_id)
    assert len(after_last_delete["sessions"]) == 1
    assert after_last_delete["active_session_id"] != second_id
    assert after_last_delete["sessions"][0]["title"] == "New Chat"


def test_project_chat_rejects_invalid_ids_and_corrupt_state(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    service = ChatService()
    service.sessions(project)

    try:
        service.messages(project, "../../escape")
    except ValueError as exc:
        assert "session_id" in str(exc)
    else:
        raise AssertionError("invalid session id was accepted")

    state_file = project / ".ai-task-runner" / "ui" / "chat" / "state.json"
    state_file.write_text("{broken", encoding="utf-8")
    try:
        service.sessions(project)
    except ValueError as exc:
        assert "Chat state is invalid" in str(exc)
    else:
        raise AssertionError("corrupt chat state was silently replaced")


def _json_request(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        method=method,
        headers={"Content-Type": "application/json"} if payload is not None else {},
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_project_chat_session_api_uses_existing_ui_server(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    project_query = urllib.parse.quote(str(project))

    try:
        initial = _json_request(f"{base}/api/chat/sessions?project={project_query}")
        assert len(initial["sessions"]) == 1

        created = _json_request(
            f"{base}/api/chat/session/create",
            method="POST",
            body={
                "project": str(project),
                "title": "API Chat",
                "request_id": "api-create-1",
            },
        )
        session_id = created["session_id"]
        assert session_id != initial["active_session_id"]

        repeated = _json_request(
            f"{base}/api/chat/session/create",
            method="POST",
            body={
                "project": str(project),
                "title": "ignored",
                "request_id": "api-create-1",
            },
        )
        assert repeated["session_id"] == session_id
        assert len(repeated["sessions"]) == 2

        server.state.chat_service.append_message(project, session_id, "assistant", "hello")
        messages = _json_request(
            f"{base}/api/chat/messages?project={project_query}&session_id={session_id}"
        )
        assert messages["session_id"] == session_id
        assert [row["content"] for row in messages["messages"]] == ["hello"]

        renamed = _json_request(
            f"{base}/api/chat/session/rename",
            method="POST",
            body={"project": str(project), "session_id": session_id, "title": "Renamed"},
        )
        assert any(
            row["session_id"] == session_id and row["title"] == "Renamed"
            for row in renamed["sessions"]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_chat_agent_turn_is_separate_from_runner_history_and_reuses_agent_session(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {
            "text": "reply-" + str(len(calls)),
            "session_id": kwargs.get("session_id") or "agent-session-1",
        }

    chat = ChatService()
    service = ChatAgentService(repo, runner=fake_runner)
    session_id = chat.sessions(project)["active_session_id"]

    service.turn(project, chat, session_id=session_id, message="hello", backend="qwen", model="model-a", mode="auto")
    service.turn(project, chat, session_id=session_id, message="again", backend="qwen", model="model-a", mode="auto")

    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "hello", "reply-1", "again", "reply-2"
    ]
    assert calls[0]["session_id"] == ""
    assert calls[1]["session_id"] == "agent-session-1"
    assert not (project / ".ai-task-runner" / "ui" / "messages.jsonl").exists()


def test_chat_agent_session_resets_when_project_agent_changes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    seen: list[tuple[str, str]] = []

    def fake_runner(**kwargs):
        seen.append((kwargs["backend"], kwargs["session_id"]))
        return {"text": "ok", "session_id": kwargs["backend"] + "-session"}

    chat = ChatService()
    service = ChatAgentService(repo, runner=fake_runner)
    session_id = chat.sessions(project)["active_session_id"]

    service.turn(project, chat, session_id=session_id, message="a", backend="qwen", mode="auto")
    service.turn(project, chat, session_id=session_id, message="b", backend="opencode", mode="auto")
    service.turn(project, chat, session_id=session_id, message="c", backend="opencode", mode="auto")

    assert seen == [
        ("qwen", ""),
        ("opencode", ""),
        ("opencode", "opencode-session"),
    ]
