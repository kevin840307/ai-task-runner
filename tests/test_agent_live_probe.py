from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import tool.agent_live_probe as probe


def test_project_skill_fixture_is_shared_and_cleans_only_owned_paths(tmp_path: Path) -> None:
    existing = tmp_path / ".agents" / "skills" / "existing" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("existing", encoding="utf-8")

    with probe._project_skill_fixture(tmp_path) as path:
        assert path.is_file()
        content = path.read_text(encoding="utf-8")
        assert f"name: {probe.SKILL_NAME}" in content
        assert 'opencode/slash: "true"' in content
        assert existing.read_text(encoding="utf-8") == "existing"

    assert not (tmp_path / ".agents" / "skills" / probe.SKILL_NAME).exists()
    assert existing.read_text(encoding="utf-8") == "existing"


def test_project_skill_fixture_refuses_to_overwrite_existing_probe_skill(
    tmp_path: Path,
) -> None:
    path = tmp_path / ".agents" / "skills" / probe.SKILL_NAME
    path.mkdir(parents=True)

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        with probe._project_skill_fixture(tmp_path):
            pass


def test_validate_settings_requires_real_models_modes_queue_and_ask() -> None:
    value = probe._validate_settings(
        "sample",
        {
            "agent": "sample",
            "models": ["model-b", "model-a"],
            "modes": [
                {"id": "read", "supported": True},
                {"id": "auto", "supported": True},
                {"id": "yolo", "supported": True},
            ],
            "reasoning": [{"id": "high"}],
            "features": {
                "ask": True,
                "ask_transport": "native",
                "queue_mode": "service_fifo",
                "detail": "ok",
            },
        },
        require_ask=True,
    )

    assert value["models"] == ["model-b", "model-a"]
    assert value["modes"] == ["auto", "read", "yolo"]
    assert value["reasoning"] == ["high"]
    assert value["features"]["ask"] is True

    with pytest.raises(RuntimeError, match="no models"):
        probe._validate_settings(
            "sample",
            {
                "agent": "sample",
                "models": [],
                "modes": [{"id": "read"}, {"id": "auto"}],
                "features": {
                    "ask": True,
                    "ask_transport": "native",
                    "queue_mode": "service_fifo",
                },
            },
            require_ask=True,
        )
    with pytest.raises(RuntimeError, match="native Ask is unavailable"):
        probe._validate_settings(
            "sample",
            {
                "agent": "sample",
                "models": ["m"],
                "modes": [{"id": "read"}, {"id": "auto"}],
                "features": {
                    "ask": False,
                    "queue_mode": "service_fifo",
                    "detail": "not wired",
                },
            },
            require_ask=True,
        )


def test_validate_capabilities_requires_live_probe_skill_and_slash_command() -> None:
    value = probe._validate_capabilities(
        "sample",
        {
            "backend": "sample",
            "capabilities": [
                {
                    "kind": "command",
                    "name": "help",
                    "token": "/help",
                    "enabled": True,
                },
                {
                    "kind": "skill",
                    "name": probe.SKILL_NAME,
                    "token": f"/{probe.SKILL_NAME}",
                    "enabled": True,
                    "user_invocable": True,
                    "source": "project",
                },
            ],
        },
    )
    assert value["command_tokens"] == ["/help"]
    assert value["skill_token"] == f"/{probe.SKILL_NAME}"

    with pytest.raises(RuntimeError, match="Skill discovery"):
        probe._validate_capabilities(
            "sample",
            {
                "backend": "sample",
                "capabilities": [
                    {
                        "kind": "command",
                        "name": "help",
                        "token": "/help",
                        "enabled": True,
                    }
                ],
            },
        )


def test_parse_model_overrides_is_backend_scoped() -> None:
    assert probe._parse_model_overrides(
        ["qwen=qwen-model", "opencode=provider/model"]
    ) == {
        "qwen": "qwen-model",
        "opencode": "provider/model",
    }
    with pytest.raises(ValueError, match="BACKEND=MODEL"):
        probe._parse_model_overrides(["missing"])
    with pytest.raises(ValueError, match="duplicate"):
        probe._parse_model_overrides(["qwen=a", "qwen=b"])


def test_probe_backend_reuses_canonical_catalogs_and_chat_ping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        probe,
        "settings_catalog",
        lambda project, backend, model: {
            "agent": backend,
            "models": ["native/model"],
            "modes": [{"id": "read"}, {"id": "auto"}],
            "reasoning": [],
            "features": {
                "ask": True,
                "ask_transport": "native",
                "queue_mode": "service_fifo",
                "detail": "live",
            },
        },
    )
    monkeypatch.setattr(
        probe,
        "capability_catalog",
        lambda project, backend: {
            "backend": backend,
            "capabilities": [
                {
                    "kind": "command",
                    "name": "help",
                    "token": "/help",
                    "enabled": True,
                },
                {
                    "kind": "skill",
                    "name": probe.SKILL_NAME,
                    "token": f"/{probe.SKILL_NAME}",
                    "enabled": True,
                    "user_invocable": True,
                },
            ],
        },
    )
    calls = []
    monkeypatch.setattr(
        probe,
        "_run_chat_ping",
        lambda project, backend, model, timeout: (
            calls.append(("chat", Path(project), backend, model, timeout))
            or {"ok": True, "session_id": "s", "model_override": model}
        ),
    )
    monkeypatch.setattr(
        probe,
        "_run_native_ask_roundtrip",
        lambda project, backend, model, timeout: (
            calls.append(("ask", Path(project), backend, model, timeout))
            or {"ok": True, "question_count": 1, "answered": True, "continued": True}
        ),
    )

    value = probe.probe_backend(
        tmp_path,
        "sample",
        model="native/model",
        timeout=7,
    )

    assert value["status"] == "pass"
    assert value["model_count"] == 1
    assert value["native_ask"]["continued"] is True
    assert calls == [
        ("chat", tmp_path, "sample", "native/model", 7),
        ("ask", tmp_path, "sample", "native/model", 7),
    ]

def test_answers_for_ask_reuses_canonical_question_shape() -> None:
    answers = probe._answers_for_ask({
        "questions": [
            {
                "question_id": "choice",
                "kind": "choice",
                "options": [{"value": "continue", "label": "Continue"}],
            },
            {
                "question_id": "multi",
                "kind": "multi_choice",
                "options": [{"value": "queue", "label": "Queue"}],
            },
            {
                "question_id": "text",
                "kind": "text",
                "options": [],
            },
        ],
    })

    assert answers == {
        "choice": {"value": "continue"},
        "multi": {"values": ["queue"]},
        "text": "Continue",
    }


def test_native_ask_roundtrip_uses_chat_service_and_restores_active_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed = probe.ChatService()
    original = seed.sessions(tmp_path)
    original_session = original["active_session_id"]

    class FakeAgentService:
        def __init__(self, _root: Path) -> None:
            self.cancelled = False

        def turn(self, project, chat, **kwargs):
            created = chat.create_ask(
                project,
                kwargs["session_id"],
                request_id="native-probe-request",
                questions=[{
                    "id": "continue",
                    "header": "Live probe",
                    "question": "Continue live adapter probe?",
                    "options": [{"value": "continue", "label": "Continue"}],
                }],
                source="native",
                backend=kwargs["backend"],
                agent_session_id="native-session",
                native_request_id="native-request",
            )
            ask_id = created["ask"]["ask_id"]
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                current = chat.ask(project, kwargs["session_id"])["ask"]
                if isinstance(current, dict) and current["status"] == "answered":
                    chat.append_message(
                        project,
                        kwargs["session_id"],
                        "assistant",
                        probe.ASK_MARKER,
                    )
                    return {"status": "idle", "ask_id": ask_id}
                time.sleep(0.01)
            raise RuntimeError("answer was not delivered")

        def complete_ask(
            self,
            project,
            chat,
            *,
            session_id,
            ask_id,
            request_id,
            answers=None,
            cancelled=False,
        ):
            if cancelled:
                return chat.cancel_ask(
                    project,
                    session_id,
                    ask_id,
                    request_id=request_id,
                )
            return chat.submit_ask(
                project,
                session_id,
                ask_id,
                answers,
                request_id=request_id,
            )

        def cancel_turn(self, *args, **kwargs):
            self.cancelled = True
            return {"status": "cancelled"}

    monkeypatch.setattr(probe, "ChatAgentService", FakeAgentService)

    value = probe._run_native_ask_roundtrip(
        tmp_path,
        "sample",
        model="native/model",
        timeout=3,
    )

    assert value == {
        "ok": True,
        "question_count": 1,
        "answered": True,
        "continued": True,
    }
    after = seed.sessions(tmp_path)
    assert after["active_session_id"] == original_session
    assert [item["session_id"] for item in after["sessions"]] == [original_session]


def test_evidence_payload_marks_only_full_nondiagnostic_gate_and_redacts_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "_source_head", lambda: "source-head")
    results = [
        {
            "backend": backend,
            "status": "pass",
            "chat_ping": {
                "ok": True,
                "session_id": f"{backend}-native-session",
                "model_override": "",
            },
            "native_ask": {
                "ok": True,
                "question_count": 1,
                "answered": True,
                "continued": True,
            },
        }
        for backend in probe.DEFAULT_BACKENDS
    ]

    value = probe._evidence_payload(
        tmp_path,
        list(probe.DEFAULT_BACKENDS),
        results,
        ok=True,
        discovery_only=False,
        allow_missing=False,
        allow_no_ask=False,
    )

    assert value["schema_version"] == 1
    assert value["source_head"] == "source-head"
    assert value["formal_gate"] is True
    assert value["ok"] is True
    assert value["requested_backends"] == list(probe.DEFAULT_BACKENDS)
    assert value["recorded_at_utc"]
    for item in value["results"]:
        assert "session_id" not in item["chat_ping"]
        assert item["chat_ping"]["session_id_present"] is True

    diagnostic = probe._evidence_payload(
        tmp_path,
        list(probe.DEFAULT_BACKENDS),
        results,
        ok=True,
        discovery_only=True,
        allow_missing=False,
        allow_no_ask=False,
    )
    assert diagnostic["formal_gate"] is False
    assert diagnostic["diagnostic"]["discovery_only"] is True


def test_write_evidence_atomically_replaces_requested_json_path(tmp_path: Path) -> None:
    target = tmp_path / "evidence" / "agent-live.json"
    target.parent.mkdir()
    target.write_text('{"stale": true}\n', encoding="utf-8")
    payload = {"schema_version": 1, "formal_gate": True, "results": []}

    saved = probe._write_evidence(str(target), payload)

    assert saved == target.resolve()
    assert json.loads(target.read_text(encoding="utf-8")) == payload
    assert not target.with_name(target.name + ".tmp").exists()

