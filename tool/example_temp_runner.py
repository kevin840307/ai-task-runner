from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Sequence

import yaml

SOURCE_ROOT = Path(__file__).resolve().parents[1]
_IGNORED_NAMES = {".git", ".pytest_cache", "__pycache__", ".mypy_cache", ".ruff_cache"}


def _copy_workspace(label: str) -> Path:
    base = Path(os.environ.get("AI_TASK_RUNNER_EXAMPLE_TEMP", tempfile.gettempdir())) / "ai-task-runner-examples"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = base / f"{label}-{stamp}-{os.getpid()}"

    def ignore(_path: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _IGNORED_NAMES or name.endswith((".pyc", ".pyo"))}

    shutil.copytree(SOURCE_ROOT, target, ignore=ignore)
    return target


def _example_items(root: Path) -> list[dict[str, object]]:
    data = yaml.safe_load((root / "examples" / "examples.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("examples/examples.yaml must contain a root-level list")
    return [item for item in data if isinstance(item, dict)]


def _select_example(root: Path, name: str) -> Path:
    prefix = f"{name}/"
    selected = [item for item in _example_items(root) if str(item.get("project_root", "")).replace("\\", "/").startswith(prefix)]
    if len(selected) != 1:
        raise ValueError(f"example {name!r} matched {len(selected)} items in examples/examples.yaml")
    path = root / "examples" / ".selected-example.yaml"
    path.write_text(yaml.safe_dump(selected, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def _runner_command(root: Path, script: Path, extra: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        str(root / "ai_task_runner.py"),
        "--loop-context-compress",
        "--project-root",
        str(root / "examples"),
        "--script",
        str(script),
        *extra,
    ]


def _run(command: Sequence[str], cwd: Path) -> int:
    print(f"[example-temp] command: {subprocess.list2cmdline(list(command))}")
    return subprocess.call(list(command), cwd=cwd)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run examples from a fresh temporary copy of the repository.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run examples/examples.yaml from the temporary copy.")
    group.add_argument("--example", help="Run one example folder listed in examples/examples.yaml.")
    group.add_argument("--exec", dest="exec_relative", help="Run one Python file from the temporary copy.")
    p.add_argument("args", nargs=argparse.REMAINDER, help="Arguments after -- are forwarded to the Runner or Python file.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    extra = list(ns.args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    label = "all" if ns.all else (Path(ns.example).name if ns.example else Path(ns.exec_relative).stem)
    root = _copy_workspace(label)
    print(f"[example-temp] workspace: {root}")
    print("[example-temp] original examples remain unchanged; rerun creates a new clean workspace.")

    try:
        if ns.exec_relative:
            target = (root / ns.exec_relative).resolve()
            if root.resolve() not in target.parents or not target.is_file():
                raise ValueError(f"invalid --exec path: {ns.exec_relative}")
            return _run([sys.executable, str(target), *extra], root)
        script = root / "examples" / "examples.yaml" if ns.all else _select_example(root, ns.example)
        return _run(_runner_command(root, script, extra), root)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[example-temp] ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        print(f"[example-temp] results kept at: {root}")


if __name__ == "__main__":
    raise SystemExit(main())
