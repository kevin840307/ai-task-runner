from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tool.chat_turn import _bounded_history, run_chat


class FakeClient:
    def __init__(self, session_id="", *, fail_invalid=False):
        self.session_id = session_id
        self.backend = "fake"
        self.model = "fake-model"
        self.prompts = []
        self.fail_invalid = fail_invalid

    def ask(self, prompt, timeout=None):
        self.prompts.append(prompt)
        if self.fail_invalid:
            self.session_id = ""
            from runner.agent import AIError
            raise AIError("session old is unavailable")
        if not self.session_id:
            self.session_id = "session-new"
        return "answer"


def config_factory(clients):
    def factory(config, root, **kwargs):
        client = FakeClient(kwargs.get("session_id", ""))
        clients.append((client, kwargs))
        return client
    return factory


def test_chat_turn_fresh_session_gets_bounded_history(tmp_path):
    clients = []
    result = run_chat(
        {
            "message": "latest",
            "history": [
                {"role": "user", "text": "earlier"},
                {"role": "assistant", "text": "reply"},
            ],
        },
        project=tmp_path,
        backend="fake",
        model="",
        session_id="",
        client_factory=config_factory(clients),
    )

    client, kwargs = clients[0]
    assert result["text"] == "answer"
    assert result["session_id"] == "session-new"
    assert kwargs["mode"] == "planning"
    assert kwargs["allow_project_read"] is True
    assert "earlier" in client.prompts[0]
    assert "latest" in client.prompts[0]


def test_chat_turn_same_session_sends_only_new_message(tmp_path):
    clients = []
    run_chat(
        {
            "message": "follow up",
            "history": [{"role": "user", "text": "do not repeat me"}],
        },
        project=tmp_path,
        backend="fake",
        model="",
        session_id="session-existing",
        client_factory=config_factory(clients),
    )

    prompt = clients[0][0].prompts[0]
    assert "follow up" in prompt
    assert "do not repeat me" not in prompt


def test_chat_turn_invalidated_session_rebuilds_once_from_history(tmp_path):
    clients = []

    def factory(config, root, **kwargs):
        current = kwargs.get("session_id", "")
        client = FakeClient(current, fail_invalid=bool(current))
        clients.append((client, kwargs))
        return client

    result = run_chat(
        {
            "message": "latest",
            "history": [
                {"role": "user", "text": "earlier"},
                {"role": "assistant", "text": "reply"},
            ],
        },
        project=tmp_path,
        backend="fake",
        model="fake-model",
        session_id="stale-session",
        client_factory=factory,
    )

    assert len(clients) == 2
    assert clients[0][1]["session_id"] == "stale-session"
    assert clients[1][1]["session_id"] == ""
    assert "earlier" not in clients[0][0].prompts[0]
    assert "earlier" in clients[1][0].prompts[0]
    assert result["session_id"] == "session-new"
    assert result["text"] == "answer"


def test_bounded_history_keeps_recent_messages_only():
    rows = [{"role": "user", "text": str(index) * 3000} for index in range(60)]
    bounded = _bounded_history(rows)
    assert len(bounded) <= 40
    assert sum(len(row["text"]) for row in bounded) <= 43000
    assert bounded[-1]["text"].startswith("59")


def test_chat_turn_rejects_empty_message(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        run_chat(
            {"message": "", "history": []},
            project=tmp_path,
            backend="fake",
            model="",
            session_id="",
            client_factory=config_factory([]),
        )
