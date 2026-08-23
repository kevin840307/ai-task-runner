import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ORCHESTRATION = {
    "runner.api",
    "runner.engine.core",
    "runner.app.script_runner",
    "runner.workflow.planning",
    "runner.workflow.reviewing",
    "runner.workflow.model_calls",
    "runner.workflow.validation.ai",
    "runner.workflow.validation.file",
}

FORBIDDEN_IMPORTS = {
    "runner/config/runtime.py": ORCHESTRATION | {"runner.agent"},
    "runner/engine/state_store.py": ORCHESTRATION,
    "runner/agent/arguments.py": ORCHESTRATION,
    "runner/agent/calls.py": ORCHESTRATION,
    "runner/agent/debug.py": ORCHESTRATION,
    "runner/agent/prompts.py": ORCHESTRATION,
    "runner/agent/results.py": ORCHESTRATION,
    "runner/backends/qwen_args.py": ORCHESTRATION,
    "runner/safety/git_guard.py": ORCHESTRATION,
    "runner/safety/policy.py": ORCHESTRATION,
    "runner/safety/project_guard.py": ORCHESTRATION,
    "runner/workflow/planning.py": {
        "runner.engine.core",
        "runner.app.script_runner",
        "runner.workflow.reviewing",
        "runner.workflow.validation.ai",
        "runner.workflow.validation.file",
    },
    "runner/workflow/reviewing.py": {
        "runner.engine.core",
        "runner.app.script_runner",
        "runner.workflow.planning",
        "runner.workflow.validation.ai",
        "runner.workflow.validation.file",
    },
    "runner/workflow/model_calls.py": {
        "runner.engine.core",
        "runner.app.script_runner",
        "runner.workflow.planning",
        "runner.workflow.reviewing",
        "runner.workflow.validation.ai",
        "runner.workflow.validation.file",
    },
    "runner/workflow/validation/ai.py": {
        "runner.engine.core",
        "runner.app.script_runner",
        "runner.workflow.planning",
        "runner.workflow.reviewing",
        "runner.workflow.validation.file",
    },
    "runner/workflow/validation/file.py": {
        "runner.engine.core",
        "runner.app.script_runner",
        "runner.workflow.planning",
        "runner.workflow.reviewing",
        "runner.workflow.validation.ai",
    },
}


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


def test_lower_layers_do_not_import_back_into_orchestration():
    for filename, forbidden in FORBIDDEN_IMPORTS.items():
        imports = module_imports(filename)
        assert not imports.intersection(forbidden), filename


def test_core_depends_only_on_graph_stage_and_generic_runtime_layers():
    imports = module_imports("runner/engine/core.py")
    required = {
        "runner.workflow.flow",
        "runner.workflow.stages",
        "runner.runtime",
        "runner.runtime.project_state",
        "runner.agent",
    }
    assert required <= imports
    assert not {name for name in imports if name.startswith("runner.safety") or name.startswith("runner.extensions.")}


def test_root_python_files_stay_minimal():
    assert {path.name for path in ROOT.glob("*.py")} == {
        "ai_task_runner.py",
        "ai_task_runner_validator.py",
    }


def test_in_run_resume_never_builds_a_new_client_from_an_existing_session():
    production = [
        ROOT / "runner" / "workflow" / "planning.py",
        ROOT / "runner" / "workflow" / "reviewing.py",
        ROOT / "runner" / "workflow" / "validation" / "ai.py",
    ]
    source = "\n".join(path.read_text(encoding="utf-8") for path in production)
    assert "session_id=reviewer.session_id" not in source
    assert "session_id=draft_planner.session_id" not in source
    assert "new_planner(session_id=" not in source
