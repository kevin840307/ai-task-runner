from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Sequence

import yaml

SOURCE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_EXAMPLES = SOURCE_ROOT / "examples"
_PATH_FIELDS = ("goal_file", "validator", "ai_validator_prompt_file", "workflow_file")


def _workspace_base() -> Path:
    override = os.environ.get("AI_TASK_RUNNER_EXAMPLE_TEMP")
    return (Path(override).expanduser() if override else SOURCE_ROOT / ".example_runs").resolve()


def _new_workspace() -> Path:
    base = _workspace_base()
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"r-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    target.mkdir()
    (target / "examples").mkdir()
    return target


def _example_items() -> list[dict[str, object]]:
    data = yaml.safe_load((SOURCE_EXAMPLES / "examples.yaml").read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("examples/examples.yaml must contain a root-level list")
    return [item for item in data if isinstance(item, dict)]


def _example_name(item: dict[str, object]) -> str:
    root = str(item.get("project_root", "")).replace("\\", "/")
    name = root.split("/", 1)[0]
    if not name:
        raise ValueError("example item requires project_root under examples/")
    return name


def _copy_example(workspace: Path, name: str) -> None:
    source = SOURCE_EXAMPLES / name
    if not source.is_dir():
        raise ValueError(f"example folder not found: {name}")
    shutil.copytree(source, workspace / "examples" / name)


def _portable_items(items: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    examples_root = SOURCE_EXAMPLES.resolve()
    for raw in items:
        item = dict(raw)
        for field in _PATH_FIELDS:
            value = item.get(field)
            if not isinstance(value, str) or not value or value.lower() == "ai":
                continue
            path = Path(value).expanduser()
            source = path.resolve() if path.is_absolute() else (examples_root / path).resolve()
            try:
                source.relative_to(examples_root)
            except ValueError:
                if source.exists():
                    item[field] = str(source)
        result.append(item)
    return result


def _prepare_script(workspace: Path, name: str | None) -> Path:
    items = _example_items()
    if name is not None:
        items = [item for item in items if _example_name(item) == name]
        if len(items) != 1:
            raise ValueError(f"example {name!r} matched {len(items)} items in examples/examples.yaml")
        _copy_example(workspace, name)
        script = workspace / "examples" / ".selected-example.yaml"
    else:
        for example_name in dict.fromkeys(_example_name(item) for item in items):
            _copy_example(workspace, example_name)
        script = workspace / "examples" / "examples.yaml"
    script.write_text(
        yaml.safe_dump(_portable_items(items), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return script


def _runner_command(workspace: Path, script: Path, extra: Sequence[str]) -> list[str]:
    return [
        sys.executable,
        str(SOURCE_ROOT / "ai_task_runner.py"),
        "--loop-context-compress",
        "--project-root",
        str(workspace / "examples"),
        "--script",
        str(script),
        *extra,
    ]


def _run(command: Sequence[str], cwd: Path) -> int:
    print(f"[example-temp] command: {subprocess.list2cmdline(list(command))}")
    environment = dict(os.environ)
    environment["AI_TASK_RUNNER_SOURCE_ROOT"] = str(SOURCE_ROOT)
    return subprocess.call(list(command), cwd=cwd, env=environment)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run examples from a fresh isolated example copy.")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Copy and run all examples.")
    group.add_argument("--example", help="Copy and run one example folder listed in examples/examples.yaml.")
    group.add_argument("--exec", dest="exec_relative", help="Copy one example and run a Python file inside it.")
    p.add_argument("args", nargs=argparse.REMAINDER, help="Arguments after -- are forwarded to the Runner or Python file.")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = parser().parse_args(argv)
    extra = list(ns.args)
    if extra[:1] == ["--"]:
        extra = extra[1:]
    workspace = _new_workspace()
    print(f"[example-temp] workspace: {workspace}")
    print("[example-temp] original examples remain unchanged; rerun creates a new clean workspace.")

    try:
        if ns.exec_relative:
            relative = Path(ns.exec_relative)
            parts = relative.parts
            if len(parts) < 3 or parts[0].lower() != "examples":
                raise ValueError("--exec must point inside examples/<name>/")
            _copy_example(workspace, parts[1])
            target = (workspace / relative).resolve()
            if not target.is_file():
                raise ValueError(f"invalid --exec path: {ns.exec_relative}")
            return _run([sys.executable, str(target), *extra], workspace)
        script = _prepare_script(workspace, None if ns.all else ns.example)
        return _run(_runner_command(workspace, script, extra), workspace / "examples")
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"[example-temp] ERROR: {error}", file=sys.stderr)
        return 2
    finally:
        print(f"[example-temp] results kept at: {workspace}")


if __name__ == "__main__":
    raise SystemExit(main())
