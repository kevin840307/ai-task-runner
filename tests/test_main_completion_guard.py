from types import SimpleNamespace

import ai_task_runner


def _request(tmp_path):
    return ai_task_runner.RunRequest(goal="g", project_root=str(tmp_path), validator="ai", retry_delay=0)


def test_main_repeats_until_run_result_is_completed(monkeypatch, tmp_path):
    request = _request(tmp_path)
    calls = []
    results = iter([
        SimpleNamespace(exit_code=0, completed=False, state_files=()),
        SimpleNamespace(exit_code=0, completed=True, state_files=()),
    ])
    monkeypatch.setattr(ai_task_runner.RunRequest, "from_namespace", classmethod(lambda cls, ns: request))
    monkeypatch.setattr(ai_task_runner, "run", lambda current: calls.append((current.resume, current.force_new)) or next(results))
    monkeypatch.setattr(ai_task_runner, "_report_error", lambda *args, **kwargs: None)
    assert ai_task_runner.main([]) == 0
    assert len(calls) == 2


def test_main_does_not_exit_on_nonzero_unfinished_result(monkeypatch, tmp_path):
    request = _request(tmp_path)
    calls = []
    results = iter([
        SimpleNamespace(exit_code=7, completed=False, state_files=()),
        SimpleNamespace(exit_code=0, completed=True, state_files=()),
    ])
    monkeypatch.setattr(ai_task_runner.RunRequest, "from_namespace", classmethod(lambda cls, ns: request))
    monkeypatch.setattr(ai_task_runner, "run", lambda current: calls.append(True) or next(results))
    monkeypatch.setattr(ai_task_runner, "_report_error", lambda *args, **kwargs: None)
    assert ai_task_runner.main([]) == 0
    assert len(calls) == 2


def test_plan_only_may_exit_without_validator_completion(monkeypatch, tmp_path):
    request = _request(tmp_path)
    request.plan_only = True
    monkeypatch.setattr(ai_task_runner.RunRequest, "from_namespace", classmethod(lambda cls, ns: request))
    monkeypatch.setattr(ai_task_runner, "run", lambda current: SimpleNamespace(exit_code=0, completed=False, state_files=()))
    assert ai_task_runner.main([]) == 0
