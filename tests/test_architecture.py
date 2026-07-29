import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_IMPORTS = {
    "agent_args.py": {
        "planning",
        "prompting",
        "runner_core",
        "runner_support",
        "script_runner",
        "ui",
        "validation",
    },
    "script_runner.py": {
        "planning",
        "prompting",
        "runner_core",
        "runner_support",
        "ui",
        "validation",
    },
    "planning.py": {
        "runner_core",
        "script_runner",
        "ui",
        "validation",
    },
    "prompting.py": {
        "runner_core",
        "runner_support",
        "script_runner",
        "ui",
        "validation",
    },
    "validation.py": {
        "planning",
        "runner_core",
        "script_runner",
    },
    "ui.py": {
        "planning",
        "prompting",
        "runner_core",
        "runner_support",
        "script_runner",
        "validation",
    },
}


def module_imports(filename: str) -> set[str]:
    tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_helper_modules_do_not_import_back_into_orchestration():
    for filename, forbidden in FORBIDDEN_IMPORTS.items():
        imports = module_imports(filename)
        assert not imports.intersection(forbidden), filename


def test_runner_core_depends_on_feature_modules():
    imports = module_imports("runner_core.py")
    assert {
        "agent_args",
        "planning",
        "prompting",
        "script_runner",
        "ui",
        "validation",
    } <= imports
