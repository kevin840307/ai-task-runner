import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module_imports(filename: str) -> set[str]:
    path = ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package_parts = path.relative_to(ROOT).parent.parts
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                base = package_parts[: max(0, len(package_parts) - node.level + 1)]
                modules.add(".".join([*base, node.module]))
            else:
                modules.add(node.module)
    return modules


def test_core_ownership_is_obvious():
    for package in ("flow", "model", "extensions", "agent", "engine"):
        assert not (ROOT / "runner" / package).exists()
    for package in ("workflow", "ai", "runtime", "backends", "plugins", "project", "utils", "prompts"):
        assert (ROOT / "runner" / package).is_dir()


def test_task_runner_uses_stage_executor_and_never_concrete_stage_types():
    source = (ROOT / "runner/task_runner.py").read_text(encoding="utf-8")
    assert "StageExecutor" in source
    assert "build_pipeline" in source
    for name in ("BaseStage", "PlanStage", "ReviewStage", "ValidateStage"):
        assert name not in source


def test_stage_executor_is_only_hook_boundary():
    executor = (ROOT / "runner/workflow/stages/executor.py").read_text(encoding="utf-8")
    assert ".hooks.before(" in executor
    assert ".hooks.after(" in executor
    for path in (ROOT / "runner/workflow/stages").glob("*.py"):
        if path.name in {"executor.py", "__init__.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert ".hooks.before(" not in source
        assert ".hooks.after(" not in source
        assert "current_runtime().hooks" not in source


def test_stage_never_uses_graph_or_transition_objects():
    for path in (ROOT / "runner/workflow/stages").glob("*.py"):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        assert "flow.next(" not in source
        assert "Transition(" not in source
        assert "FlowDefinition" not in source


def test_ai_package_contains_only_ai_concerns():
    names = {path.name for path in (ROOT / "runner/ai").glob("*.py")}
    assert {"client.py", "contracts.py", "session.py", "structured_output.py", "diagnostics.py", "errors.py", "__init__.py"} <= names
    for forbidden in ("retry.py", "trace.py", "history.py"):
        assert forbidden not in names


def test_runtime_does_not_own_ai_calls_or_stage_hooks():
    runtime_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "runner/runtime").glob("*.py"))
    assert ".ask(" not in runtime_source
    assert "hooks.before(" not in runtime_source
    assert "hooks.after(" not in runtime_source


def test_root_python_files_stay_minimal():
    assert {path.name for path in ROOT.glob("*.py")} == {"ai_task_runner.py", "ai_task_runner_validator.py"}


def test_recovery_is_centralized_in_stage_executor():
    assert not (ROOT / "runner/utils/recovery.py").exists()
    source = (ROOT / "runner/workflow/stages/executor.py").read_text(encoding="utf-8")
    for token in ("same_failures", "fresh_session_round", "is_transient_error", "_fresh_session"):
        assert token in source


def test_ai_contracts_are_separate_from_backend_implementations():
    contracts = (ROOT / "runner/ai/contracts.py").read_text(encoding="utf-8")
    base = (ROOT / "runner/backends/base.py").read_text(encoding="utf-8")
    assert "class AIBackend(Protocol)" in contracts
    assert "class AIClientProtocol(Protocol)" in contracts
    assert "class BaseBackend(ABC)" in base


def test_project_and_utils_ownership_is_explicit():
    project = {path.name for path in (ROOT / "runner/project").glob("*.py")}
    assert {"files.py", "policy.py", "instructions.py", "__init__.py"} <= project
    utils = {path.name for path in (ROOT / "runner/utils").glob("*.py")}
    assert utils == {"files.py", "logs.py", "text.py", "__init__.py"}


def test_registries_are_not_hidden_in_contract_or_package_init_files():
    assert (ROOT / "runner/backends/registry.py").is_file()
    assert (ROOT / "runner/plugins/registry.py").is_file()
    backend_init = (ROOT / "runner/backends/__init__.py").read_text(encoding="utf-8")
    plugin_contracts = (ROOT / "runner/plugins/contracts.py").read_text(encoding="utf-8")
    assert "def create_backend(" not in backend_init
    assert "current_runtime" not in plugin_contracts


def test_workflow_uses_semantic_progress_not_raw_event_transport():
    workflow = ROOT / "runner" / "workflow"
    for path in workflow.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "runtime import events" not in source, path
        assert "runtime.events" not in source, path
        assert "publish(\"runner." not in source, path


def test_internal_config_has_no_namespace_compatibility_layer():
    runtime = (ROOT / "runner/config/runtime.py").read_text(encoding="utf-8")
    bootstrap = (ROOT / "runner/bootstrap.py").read_text(encoding="utf-8")
    assert "argparse" not in runtime
    assert "from_namespace" not in runtime
    assert "to_namespace" not in runtime
    assert "argparse.Namespace" not in bootstrap


def test_loop_context_compression_is_a_plugin():
    plugin = ROOT / "runner/plugins/context_compression.py"
    client = (ROOT / "runner/ai/client.py").read_text(encoding="utf-8")
    assert plugin.is_file()
    assert "class ContextCompressionPlugin" in plugin.read_text(encoding="utf-8")
    assert "loop_context_compress" not in client
    for path in (ROOT / "runner/workflow").rglob("*.py"):
        assert "context_compress" not in path.read_text(encoding="utf-8")

    for relative in (
        "ai_task_runner.py",
        "runner/config/runtime.py",
        "runner/script_loader.py",
        "runner/script_runner.py",
    ):
        assert "loop_context_compress" not in (ROOT / relative).read_text(encoding="utf-8")


def test_console_and_script_runner_do_not_own_event_transport():
    console = (ROOT / "runner/plugins/console.py").read_text(encoding="utf-8")
    script = (ROOT / "runner/script_runner.py").read_text(encoding="utf-8")
    for legacy in ("event_callback", "json_events", "log_path", "def _emit("):
        assert legacy not in console
    for transport in ("event_callback", "json_events", "human_output"):
        assert transport not in script


def test_public_capabilities_use_owner_modules_without_reexport_only_facades():
    assert not (ROOT / "runner/tooling.py").exists()
    root_init = (ROOT / "runner/__init__.py").read_text(encoding="utf-8")
    assert "__getattr__" not in root_init
    assert "RunRequest" not in root_init
    assert "RunResult" not in root_init
    for relative in (
        "runner/ai/__init__.py",
        "runner/backends/__init__.py",
        "runner/config/__init__.py",
        "runner/utils/__init__.py",
    ):
        tree = ast.parse((ROOT / relative).read_text(encoding="utf-8"))
        assert not any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)), relative
