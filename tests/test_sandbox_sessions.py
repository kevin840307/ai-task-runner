from __future__ import annotations

import json
from pathlib import Path

import runner.backends.qwen as qwen
from runner.backends.base import AgentMode
from runner.backends.qwen import QwenBackend, bridge_sandbox_session
from runner.runtime.process_control import ProcessResult


def _backend(root: Path, extra_args=("--sandbox",)) -> QwenBackend:
    command = root / "qwen-test"
    command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    command.chmod(0o755)
    return QwenBackend(str(command), root, list(extra_args), 120)


def test_bridge_sandbox_session_rewrites_container_cwd_to_host_project(tmp_path):
    projects = tmp_path / "projects"
    source = projects / "-workspace" / "chats" / "session-1.jsonl"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({"cwd": "/workspace", "message": "keep"}) + "\n", encoding="utf-8")
    host = tmp_path / "host" / "project"
    host.mkdir(parents=True)

    bridge_sandbox_session(host, "session-1", projects)

    project_id = __import__("re").sub(r"[^a-zA-Z0-9]", "-", str(host.resolve()))
    target = projects / project_id / "chats" / "session-1.jsonl"
    record = json.loads(target.read_text(encoding="utf-8"))
    assert record["cwd"] == str(host.resolve())
    assert record["message"] == "keep"


def test_resume_with_sandbox_bridges_same_session(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(qwen, "bridge_sandbox_session", lambda root, session: calls.append((root, session)))
    backend = _backend(tmp_path)
    command = backend.build_command("work", "same-session")
    assert calls == [(tmp_path, "same-session")]
    assert command[command.index("--resume") + 1] == "same-session"


def test_context_command_with_sandbox_bridges_same_session(tmp_path, monkeypatch):
    bridges = []
    commands = []
    monkeypatch.setattr(qwen, "bridge_sandbox_session", lambda root, session: bridges.append(session))
    monkeypatch.setattr(qwen, "run_process", lambda command, root, timeout: commands.append(command) or ProcessResult("Used 50.0k tokens (50.0%)", 0, False))
    backend = _backend(tmp_path)
    assert "50.0%" in backend.context_snapshot("same-session")
    assert bridges == ["same-session"]
    assert "--resume" in commands[0] and "same-session" in commands[0]


def test_compress_command_with_sandbox_bridges_same_session(tmp_path, monkeypatch):
    bridges = []
    commands = []
    monkeypatch.setattr(qwen, "bridge_sandbox_session", lambda root, session: bridges.append(session))
    monkeypatch.setattr(qwen, "run_process", lambda command, root, timeout: commands.append(command) or ProcessResult("compressed", 0, False))
    backend = _backend(tmp_path)
    assert backend.compress_session("same-session") == "compressed"
    assert bridges == ["same-session"]
    assert "/compress-fast" in commands[0]
