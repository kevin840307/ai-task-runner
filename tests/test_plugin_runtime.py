from pathlib import Path
from types import SimpleNamespace

import pytest

from runner.plugins.runtime import HookChain


def _action(tmp_path: Path):
    return SimpleNamespace(
        root=tmp_path,
        work=tmp_path / ".ai-task-runner",
        mode="write",
        actor="test",
    )


def test_hook_chain_runs_before_in_order_after_in_reverse_and_deduplicates(tmp_path):
    calls = []

    class Hook:
        def __init__(self, name):
            self.name = name

        def before_execution(self, action):
            calls.append(("before", self.name, action.actor))
            return self.name + "-token"

        def after_execution(self, action, token):
            calls.append(("after", self.name, token))
            return [self.name + "-violation"]

    first = Hook("first")
    second = Hook("second")
    chain = HookChain()
    chain.add(first)
    chain.add(first)
    chain.add(second)

    tokens = chain.before(_action(tmp_path))
    violations = chain.after(_action(tmp_path), tokens)

    assert calls == [
        ("before", "first", "test"),
        ("before", "second", "test"),
        ("after", "second", "second-token"),
        ("after", "first", "first-token"),
    ]
    assert violations == ["second-violation", "first-violation"]


def test_hook_chain_before_failure_cleans_up_prior_tokens_and_preserves_error(tmp_path):
    calls = []

    class First:
        def before_execution(self, _action):
            calls.append("first-before")
            return "token"

        def after_execution(self, _action, token):
            calls.append(("first-after", token))
            return []

    class Broken:
        def before_execution(self, _action):
            calls.append("broken-before")
            raise ValueError("policy setup failed")

    chain = HookChain()
    chain.add(First())
    chain.add(Broken())

    with pytest.raises(ValueError, match="policy setup failed"):
        chain.before(_action(tmp_path))

    assert calls == ["first-before", "broken-before", ("first-after", "token")]


def test_hook_chain_after_runs_all_cleanup_and_raises_first_reverse_order_error(tmp_path):
    calls = []

    class Hook:
        def __init__(self, name, error):
            self.name = name
            self.error = error

        def before_execution(self, _action):
            return self.name

        def after_execution(self, _action, _token):
            calls.append(self.name)
            raise self.error

    chain = HookChain()
    chain.add(Hook("first", RuntimeError("first failed")))
    chain.add(Hook("second", ValueError("second failed")))
    tokens = chain.before(_action(tmp_path))

    with pytest.raises(ValueError, match="second failed"):
        chain.after(_action(tmp_path), tokens)

    assert calls == ["second", "first"]


def test_hook_chain_wraps_change_detector_in_plugin_order(tmp_path):
    calls = []

    class Hook:
        def __init__(self, name):
            self.name = name

        def before_execution(self, _action):
            return self.name

        def wrap_change_detector(self, _action, token, base):
            def wrapped():
                calls.append(token)
                return base()
            return wrapped

    chain = HookChain()
    chain.add(Hook("first"))
    chain.add(Hook("second"))
    tokens = chain.before(_action(tmp_path))

    def base():
        calls.append("base")
        return True

    detector = chain.change_detector(_action(tmp_path), tokens, base)

    assert detector is not None
    assert detector() is True
    assert calls == ["second", "first", "base"]


def test_hook_chain_applies_environment_command_and_instruction_transforms(tmp_path):
    class First:
        def process_environment(self, environment):
            return {**environment, "FIRST": "1"}

        def process_command(self, command, environment):
            assert environment["BASE"] == "yes"
            return [*command, "--first"]

        def instructions(self, root):
            assert root == tmp_path
            return " First rule "

    class Second:
        def process_environment(self, environment):
            assert environment["FIRST"] == "1"
            return {**environment, "SECOND": "2"}

        def process_command(self, command, environment):
            assert command[-1] == "--first"
            return [*command, "--second"]

        def instructions(self, _root):
            return "Second rule"

    chain = HookChain()
    chain.add(First())
    chain.add(Second())

    assert chain.process_environment({"BASE": "yes"}) == {
        "BASE": "yes",
        "FIRST": "1",
        "SECOND": "2",
    }
    assert chain.process_command(["agent"], {"BASE": "yes"}) == [
        "agent",
        "--first",
        "--second",
    ]
    assert chain.instructions(tmp_path) == "First rule\nSecond rule"


def test_hook_chain_model_error_is_fail_soft_and_continues_other_plugins():
    class Broken:
        def model_error(self, _client, _error):
            raise RuntimeError("diagnostic plugin broke")

    class Healthy:
        def model_error(self, _client, error):
            error.diagnostics["healthy_plugin"] = "observed"

    chain = HookChain()
    chain.add(Broken())
    chain.add(Healthy())
    error = SimpleNamespace(diagnostics={})

    chain.model_error(SimpleNamespace(), error)

    assert error.diagnostics["plugin_error"] == (
        "RuntimeError: diagnostic plugin broke"
    )
    assert error.diagnostics["healthy_plugin"] == "observed"
