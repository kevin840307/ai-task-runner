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
    for name in ("AIStage", "PlanStage", "PythonValidatorStage", "ReviewStage", "ValidateStage"):
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
    for token in ("same_failures", "fresh_session_round", "_is_service_error", "_fresh_session"):
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
    assert utils == {"files.py", "text.py", "__init__.py"}


def test_registries_are_not_hidden_in_contract_or_package_init_files():
    assert (ROOT / "runner/backends/registry.py").is_file()
    assert (ROOT / "runner/plugins/registry.py").is_file()
    backend_init = (ROOT / "runner/backends/__init__.py").read_text(encoding="utf-8")
    plugin_contracts = (ROOT / "runner/plugins/contracts.py").read_text(encoding="utf-8")
    assert "def create_backend(" not in backend_init
    assert "current_runtime" not in plugin_contracts
