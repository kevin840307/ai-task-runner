#!/usr/bin/env python3
"""Split one Runner YAML script across Git worktrees and run it in parallel."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import random
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]


class LauncherError(RuntimeError):
    pass


@dataclass(frozen=True)
class Job:
    name: str
    branch: str
    worktree: Path
    source_task_yaml: Path
    task_yaml: Path
    task_items: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class LaunchConfig:
    repo: Path
    runner: Path
    base_branch: str
    concurrency: int
    start_jitter_seconds: tuple[float, float]
    jobs: tuple[Job, ...]
    worktree_root: Path | None = None
    job_stem: str = ""


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LauncherError(f"{label} must be an object")
    return value


def _require_text(value: Any, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise LauncherError(f"{label} is required")
    return text


def _positive_int(value: Any, label: str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise LauncherError(f"{label} must be a positive integer") from exc
    if result <= 0:
        raise LauncherError(f"{label} must be a positive integer")
    return result


def _path(value: Any, base: Path, label: str) -> Path:
    path = Path(_require_text(value, label)).expanduser()
    return path if path.is_absolute() else base / path


def _jitter(value: Any) -> tuple[float, float]:
    if value is None:
        return (0.0, 0.0)
    if not isinstance(value, list) or len(value) != 2:
        raise LauncherError("start_jitter_seconds must be [min, max]")
    try:
        low, high = float(value[0]), float(value[1])
    except (TypeError, ValueError) as exc:
        raise LauncherError("start_jitter_seconds must contain numbers") from exc
    if low < 0 or high < low:
        raise LauncherError("start_jitter_seconds must satisfy 0 <= min <= max")
    return (low, high)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return slug or "task"


def _load_task_items(path: Path) -> list[dict[str, Any]]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LauncherError(f"task_yaml not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise LauncherError(f"invalid task_yaml: {path}") from exc
    if not isinstance(data, list) or not data:
        raise LauncherError(f"task_yaml must be a non-empty list: {path}")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise LauncherError(f"task_yaml item {index} must be an object: {path}")
        result.append(dict(item))
    return result


def _chunks(items: list[dict[str, Any]], count: int) -> list[list[dict[str, Any]]]:
    count = min(count, len(items))
    base, extra = divmod(len(items), count)
    chunks: list[list[dict[str, Any]]] = []
    offset = 0
    for index in range(count):
        size = base + (1 if index < extra else 0)
        chunks.append(items[offset:offset + size])
        offset += size
    return chunks


def load_config(path: Path) -> LaunchConfig:
    config_path = path.expanduser().resolve()
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LauncherError(f"could not read config: {config_path}") from exc
    cfg = _require_mapping(raw, "config")
    unsupported = sorted(set(cfg) - {
        "repo",
        "worktree_root",
        "concurrency",
        "base_branch",
        "start_jitter_seconds",
        "task_yaml",
        "runner",
    })
    if unsupported:
        raise LauncherError(f"unsupported config field(s): {', '.join(unsupported)}")

    repo = _path(cfg.get("repo"), config_path.parent, "repo").resolve()
    worktree_root = _path(cfg.get("worktree_root"), config_path.parent, "worktree_root").resolve()
    runner = _path(cfg.get("runner", str(ROOT / "ai_task_runner.py")), config_path.parent, "runner").resolve()
    concurrency = _positive_int(cfg.get("concurrency", 1), "concurrency")
    base_branch = str(cfg.get("base_branch") or "HEAD").strip() or "HEAD"
    source_task_yaml = _path(cfg.get("task_yaml"), repo, "task_yaml").resolve()
    items = _load_task_items(source_task_yaml)
    stem = _slug(source_task_yaml.stem)
    jobs = []
    for index, chunk in enumerate(_chunks(items, concurrency), 1):
        name = f"{stem}_{index}"
        worktree = (worktree_root / f"{repo.name}_{index}").resolve()
        jobs.append(Job(
            name=name,
            branch=f"ai/{name}",
            worktree=worktree,
            source_task_yaml=source_task_yaml,
            task_yaml=(worktree / ".ai-task-runner" / "launcher" / "scripts" / f"{name}.yaml").resolve(),
            task_items=tuple(chunk),
        ))
    return LaunchConfig(
        repo=repo,
        runner=runner,
        base_branch=base_branch,
        concurrency=concurrency,
        start_jitter_seconds=_jitter(cfg.get("start_jitter_seconds")),
        jobs=tuple(jobs),
        worktree_root=worktree_root,
        job_stem=stem,
    )


def _absolute_script_file(value: Any, source_dir: Path) -> str:
    path = Path(_require_text(value, "script file")).expanduser()
    if not path.is_absolute():
        path = source_dir / path
    return str(path.resolve())


def materialize_task_yaml(job: Job) -> Path:
    source_dir = job.source_task_yaml.parent
    rewritten: list[dict[str, Any]] = []
    for item in job.task_items:
        next_item = dict(item)
        next_item["project_root"] = str(job.worktree)
        for field in ("goal_file", "ai_validator_prompt_file", "workflow_file"):
            if field in next_item and next_item[field]:
                next_item[field] = _absolute_script_file(next_item[field], source_dir)
        rewritten.append(next_item)
    job.task_yaml.parent.mkdir(parents=True, exist_ok=True)
    job.task_yaml.write_text(yaml.safe_dump(rewritten, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return job.task_yaml


def _run(command: list[str], *, cwd: Path, dry_run: bool = False, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(command))
    if dry_run:
        return subprocess.CompletedProcess(command, 0, "", "")
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True)
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise LauncherError(f"command failed ({result.returncode}): {' '.join(command)}\n{detail}")
    return result


def ensure_git_repo(repo: Path) -> None:
    if not repo.is_dir():
        raise LauncherError(f"repo not found: {repo}")
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo, text=True, capture_output=True)
    if result.returncode != 0:
        raise LauncherError(f"not a git repository: {repo}")


def verify_existing_worktree(config: LaunchConfig, job: Job) -> None:
    """Fail fast instead of reusing an unrelated/stale directory."""
    result = subprocess.run(
        ["git", "-C", str(job.worktree), "rev-parse", "--show-toplevel"],
        text=True, capture_output=True,
    )
    if result.returncode != 0 or Path(result.stdout.strip()).resolve() != job.worktree.resolve():
        raise LauncherError(f"existing path is not the expected Git worktree: {job.worktree}")
    branch = subprocess.run(
        ["git", "-C", str(job.worktree), "branch", "--show-current"],
        text=True, capture_output=True,
    )
    if branch.returncode != 0 or branch.stdout.strip() != job.branch:
        found = branch.stdout.strip() or "detached/unknown"
        raise LauncherError(
            f"existing worktree branch mismatch for {job.worktree}: expected {job.branch}, found {found}"
        )


def _managed_jobs(config: LaunchConfig) -> list[Job]:
    """Return current jobs plus stale launcher-owned worktree directories."""
    jobs = {job.worktree.resolve(): job for job in config.jobs}
    if not config.jobs:
        return []
    root = (config.worktree_root or config.jobs[0].worktree.parent).resolve()
    stem = config.job_stem or _slug(config.jobs[0].source_task_yaml.stem)
    pattern = re.compile(rf"^{re.escape(config.repo.name)}_(\d+)$")
    for path in root.glob(f"{config.repo.name}_*"):
        match = pattern.match(path.name)
        if not match or not path.exists():
            continue
        index = int(match.group(1))
        resolved = path.resolve()
        if resolved in jobs:
            continue
        jobs[resolved] = Job(
            name=f"{stem}_{index}", branch=f"ai/{stem}_{index}", worktree=resolved,
            source_task_yaml=config.jobs[0].source_task_yaml,
            task_yaml=resolved / ".ai-task-runner" / "launcher" / "scripts" / f"{stem}_{index}.yaml",
            task_items=(),
        )
    return sorted(jobs.values(), key=lambda item: item.worktree.name)


def prepare(config: LaunchConfig, *, dry_run: bool = False) -> None:
    ensure_git_repo(config.repo)
    if not config.runner.is_file():
        raise LauncherError(f"runner not found: {config.runner}")
    for job in config.jobs:
        if job.worktree.exists():
            verify_existing_worktree(config, job)
            print(f"exists: {job.worktree}")
        else:
            job.worktree.parent.mkdir(parents=True, exist_ok=True)
            _run(["git", "worktree", "add", "-b", job.branch, str(job.worktree), config.base_branch], cwd=config.repo, dry_run=dry_run)
        if not dry_run:
            materialize_task_yaml(job)


def clean(config: LaunchConfig, *, delete_branches: bool = False, force: bool = False, dry_run: bool = False) -> None:
    ensure_git_repo(config.repo)
    for job in _managed_jobs(config):
        if job.worktree.exists():
            command = ["git", "worktree", "remove"]
            if force:
                command.append("--force")
            command.append(str(job.worktree))
            _run(command, cwd=config.repo, dry_run=dry_run)
        if delete_branches:
            _run(["git", "branch", "-D" if force else "-d", job.branch], cwd=config.repo, dry_run=dry_run, check=False)


def rebuild(config: LaunchConfig, *, delete_branches: bool = False, force: bool = False, dry_run: bool = False) -> None:
    clean(config, delete_branches=delete_branches, force=force, dry_run=dry_run)
    prepare(config, dry_run=dry_run)


def runner_command(config: LaunchConfig, job: Job, *, require_script: bool = True) -> list[str]:
    if require_script and not job.task_yaml.is_file():
        raise LauncherError(f"task YAML copy not found for {job.name}: {job.task_yaml}")
    return [
        sys.executable,
        str(config.runner),
        "--project-root",
        str(job.worktree),
        "--script",
        str(job.task_yaml),
    ]


def _sleep_jitter(bounds: tuple[float, float]) -> None:
    if bounds[1] > 0:
        time.sleep(random.uniform(*bounds))


def run_jobs(config: LaunchConfig, *, dry_run: bool = False) -> int:
    prepare(config, dry_run=dry_run)
    active: list[tuple[Job, subprocess.Popen[Any], Any]] = []
    pending = list(config.jobs)
    failed = 0
    while pending or active:
        while pending and len(active) < config.concurrency:
            job = pending.pop(0)
            if not dry_run:
                materialize_task_yaml(job)
            command = runner_command(config, job, require_script=not dry_run)
            log_dir = job.worktree / ".ai-task-runner" / "launcher"
            log_path = log_dir / f"{job.name}.log"
            print(f"start: {job.name} -> {log_path}")
            if dry_run:
                print("+ " + " ".join(command))
                continue
            log_dir.mkdir(parents=True, exist_ok=True)
            log = log_path.open("w", encoding="utf-8", errors="replace")
            process = subprocess.Popen(command, cwd=job.worktree, stdout=log, stderr=subprocess.STDOUT)
            active.append((job, process, log))
            _sleep_jitter(config.start_jitter_seconds)
        if dry_run:
            continue
        time.sleep(1)
        still_active: list[tuple[Job, subprocess.Popen[Any], Any]] = []
        for job, process, log in active:
            code = process.poll()
            if code is None:
                still_active.append((job, process, log))
                continue
            log.close()
            print(f"exit: {job.name} -> {code}")
            if code != 0:
                failed += 1
        active = still_active
    return 1 if failed else 0


def print_plan(config: LaunchConfig) -> None:
    print(f"repo: {config.repo}")
    print(f"runner: {config.runner}")
    print(f"base_branch: {config.base_branch}")
    print(f"concurrency: {config.concurrency}")
    for job in config.jobs:
        print(f"- {job.name}: branch={job.branch} worktree={job.worktree} items={len(job.task_items)} task_yaml={job.task_yaml}")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Split one Runner YAML script across Git worktrees.")
    p.add_argument("command", choices=["plan", "prepare", "run", "clean", "rebuild"])
    p.add_argument("config", type=Path, help="launcher YAML config")
    p.add_argument("--delete-branches", action="store_true", help="with clean/rebuild, delete configured branches after removing worktrees")
    p.add_argument("--force", action="store_true", help="force dirty worktree removal and branch deletion")
    p.add_argument("--dry-run", action="store_true", help="print commands without changing files or launching jobs")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "plan":
            print_plan(config)
        elif args.command == "prepare":
            prepare(config, dry_run=args.dry_run)
        elif args.command == "clean":
            clean(config, delete_branches=args.delete_branches, force=args.force, dry_run=args.dry_run)
        elif args.command == "rebuild":
            rebuild(config, delete_branches=args.delete_branches, force=args.force, dry_run=args.dry_run)
        elif args.command == "run":
            return run_jobs(config, dry_run=args.dry_run)
        return 0
    except LauncherError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
