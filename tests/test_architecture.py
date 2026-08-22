import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = {
    "runner/state_store.py": {
        "runner.core",
        "runner.planning",
        "runner.reviewing",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/ai_validation.py": {
        "runner.core",
        "runner.file_validation",
        "runner.planning",
        "runner.reviewing",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/file_validation.py": {
        "runner.ai_validation",
        "runner.core",
        "runner.planning",
        "runner.reviewing",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/config.py": {
        "runner.agent",
        "runner.core",
        "runner.planning",
        "runner.reviewing",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/agent_factory.py": {
        "runner.core",
        "runner.planning",
        "runner.reviewing",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/agent_args.py": {
        "runner.planning",
        "runner.prompting",
        "runner.core",
        "runner.support",
        "runner.script_runner",
        "runner.ui",
        "runner.validation",
    },
    "runner/backends/qwen_args.py": {
        "runner.core",
        "runner.planning",
        "runner.prompting",
        "runner.reviewing",
        "runner.script_runner",
        "runner.support",
        "runner.ui",
        "runner.validation",
    },
    "runner/script_runner.py": {
        "runner.planning",
        "runner.prompting",
        "runner.core",
        "runner.support",
        "runner.ui",
        "runner.validation",
    },
    "runner/planning.py": {
        "runner.core",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/reviewing.py": {
        "runner.core",
        "runner.script_runner",
        "runner.validation",
    },
    "runner/model_results.py": {
        "runner.core",
        "runner.planning",
        "runner.prompting",
        "runner.reviewing",
        "runner.script_runner",
        "runner.support",
        "runner.ui",
        "runner.validation",
    },
    "runner/prompting.py": {
        "runner.core",
        "runner.support",
        "runner.script_runner",
        "runner.ui",
        "runner.validation",
    },
    "runner/validation.py": {
        "runner.planning",
        "runner.core",
        "runner.script_runner",
    },
    "runner/ui.py": {
        "runner.planning",
        "runner.prompting",
        "runner.core",
        "runner.support",
        "runner.script_runner",
        "runner.validation",
    },
}


def module_imports(filename: str) -> set[str]:
    path = ROOT / filename
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package_parts = path.relative_to(ROOT).parent.parts
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.level:
                base = package_parts[: max(0, len(package_parts) - node.level + 1)]
                modules.add(".".join([*base, node.module]))
            else:
                parts = node.module.split(".")
                modules.add(".".join(parts[:2]) if parts[0] == "runner" and len(parts) > 1 else parts[0])
    return modules


def test_helper_modules_do_not_import_back_into_orchestration():
    for filename, forbidden in FORBIDDEN_IMPORTS.items():
        imports = module_imports(filename)
        assert not imports.intersection(forbidden), filename


def test_core_depends_on_feature_modules():
    imports = module_imports("runner/core.py")
    assert {
        "runner.agent_factory",
        "runner.ai_validation",
        "runner.config",
        "runner.file_validation",
        "runner.planning",
        "runner.prompting",
        "runner.reviewing",
        "runner.script_runner",
        "runner.ui",
        "runner.state_store",
    } <= imports


def test_root_python_files_stay_minimal():
    assert {path.name for path in ROOT.glob("*.py")} == {
        "ai_task_runner.py",
        "ai_task_runner_validator.py",
    }


def test_in_run_resume_never_builds_a_new_client_from_an_existing_session():
    root = Path(__file__).resolve().parents[1]
    production = [
        root / "runner" / "planning.py",
        root / "runner" / "reviewing.py",
        root / "runner" / "ai_validation.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in production)
    assert "session_id=reviewer.session_id" not in source
    assert "session_id=draft_planner.session_id" not in source
    assert "new_planner(session_id=" not in source
