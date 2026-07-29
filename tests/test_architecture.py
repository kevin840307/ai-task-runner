import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = {
    "runner/agent_args.py": {
        "runner.planning",
        "runner.prompting",
        "runner.core",
        "runner.support",
        "runner.script_runner",
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
        "runner.agent_args",
        "runner.planning",
        "runner.prompting",
        "runner.script_runner",
        "runner.ui",
        "runner.validation",
    } <= imports


def test_root_python_files_stay_minimal():
    assert {path.name for path in ROOT.glob("*.py")} == {
        "ai_task_runner.py",
        "ai_task_runner_validator.py",
    }
