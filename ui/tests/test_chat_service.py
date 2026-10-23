from __future__ import annotations

import json
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from runner.agent import ChatFeatureSpec
from ui.agent_capability_service import AgentCapabilityService
from ui.agent_settings_service import AgentSettingsService
from ui.chat_agent_service import (
    CHAT_AGENT_CANCEL_GRACE_SECONDS,
    CHAT_AGENT_TIMEOUT_SECONDS,
    CHAT_AGENT_WRAPPER_GRACE_SECONDS,
    ChatAgentService,
)
from ui.chat_service import ChatService, STATE_VERSION
from ui.server import UIServer
from ui.task_draft_service import TaskDraftService


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


def test_chat_server_reopen_does_not_touch_runner_runtime_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    runtime = project / ".ai-task-runner"
    runtime.mkdir()
    sentinels = {
        runtime / "state.json": '{"run_id":"runner-sentinel","completed":false}\n',
        runtime / "runner-process.json": '{"supervisor_pid":12345,"worker_pid":12346}\n',
        runtime / "stop.request": "keep-runner-stop-request\n",
    }
    for path, content in sentinels.items():
        path.write_text(content, encoding="utf-8")

    first = UIServer(repo, "127.0.0.1", 0)
    try:
        session_id = first.state.chat_service.sessions(project)["active_session_id"]
        first.state.chat_service.append_message(
            project,
            session_id,
            "user",
            "ordinary chat survives server reopen",
        )
    finally:
        first.server_close()

    reopened = UIServer(repo, "127.0.0.1", 0)
    try:
        assert reopened.state.chat_service.sessions(project)["active_session_id"] == session_id
        assert reopened.state.chat_service.messages(project, session_id)["messages"][0]["content"] == (
            "ordinary chat survives server reopen"
        )
        for path, content in sentinels.items():
            assert path.read_text(encoding="utf-8") == content
    finally:
        reopened.server_close()


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

        server.state.task_drafts = TaskDraftService(
            repo,
            runner=lambda **kwargs: {
                "draft": {
                    "title": "Delete with Chat",
                    "items": [{"title": "A", "prompt": "Do A"}],
                }
            },
        )
        transient = server.state.task_drafts.generate(
            project,
            spec="delete this session draft",
            draft_mode="single",
            backend="qwen",
            workflow="workflow.yaml",
            request_id="delete-session-draft",
            session_id=session_id,
        )
        deleted = _json_request(
            f"{base}/api/chat/session/delete",
            method="POST",
            body={"project": str(project), "session_id": session_id},
        )
        assert all(row["session_id"] != session_id for row in deleted["sessions"])
        with pytest.raises(ValueError, match="no longer available"):
            server.state.task_drafts.get(
                project,
                transient["draft_id"],
                session_id=session_id,
            )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_chat_event_feed_is_durable_cursor_based_and_session_scoped(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    first = chat.sessions(project)["active_session_id"]
    second = chat.create_session(project, request_id="events-second")["session_id"]

    message = chat.append_message(project, first, "user", "hello")
    queued = chat.enqueue_turn(
        project,
        first,
        "work",
        request_id="events-turn",
        backend="qwen",
    )
    ask = chat.create_ask(
        project,
        first,
        request_id="events-ask",
        turn_id=queued["turn_id"],
        questions=[{"id": "ok", "question": "Continue?", "options": ["yes", "no"]}],
    )
    chat.submit_ask(
        project,
        first,
        ask["ask"]["ask_id"],
        {"ok": "yes"},
        request_id="events-answer",
    )
    claimed = chat.claim_next(project, first)
    assert claimed is not None
    chat.complete_queue_item(project, first, queued["queue_item_id"])

    snapshot = ChatService().events(project, first, after=0)
    assert snapshot["cursor"] >= 7
    assert snapshot["reset_required"] is False
    assert [row["type"] for row in snapshot["events"]] == [
        "message_completed",
        "queue_updated",
        "ask_requested",
        "ask_resolved",
        "queue_updated",
        "queue_updated",
        "turn_completed",
    ]
    assert snapshot["events"][0]["payload"]["message_id"] == message["message_id"]
    cursor = snapshot["cursor"]
    assert ChatService().events(project, first, after=cursor)["events"] == []
    assert ChatService().events(project, second, after=0)["events"] == []

    state_file = project / ".ai-task-runner" / "ui" / "chat" / "state.json"
    raw = json.loads(state_file.read_text(encoding="utf-8"))
    assert raw["version"] == STATE_VERSION
    first_state = next(row for row in raw["sessions"] if row["session_id"] == first)
    assert first_state["event_seq"] == cursor
    assert first_state["events"][-1]["type"] == "turn_completed"


def test_chat_event_feed_http_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    server = UIServer(repo, "127.0.0.1", 0)
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    server.state.chat_service.append_message(project, session_id, "assistant", "event reply")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        project_query = urllib.parse.quote(str(project))
        value = _json_request(
            f"http://127.0.0.1:{server.port}/api/chat/events"
            f"?project={project_query}&session_id={session_id}&after=0"
        )
        assert value["session_id"] == session_id
        assert value["cursor"] == 1
        assert value["events"][0]["type"] == "message_completed"
        assert "content" not in value["events"][0]["payload"]
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

    service.turn(
        project, chat, session_id=session_id, message="hello",
        backend="qwen", model="model-a", mode="auto", reasoning="high",
        request_id="continuity-1",
    )
    service.turn(
        project, chat, session_id=session_id, message="again",
        backend="qwen", model="model-a", mode="auto", reasoning="high",
        request_id="continuity-2",
    )

    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "hello", "reply-1", "again", "reply-2"
    ]
    assert calls[0]["session_id"] == ""
    assert calls[1]["session_id"] == "agent-session-1"
    assert calls[0]["reasoning"] == "high"
    assert calls[1]["reasoning"] == "high"
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

    service.turn(project, chat, session_id=session_id, message="a", backend="qwen", mode="auto", request_id="switch-1")
    service.turn(project, chat, session_id=session_id, message="b", backend="opencode", mode="auto", request_id="switch-2")
    service.turn(project, chat, session_id=session_id, message="c", backend="opencode", mode="auto", request_id="switch-3")

    assert seen == [
        ("qwen", ""),
        ("opencode", ""),
        ("opencode", "opencode-session"),
    ]



def test_project_chat_turn_http_uses_project_preferences_without_runner_task(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    runtime = project / ".ai-task-runner"
    runtime.mkdir()
    runtime_sentinels = {
        runtime / "state.json": '{"run_id":"active-runner-task","completed":false}\n',
        runtime / "runner-process.json": '{"supervisor_pid":12345,"worker_pid":12346}\n',
        runtime / "stop.request": "runner-owned-stop-state\n",
    }
    for path, content in runtime_sentinels.items():
        path.write_text(content, encoding="utf-8")

    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {"text": "http reply", "session_id": "native-session"}

    server = UIServer(repo, "127.0.0.1", 0)
    server.state.chat_agent = ChatAgentService(repo, runner=fake_runner)
    server.state.project_preferences.update(project, {
        "agent": "opencode",
        "model": "provider/model-a",
        "mode": "read",
    })
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = _json_request(
            f"http://127.0.0.1:{server.port}/api/chat/turn",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "message": "normal chat",
                "request_id": "http-normal-chat-1",
            },
        )
        assert response["agent"] == "opencode"
        assert response["model"] == "provider/model-a"
        assert response["mode"] == "read"
        assert calls[0]["backend"] == "opencode"
        assert calls[0]["model"] == "provider/model-a"
        assert calls[0]["mode"] == "read"
        assert [row["content"] for row in server.state.chat_service.messages(project, session_id)["messages"]] == [
            "normal chat", "http reply"
        ]
        assert not (project / ".ai-task-runner" / "ui" / "messages.jsonl").exists()

        server.state.chat_agent = ChatAgentService(
            repo,
            runner=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("chat backend unavailable")),
        )
        failed = _json_request(
            f"http://127.0.0.1:{server.port}/api/chat/turn",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "message": "failing ordinary chat",
                "request_id": "http-normal-chat-failure-1",
            },
        )
        assert failed["status"] == "error"
        assert failed["error"] == "chat backend unavailable"
        for path, content in runtime_sentinels.items():
            assert path.read_text(encoding="utf-8") == content
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_agent_capability_service_caches_native_projection(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls = 0

    def fake_catalog(root, backend):
        nonlocal calls
        calls += 1
        assert backend == "qwen"
        assert Path(root) == project
        return {
            "backend": "qwen",
            "capabilities": [{
                "token": "/btw",
                "name": "btw",
                "description": "Side question",
                "kind": "command",
                "source": "builtin",
                "user_invocable": True,
                "enabled": True,
                "permission": "available",
                "availability": "available",
            }],
        }

    monkeypatch.setattr("ui.agent_capability_service.capability_catalog", fake_catalog)
    service = AgentCapabilityService(repo, ttl_seconds=60)
    first = service.get(project, "qwen")
    second = service.get(project, "qwen")
    refreshed = service.get(project, "qwen", refresh=True)

    assert first["cached"] is False
    assert second["cached"] is True
    assert refreshed["cached"] is False
    assert calls == 2
    assert first["capabilities"][0]["token"] == "/btw"


def test_agent_capability_service_fails_closed_on_discovery_error(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    def fail_catalog(*args, **kwargs):
        raise RuntimeError("native registry unavailable")

    monkeypatch.setattr("ui.agent_capability_service.capability_catalog", fail_catalog)
    service = AgentCapabilityService(repo)
    with pytest.raises(ValueError, match="native registry unavailable"):
        service.get(project, "qwen")



def test_chat_queue_is_durable_fifo_and_session_scoped(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    first = chat.sessions(project)["active_session_id"]
    second = chat.create_session(project, request_id="second-session")["session_id"]

    first_turn = chat.enqueue_turn(
        project, first, "one",
        request_id="turn-1", backend="qwen", model="m1", mode="auto",
    )
    assert first_turn["turn_id"].startswith("turn-")
    chat.enqueue_turn(
        project, first, "two",
        request_id="turn-2", backend="qwen", model="m1", mode="auto",
    )
    chat.enqueue_turn(
        project, second, "other",
        request_id="turn-3", backend="opencode", model="m2", mode="read",
    )

    restarted = ChatService()
    assert [row["content"] for row in restarted.queue(project, first)["items"]] == ["one", "two"]
    assert restarted.queue(project, first)["items"][0]["turn_id"] == first_turn["turn_id"]
    assert [row["content"] for row in restarted.queue(project, second)["items"]] == ["other"]

    first_item = restarted.queue(project, first)["items"][0]
    restarted.update_queue_item(project, first, first_item["queue_item_id"], "one edited")
    assert restarted.queue(project, first)["items"][0]["content"] == "one edited"
    restarted.delete_queue_item(project, first, first_item["queue_item_id"])
    assert [row["content"] for row in restarted.queue(project, first)["items"]] == ["two"]
    assert [row["content"] for row in restarted.queue(project, second)["items"]] == ["other"]

    with pytest.raises(ValueError, match="empty"):
        restarted.update_queue_item(
            project,
            first,
            restarted.queue(project, first)["items"][0]["queue_item_id"],
            "   ",
        )

    long_message = "queued-" + ("x" * 4096)
    remaining = restarted.queue(project, first)["items"][0]
    restarted.update_queue_item(project, first, remaining["queue_item_id"], long_message)
    assert ChatService().queue(project, first)["items"][0]["content"] == long_message
    assert [row["content"] for row in ChatService().queue(project, second)["items"]] == ["other"]


def test_expired_chat_agent_session_is_cleared_without_replaying_failed_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.set_agent_session(project, session_id, "qwen", "stale-agent-session")
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(),
    )

    def fake_runner(**kwargs):
        prompt = str(kwargs["prompt"])
        native_session = str(kwargs["session_id"])
        calls.append((prompt, native_session))
        if native_session:
            raise RuntimeError("No saved session found for stale-agent-session")
        return {"text": "fresh reply", "session_id": "fresh-agent-session"}

    service = ChatAgentService(repo, runner=fake_runner)
    failed = service.turn(
        project,
        chat,
        session_id=session_id,
        message="first",
        backend="qwen",
        request_id="expired-session-first",
    )

    assert failed["status"] == "error"
    assert chat.agent_session(project, session_id, "qwen") == ""
    assert calls == [("first", "stale-agent-session")]
    assert "retry this Chat turn" in failed["error"]

    continued = service.turn(
        project,
        chat,
        session_id=session_id,
        message="second",
        backend="qwen",
        request_id="expired-session-second",
    )

    assert continued["status"] == "idle"
    assert calls == [
        ("first", "stale-agent-session"),
        ("second", ""),
    ]
    assert chat.agent_session(project, session_id, "qwen") == "fresh-agent-session"
    assert [
        row["content"]
        for row in chat.messages(project, session_id)["messages"]
        if row["role"] == "user"
    ] == ["first", "second"]


def test_chat_public_projection_excludes_native_transport_session_details(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.set_agent_session(
        project,
        session_id,
        "opencode",
        "private-agent-session",
    )
    chat.create_ask(
        project,
        session_id,
        request_id="public-redaction-question",
        turn_id="public-redaction-turn",
        questions=[{
            "id": "confirm",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["yes", "no"],
        }],
        source="native",
        backend="opencode",
        agent_session_id="private-native-session",
        native_request_id="private-native-request",
    )

    public_payload = json.dumps({
        "sessions": chat.sessions(project),
        "ask": chat.ask(project, session_id),
        "events": chat.events(project, session_id),
    })

    assert "private-agent-session" not in public_payload
    assert "private-native-session" not in public_payload
    assert "private-native-request" not in public_payload
    assert "agent_session_id" not in public_payload
    assert "native_request_id" not in public_payload


def test_chat_agent_busy_turns_queue_and_drain_fifo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []

    def fake_runner(**kwargs):
        prompt = kwargs["prompt"]
        calls.append(prompt)
        if prompt == "one":
            started.set()
            assert release.wait(timeout=3)
        return {
            "text": "reply-" + prompt,
            "session_id": kwargs.get("session_id") or "agent-session",
        }

    chat = ChatService()
    service = ChatAgentService(repo, runner=fake_runner)
    session_id = chat.sessions(project)["active_session_id"]
    owner_result: list[dict] = []

    thread = threading.Thread(
        target=lambda: owner_result.append(service.turn(
            project, chat, session_id=session_id, message="one",
            backend="qwen", model="m", mode="auto", request_id="r1",
        )),
        daemon=True,
    )
    thread.start()
    assert started.wait(timeout=2)

    second = service.turn(
        project, chat, session_id=session_id, message="two",
        backend="qwen", model="m", mode="auto", request_id="r2",
    )
    third = service.turn(
        project, chat, session_id=session_id, message="three",
        backend="qwen", model="m", mode="auto", request_id="r3",
    )
    assert second["status"] == "queued"
    assert third["status"] == "queued"
    assert [row["content"] for row in service.status(
        project, chat, session_id=session_id
    )["items"]] == ["two", "three"]

    release.set()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert calls == ["one", "two", "three"]
    assert owner_result[0]["status"] == "idle"
    assert service.status(project, chat, session_id=session_id)["items"] == []
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "one", "reply-one", "two", "reply-two", "three", "reply-three",
    ]



@pytest.mark.parametrize("outcome", ["completed", "failed", "cancelled"])
def test_chat_queue_terminal_outcome_is_durable_and_idempotent(
    tmp_path: Path,
    outcome: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    request_id = f"terminal-{outcome}"
    queued = chat.enqueue_turn(
        project,
        session_id,
        "terminal item",
        request_id=request_id,
        backend="qwen",
    )
    claimed = chat.claim_next(project, session_id)
    assert claimed is not None
    assert claimed["status"] == "dispatching"

    chat.complete_queue_item(
        project,
        session_id,
        queued["queue_item_id"],
        outcome=outcome,
    )
    assert chat.queue(project, session_id) == {
        "session_id": session_id,
        "items": [],
        "dispatching": None,
    }

    duplicate = ChatService().enqueue_turn(
        project,
        session_id,
        "terminal item",
        request_id=request_id,
        backend="qwen",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["request_status"] == outcome
    assert duplicate["queue_item_id"] == queued["queue_item_id"]
    assert duplicate["turn_id"] == queued["turn_id"]


def test_chat_queue_recovers_dispatching_item_after_restart(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.enqueue_turn(
        project, session_id, "persisted",
        request_id="persisted-1", backend="qwen", mode="auto",
    )
    claimed = chat.claim_next(project, session_id)
    assert claimed is not None
    assert chat.queue(project, session_id)["dispatching"]["content"] == "persisted"
    first_user = chat.append_message(
        project,
        session_id,
        "user",
        "persisted",
        turn_id=claimed["turn_id"],
    )

    calls: list[str] = []
    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: (
            calls.append(kwargs["prompt"])
            or {"text": "ok", "session_id": "native"}
        ),
    )
    result = service.drain(project, ChatService(), session_id=session_id)
    assert result["status"] == "idle"
    assert calls == ["persisted"]
    assert ChatService().queue(project, session_id)["items"] == []
    messages = ChatService().messages(project, session_id)["messages"]
    assert [row["role"] for row in messages] == ["user", "assistant"]
    assert messages[0]["message_id"] == first_user["message_id"]
    assert messages[0]["turn_id"] == claimed["turn_id"]
    assert messages[1]["turn_id"] == claimed["turn_id"]


def test_chat_queue_restart_does_not_repeat_completed_agent_turn(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    queued = chat.enqueue_turn(
        project,
        session_id,
        "persisted complete",
        request_id="persisted-complete-1",
        backend="qwen",
    )
    claimed = chat.claim_next(project, session_id)
    assert claimed is not None
    chat.append_message(
        project,
        session_id,
        "user",
        "persisted complete",
        turn_id=queued["turn_id"],
    )
    assistant = chat.append_message(
        project,
        session_id,
        "assistant",
        "already durable",
        turn_id=queued["turn_id"],
    )

    calls: list[str] = []
    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: (
            calls.append(kwargs["prompt"])
            or {"text": "should-not-run", "session_id": "native"}
        ),
    )
    result = service.drain(project, ChatService(), session_id=session_id)

    assert result["status"] == "idle"
    assert calls == []
    assert ChatService().queue(project, session_id)["items"] == []
    messages = ChatService().messages(project, session_id)["messages"]
    assert [row["content"] for row in messages] == ["persisted complete", "already durable"]
    assert messages[1]["message_id"] == assistant["message_id"]


def test_chat_turn_requires_request_id(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: {"text": "unused", "session_id": "native"},
    )
    with pytest.raises(ValueError, match="request_id is required"):
        service.turn(
            project,
            chat,
            session_id=chat.sessions(project)["active_session_id"],
            message="no id",
            backend="qwen",
        )


def test_chat_queue_backend_failure_records_error_and_preserves_later_items(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.enqueue_turn(project, session_id, "bad", request_id="bad-1", backend="qwen")
    chat.enqueue_turn(project, session_id, "later", request_id="later-1", backend="qwen")

    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("backend down")),
    )
    result = service.drain(project, chat, session_id=session_id)
    assert result["status"] == "error"
    assert "backend down" in result["error"]
    assert [row["content"] for row in result["items"]] == ["later"]
    messages = chat.messages(project, session_id)["messages"]
    assert messages[-1]["role"] == "system"
    assert "backend down" in messages[-1]["content"]



def test_project_chat_queue_http_edit_delete_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    server = UIServer(repo, "127.0.0.1", 0)
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    queued = server.state.chat_service.enqueue_turn(
        project,
        session_id,
        "queued",
        request_id="queue-api-1",
        backend="qwen",
        mode="auto",
        reasoning="high",
    )
    queue_item_id = queued["queue_item_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    project_query = urllib.parse.quote(str(project))
    try:
        status = _json_request(
            f"{base}/api/chat/queue?project={project_query}&session_id={session_id}"
        )
        assert [row["content"] for row in status["items"]] == ["queued"]
        updated = _json_request(
            f"{base}/api/chat/queue/update",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "queue_item_id": queue_item_id,
                "message": "edited",
            },
        )
        assert [row["content"] for row in updated["items"]] == ["edited"]
        deleted = _json_request(
            f"{base}/api/chat/queue/delete",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "queue_item_id": queue_item_id,
            },
        )
        assert deleted["items"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_project_chat_delete_is_guarded_while_turn_is_active(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    started = threading.Event()
    release = threading.Event()

    def fake_runner(**kwargs):
        started.set()
        assert release.wait(timeout=3)
        return {"text": "done", "session_id": "native"}

    server = UIServer(repo, "127.0.0.1", 0)
    server.state.chat_agent = ChatAgentService(repo, runner=fake_runner)
    server.state.project_preferences.update(project, {"agent": "qwen"})
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    worker = threading.Thread(
        target=lambda: server.state.chat_agent.turn(
            project,
            server.state.chat_service,
            session_id=session_id,
            message="busy",
            backend="qwen",
            request_id="busy-delete-1",
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=2)
    status = server.state.chat_agent.status(
        project,
        server.state.chat_service,
        session_id=session_id,
    )
    assert status["busy"] is True
    try:
        if status["busy"]:
            raise ValueError("Stop or wait for the active Chat turn before deleting this Chat")
    except ValueError as exc:
        assert "active Chat turn" in str(exc)
    else:
        raise AssertionError("busy Chat delete guard was not enforced")
    release.set()
    worker.join(timeout=4)
    assert not worker.is_alive()



def test_agent_settings_service_preserves_native_reasoning_ids(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls = 0

    def fake_catalog(root, backend, model):
        nonlocal calls
        calls += 1
        assert Path(root) == project
        assert backend == "opencode"
        assert model == "openai/gpt-5.2"
        return {
            "agent": "opencode",
            "models": ["openai/gpt-5.2"],
            "modes": [{
                "id": "auto",
                "native": "--auto",
                "description": "safe",
                "supported": True,
                "unsafe": False,
            }],
            "reasoning": [{
                "id": "deep",
                "label": "Deep",
                "native": "openai/gpt-5.2#deep",
                "description": "variant",
                "default": False,
            }],
            "features": {
                "ask": True,
                "ask_transport": "question_api",
                "queue_mode": "service_fifo",
                "detail": "native",
            },
        }

    monkeypatch.setattr("ui.agent_settings_service.settings_catalog", fake_catalog)

    service = AgentSettingsService(repo, ttl_seconds=60)
    value = service.get(project, "opencode", "openai/gpt-5.2")
    assert value["reasoning"][0]["id"] == "deep"
    assert value["features"]["ask"] is True
    assert value["models"] == ["openai/gpt-5.2"]
    assert service.get(project, "opencode", "openai/gpt-5.2")["cached"] is True
    assert calls == 1



def test_chat_queue_snapshots_reasoning_per_item(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.enqueue_turn(
        project,
        session_id,
        "deep work",
        request_id="reasoning-1",
        backend="opencode",
        model="openai/gpt-5.2",
        mode="auto",
        reasoning="deep",
    )
    claimed = chat.claim_next(project, session_id)
    assert claimed is not None
    assert claimed["reasoning"] == "deep"
    assert claimed["model"] == "openai/gpt-5.2"


def test_chat_agent_passes_snapshotted_reasoning_to_runner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[dict] = []

    def fake_runner(**kwargs):
        calls.append(dict(kwargs))
        return {"text": "ok", "session_id": "native"}

    chat = ChatService()
    service = ChatAgentService(repo, runner=fake_runner)
    session_id = chat.sessions(project)["active_session_id"]
    result = service.turn(
        project,
        chat,
        session_id=session_id,
        message="reason",
        backend="opencode",
        model="openai/gpt-5.2",
        mode="auto",
        reasoning="deep",
        request_id="reasoning-turn-1",
    )
    assert result["turn_id"].startswith("turn-")
    assert result["queue_item_id"].startswith("queue-")
    assert calls[0]["reasoning"] == "deep"
    assert calls[0]["model"] == "openai/gpt-5.2"



def test_chat_ask_is_durable_session_scoped_and_validated(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    first = chat.sessions(project)["active_session_id"]
    second = chat.create_session(project, request_id="ask-second-session")["session_id"]

    created = chat.create_ask(
        project,
        first,
        request_id="turn-request-1",
        turn_id="turn-stable-1",
        questions=[
            {
                "id": "approach",
                "header": "Approach",
                "question": "Which approach?",
                "options": [
                    {"value": "safe", "label": "Safe", "description": "Keep compatibility"},
                    {"value": "clean", "label": "Clean"},
                ],
            },
            {
                "id": "features",
                "header": "Features",
                "question": "Which features?",
                "kind": "multi_choice",
                "options": [
                    {"value": "queue", "label": "Queue"},
                    {"value": "ask", "label": "Ask"},
                    {"value": "tasks", "label": "Tasks"},
                ],
            },
            {
                "id": "reason",
                "header": "Reason",
                "question": "Why?",
                "kind": "text",
            },
        ],
    )
    ask_id = created["ask"]["ask_id"]
    assert created["ask"]["turn_id"] == "turn-stable-1"
    assert created["ask"]["questions"][0]["allow_other"] is True
    assert chat.ask(project, second)["ask"] is None

    restarted = ChatService()
    pending = restarted.ask(project, first)["ask"]
    assert pending["ask_id"] == ask_id
    assert pending["status"] == "waiting"

    try:
        restarted.submit_ask(
            project,
            first,
            ask_id,
            {"approach": {"other": ""}, "reason": ""},
            request_id="answer-1",
        )
    except ValueError as exc:
        assert "answer" in str(exc).lower()
    else:
        raise AssertionError("blank Ask answer was accepted")

    answered = restarted.submit_ask(
        project,
        first,
        ask_id,
        {
            "approach": {"other": "Use a narrow compatibility shim"},
            "features": {"values": ["queue", "ask", "queue"], "other": "Native form"},
            "reason": "It limits migration risk",
        },
        request_id="answer-2",
    )
    assert answered["ask"]["status"] == "answered"
    assert answered["ask"]["answers"]["approach"]["other"] == "Use a narrow compatibility shim"
    assert answered["ask"]["answers"]["features"] == {
        "values": ["queue", "ask"],
        "other": "Native form",
    }
    repeated = restarted.submit_ask(
        project,
        first,
        ask_id,
        {
            "approach": {"value": "safe"},
            "reason": "ignored duplicate payload",
        },
        request_id="answer-2",
    )
    assert repeated["duplicate"] is True
    assert repeated["ask"]["answers"]["approach"]["other"] == "Use a narrow compatibility shim"


def test_chat_ask_multi_choice_requires_at_least_one_value_or_custom_answer(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="multi-turn",
        questions=[{
            "id": "features",
            "header": "Features",
            "question": "Pick any",
            "multiple": True,
            "options": ["queue", "ask"],
        }],
    )
    question = created["ask"]["questions"][0]
    assert question["kind"] == "multi_choice"
    with pytest.raises(ValueError, match="required"):
        chat.submit_ask(
            project,
            session_id,
            created["ask"]["ask_id"],
            {"features": {"values": []}},
            request_id="multi-empty",
        )


def test_native_ask_answer_continues_same_chat_turn(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    started = threading.Event()
    resolved = threading.Event()
    payload = {
        "id": "native-question-1",
        "sessionID": "ses-native",
        "questions": [{
            "header": "Approach",
            "question": "Choose one",
            "options": [{"label": "Safe"}],
        }],
    }
    native_calls: list[dict] = []

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(
            ask=True,
            ask_transport="daemon_permission_request",
        ),
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.ensure_native_session",
        lambda *args, **kwargs: "ses-native",
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.pending_native_ask",
        lambda *args, **kwargs: None if resolved.is_set() else (payload if started.is_set() else None),
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.normalize_ask_request",
        lambda *args, **kwargs: [{
            "id": "q1",
            "header": "Approach",
            "question": "Choose one",
            "options": ["Safe"],
        }],
    )

    def resolve(*args, **kwargs):
        native_calls.append({
            "answers": kwargs.get("answers") if "answers" in kwargs else args[4],
            "cancelled": kwargs.get("cancelled", False),
        })
        resolved.set()

    monkeypatch.setattr("ui.chat_agent_service.resolve_native_ask", resolve)

    def fake_runner(**kwargs):
        assert kwargs["session_id"] == "ses-native"
        started.set()
        assert resolved.wait(timeout=4)
        return {"text": "continued after answer", "session_id": "ses-native"}

    service = ChatAgentService(repo, runner=fake_runner)
    turn_result: list[dict] = []
    worker = threading.Thread(
        target=lambda: turn_result.append(service.turn(
            project,
            chat,
            session_id=session_id,
            message="Need a decision",
            backend="opencode",
            request_id="native-turn-1",
        )),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=2)

    deadline = __import__("time").monotonic() + 4
    ask = None
    while __import__("time").monotonic() < deadline:
        ask = chat.ask(project, session_id)["ask"]
        if ask and ask["status"] == "waiting":
            break
        __import__("time").sleep(0.05)
    assert ask is not None
    assert ask["source"] == "native"

    completed = service.complete_ask(
        project,
        chat,
        session_id=session_id,
        ask_id=ask["ask_id"],
        request_id="native-answer-1",
        answers={"q1": {"value": "Safe"}},
    )
    assert completed["ask"]["status"] == "answered"
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert native_calls == [{
        "answers": {"q1": {"value": "Safe"}},
        "cancelled": False,
    }]
    assert turn_result[0]["status"] == "idle"
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "Need a decision",
        "continued after answer",
    ]
    assert chat.agent_session(project, session_id, "opencode") == "ses-native"


def test_native_ask_cancel_rejects_and_unblocks_same_turn(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    started = threading.Event()
    rejected = threading.Event()
    payload = {
        "id": "native-question-cancel",
        "sessionID": "ses-native",
        "questions": [{
            "header": "Confirm",
            "question": "Continue?",
            "options": [{"label": "Yes"}, {"label": "No"}],
        }],
    }

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(ask=True, ask_transport="question_api"),
    )
    monkeypatch.setattr("ui.chat_agent_service.ensure_native_session", lambda *args, **kwargs: "ses-native")
    monkeypatch.setattr(
        "ui.chat_agent_service.pending_native_ask",
        lambda *args, **kwargs: None if rejected.is_set() else (payload if started.is_set() else None),
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.normalize_ask_request",
        lambda *args, **kwargs: [{
            "id": "q1", "header": "Confirm", "question": "Continue?", "options": ["Yes", "No"],
        }],
    )
    native_cancel: list[bool] = []

    def resolve(*args, **kwargs):
        native_cancel.append(bool(kwargs.get("cancelled")))
        rejected.set()

    monkeypatch.setattr("ui.chat_agent_service.resolve_native_ask", resolve)

    def fake_runner(**kwargs):
        started.set()
        assert rejected.wait(timeout=4)
        return {"text": "continued after reject", "session_id": "ses-native"}

    service = ChatAgentService(repo, runner=fake_runner)
    worker = threading.Thread(
        target=lambda: service.turn(
            project,
            chat,
            session_id=session_id,
            message="Ask then cancel",
            backend="opencode",
            request_id="native-turn-cancel",
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=2)
    deadline = __import__("time").monotonic() + 4
    ask = None
    while __import__("time").monotonic() < deadline:
        ask = chat.ask(project, session_id)["ask"]
        if ask and ask["status"] == "waiting":
            break
        __import__("time").sleep(0.05)
    assert ask is not None
    completed = service.complete_ask(
        project,
        chat,
        session_id=session_id,
        ask_id=ask["ask_id"],
        request_id="native-cancel-1",
        cancelled=True,
    )
    assert completed["ask"]["status"] == "cancelled"
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert native_cancel == [True]


def test_failed_native_ask_turn_is_cancelled_immediately_and_queue_unblocks(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    started = threading.Event()
    release_failure = threading.Event()
    native_cancelled = threading.Event()
    payload = {
        "id": "native-question-failed-turn",
        "sessionID": "ses-native",
        "questions": [{
            "header": "Confirm",
            "question": "Continue?",
            "options": [{"label": "Yes"}, {"label": "No"}],
        }],
    }

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(
            ask=True,
            ask_transport="daemon_permission_request",
        ),
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.ensure_native_session",
        lambda *args, **kwargs: "ses-native",
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.pending_native_ask",
        lambda *args, **kwargs: (
            None
            if native_cancelled.is_set()
            else (payload if started.is_set() else None)
        ),
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.normalize_ask_request",
        lambda *args, **kwargs: [{
            "id": "q1",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["Yes", "No"],
        }],
    )
    native_cancel_calls: list[bool] = []

    def resolve(*args, **kwargs):
        native_cancel_calls.append(bool(kwargs.get("cancelled")))
        native_cancelled.set()

    monkeypatch.setattr("ui.chat_agent_service.resolve_native_ask", resolve)

    def fake_runner(**kwargs):
        if kwargs["prompt"] == "later":
            return {"text": "later reply", "session_id": "ses-native"}
        started.set()
        assert release_failure.wait(timeout=4)
        raise RuntimeError("backend died after asking")

    service = ChatAgentService(repo, runner=fake_runner)
    turn_result: list[dict] = []
    worker = threading.Thread(
        target=lambda: turn_result.append(service.turn(
            project,
            chat,
            session_id=session_id,
            message="ask then fail",
            backend="qwen",
            request_id="native-failed-turn",
        )),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=2)

    deadline = time.monotonic() + 4
    ask = None
    while time.monotonic() < deadline:
        ask = chat.ask(project, session_id)["ask"]
        if ask and ask["status"] == "waiting":
            break
        time.sleep(0.05)
    assert ask is not None
    assert ask["source"] == "native"

    chat.enqueue_turn(
        project,
        session_id,
        "later",
        request_id="after-failed-native-ask",
        backend="qwen",
    )
    release_failure.set()
    worker.join(timeout=5)
    assert not worker.is_alive()

    assert turn_result[0]["status"] == "error"
    assert "backend died after asking" in turn_result[0]["error"]
    assert chat.ask(project, session_id)["ask"]["status"] == "cancelled"
    assert native_cancel_calls == [True]
    assert [row["content"] for row in chat.queue(project, session_id)["items"]] == ["later"]

    drained = service.drain(project, chat, session_id=session_id)
    assert drained["status"] == "idle"
    assert chat.queue(project, session_id)["items"] == []
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]][-2:] == [
        "later",
        "later reply",
    ]


def test_failed_turn_cleanup_does_not_cancel_another_turns_native_ask(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="other-turn-native-ask",
        turn_id="turn-other",
        questions=[{
            "id": "q1",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["Yes", "No"],
        }],
        source="native",
        backend="qwen",
        agent_session_id="ses-native",
        native_request_id="native-other",
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.resolve_native_ask",
        lambda *args, **kwargs: pytest.fail("another turn Ask must not be resolved"),
    )
    service = ChatAgentService(repo, runner=lambda **kwargs: {})

    assert service._cancel_failed_turn_native_ask(
        project,
        chat,
        session_id=session_id,
        turn_id="turn-failed",
    ) == ""
    current = chat.ask(project, session_id)["ask"]
    assert current["ask_id"] == created["ask"]["ask_id"]
    assert current["status"] == "waiting"


def test_native_ask_transport_failure_rolls_back_to_waiting(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="native-failure-question",
        turn_id="native-failure-turn",
        questions=[{
            "id": "q1",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["Yes", "No"],
        }],
        source="native",
        backend="opencode",
        agent_session_id="ses-native",
        native_request_id="native-failure",
    )
    payload = {
        "id": "native-failure",
        "sessionID": "ses-native",
        "questions": [{
            "header": "Confirm",
            "question": "Continue?",
            "options": [{"label": "Yes"}, {"label": "No"}],
        }],
    }
    monkeypatch.setattr(
        "ui.chat_agent_service.pending_native_ask",
        lambda *args, **kwargs: payload,
    )
    monkeypatch.setattr(
        "ui.chat_agent_service.resolve_native_ask",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("reply failed")),
    )
    service = ChatAgentService(repo, runner=lambda **kwargs: {})
    with pytest.raises(RuntimeError, match="reply failed"):
        service.complete_ask(
            project,
            chat,
            session_id=session_id,
            ask_id=created["ask"]["ask_id"],
            request_id="native-failure-answer",
            answers={"q1": {"value": "Yes"}},
        )
    restored = chat.ask(project, session_id)["ask"]
    assert restored["status"] == "waiting"
    context = chat.ask_context(project, session_id, restored["ask_id"])
    assert context["answers"] is None


def test_chat_ask_cancel_and_http_contract(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    project_query = urllib.parse.quote(str(project))
    try:
        created = _json_request(
            f"{base}/api/chat/ask/demo",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "request_id": "http-turn-1",
            },
        )
        ask_id = created["ask"]["ask_id"]
        assert len(created["ask"]["questions"]) == 3
        assert created["ask"]["questions"][0]["kind"] == "choice"
        assert created["ask"]["questions"][1]["kind"] == "multi_choice"

        pending = _json_request(
            f"{base}/api/chat/ask?project={project_query}&session_id={session_id}"
        )
        assert pending["ask"]["ask_id"] == ask_id

        cancelled = _json_request(
            f"{base}/api/chat/ask/cancel",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "ask_id": ask_id,
                "request_id": "cancel-http-1",
            },
        )
        assert cancelled["ask"]["status"] == "cancelled"
        repeated = _json_request(
            f"{base}/api/chat/ask/cancel",
            method="POST",
            body={
                "project": str(project),
                "session_id": session_id,
                "ask_id": ask_id,
                "request_id": "cancel-http-1",
            },
        )
        assert repeated["duplicate"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



def test_native_ask_http_submit_is_idempotent_and_uses_chat_agent_owner(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()

    server = UIServer(repo, "127.0.0.1", 0)
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    created = server.state.chat_service.create_ask(
        project,
        session_id,
        request_id="native-http-question",
        turn_id="native-http-turn",
        questions=[{
            "id": "q1",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["Yes", "No"],
        }],
        source="native",
        backend="opencode",
        agent_session_id="ses-native",
        native_request_id="native-http-request",
    )
    ask_id = created["ask"]["ask_id"]
    native_calls: list[tuple[str, bool]] = []

    def fake_resolve(project_arg, chat_arg, *, session_id, ask_id, cancelled=False):
        native_calls.append((ask_id, cancelled))

    server.state.chat_agent.resolve_ask = fake_resolve
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"
    body = {
        "project": str(project),
        "session_id": session_id,
        "ask_id": ask_id,
        "answers": {"q1": {"value": "Yes"}},
        "request_id": "native-http-answer",
    }
    try:
        first = _json_request(
            f"{base}/api/chat/ask/submit",
            method="POST",
            body=body,
        )
        assert first["ask"]["status"] == "answered"
        repeated = _json_request(
            f"{base}/api/chat/ask/submit",
            method="POST",
            body=body,
        )
        assert repeated["duplicate"] is True
        assert native_calls == [(ask_id, False)]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_waiting_ask_blocks_new_turns_into_session_queue_until_resolved(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    calls: list[str] = []
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    chat.create_ask(
        project,
        session_id,
        request_id="ask-turn-1",
        turn_id="turn-ask-1",
        questions=[{
            "id": "confirm",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["yes", "no"],
        }],
    )
    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: (
            calls.append(kwargs["prompt"])
            or {"text": "reply-" + kwargs["prompt"], "session_id": "native"}
        ),
    )

    for index, message in enumerate(("one", "two", "three"), start=1):
        result = service.turn(
            project,
            chat,
            session_id=session_id,
            message=message,
            backend="qwen",
            mode="auto",
            request_id=f"ask-queued-{index}",
        )
        assert result["status"] == "waiting_ask"
        assert result["busy"] is True

    assert calls == []
    status = service.status(project, chat, session_id=session_id)
    assert status["busy"] is True
    assert status["status"] == "waiting_ask"
    assert [row["content"] for row in chat.queue(project, session_id)["items"]] == [
        "one", "two", "three",
    ]
    ask_id = chat.ask(project, session_id)["ask"]["ask_id"]
    chat.submit_ask(
        project,
        session_id,
        ask_id,
        {"confirm": {"value": "yes"}},
        request_id="ask-answer-1",
    )
    drained = service.drain(project, chat, session_id=session_id)
    assert drained["status"] == "idle"
    assert calls == ["one", "two", "three"]
    assert chat.queue(project, session_id)["items"] == []



def test_chat_queue_migrates_legacy_processing_and_done_statuses(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    queued = chat.enqueue_turn(
        project,
        session_id,
        "legacy",
        request_id="legacy-status-1",
        backend="qwen",
    )
    queue_item_id = queued["queue_item_id"]
    state_path = project / ".ai-task-runner" / "ui" / "chat" / "state.json"
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw["version"] = 4
    legacy_queue = raw["sessions"][0]["queue"][0]
    legacy_queue["queue_id"] = legacy_queue.pop("queue_item_id")
    legacy_queue.pop("turn_id", None)
    legacy_queue["status"] = "processing"
    legacy_request = raw["turn_requests"]["legacy-status-1"]
    legacy_request["queue_id"] = legacy_request.pop("queue_item_id")
    legacy_request.pop("turn_id", None)
    legacy_request["status"] = "processing"
    raw["turn_requests"]["finished"] = {
        "session_id": session_id,
        "queue_id": queue_item_id,
        "status": "done",
    }
    state_path.write_text(json.dumps(raw), encoding="utf-8")

    restarted = ChatService()
    snapshot = restarted.queue(project, session_id)
    assert snapshot["dispatching"]["status"] == "dispatching"
    migrated_turn_id = snapshot["dispatching"]["turn_id"]
    assert migrated_turn_id.startswith("turn-")
    assert ChatService().queue(project, session_id)["dispatching"]["turn_id"] == migrated_turn_id

    normalized = json.loads(restarted._state_path(project).read_text(encoding="utf-8"))
    # Loading is migration-only; persisted rewrite happens on the next state mutation.
    restarted.recover_dispatching(project, session_id)
    normalized = json.loads(restarted._state_path(project).read_text(encoding="utf-8"))
    assert normalized["version"] == STATE_VERSION
    assert normalized["sessions"][0]["queue"][0]["status"] == "queued"
    assert normalized["sessions"][0]["queue"][0]["turn_id"] == migrated_turn_id
    assert normalized["sessions"][0]["queue"][0]["queue_item_id"] == queue_item_id
    assert "queue_id" not in normalized["sessions"][0]["queue"][0]
    assert normalized["turn_requests"]["legacy-status-1"]["turn_id"] == migrated_turn_id
    assert normalized["turn_requests"]["legacy-status-1"]["queue_item_id"] == queue_item_id
    assert "queue_id" not in normalized["turn_requests"]["legacy-status-1"]
    assert normalized["turn_requests"]["legacy-status-1"]["status"] == "queued"


def test_waiting_ask_timeout_is_durable_and_unblocks_queue(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="timeout-question",
        turn_id="timeout-turn",
        questions=[{
            "id": "confirm",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["yes", "no"],
        }],
        timeout_seconds=0.01,
    )
    chat.enqueue_turn(
        project,
        session_id,
        "queued after timeout",
        request_id="timeout-queued-turn",
        backend="qwen",
    )
    time.sleep(0.02)

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(),
    )
    service = ChatAgentService(
        repo,
        runner=lambda **kwargs: {
            "text": "continued after timeout",
            "session_id": "session-after-timeout",
        },
    )
    result = service.drain(project, chat, session_id=session_id)

    assert result["status"] == "idle"
    assert chat.ask(project, session_id)["ask"]["ask_id"] == created["ask"]["ask_id"]
    assert chat.ask(project, session_id)["ask"]["status"] == "cancelled"
    assert chat.queue(project, session_id)["items"] == []
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "Ask timed out; the pending Agent question was cancelled.",
        "queued after timeout",
        "continued after timeout",
    ]


def test_expired_native_ask_cancel_is_idempotent_when_agent_request_is_already_gone(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="native-timeout-question",
        turn_id="native-timeout-turn",
        questions=[{
            "id": "confirm",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["yes", "no"],
        }],
        source="native",
        backend="opencode",
        agent_session_id="ses-native",
        native_request_id="native-timeout-request",
        timeout_seconds=0.01,
    )
    time.sleep(0.02)
    monkeypatch.setattr(
        "ui.chat_agent_service.pending_native_ask",
        lambda *args, **kwargs: None,
    )

    service = ChatAgentService(repo, runner=lambda **kwargs: {})
    status = service.status(project, chat, session_id=session_id)

    assert status["status"] == "idle"
    assert status["waiting_ask"] is False
    assert chat.ask(project, session_id)["ask"]["ask_id"] == created["ask"]["ask_id"]
    assert chat.ask(project, session_id)["ask"]["status"] == "cancelled"


def test_restart_recovers_unowned_inflight_ask_resolution(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    created = chat.create_ask(
        project,
        session_id,
        request_id="restart-question",
        turn_id="restart-turn",
        questions=[{
            "id": "confirm",
            "header": "Confirm",
            "question": "Continue?",
            "options": ["yes", "no"],
        }],
    )
    chat.begin_ask_resolution(
        project,
        session_id,
        created["ask"]["ask_id"],
        {"confirm": {"value": "yes"}},
        request_id="restart-answer",
    )

    restarted = ChatAgentService(repo, runner=lambda **kwargs: {})
    status = restarted.status(project, chat, session_id=session_id)

    assert status["status"] == "waiting_ask"
    assert status["waiting_ask"] is True
    restored = chat.ask(project, session_id)["ask"]
    assert restored["status"] == "waiting"
    assert chat.ask_context(project, session_id, restored["ask_id"])["answer_request_id"] == ""


def test_chat_agent_tool_uses_shared_timeout_contract(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    captured: dict[str, object] = {}

    class Process:
        returncode = 0

        def poll(self):
            return 0

        def communicate(self, input=None, timeout=None):
            captured["input"] = input
            captured["timeout"] = timeout
            return json.dumps({"text": "ok", "session_id": "native"}), ""

    def fake_popen(command, **kwargs):
        captured["command"] = list(command)
        captured["options"] = dict(kwargs)
        return Process()

    monkeypatch.setattr("ui.chat_agent_service.subprocess.Popen", fake_popen)
    service = ChatAgentService(repo)
    value = service._run_tool(
        execution_key=(str(project), "chat-test", "queue-test"),
        project=project,
        backend="qwen",
        model="model-a",
        mode="auto",
        reasoning="high",
        session_id="session-a",
        prompt="hello",
    )

    command = captured["command"]
    assert command[command.index("--timeout") + 1] == str(CHAT_AGENT_TIMEOUT_SECONDS)
    assert captured["timeout"] == CHAT_AGENT_TIMEOUT_SECONDS + CHAT_AGENT_WRAPPER_GRACE_SECONDS
    assert captured["input"] == "hello"
    assert value == {"text": "ok", "session_id": "native"}


def test_chat_agent_tool_timeout_signals_then_forces_cleanup(tmp_path: Path, monkeypatch) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)

    class Process:
        returncode = None

        def __init__(self):
            self.calls = 0
            self.signalled = False
            self.killed = False

        def poll(self):
            return self.returncode

        def terminate(self):
            self.signalled = True

        def send_signal(self, _signal):
            self.signalled = True

        def kill(self):
            self.killed = True
            self.returncode = -9

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls <= 2:
                raise subprocess.TimeoutExpired("chat-agent", timeout or 0)
            return "", ""

    process = Process()
    monkeypatch.setattr(
        "ui.chat_agent_service.subprocess.Popen",
        lambda *args, **kwargs: process,
    )
    service = ChatAgentService(repo)

    with pytest.raises(
        RuntimeError,
        match=f"timed out after {CHAT_AGENT_TIMEOUT_SECONDS} seconds",
    ):
        service._run_tool(
            execution_key=(str(project), "chat-timeout", "queue-timeout"),
            project=project,
            backend="qwen",
            model="",
            mode="auto",
            reasoning="",
            session_id="",
            prompt="hang",
        )

    assert process.signalled is True
    assert process.killed is True
    assert process.calls == 3
    assert CHAT_AGENT_CANCEL_GRACE_SECONDS > 0


def test_chat_turn_cancel_marks_current_item_cancelled_and_runs_queued_next_turn(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    started = threading.Event()
    release = threading.Event()
    calls: list[str] = []
    result_box: dict[str, dict] = {}

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(),
    )

    def fake_runner(**kwargs):
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        if prompt == "first":
            started.set()
            assert release.wait(timeout=4)
        return {"text": f"reply {prompt}", "session_id": "agent-session"}

    service = ChatAgentService(repo, runner=fake_runner)
    worker = threading.Thread(
        target=lambda: result_box.setdefault(
            "value",
            service.turn(
                project,
                chat,
                session_id=session_id,
                message="first",
                backend="qwen",
                request_id="turn-cancel-first",
            ),
        ),
        daemon=True,
    )
    worker.start()
    assert started.wait(timeout=2)

    queued = service.turn(
        project,
        chat,
        session_id=session_id,
        message="second",
        backend="qwen",
        request_id="turn-cancel-second",
    )
    assert queued["status"] == "queued"

    first_cancel = service.cancel_turn(project, chat, session_id=session_id)
    repeated_cancel = service.cancel_turn(project, chat, session_id=session_id)
    assert first_cancel["cancelled"] is True
    assert first_cancel["duplicate"] is False
    assert repeated_cancel["duplicate"] is True

    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert result_box["value"]["status"] == "idle"
    assert len(result_box["value"]["cancelled"]) == 1
    assert calls == ["first", "second"]
    assert chat.queue(project, session_id)["items"] == []
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "first",
        "Agent turn cancelled.",
        "second",
        "reply second",
    ]


def test_chat_turn_cancel_http_endpoint_is_non_blocking_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    (repo / "ui" / "data").mkdir(parents=True)
    (repo / "ui" / "static").mkdir(parents=True)
    project.mkdir()
    started = threading.Event()
    release = threading.Event()
    response_box: dict[str, dict] = {}

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(),
    )

    def fake_runner(**kwargs):
        started.set()
        assert release.wait(timeout=4)
        return {"text": "should be discarded", "session_id": "agent-session"}

    server = UIServer(repo, "127.0.0.1", 0)
    server.state.chat_agent = ChatAgentService(repo, runner=fake_runner)
    server.state.project_preferences.update(project, {"agent": "qwen"})
    session_id = server.state.chat_service.sessions(project)["active_session_id"]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.port}"

    turn_thread = threading.Thread(
        target=lambda: response_box.setdefault(
            "turn",
            _json_request(
                f"{base}/api/chat/turn",
                method="POST",
                body={
                    "project": str(project),
                    "session_id": session_id,
                    "message": "long turn",
                    "request_id": "http-cancel-turn",
                },
            ),
        ),
        daemon=True,
    )
    try:
        turn_thread.start()
        assert started.wait(timeout=2)
        cancelled = _json_request(
            f"{base}/api/chat/turn/cancel",
            method="POST",
            body={"project": str(project), "session_id": session_id, "request_id": "http-cancel-request"},
        )
        repeated = _json_request(
            f"{base}/api/chat/turn/cancel",
            method="POST",
            body={"project": str(project), "session_id": session_id, "request_id": "http-cancel-request"},
        )
        assert cancelled["status"] == "cancelling"
        assert cancelled["cancelled"] is True
        assert cancelled["duplicate"] is False
        assert repeated["duplicate"] is True

        release.set()
        turn_thread.join(timeout=5)
        assert not turn_thread.is_alive()
        assert response_box["turn"]["status"] == "idle"
        assert len(response_box["turn"]["cancelled"]) == 1
        assert [row["content"] for row in server.state.chat_service.messages(project, session_id)["messages"]] == [
            "long turn",
            "Agent turn cancelled.",
        ]
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_stale_stop_after_item_execution_does_not_cancel_next_queue_item(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    project = repo / "project"
    project.mkdir(parents=True)
    chat = ChatService()
    session_id = chat.sessions(project)["active_session_id"]
    finalize_started = threading.Event()
    release_finalize = threading.Event()
    calls: list[str] = []
    result_box: dict[str, dict] = {}

    monkeypatch.setattr(
        "ui.chat_agent_service.chat_features",
        lambda *args, **kwargs: ChatFeatureSpec(),
    )

    def fake_runner(**kwargs):
        prompt = str(kwargs["prompt"])
        calls.append(prompt)
        return {"text": f"reply {prompt}", "session_id": "agent-session"}

    original_complete = chat.complete_queue_item

    def blocking_complete(project_arg, session_arg, queue_item_id, *, outcome="completed"):
        if outcome == "completed" and not finalize_started.is_set():
            finalize_started.set()
            assert release_finalize.wait(timeout=4)
        return original_complete(project_arg, session_arg, queue_item_id, outcome=outcome)

    chat.complete_queue_item = blocking_complete
    service = ChatAgentService(repo, runner=fake_runner)
    worker = threading.Thread(
        target=lambda: result_box.setdefault(
            "value",
            service.turn(
                project,
                chat,
                session_id=session_id,
                message="first",
                backend="qwen",
                request_id="stale-stop-first",
            ),
        ),
        daemon=True,
    )
    worker.start()
    assert finalize_started.wait(timeout=2)

    queued = service.turn(
        project,
        chat,
        session_id=session_id,
        message="second",
        backend="qwen",
        request_id="stale-stop-second",
    )
    assert queued["status"] == "queued"

    stale = service.cancel_turn(project, chat, session_id=session_id)
    assert stale["cancelled"] is False
    assert stale["status"] == "idle"

    release_finalize.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert result_box["value"]["cancelled"] == []
    assert calls == ["first", "second"]
    assert [row["content"] for row in chat.messages(project, session_id)["messages"]] == [
        "first",
        "reply first",
        "second",
        "reply second",
    ]
