from types import SimpleNamespace

from runner.agent import Agent, configure_agent, create_agent


class FakeAgent:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
    def set_extra_args(self, values):
        self.extra_args = list(values)


def config(**overrides):
    values = dict(
        backend="qwen", command="fake", agent_arg=["--x"], sandbox=False,
        agent_timeout=12, loop_context_compress=False,
        loop_context_compress_threshold=50,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_create_agent_applies_shared_settings_without_factory(tmp_path):
    agent = create_agent(config(), tmp_path, tmp_path / "debug", constructor=FakeAgent)
    assert agent.root == tmp_path
    assert agent.timeout == 12
    assert agent.debug_dir == tmp_path / "debug"


def test_create_agent_preserves_precomputed_arguments(tmp_path):
    agent = create_agent(config(), tmp_path, constructor=FakeAgent, extra_args=["--custom"])
    assert "--custom" in agent.extra_args


def test_configure_agent_reuses_existing_instance(tmp_path):
    agent = create_agent(config(), tmp_path, constructor=FakeAgent)
    identity = id(agent)
    configure_agent(agent, config(), "planning", allow_project_read=True)
    assert id(agent) == identity
    assert isinstance(agent.extra_args, list)
