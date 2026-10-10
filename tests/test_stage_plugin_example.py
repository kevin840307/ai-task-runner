"""Keep the documented external Stage example executable."""

from pathlib import Path

from runner.workflow.loader import load_workflow
from runner.workflow.registry import STAGE_REGISTRY, create_stage, stage_catalog
from runner.workflow.stages import StageResult


EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "12_custom_stage_plugin"


def test_echo_plugin_example_registers_and_uses_probe_input(monkeypatch):
    monkeypatch.syspath_prepend(str(EXAMPLE / "src"))
    from echo_stage_plugin import setup

    setup()
    try:
        assert {item["name"] for item in stage_catalog()["echo"]["options"]} == {"status", "prefix"}
        definition = load_workflow(EXAMPLE / "workflow.yaml")[0]
        stage = create_stage(definition)
        previous = StageResult("input", "pass", output="hello")
        result = stage.run(None, previous)
        assert result.status == "pass"
        assert result.output == "Echo: hello"
    finally:
        STAGE_REGISTRY.pop("echo", None)
