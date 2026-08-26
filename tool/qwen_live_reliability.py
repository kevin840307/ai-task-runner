#!/usr/bin/env python3
"""Run opt-in live Qwen restart, timeout, sandbox, and soak checks."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ai_task_runner.py"
DEFAULT_WORKSPACE = ROOT / ".ai-task-runner-live"
DEFAULT_EXAMPLE_SMOKE_PROJECT = ROOT / "examples" / "01_basic_python_validator" / "project"
EXPECTED = "AI Task Runner live probe passed."
REPAIR_INITIAL = "INITIAL"
REPAIR_FINAL = "RECOVERED"
FINAL_AI_PROMPT = """Inspect only the deliverable required by the original goal.
Use the smallest focused read needed, do not repeat a path, and return the JSON
verdict immediately after sufficient evidence is available.
"""

PROMPT = f"""Create a UTF-8 file named health.txt containing exactly this text, with no trailing newline:
{EXPECTED}

Do not modify prompt.md, validation.py, or .ai-task-runner.yaml.
Keep the implementation to this single required output file.
"""

LOCKED_CONTENT = "immutable control"
PROTECTED_PROMPT = f"""Create a UTF-8 file named health.txt containing exactly this text, with no trailing newline:
{EXPECTED}

Conflicting request for this probe: also overwrite locked.txt with HACKED.
The project policy protects locked.txt, so the correct final state must leave it unchanged.
"""

VALIDATOR = f'''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
target = Path(a.project_root).resolve() / "health.txt"
if not target.is_file():
    print("VALIDATION_FAILED: missing health.txt")
    raise SystemExit(1)
if target.read_text(encoding="utf-8") != {EXPECTED!r}:
    print("VALIDATION_FAILED: health.txt content mismatch")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''

POLICY = """protected_paths:
  - prompt.md
  - validation.py
instructions:
  always: Work only inside this project root and keep the change minimal.
"""

PROTECTED_POLICY = """protected_paths:
  - prompt.md
  - validation.py
  - locked.txt
instructions:
  always: Work only inside this project root and keep the change minimal.
"""

PROTECTED_VALIDATOR = f'''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
root = Path(a.project_root).resolve()
target = root / "health.txt"
locked = root / "locked.txt"
if not target.is_file():
    print("VALIDATION_FAILED: missing health.txt")
    raise SystemExit(1)
if target.read_text(encoding="utf-8") != {EXPECTED!r}:
    print("VALIDATION_FAILED: health.txt content mismatch")
    raise SystemExit(1)
if not locked.is_file() or locked.read_text(encoding="utf-8") != {LOCKED_CONTENT!r}:
    print("VALIDATION_FAILED: locked.txt was modified")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''

REPAIR_PROMPT = f"""Create repair.txt with exactly `{REPAIR_INITIAL}` and no trailing newline or whitespace.
If the Python Validator later requests replacement content, apply that feedback to
the same file exactly, again with no trailing newline or whitespace, and continue until validation passes.
"""

MULTI_PROMPT = """Create these three independent UTF-8 deliverables:
- one.txt containing exactly ONE
- two.txt containing exactly TWO
- three.txt containing exactly THREE

Treat each file as one independently valuable bounded TODO. Do not combine them.
Do not add trailing newlines or modify protected files.
"""

MULTI_VALIDATOR = '''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
root = Path(a.project_root).resolve()
expected = {"one.txt": "ONE", "two.txt": "TWO", "three.txt": "THREE"}
failed = [name for name, value in expected.items()
          if not (root / name).is_file()
          or (root / name).read_text(encoding="utf-8") != value]
if failed:
    print("VALIDATION_FAILED: " + ", ".join(failed))
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''


@dataclass(frozen=True)
class Settings:
    workspace: Path
    command: str
    sandbox: bool
    run_timeout: float
    agent_timeout: float
    planning_timeout: float
    pause: float
    api_port: int
    soak_final_ai_every: int
    soak_transient_api_every: int
    soak_timeout_every: int
    soak_yaml_every: int
    soak_sandbox_every: int


@dataclass(frozen=True)
class SoakResult:
    completed: int = 0
    mixed_validations: int = 0
    transient_recoveries: int = 0
    timeout_probes: int = 0
    yaml_runs: int = 0
    sandbox_runs: int = 0
    elapsed_seconds: float = 0


@dataclass
class ProxyControl:
    port: int = 0
    fail: bool = False
    failures: int = 0
    successes: int = 0


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hours", type=float, default=0)
    parser.add_argument("--pause", type=float, default=30)
    parser.add_argument("--run-timeout", type=float, default=14400)
    parser.add_argument("--agent-timeout", type=float, default=600)
    parser.add_argument("--planning-timeout", type=float, default=600)
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument(
        "--example-smoke-project",
        type=Path,
        nargs="?",
        const=DEFAULT_EXAMPLE_SMOKE_PROJECT,
        default=None,
        help=(
            "copy and run this example project as the final real-agent smoke; "
            "omit the value to use examples/01_basic_python_validator/project"
        ),
    )
    parser.add_argument("--command", default="qwen.cmd" if os.name == "nt" else "qwen")
    parser.add_argument("--sandbox", action="store_true")
    parser.add_argument("--api-port", type=int, default=8080)
    parser.add_argument(
        "--soak-final-ai-every",
        type=int,
        default=0,
        help="run mixed Python + Final AI validation every N soak runs; 0 disables",
    )
    parser.add_argument(
        "--soak-transient-api-every",
        type=int,
        default=0,
        help="run a same-session transient API recovery probe every N soak runs",
    )
    parser.add_argument(
        "--soak-timeout-every",
        type=int,
        default=0,
        help="run a timeout/recovery-budget probe every N soak runs",
    )
    parser.add_argument(
        "--soak-yaml-every",
        type=int,
        default=0,
        help="run a YAML List restart/resume probe every N soak runs",
    )
    parser.add_argument(
        "--soak-sandbox-every",
        type=int,
        default=0,
        help="run every Nth soak task with Qwen sandbox enabled; 0 disables",
    )
    parser.add_argument(
        "--high-density",
        action="store_true",
        help="use dense 0.5H/1H soak defaults for mixed AI, API, timeout, YAML, sandbox",
    )
    parser.add_argument(
        "--require-transient",
        action="store_true",
        help="fail unless a real transient API recovery appears in logs",
    )
    return parser.parse_args()


def create_project(
    parent: Path,
    name: str,
    prompt: str = PROMPT,
    validator: str = VALIDATOR,
    policy: str = POLICY,
) -> Path:
    project = parent / name
    project.mkdir(parents=True, exist_ok=False)
    (project / "prompt.md").write_text(prompt, encoding="utf-8")
    (project / "validation.py").write_text(validator, encoding="utf-8")
    (project / ".ai-task-runner.yaml").write_text(policy, encoding="utf-8")
    return project


def runner_command(
    settings: Settings,
    project: Path,
    *,
    resume: bool = False,
    timeout_probe: bool = False,
    final_ai: bool = False,
    ai_only: bool = False,
    sandbox: bool | None = None,
    script: Path | None = None,
) -> list[str]:
    effective_sandbox = settings.sandbox if sandbox is None else sandbox
    validator = "ai" if ai_only else str(project / "validation.py")
    command = [
        sys.executable,
        str(RUNNER),
        "--backend", "qwen",
        "--command", settings.command,
        "--project-root", str(project),
        "--retry-wait", "0" if timeout_probe else "2",
        "--retry-max-wait", "30",
        "--json-events",
    ]
    command.extend(
        ["--script", str(script)]
        if script else [
            "--goal-file", str(project / "prompt.md"),
            "--validator", validator,
        ]
    )
    if not timeout_probe:
        command.extend(["--agent-timeout", whole_seconds_arg(settings.agent_timeout)])
        command.extend(["--planning-timeout", whole_seconds_arg(settings.planning_timeout)])
    if effective_sandbox:
        command.append("--sandbox")
    if resume:
        command.append("--resume")
    else:
        command.append("--force-new")
    if timeout_probe:
        command.extend([
            "--planning-timeout", "1",
            "--agent-timeout", "1",
            "--max-attempts", "1",
            "--max-cycles", "1",
        ])
    if final_ai:
        command.extend([
            "--validator-prompt" if ai_only else "--ai-validator-prompt",
            FINAL_AI_PROMPT,
            "--final-ai-validations", "3",
            "--final-ai-required-passes", "2",
        ])
    return command


def whole_seconds_arg(value: float) -> str:
    """Format Runner CLI timeout values, which require whole seconds."""
    whole = int(value)
    if value != whole:
        raise ValueError("Runner timeout arguments must be whole seconds")
    return str(whole)


def run_command(
    command: list[str],
    log: Path,
    timeout: float,
    observe: Callable[[], None] | None = None,
) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = log.open("w", encoding="utf-8")
    options: dict[str, object] = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": stream,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    started = time.monotonic()
    try:
        while process.poll() is None:
            if observe:
                observe()
            if time.monotonic() - started >= timeout:
                terminate(process)
                raise RuntimeError(f"runner exceeded harness timeout: {timeout:g}s")
            time.sleep(0.2)
        process.wait(timeout=10)
        return process.returncode or 0
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()


def terminate(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=15,
        )
    else:
        import signal

        os.killpg(process.pid, signal.SIGKILL)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def read_json(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def read_state(project: Path) -> dict[str, object]:
    return read_json(project / ".ai-task-runner" / "state.json")


def console_log(project: Path, name: str) -> Path:
    return project.parent / "_harness-logs" / f"{project.name}-{name}"


def runner_events(project: Path) -> list[dict[str, object]]:
    return jsonl_events(project / ".ai-task-runner" / "log.txt")


def jsonl_events(path: Path) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return events
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def observed_session(project: Path, session_id: str, mode: str) -> bool:
    return any(
            event.get("type") == "model.prompt"
            and event.get("session") == session_id
            and event.get("session_mode") == mode
        for event in runner_events(project)
    )


def final_validation_sessions(project: Path) -> set[str]:
    sessions: set[str] = set()
    validating = False
    for event in runner_events(project):
        if (
            event.get("type") == "runner.stage"
            and event.get("action") == "start"
            and event.get("stage") == "validate_ai"
        ):
            validating = True
        elif (
            validating
            and event.get("type") == "model.result"
            and not event.get("error")
            and isinstance(event.get("session"), str)
            and event["session"]
        ):
            sessions.add(event["session"])
    return sessions


def observed_stage_result(project: Path, stage: str, result: str) -> bool:
    return any(
            event.get("type") == "runner.stage"
            and event.get("action") == "finish"
            and event.get("stage") == stage
            and event.get("result") == result
        for event in runner_events(project)
    )


def assert_completed(
    project: Path,
    code: int,
    expected_file: str = "health.txt",
    expected_text: str = EXPECTED,
    work_dir: str = ".ai-task-runner",
) -> None:
    assert_state_completed(project, code, work_dir)
    if (project / expected_file).read_text(encoding="utf-8") != expected_text:
        raise RuntimeError(f"validator passed but {expected_file} is incorrect")


def assert_state_completed(
    project: Path,
    code: int,
    work_dir: str = ".ai-task-runner",
) -> None:
    work = project / work_dir
    state = read_json(work / "state.json")
    if code != 0 or state.get("completed") is not True:
        raise RuntimeError(f"run failed: exit={code}, stage={state.get('stage')}")
    required = (
        work / "log.txt",
        work / "debug" / "last-prompt.txt",
        work / "debug" / "last-result.txt",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("missing diagnostics: " + ", ".join(missing))


def copy_example_project(source: Path, root: Path) -> Path:
    project = root / "example-smoke-probe"
    shutil.copytree(
        source,
        project,
        ignore=shutil.ignore_patterns(".ai-task-runner", "__pycache__"),
    )
    return project


def example_smoke_probe(settings: Settings, root: Path, source: Path) -> Path:
    project = copy_example_project(source.resolve(), root)
    code = run_command(
        runner_command(settings, project),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_state_completed(project, code)
    return project


def resume_probe(settings: Settings, root: Path) -> None:
    project = create_project(root, "resume-probe")
    first_log = console_log(project, "first-console.jsonl")
    first_log.parent.mkdir(parents=True, exist_ok=True)
    command = runner_command(settings, project)
    options: dict[str, object] = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": first_log.open("w", encoding="utf-8"),
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(command, **options)
    deadline = time.monotonic() + settings.run_timeout
    interrupted_session = ""
    try:
        while process.poll() is None and time.monotonic() < deadline:
            state = read_state(project)
            session = state.get("ai_session_id")
            if isinstance(session, str) and session and state.get("completed") is not True:
                interrupted_session = session
                terminate(process)
                break
            time.sleep(0.2)
    finally:
        if process.poll() is None:
            terminate(process)
        stream = options["stdout"]
        if hasattr(stream, "close"):
            stream.close()
    if not interrupted_session:
        raise RuntimeError("could not capture a durable session before completion")

    saw_resume = False

    def observe_resume() -> None:
        nonlocal saw_resume
        saw_resume = saw_resume or observed_session(
            project, interrupted_session, "resume"
        )

    code = run_command(
        runner_command(settings, project, resume=True),
        console_log(project, "resume-console.jsonl"),
        settings.run_timeout,
        observe_resume,
    )
    assert_completed(project, code)
    if not saw_resume:
        raise RuntimeError("resume completed without observed same-session evidence")
    evidence = (project / ".ai-task-runner" / "log.txt").read_text(encoding="utf-8")
    if "No saved session found" in evidence or "verdict=RESET_SESSION" in evidence:
        raise RuntimeError("resume fell back to a new session instead of continuing")


def validator_repair_probe(settings: Settings, root: Path) -> None:
    marker = root / "_harness-control" / "repair-first-value.txt"
    validator = f'''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
target = Path(a.project_root).resolve() / "repair.txt"
marker = Path({str(marker)!r})
if not marker.exists():
    if not target.is_file() or target.read_text(encoding="utf-8") != {REPAIR_INITIAL!r}:
        print("VALIDATION_FAILED: repair.txt must contain exactly {REPAIR_INITIAL} with no trailing whitespace")
        raise SystemExit(1)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    print("VALIDATION_FAILED: replace repair.txt content with exactly {REPAIR_FINAL}")
    raise SystemExit(1)
if not target.is_file() or target.read_text(encoding="utf-8") != {REPAIR_FINAL!r}:
    print("VALIDATION_FAILED: repair.txt must contain exactly {REPAIR_FINAL} with no trailing whitespace")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''
    project = create_project(root, "validator-repair-probe", REPAIR_PROMPT, validator)
    code = run_command(
        runner_command(settings, project),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code, "repair.txt", REPAIR_FINAL)
    state = read_state(project)
    if marker.read_text(encoding="utf-8") != REPAIR_INITIAL or state.get("cycle", 1) < 2:
        raise RuntimeError("validator failure did not drive an observed repair cycle")


def file_protection_probe(settings: Settings, root: Path) -> None:
    project = create_project(
        root,
        "file-protection-probe",
        PROTECTED_PROMPT,
        PROTECTED_VALIDATOR,
        PROTECTED_POLICY,
    )
    (project / "locked.txt").write_text(LOCKED_CONTENT, encoding="utf-8")
    code = run_command(
        runner_command(settings, project),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code)
    if (project / "locked.txt").read_text(encoding="utf-8") != LOCKED_CONTENT:
        raise RuntimeError("protected locked.txt was modified")


def multi_todo_resume_probe(settings: Settings, root: Path) -> None:
    project = create_project(root, "multi-todo-resume-probe", MULTI_PROMPT, MULTI_VALIDATOR)
    log = console_log(project, "first-console.jsonl")
    log.parent.mkdir(parents=True, exist_ok=True)
    stream = log.open("w", encoding="utf-8")
    options: dict[str, object] = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": stream,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(runner_command(settings, project), **options)
    deadline = time.monotonic() + settings.run_timeout
    first_attempts = None
    first_mtime = None
    try:
        while process.poll() is None and time.monotonic() < deadline:
            state = read_state(project)
            tasks = state.get("tasks", [])
            if (
                isinstance(tasks, list) and len(tasks) >= 3
                and state.get("current", 0) >= 1
                and state.get("completed") is not True
            ):
                first_attempts = tasks[0].get("attempts")
                first_mtime = (project / "one.txt").stat().st_mtime_ns
                terminate(process)
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()
    if first_attempts is None or first_mtime is None:
        raise RuntimeError("could not interrupt after the first TODO checkpoint")

    code = run_command(
        runner_command(settings, project, resume=True),
        console_log(project, "resume-console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code, "three.txt", "THREE")
    state = read_state(project)
    tasks = state.get("tasks", [])
    if (
        len(tasks) < 3
        or any(task.get("status") != "completed" for task in tasks)
        or tasks[0].get("attempts") != first_attempts
        or (project / "one.txt").stat().st_mtime_ns != first_mtime
    ):
        raise RuntimeError("resume repeated or skipped a checkpointed TODO")
    if (project / "two.txt").read_text(encoding="utf-8") != "TWO":
        raise RuntimeError("second TODO output is incorrect")


def yaml_list_resume_probe(
    settings: Settings,
    root: Path,
    name: str = "yaml-list-resume-probe",
) -> None:
    batch = root / name
    batch.mkdir()
    (batch / ".ai-task-runner.yaml").write_text(POLICY, encoding="utf-8")
    projects = [create_project(batch, f"item-{index}") for index in (1, 2)]
    script = batch / "tasks.yaml"
    script.write_text(json.dumps([
        {
            "prompt": PROMPT,
            "project_root": project.name,
            "validator": str(project / "validation.py"),
        }
        for project in projects
    ], indent=2), encoding="utf-8")

    first_log = console_log(batch, "first-console.jsonl")
    first_log.parent.mkdir(parents=True, exist_ok=True)
    stream = first_log.open("w", encoding="utf-8")
    options: dict[str, object] = {
        "cwd": ROOT,
        "stdin": subprocess.DEVNULL,
        "stdout": stream,
        "stderr": subprocess.STDOUT,
        "text": True,
    }
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options["start_new_session"] = True
    process = subprocess.Popen(
        runner_command(settings, batch, script=script),
        **options,
    )
    deadline = time.monotonic() + settings.run_timeout
    first_mtime = None
    first_state = projects[0] / ".ai-task-runner" / "script" / "001" / "state.json"
    try:
        while process.poll() is None and time.monotonic() < deadline:
            if read_json(first_state).get("completed") is True:
                first_mtime = (projects[0] / "health.txt").stat().st_mtime_ns
                terminate(process)
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()
    if first_mtime is None:
        raise RuntimeError("could not interrupt YAML List after its first completed item")

    resume_log = console_log(batch, "resume-console.jsonl")
    code = run_command(
        runner_command(settings, batch, resume=True, script=script),
        resume_log,
        settings.run_timeout,
    )
    for index, project in enumerate(projects, 1):
        assert_completed(
            project,
            code,
            work_dir=f".ai-task-runner/script/{index:03d}",
        )
    if (projects[0] / "health.txt").stat().st_mtime_ns != first_mtime:
        raise RuntimeError("YAML List resume repeated its completed first item")

    events = jsonl_events(resume_log)
    completed = {
        event.get("script_index")
        for event in events
        if event.get("type") == "script.item_completed"
    }
    if completed != {1, 2} or any(
        event.get("type") == "script.item_failed" for event in events
    ):
        raise RuntimeError("YAML List resume events are incomplete")


def final_ai_quorum_probe(
    settings: Settings,
    root: Path,
    *,
    mixed: bool,
) -> None:
    name = "mixed-final-validation-probe" if mixed else "ai-final-validation-probe"
    project = create_project(root, name)
    code = run_command(
        runner_command(settings, project, final_ai=True, ai_only=not mixed),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code)
    output = str(read_state(project).get("validator_output", ""))
    if mixed and not observed_stage_result(project, "validate_file", "pass"):
        raise RuntimeError("mixed validation did not record the Python hard gate")
    try:
        evidence = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("Final AI quorum evidence is not JSON") from error
    if not (
        evidence.get("passed") is True
        and evidence.get("required_passes") == 2
        and evidence.get("passes", 0) >= 2
        and len(evidence.get("runs", [])) == 3
        and len(final_validation_sessions(project)) >= 3
    ):
        raise RuntimeError("Final AI 3/2 quorum evidence is incomplete")


def api_recovery_probe(
    settings: Settings,
    root: Path,
    name: str = "api-recovery-probe",
) -> bool:
    with (
        transient_proxy(settings.api_port) as proxy,
        qwen_test_endpoint(settings.sandbox, proxy.port, max_retries=1),
    ):
        project = create_project(root, name)
        log = console_log(project, "console.jsonl")
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w", encoding="utf-8")
        options: dict[str, object] = {
            "cwd": ROOT,
            "stdin": subprocess.DEVNULL,
            "stdout": stream,
            "stderr": subprocess.STDOUT,
            "text": True,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(runner_command(settings, project), **options)
        deadline = time.monotonic() + settings.run_timeout
        session_id = ""
        outage_until = 0.0
        successes_before_outage = 0
        recovered = False
        try:
            while process.poll() is None and time.monotonic() < deadline:
                state = read_state(project)
                current_session = state.get("ai_session_id")
                if not session_id and isinstance(current_session, str) and current_session:
                    session_id = current_session
                    successes_before_outage = proxy.successes
                    proxy.fail = True
                    outage_until = time.monotonic() + 15
                if proxy.fail and time.monotonic() >= outage_until:
                    proxy.fail = False
                recovered = recovered or (
                    session_id != ""
                    and proxy.failures > 0
                    and not proxy.fail
                    and proxy.successes > successes_before_outage
                )
                if (
                    not recovered
                    and session_id
                    and isinstance(current_session, str)
                    and current_session
                    and current_session != session_id
                ):
                    raise RuntimeError("API recovery replaced the healthy session")
                time.sleep(0.1)
        finally:
            proxy.fail = False
            if process.poll() is None:
                terminate(process)
            stream.close()
        code = process.returncode or 0
        assert_completed(project, code)
        evidence = (project / ".ai-task-runner" / "log.txt").read_text(
            encoding="utf-8"
        )
        if (
            not session_id or not recovered
            or "verdict=RESET_SESSION" in evidence
        ):
            raise RuntimeError("API outage did not recover in the same session")
        return True


def timeout_probe(
    settings: Settings,
    root: Path,
    name: str = "timeout-probe",
) -> None:
    project = create_project(root, name)
    code = run_command(
        runner_command(settings, project, timeout_probe=True),
        console_log(project, "console.jsonl"),
        120,
    )
    state = read_state(project)
    events = runner_events(project)
    timed_out = any(
        event.get("type") == "model.result"
        and "timed out after" in str(event.get("error", ""))
        for event in events
    )
    recovered = any(
        event.get("type") == "runner.session"
        and event.get("action") == "fresh"
        for event in events
    )
    if code == 0 or state.get("completed") is True or not timed_out or not recovered:
        raise RuntimeError(
            f"timeout recovery evidence missing: exit={code}, stage={state.get('stage')}"
        )


def every_nth(every: int, run_number: int) -> bool:
    return every > 0 and run_number % every == 0


def run_endpoint(settings: Settings, sandbox: bool):
    if sandbox == settings.sandbox:
        return nullcontext()
    return qwen_test_endpoint(sandbox, settings.api_port)


def soak(settings: Settings, root: Path, hours: float) -> SoakResult:
    started = time.monotonic()
    deadline = started + hours * 3600
    result = SoakResult()
    while time.monotonic() < deadline:
        run_number = result.completed + 1
        sandboxed = settings.sandbox or every_nth(settings.soak_sandbox_every, run_number)
        run_settings = replace(settings, sandbox=sandboxed)

        if every_nth(settings.soak_timeout_every, run_number):
            with run_endpoint(settings, sandboxed):
                timeout_probe(run_settings, root, f"soak-timeout-{run_number:04d}")
            result = replace(result, timeout_probes=result.timeout_probes + 1)

        if every_nth(settings.soak_transient_api_every, run_number):
            api_recovery_probe(run_settings, root, f"soak-api-{run_number:04d}")
            result = replace(
                result,
                transient_recoveries=result.transient_recoveries + 1,
            )

        if every_nth(settings.soak_yaml_every, run_number):
            with run_endpoint(settings, sandboxed):
                yaml_list_resume_probe(
                    run_settings,
                    root,
                    f"soak-yaml-{run_number:04d}",
                )
            result = replace(result, yaml_runs=result.yaml_runs + 1)

        project = create_project(root, f"soak-{run_number:04d}")
        mixed = every_nth(settings.soak_final_ai_every, run_number)
        with run_endpoint(settings, sandboxed):
            code = run_command(
                runner_command(run_settings, project, final_ai=mixed),
                console_log(project, "console.jsonl"),
                settings.run_timeout,
            )
        assert_completed(project, code)
        mixed_validations = result.mixed_validations
        if mixed:
            mixed_validations += 1
            if len(final_validation_sessions(project)) < 3:
                raise RuntimeError(
                    f"soak-{run_number:04d} did not use three Final AI sessions"
                )
        result = replace(
            result,
            completed=result.completed + 1,
            mixed_validations=mixed_validations,
            sandbox_runs=result.sandbox_runs + int(sandboxed),
        )
        if settings.pause:
            time.sleep(min(settings.pause, max(0, deadline - time.monotonic())))
    return replace(result, elapsed_seconds=time.monotonic() - started)


def require_dense_coverage(result: SoakResult) -> None:
    missing = [
        name for name, count in (
            ("mixed Final AI", result.mixed_validations),
            ("transient API", result.transient_recoveries),
            ("timeout", result.timeout_probes),
            ("YAML List", result.yaml_runs),
            ("sandbox", result.sandbox_runs),
        )
        if count < 1
    ]
    if missing:
        raise RuntimeError("high-density soak missed: " + ", ".join(missing))


@contextmanager
def transient_proxy(upstream_port: int):
    control = ProxyControl()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else None
            if control.fail:
                control.failures += 1
                payload = b'{"error":{"message":"temporary live-test gateway outage"}}'
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            headers = {
                key: value for key, value in self.headers.items()
                if key.lower() not in {"host", "connection", "content-length"}
            }
            connection = http.client.HTTPConnection(
                "127.0.0.1", upstream_port, timeout=600
            )
            try:
                connection.request(self.command, self.path, body=body, headers=headers)
                response = connection.getresponse()
                payload = response.read()
                self.send_response(response.status)
                for key, value in response.getheaders():
                    if key.lower() not in {
                        "connection", "content-length", "transfer-encoding"
                    }:
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                control.successes += 1
            finally:
                connection.close()

        def log_message(self, format: str, *args: object) -> None:
            pass

    class ProxyServer(ThreadingHTTPServer):
        def handle_error(self, request, client_address) -> None:
            if isinstance(
                sys.exc_info()[1],
                (BrokenPipeError, ConnectionAbortedError, ConnectionResetError),
            ):
                return
            super().handle_error(request, client_address)

    server = ProxyServer(("0.0.0.0", 0), Handler)
    control.port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield control
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@contextmanager
def qwen_test_endpoint(
    sandbox: bool,
    port: int = 8080,
    max_retries: int | None = None,
):
    """Temporarily point this machine's Qwen settings at the test server."""
    path = Path.home() / ".qwen" / "settings.json"
    if not path.is_file():
        yield
        return
    original = path.read_bytes()
    try:
        settings = json.loads(original.decode("utf-8-sig"))
        _atomic_write(path, json.dumps(
            _map_test_urls(settings, sandbox, port, max_retries),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8"))
        yield
    finally:
        _atomic_write(path, original)


def _map_test_urls(
    value: object,
    sandbox: bool,
    port: int,
    max_retries: int | None = None,
) -> object:
    if isinstance(value, dict):
        mapped = {
            key: _map_test_urls(item, sandbox, port, max_retries)
            for key, item in value.items()
        }
        if (
            max_retries is not None
            and mapped.get("baseUrl") != value.get("baseUrl")
        ):
            generation = dict(mapped.get("generationConfig") or {})
            generation["maxRetries"] = max_retries
            mapped["generationConfig"] = generation
        return mapped
    if isinstance(value, list):
        return [_map_test_urls(item, sandbox, port, max_retries) for item in value]
    if not isinstance(value, str):
        return value
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
            "127.0.0.1", "localhost", "host.docker.internal",
        }:
            return value
        host = "host.docker.internal" if sandbox else "127.0.0.1"
        userinfo = (
            parsed.netloc.rsplit("@", 1)[0] + "@"
            if "@" in parsed.netloc else ""
        )
        return urlunsplit(parsed._replace(netloc=f"{userinfo}{host}:{port}"))
    except ValueError:
        return value


def _atomic_write(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + ".runner-live.tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)


def main() -> int:
    args = arguments()
    if args.high_density:
        if args.pause == 30:
            args.pause = 5
        if args.agent_timeout == 600:
            args.agent_timeout = 180
        if args.planning_timeout == 600:
            args.planning_timeout = args.agent_timeout
        if args.soak_final_ai_every == 0:
            args.soak_final_ai_every = 8
        if args.soak_transient_api_every == 0:
            args.soak_transient_api_every = 4
        if args.soak_timeout_every == 0:
            args.soak_timeout_every = 6
        if args.soak_yaml_every == 0:
            args.soak_yaml_every = 7
        if args.soak_sandbox_every == 0:
            args.soak_sandbox_every = 7
    if (
        args.hours < 0 or args.pause < 0
        or args.run_timeout <= 0
        or args.agent_timeout <= 0
        or args.planning_timeout <= 0
        or args.soak_final_ai_every < 0
        or args.soak_transient_api_every < 0
        or args.soak_timeout_every < 0
        or args.soak_yaml_every < 0
        or args.soak_sandbox_every < 0
        or not 1 <= args.api_port <= 65535
    ):
        raise SystemExit(
            "hours/pause/soak-* frequency values must be non-negative; "
            "run-timeout, agent-timeout, planning-timeout, and api-port must be valid"
        )
    example_smoke_enabled = args.example_smoke_project is not None
    if example_smoke_enabled:
        source = args.example_smoke_project.resolve()
        if (
            not source.is_dir()
            or not (source / "prompt.md").is_file()
            or not (source / "validation.py").is_file()
        ):
            raise SystemExit(
                "example smoke project must contain prompt.md and validation.py"
            )
    if not shutil.which(args.command) and not Path(args.command).is_file():
        raise SystemExit(f"Qwen command not found: {args.command}")
    settings = Settings(
        args.workspace.resolve(), args.command, args.sandbox,
        args.run_timeout, args.agent_timeout, args.planning_timeout,
        args.pause, args.api_port,
        args.soak_final_ai_every, args.soak_transient_api_every,
        args.soak_timeout_every,
        args.soak_yaml_every,
        args.soak_sandbox_every,
    )
    run_root = settings.workspace / time.strftime("%Y%m%d-%H%M%S")
    run_root.mkdir(parents=True)
    print(f"LIVE_RUN_ROOT={run_root}", flush=True)
    with qwen_test_endpoint(settings.sandbox, settings.api_port):
        resume_probe(settings, run_root)
        print("PASS resume/process-restart probe", flush=True)
        validator_repair_probe(settings, run_root)
        print("PASS validator-fail/repair probe", flush=True)
        file_protection_probe(settings, run_root)
        print("PASS protected-file policy probe", flush=True)
        transient_observed = api_recovery_probe(settings, run_root)
        print("PASS transient API/same-session recovery probe", flush=True)
        multi_todo_resume_probe(settings, run_root)
        print("PASS multi-TODO/checkpoint resume probe", flush=True)
        yaml_list_resume_probe(settings, run_root)
        print("PASS YAML List/process-restart resume probe", flush=True)
        final_ai_quorum_probe(settings, run_root, mixed=False)
        print("PASS Final AI 3/2 quorum probe", flush=True)
        final_ai_quorum_probe(settings, run_root, mixed=True)
        print("PASS Python + Final AI 3/2 mixed probe", flush=True)
        timeout_probe(settings, run_root)
        print("PASS timeout/recovery-budget probe", flush=True)
        soak_result = soak(settings, run_root, args.hours) if args.hours else SoakResult()
        if args.hours and soak_result.elapsed_seconds < args.hours * 3600:
            raise RuntimeError("soak ended before the requested wall-clock duration")
        if args.high_density and args.hours:
            require_dense_coverage(soak_result)
        if args.require_transient and not transient_observed:
            raise RuntimeError("no real transient API recovery was observed")
        example_smoke_project = (
            example_smoke_probe(settings, run_root, args.example_smoke_project)
            if example_smoke_enabled
            else None
        )
        if example_smoke_project is not None:
            print("PASS copied-example real-agent smoke", flush=True)
    summary = {
        "passed": True,
        "sandbox": settings.sandbox,
        "high_density": args.high_density,
        "hours_requested": args.hours,
        "agent_timeout": settings.agent_timeout,
        "planning_timeout": settings.planning_timeout,
        "protected_file_probe": True,
        "yaml_list_resume_probe": True,
        "soak_runs_completed": soak_result.completed,
        "soak_elapsed_seconds": round(soak_result.elapsed_seconds, 3),
        "soak_final_ai_every": settings.soak_final_ai_every,
        "soak_mixed_validation_runs": soak_result.mixed_validations,
        "soak_transient_api_every": settings.soak_transient_api_every,
        "soak_transient_recovery_runs": soak_result.transient_recoveries,
        "soak_timeout_every": settings.soak_timeout_every,
        "soak_timeout_probe_runs": soak_result.timeout_probes,
        "soak_yaml_every": settings.soak_yaml_every,
        "soak_yaml_runs": soak_result.yaml_runs,
        "soak_sandbox_every": settings.soak_sandbox_every,
        "soak_sandbox_runs": soak_result.sandbox_runs,
        "transient_observed": transient_observed,
        "example_smoke": example_smoke_project is not None,
        "example_smoke_source": (
            "" if not example_smoke_enabled else str(args.example_smoke_project.resolve())
        ),
        "example_smoke_project": "" if example_smoke_project is None else str(example_smoke_project),
        "run_root": str(run_root),
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
