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
    for package in ("engine", "workflow", "agent", "ai"):
        assert not (ROOT / "runner" / package).exists()
    for package in ("flow", "model", "runtime", "backends", "extensions", "utils", "prompts"):
        assert (ROOT / "runner" / package).is_dir()


def test_task_runner_uses_stage_executor_and_never_concrete_stage_types():
    source = (ROOT / "runner/task_runner.py").read_text(encoding="utf-8")
    assert "StageExecutor" in source
    assert "build_pipeline" in source
    for name in ("GlobalStage", "PlanStage", "PythonValidationStage", "ReviewStage", "ValidateStage"):
        assert name not in source


def test_stage_executor_is_only_hook_boundary():
    executor = (ROOT / "runner/flow/stages/executor.py").read_text(encoding="utf-8")
    assert ".hooks.before(" in executor
    assert ".hooks.after(" in executor
    for path in (ROOT / "runner/flow/stages").glob("*.py"):
        if path.name in {"executor.py", "__init__.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        assert ".hooks.before(" not in source
        assert ".hooks.after(" not in source
        assert "current_runtime().hooks" not in source


def test_stage_never_uses_graph_or_transition_objects():
    for path in (ROOT / "runner/flow/stages").glob("*.py"):
        if path.name == "__init__.py":
            continue
        source = path.read_text(encoding="utf-8")
        assert "flow.next(" not in source
        assert "Transition(" not in source
        assert "FlowDefinition" not in source


def test_model_package_contains_only_model_concerns():
    names = {path.name for path in (ROOT / "runner/model").glob("*.py")}
    assert {"model.py", "session.py", "response.py", "errors.py", "prompt.py", "__init__.py"} <= names
    for forbidden in ("retry.py", "trace.py", "history.py"):
        assert forbidden not in names


def test_runtime_does_not_own_model_ask_or_stage_hooks():
    runtime_source = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "runner/runtime").glob("*.py"))
    assert "model.ask(" not in runtime_source
    assert "hooks.before(" not in runtime_source
    assert "hooks.after(" not in runtime_source


def test_root_python_files_stay_minimal():
    assert {path.name for path in ROOT.glob("*.py")} == {"ai_task_runner.py", "ai_task_runner_validator.py"}


def test_recovery_is_centralized_in_stage_executor():
    assert not (ROOT / "runner/utils/recovery.py").exists()
    source = (ROOT / "runner/flow/stages/executor.py").read_text(encoding="utf-8")
    for token in ("same_failures", "fresh_session_round", "_is_service_error", "_fresh_session"):
        assert token in source


def test_model_abstract_contracts_live_in_model_package():
    backend_sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "runner/backends").glob("*.py"))
    assert "class ModelBackend(ABC)" not in backend_sources
    model_package = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "runner/model").glob("*.py"))
    assert "class ModelBackend(ABC)" in model_package
    assert "class Model(Protocol)" in model_package
