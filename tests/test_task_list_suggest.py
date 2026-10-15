from __future__ import annotations

import json

import pytest

import tool.task_list_suggest as suggest


class FakeClient:
    backend = "fake"
    model = "fake-model"

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def ask(self, prompt: str, timeout=None):
        self.prompts.append(prompt)
        return self.response


def test_parse_payload_preserves_order_and_rejects_invalid_shape():
    raw = json.dumps({"items": [{"instruction": "One"}, {"instruction": "Two"}]})
    assert suggest._parse_payload(raw) == [
        {"instruction": "One"},
        {"instruction": "Two"},
    ]
    with pytest.raises(Exception):
        suggest._parse_payload(json.dumps({"items": []}))


def test_context_is_bounded_and_keeps_recent_conversation():
    history = [
        {"role": "user", "text": f"old-{index}-" + ("x" * 1200)}
        for index in range(40)
    ]
    context = suggest._context(history)
    assert len(context) <= suggest.MAX_CONTEXT_CHARS + 1500
    assert "old-39-" in context
    assert "old-0-" not in context


def test_run_uses_canonical_read_only_agent_and_returns_ordered_preview(tmp_path, monkeypatch):
    client = FakeClient(json.dumps({
        "items": [
            {"instruction": "Inspect"},
            {"instruction": "Implement"},
            {"instruction": "Validate"},
        ]
    }))
    captured = {}

    def factory(config, project, **kwargs):
        captured["config"] = config
        captured["project"] = project
        captured["kwargs"] = kwargs
        return client

    monkeypatch.setattr(suggest, "create_ai_client", factory)
    result = suggest.run(
        {
            "request": "Refactor safely",
            "history": [{"role": "user", "text": "Keep compatibility"}],
        },
        tmp_path,
        "fake",
        "fake-model",
    )

    assert [item["instruction"] for item in result["items"]] == [
        "Inspect", "Implement", "Validate"
    ]
    assert captured["project"] == tmp_path
    assert captured["kwargs"]["mode"] == "planning"
    assert captured["kwargs"]["allow_project_read"] is True
    assert captured["kwargs"]["session_id"] == ""
    assert captured["kwargs"]["model_override"] == "fake-model"
    assert captured["config"].force_new is True
    assert captured["config"].auto_register_ui_project is False
    assert "Do not edit files or run the Task" in client.prompts[0]
    assert "Keep compatibility" in client.prompts[0]
