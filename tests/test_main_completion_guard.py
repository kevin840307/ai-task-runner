from types import SimpleNamespace

import ai_task_runner


def _request(tmp_path):
    return ai_task_runner.RunRequest(goal="g", project_root=str(tmp_path), validator="ai", retry_delay=0)


def test_main_delegates_completion_guard_to_shared_api(monkeypatch, tmp_path):
    request = _request(tmp_path)
    calls = []
    monkeypatch.setattr(ai_task_runner.RunRequest, "from_namespace", classmethod(lambda cls, ns: request))
    monkeypatch.setattr(
        ai_task_runner,
        "run",
        lambda current: calls.append(current) or SimpleNamespace(exit_code=0),
    )
    assert ai_task_runner.main([]) == 0
    assert calls == [request]


