from __future__ import annotations

import io
from types import SimpleNamespace

from tool import task_draft_agent


def test_task_draft_agent_uses_canonical_backend_timeout(tmp_path, monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    class Backend:
        def configure_interaction(self, mode):
            captured["mode"] = mode

        def configure_reasoning(self, reasoning):
            captured["reasoning"] = reasoning

        def ask(self, prompt, session_id):
            assert "User specification:" in prompt
            assert session_id == ""
            return SimpleNamespace(
                text='{"title":"Generated","items":[{"title":"One","prompt":"Do one"}]}'
            )

    def fake_create_backend(name, _session, project_root, extra_args, *, timeout):
        captured["name"] = name
        captured["project_root"] = project_root
        captured["extra_args"] = list(extra_args)
        captured["timeout"] = timeout
        return Backend()

    monkeypatch.setattr(task_draft_agent, "create_backend", fake_create_backend)
    monkeypatch.setattr(
        task_draft_agent,
        "configure_interaction_args",
        lambda backend, mode, args: list(args),
    )
    monkeypatch.setattr(
        task_draft_agent,
        "configure_model_args",
        lambda backend, args, model: list(args),
    )
    monkeypatch.setattr(task_draft_agent.sys, "stdin", io.StringIO("build one task"))

    code = task_draft_agent.main([
        "--project-root",
        str(tmp_path),
        "--backend",
        "qwen",
        "--model",
        "model-a",
        "--reasoning",
        "high",
        "--draft-mode",
        "single",
    ])

    assert code == 0
    assert captured["timeout"] == task_draft_agent.TASK_DRAFT_AGENT_TIMEOUT_SECONDS
    assert captured["mode"] == "read"
    assert captured["reasoning"] == "high"
    assert '"draft"' in capsys.readouterr().out
