from runner.agent.factory import AgentFactory
from runner.api import RunRequest
from runner.config import RuntimeConfig


def test_run_request_resolves_to_typed_runtime_config():
    request = RunRequest(
        goal="goal",
        validator="ai",
        agent_args=["--model", "test-model"],
        loop_context_compress=True,
        loop_context_compress_threshold=65,
    )

    config = request.to_runtime_config()

    assert isinstance(config, RuntimeConfig)
    assert config.agent_arg == ["--model", "test-model"]
    assert config.loop_context_compress is True
    assert config.loop_context_compress_threshold == 65
    assert request.to_namespace().agent_arg == config.agent_arg


def test_agent_factory_applies_shared_settings_to_every_stage(tmp_path):
    constructed = []

    def constructor(**kwargs):
        constructed.append(kwargs)
        return object()

    config = RuntimeConfig(
        backend="qwen",
        command="qwen-custom",
        agent_arg=["--model", "test-model"],
        agent_timeout=30,
        loop_context_compress=True,
        loop_context_compress_threshold=65,
    )
    factory = AgentFactory(
        config,
        tmp_path,
        tmp_path / "debug",
        constructor=constructor,
    )

    factory.create("runtime")
    factory.create("review", timeout=12)

    runtime, review = constructed
    assert runtime["timeout"] == 30
    assert review["timeout"] == 12
    assert runtime["loop_context_compress"] is True
    assert review["loop_context_compress"] is True
    assert runtime["loop_context_compress_threshold"] == 65
    assert review["loop_context_compress_threshold"] == 65
    assert "--model" in runtime["extra_args"]
    assert "--model" in review["extra_args"]


def test_agent_factory_can_preserve_precomputed_arguments(tmp_path):
    constructed = []

    def constructor(**kwargs):
        constructed.append(kwargs)
        return object()

    factory = AgentFactory(
        RuntimeConfig(),
        tmp_path,
        None,
        constructor=constructor,
    )

    factory.create("runtime", extra_args=["--legacy-arg"])

    assert constructed[0]["extra_args"] == ["--legacy-arg"]
