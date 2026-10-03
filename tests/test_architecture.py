from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_runner_top_level_domains_are_small_and_obvious():
    runner = ROOT / "runner"
    directories = {
        path.name
        for path in runner.iterdir()
        if path.is_dir() and not path.name.startswith("__")
    }
    assert directories == {"agent", "assets", "config", "plugins", "runtime", "workflow"}


def test_agent_owns_client_backend_and_provider_adapters():
    agent = ROOT / "runner" / "agent"
    assert {
        "backend.py",
        "client.py",
        "qwen.py",
        "opencode.py",
        "structured.py",
        "__init__.py",
    } <= {path.name for path in agent.glob("*.py")}
    assert not (ROOT / "runner" / "ai").exists()
    assert not (ROOT / "runner" / "backends").exists()


def test_workspace_and_script_are_single_owner_modules():
    assert (ROOT / "runner" / "workspace.py").is_file()
    assert (ROOT / "runner" / "script.py").is_file()
    assert (ROOT / "runner" / "utils.py").is_file()
    assert not (ROOT / "runner" / "project").exists()
    assert not (ROOT / "runner" / "script_loader.py").exists()
    assert not (ROOT / "runner" / "script_runner.py").exists()
    assert not (ROOT / "runner" / "utils").exists()


def test_assets_are_one_package_with_separate_workflow_and_prompt_roots():
    assets = ROOT / "runner" / "assets"
    workflows = assets / "workflows"
    prompts = assets / "prompts"
    assert {"ai.yaml", "file.yaml", "mixed.yaml", "dynamic_handoff.yaml", "ralphy_ai_validate.yaml"} <= {
        path.name for path in workflows.glob("*.yaml")
    }
    assert {"common", "ralphy"} <= {
        path.name for path in prompts.iterdir() if path.is_dir()
    }
    assert not (prompts / "workflow").exists()
    assert not (workflows / "discussion.yaml").exists()
    assert not (prompts / "common" / "discussion.md").exists()
    assert not (prompts / "common" / "discussion_controller.md").exists()
    assert not (prompts / "common" / "discussion_judge.md").exists()
    assert not (prompts / "common" / "discussion_final_validator.md").exists()
    assert not (ROOT / "runner" / "workflows").exists()
    assert not (ROOT / "runner" / "prompts").exists()


def test_workflow_has_explicit_result_and_resource_owners():
    workflow = ROOT / "runner" / "workflow"
    for name in ("contracts.py", "flow_engine.py", "loader.py", "schema.py", "registry.py", "results.py"):
        assert (workflow / name).is_file()
    for removed in (
        "lifecycle.py",
        "reducers.py",
        "linear_routing.py",
        "semantic_routing.py",
        "pipeline.py",
        "routing.py",
        "recovery.py",
        "rules.py",
    ):
        assert not (workflow / removed).exists()
    assert (ROOT / "runner" / "resources.py").is_file()


def test_stage_executor_is_the_only_stage_retry_owner():
    executor = (ROOT / "runner/workflow/execution/stage_executor.py").read_text(encoding="utf-8")
    for token in ("stage_retries", "retry_delay", "retry_max_delay", "_fresh_session"):
        assert token in executor
    for path in (ROOT / "runner/workflow/stages").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "stage_retries" not in text
        assert "retry_max_delay" not in text


def test_plugins_have_one_discovery_boundary():
    registry = (ROOT / "runner/plugins/registry.py").read_text(encoding="utf-8")
    assert 'PLUGIN_ENTRYPOINT_GROUP = "ai_task_runner.plugins"' in registry
    assert "def discover_plugins" in registry
    assert "def register_plugins" in registry
    assert not (ROOT / "runner" / "extensions.py").exists()


def test_workflow_runner_uses_shared_engine_executor_and_resources():
    source = (ROOT / "runner/workflow_runner.py").read_text(encoding="utf-8")
    assert "build_flow_engine" in source
    assert "StageExecutor" in source
    assert "freeze_workflow" in source
    assert "load_snapshot" in source
    assert not (ROOT / "runner/task_runner.py").exists()


def test_workflow_cursor_writes_are_owned_by_flow_engine():
    allowed = ROOT / "runner" / "workflow" / "flow_engine.py"
    patterns = (
        "state.workflow_position =",
        "self.context.state.workflow_position =",
    )
    offenders = []
    for path in (ROOT / "runner").rglob("*.py"):
        if path == allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in patterns:
            if pattern in text:
                offenders.append(f"{path.relative_to(ROOT)}: {pattern}")
    assert offenders == []



def test_removed_task_scope_runtime_fields_do_not_reappear():
    offenders = []
    forbidden = (
        "task_step",
        'get("scope")',
        "get('scope')",
        '["scope"]',
        "['scope']",
        "scope: task",
    )
    for path in (ROOT / "runner").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in source:
                offenders.append(f"{path.relative_to(ROOT)}: {token}")
    assert offenders == []


def test_stage_implementations_are_split_by_responsibility():
    stages = ROOT / "runner" / "workflow" / "stages"
    expected = {
        "base_stage.py",
        "plan_stage.py",
        "ai_validator_stage.py",
        "command_stage.py",
        "handoff_stage.py",
        "__init__.py",
    }
    assert expected <= {path.name for path in stages.glob("*.py")}
    assert not (stages / "core.py").exists()
    assert not (stages / "executor.py").exists()
    assert (ROOT / "runner" / "workflow" / "execution" / "stage_executor.py").is_file()


def test_stage_executor_is_workflow_orchestration_not_a_stage_type():
    registry = (ROOT / "runner" / "workflow" / "registry.py").read_text(encoding="utf-8")
    executor = (ROOT / "runner" / "workflow" / "execution" / "stage_executor.py").read_text(encoding="utf-8")
    assert '"executor"' not in registry
    assert "class StageExecutor" in executor
    assert "stage_retries" in executor
    assert "_fresh_session" in executor



def test_stage_executor_does_not_depend_on_concrete_stage_types():
    executor = (ROOT / "runner" / "workflow" / "execution" / "stage_executor.py").read_text(encoding="utf-8")
    for concrete in (
        "PlanStage",
        "AIValidatorStage",
        "CommandStage",
        "HandoffStage",
    ):
        assert concrete not in executor
    assert "from ..contracts import" in executor
