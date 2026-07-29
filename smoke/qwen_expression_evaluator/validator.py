#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import subprocess
import sys
import traceback
from pathlib import Path


EXPECTED_BATCH = [
    {"expression": "1 + 2 * 3", "result": 7.0},
    {"expression": "(10 - 4) / 3", "result": 2.0},
    {"expression": "-2.5 * (4 + 1)", "result": -12.5},
    {"expression": "8 / (2 + 2)", "result": 2.0},
    {"expression": "bad + 1", "error": "invalid"},
]


def fail(message: str) -> int:
    print(message)
    return 1


def require_completed_tasks(state_path: Path, minimum: int) -> int | None:
    if not state_path.is_file():
        return fail("missing runner state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks", [])
    if len(tasks) < minimum:
        return fail(f"expected at least {minimum} planned tasks, got {len(tasks)}")
    if any(task.get("status") != "completed" for task in tasks):
        return fail("not all planned tasks are completed")
    if any(not task.get("last_review", {}).get("completed") for task in tasks):
        return fail("every task must be reviewed as completed")
    return None


def close_enough(actual: float, expected: float) -> bool:
    return abs(float(actual) - expected) < 1e-9


def load_module(script: Path):
    spec = importlib.util.spec_from_file_location("expression_eval_case", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import expression_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def uses_forbidden_dynamic_execution(source: str) -> bool:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"eval", "exec"}:
            return True
        if isinstance(func, ast.Attribute) and func.attr in {"eval", "exec"}:
            return True
    return False


def exception_feedback(context: str) -> str:
    return f"{context}:\n" + traceback.format_exc(limit=6)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    root = Path(args.project_root)

    state_error = require_completed_tasks(Path(args.state_file), 3)
    if state_error is not None:
        return state_error

    script = root / "expression_eval.py"
    if not script.is_file():
        return fail("missing expression_eval.py")
    source = script.read_text(encoding="utf-8")
    try:
        if uses_forbidden_dynamic_execution(source):
            return fail("expression_eval.py must not call eval or exec")
    except SyntaxError as error:
        return fail(f"expression_eval.py has invalid Python syntax: {error}")

    try:
        module = load_module(script)
    except Exception as error:
        return fail(f"cannot import expression_eval.py: {error}")
    for expression, expected in {
        "1 + 2 * 3": 7.0,
        "(10 - 4) / 3": 2.0,
        "-2.5 * (4 + 1)": -12.5,
        "3.5 + .5": 4.0,
        "--4": 4.0,
    }.items():
        try:
            actual = module.evaluate(expression)
        except Exception as error:
            return fail(exception_feedback(f"evaluate({expression!r}) raised {error}"))
        if not close_enough(actual, expected):
            return fail(f"evaluate({expression!r}) returned {actual!r}, expected {expected!r}")

    cli = subprocess.run(
        [sys.executable, str(script), "1 + 2 * 3"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    if cli.returncode != 0 or cli.stdout.strip() not in {"7", "7.0"}:
        return fail("single-expression CLI failed:\n" + cli.stdout)

    batch = subprocess.run(
        [
            sys.executable,
            str(script),
            "--batch",
            "input/expressions.txt",
            "--json",
            "results.json",
            "--markdown",
            "results.md",
        ],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
    )
    if batch.returncode != 0:
        return fail("batch CLI failed:\n" + batch.stdout)

    results_path = root / "results.json"
    if not results_path.is_file():
        return fail("missing results.json")
    results = json.loads(results_path.read_text(encoding="utf-8"))
    if len(results) != len(EXPECTED_BATCH):
        return fail(f"expected {len(EXPECTED_BATCH)} batch rows, got {len(results)}")
    for actual, expected in zip(results, EXPECTED_BATCH):
        if actual.get("expression") != expected["expression"]:
            return fail("batch expression order mismatch")
        if "result" in expected:
            if "result" not in actual or not close_enough(actual["result"], expected["result"]):
                return fail("batch result mismatch:\n" + json.dumps(results, indent=2))
        elif "error" not in actual:
            return fail("invalid expression did not produce an error entry")

    markdown = (root / "results.md").read_text(encoding="utf-8") if (root / "results.md").is_file() else ""
    if "# Expression Results" not in markdown or "| Expression | Result |" not in markdown or "bad + 1" not in markdown:
        return fail("results.md missing required content")

    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").is_file() else ""
    for heading in ("## Usage", "## Supported syntax", "## Error handling", "## Examples"):
        if heading not in readme:
            return fail(f"README.md missing {heading}")

    print("PASS: expression evaluator")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
