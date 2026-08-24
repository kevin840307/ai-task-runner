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
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "ai_task_runner.py"
DEFAULT_WORKSPACE = ROOT / ".ai-task-runner-live"
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

REPAIR_PROMPT = f"""Create repair.txt with content `{REPAIR_INITIAL}`.
If the Python Validator later requests replacement content, apply that feedback to
the same file and continue until validation passes.
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
    pause: float
    api_port: int


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
    parser.add_argument("--workspace", type=Path, default=DEFAULT_WORKSPACE)
    parser.add_argument("--command", default="qwen.cmd" if os.name == "nt" else "qwen")
    parser.add_argument("--sandbox", action="store_true")
    parser.add_argument("--api-port", type=int, default=8080)
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
) -> Path:
    project = parent / name
    project.mkdir(parents=True, exist_ok=False)
    (project / "prompt.md").write_text(prompt, encoding="utf-8")
    (project / "validation.py").write_text(validator, encoding="utf-8")
    (project / ".ai-task-runner.yaml").write_text(POLICY, encoding="utf-8")
    return project


def runner_command(
    settings: Settings,
    project: Path,
    *,
    resume: bool = False,
    timeout_probe: bool = False,
    final_ai: bool = False,
    ai_only: bool = False,
) -> list[str]:
    validator = "ai" if ai_only else str(project / "validation.py")
    command = [
        sys.executable,
        str(RUNNER),
        "--backend", "qwen",
        "--command", settings.command,
        "--project-root", str(project),
        "--goal-file", str(project / "prompt.md"),
        "--validator", validator,
        "--retry-wait", "0" if timeout_probe else "2",
        "--retry-max-wait", "30",
        "--json-events",
    ]
    if settings.sandbox:
        command.append("--sandbox")
    if resume:
        command.append("--resume")
    else:
        command.append("--force-new")
    if timeout_probe:
        command.extend([
            "--planning-timeout", "1",
            "--agent-timeout", "1",
            "--max-session-resets", "1",
            "--no-progress-timeout", "30",
        ])
    if final_ai:
        command.extend([
            "--validator-prompt" if ai_only else "--ai-validator-prompt",
            FINAL_AI_PROMPT,
            "--final-ai-validations", "3",
            "--final-ai-required-passes", "2",
        ])
    return command


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


def read_state(project: Path) -> dict[str, object]:
    path = project / ".ai-task-runner" / "state.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def console_log(project: Path, name: str) -> Path:
    return project.parent / "_harness-logs" / f"{project.name}-{name}"


def assert_completed(
    project: Path,
    code: int,
    expected_file: str = "health.txt",
    expected_text: str = EXPECTED,
) -> None:
    state = read_state(project)
    if code != 0 or state.get("completed") is not True:
        raise RuntimeError(f"run failed: exit={code}, stage={state.get('stage')}")
    if (project / expected_file).read_text(encoding="utf-8") != expected_text:
        raise RuntimeError(f"validator passed but {expected_file} is incorrect")
    required = (
        project / ".ai-task-runner" / "log.txt",
        project / ".ai-task-runner" / "checkpoint.json",
        project / ".ai-task-runner" / "debug" / "last-prompt.txt",
        project / ".ai-task-runner" / "debug" / "last-result.txt",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("missing diagnostics: " + ", ".join(missing))


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
            session = state.get("agent_session_id")
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
        current = project / ".ai-task-runner" / "debug" / "current-prompt.txt"
        try:
            saw_resume = saw_resume or "mode=resume" in current.read_text(encoding="utf-8")
        except OSError:
            pass

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
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
target = Path(a.project_root).resolve() / "repair.txt"
marker = Path({str(marker)!r})
stage = json.loads(Path(a.state_file).read_text(encoding="utf-8")).get("stage")
expected = {REPAIR_FINAL!r} if marker.exists() else {REPAIR_INITIAL!r}
if stage != "final_validate":
    if not target.is_file() or target.read_text(encoding="utf-8") != expected:
        print(f"VALIDATION_FAILED: repair.txt must contain exactly {{expected}}")
        raise SystemExit(1)
    print("VALIDATION_PASSED")
    raise SystemExit(0)
if not marker.exists():
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(target.read_text(encoding="utf-8") if target.is_file() else "MISSING", encoding="utf-8")
    print("VALIDATION_FAILED: replace repair.txt content with exactly {REPAIR_FINAL}")
    raise SystemExit(1)
if not target.is_file() or target.read_text(encoding="utf-8") != {REPAIR_FINAL!r}:
    print("VALIDATION_FAILED: repair.txt must contain exactly {REPAIR_FINAL}")
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
    if mixed:
        if not output.startswith("FILE_VALIDATION_PASS\n"):
            raise RuntimeError("mixed validation did not record the Python hard gate")
        output = output.split("\n", 1)[1]
    try:
        evidence = json.loads(output)
    except json.JSONDecodeError as error:
        raise RuntimeError("Final AI quorum evidence is not JSON") from error
    if not (
        evidence.get("passed") is True
        and evidence.get("configured_validations") == 3
        and evidence.get("required_passes") == 2
        and evidence.get("passes", 0) >= 2
        and 2 <= evidence.get("completed_validations", 0) <= 3
    ):
        raise RuntimeError("Final AI 3/2 quorum evidence is incomplete")


def api_recovery_probe(settings: Settings, root: Path) -> None:
    with transient_proxy(settings.api_port) as proxy:
        with qwen_test_endpoint(settings.sandbox, proxy.port, max_retries=1):
            project = create_project(root, "api-recovery-probe")
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
            try:
                while process.poll() is None and time.monotonic() < deadline:
                    state = read_state(project)
                    current_session = state.get("agent_session_id")
                    if not session_id and isinstance(current_session, str) and current_session:
                        session_id = current_session
                        proxy.fail = True
                        outage_until = time.monotonic() + 15
                    if proxy.fail and time.monotonic() >= outage_until:
                        proxy.fail = False
                    evidence_path = project / ".ai-task-runner" / "log.txt"
                    try:
                        evidence = evidence_path.read_text(encoding="utf-8")
                    except OSError:
                        evidence = ""
                    if session_id and current_session not in {session_id, ""}:
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
                not session_id or proxy.failures < 1
                or "verdict=RESET_SESSION" in evidence
            ):
                raise RuntimeError("API outage did not recover in the same session")


def timeout_probe(settings: Settings, root: Path) -> None:
    project = create_project(root, "timeout-probe")
    code = run_command(
        runner_command(settings, project, timeout_probe=True),
        console_log(project, "console.jsonl"),
        120,
    )
    state = read_state(project)
    log = project / ".ai-task-runner" / "log.txt"
    evidence = log.read_text(encoding="utf-8") if log.is_file() else ""
    if code == 0 or state.get("stage") != "blocked" or "kind=timeout" not in evidence:
        raise RuntimeError(
            f"timeout recovery evidence missing: exit={code}, stage={state.get('stage')}"
        )


def soak(settings: Settings, root: Path, hours: float) -> int:
    deadline = time.monotonic() + hours * 3600
    completed = 0
    while time.monotonic() < deadline:
        project = create_project(root, f"soak-{completed + 1:04d}")
        code = run_command(
            runner_command(settings, project),
            console_log(project, "console.jsonl"),
            settings.run_timeout,
        )
        assert_completed(project, code)
        completed += 1
        if settings.pause:
            time.sleep(min(settings.pause, max(0, deadline - time.monotonic())))
    return completed


def has_transient_evidence(root: Path) -> bool:
    for path in root.rglob("log.txt"):
        try:
            if "kind=transient" in path.read_text(encoding="utf-8"):
                return True
        except OSError:
            pass
    return False


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

    server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
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
    if (
        args.hours < 0 or args.pause < 0 or args.run_timeout <= 0
        or not 1 <= args.api_port <= 65535
    ):
        raise SystemExit(
            "hours/pause must be non-negative; run-timeout and api-port must be valid"
        )
    if not shutil.which(args.command) and not Path(args.command).is_file():
        raise SystemExit(f"Qwen command not found: {args.command}")
    settings = Settings(
        args.workspace.resolve(), args.command, args.sandbox,
        args.run_timeout, args.pause, args.api_port,
    )
    run_root = settings.workspace / time.strftime("%Y%m%d-%H%M%S")
    run_root.mkdir(parents=True)
    print(f"LIVE_RUN_ROOT={run_root}", flush=True)
    with qwen_test_endpoint(settings.sandbox, settings.api_port):
        resume_probe(settings, run_root)
        print("PASS resume/process-restart probe", flush=True)
        validator_repair_probe(settings, run_root)
        print("PASS validator-fail/repair probe", flush=True)
        api_recovery_probe(settings, run_root)
        print("PASS transient API/same-session recovery probe", flush=True)
        multi_todo_resume_probe(settings, run_root)
        print("PASS multi-TODO/checkpoint resume probe", flush=True)
        final_ai_quorum_probe(settings, run_root, mixed=False)
        print("PASS Final AI 3/2 quorum probe", flush=True)
        final_ai_quorum_probe(settings, run_root, mixed=True)
        print("PASS Python + Final AI 3/2 mixed probe", flush=True)
        timeout_probe(settings, run_root)
        print("PASS timeout/recovery-budget probe", flush=True)
        completed = soak(settings, run_root, args.hours) if args.hours else 0
        if args.require_transient and not has_transient_evidence(run_root):
            raise RuntimeError("no real transient API recovery was observed")
    summary = {
        "passed": True,
        "sandbox": settings.sandbox,
        "hours_requested": args.hours,
        "soak_runs_completed": completed,
        "transient_observed": has_transient_evidence(run_root),
        "run_root": str(run_root),
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
