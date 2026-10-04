#!/usr/bin/env python3
"""Run opt-in live Qwen workflow-contract, recovery, sandbox, and soak checks."""
from __future__ import annotations

import argparse
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, field, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RUNNER = ROOT / "ai_task_runner.py"
DEFAULT_WORKSPACE = ROOT / ".ai-task-runner-live"
DEFAULT_EXAMPLE_SMOKE_PROJECT = ROOT / "examples" / "01_basic_command_validator" / "project"
EXPECTED = "AI Task Runner live probe passed."

from runner.config.defaults import MAX_TRANSITION_HISTORY
from runner.workflow.loader import WORKFLOWS as RUNNER_WORKFLOWS

WORKFLOWS = {
    name: RUNNER_WORKFLOWS[name]
    for name in ("file", "ai", "mixed")
}
BUILTIN_FINAL_AI_RUNS = 3
BUILTIN_FINAL_AI_REQUIRED_PASSES = 2
LIVE_RETRY_DELAY_SECONDS = 2
LIVE_RETRY_MAX_DELAY_SECONDS = 30

PROBE_ORDER = (
    "ownership-lock",
    "windows-orphan-cleanup",
    "qwen-sandbox",
    "api-retry-classification",
    "task-array-recovery",
    "session-expiry-recovery",
    "stage-probe-live",
    "workflow-dryrun",
    "review-error-policy",
    "review-max-failures",
    "readonly-safety",
    "workflow-dryrun-negative",
    "stage-result-mapping",
    "loop-detection",
    "runtime-long-path",
    "readonly-long-path",
    "technical-artifact-safety",
    "resume",
    "stop-request-resume",
    "workflow-file",
    "workflow-ai",
    "workflow-mixed",
    "dynamic-handoff-session-policy",
    "custom-dynamic-producer",
    "review-failure-routing",
    "complete-closed-loop",
    "validator-failure-routing",
    "file-protection",
    "api-502",
    "api-429",
    "api-503",
    "api-long-http",
    "api-disconnect",
    "multi-todo-resume",
    "yaml-list-resume",
    "yaml-list-endurance",
    "final-ai-quorum",
    "timeout-recovery-budget",
    "soak",
    "example-smoke",
)

QWEN_SANDBOX_ERROR_MARKERS = (
    "failed to connect to the docker api",
    "dockerdesktoplinuxengine",
    "failed to obtain sandbox image",
    "sandbox image",
    "failed to relaunch the cli process",
)
ROUTING_INITIAL = "INITIAL"
ROUTING_FINAL = "RECOVERED"
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

YAML_ARG_VALIDATOR = f'''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
p.add_argument("--case-token", required=True)
a = p.parse_args()
if a.case_token != "ITEM-1":
    print("VALIDATION_FAILED: YAML validator_args were not propagated")
    raise SystemExit(1)
target = Path(a.project_root).resolve() / "health.txt"
if not target.is_file() or target.read_text(encoding="utf-8") != {EXPECTED!r}:
    print("VALIDATION_FAILED: health.txt mismatch")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''

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


CUSTOM_DYNAMIC_PRODUCER = '''from __future__ import annotations
import json

print(json.dumps({
    "tasks": [
        {
            "id": "health",
            "title": "Create health probe",
            "description": "Create health.txt exactly as required by the project goal.",
            "deliverable": "health.txt with the exact required text and no trailing newline.",
            "acceptance_criteria": [
                "health.txt exists",
                "health.txt content exactly matches the requested text",
                "protected files are unchanged"
            ]
        }
    ],
    "stages": [
        {
            "name": "execute",
            "type": "base",
            "profile": "execute",
            "task_id": "health"
        },
        {
            "name": "review",
            "type": "base",
            "profile": "review",
            "task_id": "health",
            "task_complete": True,
            "error_policy": {"retries": 2},
            "max_failures": 3,
            "routes": {"fail": "execute"}
        }
    ]
}, ensure_ascii=False))
'''

CUSTOM_DYNAMIC_WORKFLOW = '''stages:
  discover:
    type: command
    command: "{python} task_producer.py"
    produces: tasks

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"

flow:
  - discover
  - validate_file
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
    transient_status_counts: dict[int, int] = field(default_factory=dict)
    timeout_probes: int = 0
    yaml_runs: int = 0
    sandbox_runs: int = 0
    elapsed_seconds: float = 0
    resource_start: dict[str, int] = field(default_factory=dict)
    resource_max: dict[str, int] = field(default_factory=dict)
    resource_end: dict[str, int] = field(default_factory=dict)


@dataclass
class ProxyControl:
    port: int = 0
    fail: bool = False
    disconnect: bool = False
    status_code: int = 502
    failures: int = 0
    successes: int = 0


@dataclass(frozen=True)
class PromptRecord:
    stage: str
    call_id: str
    session: str
    session_mode: str
    text: str


@dataclass(frozen=True)
class ExampleSmokeCase:
    source: Path
    workflow: Path | None = None
    name: str = ""


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
            "omit the value to use examples/01_basic_command_validator/project"
        ),
    )
    parser.add_argument(
        "--example-smoke-workflow",
        type=Path,
        default=None,
        help="optional workflow YAML for --example-smoke-project",
    )
    parser.add_argument(
        "--example-smoke-matrix-project",
        type=Path,
        action="append",
        default=[],
        help="example project root to cross-run with --example-smoke-matrix-workflow",
    )
    parser.add_argument(
        "--example-smoke-matrix-workflow",
        type=Path,
        action="append",
        default=[],
        help="workflow YAML to cross-run with each --example-smoke-matrix-project",
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
        help="run a bounded-session transient API recovery probe every N soak runs",
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
        "--long-http-outage-seconds",
        type=float,
        default=API_RECOVERY_LONG_HTTP_OUTAGE_SECONDS,
        help=(
            "hold each 429/502/503 outage for this many seconds in the long "
            "HTTP recovery probe"
        ),
    )
    parser.add_argument(
        "--long-api-outage-seconds",
        type=float,
        default=180,
        help="disconnect the API for this many seconds in the long recovery probe",
    )
    parser.add_argument(
        "--single-process-yaml-items",
        type=int,
        default=0,
        help=(
            "run one additional YAML List invocation containing N sequential real-Qwen "
            "items to exercise same-process state/resource accumulation; 0 disables"
        ),
    )
    parser.add_argument(
        "--require-transient",
        action="store_true",
        help="fail unless a real transient API recovery appears in logs",
    )
    parser.add_argument(
        "--start-probe",
        default="",
        metavar="INDEX_OR_NAME",
        help=(
            "skip earlier reliability probes and start at this 1-based probe index "
            "or stable probe name; use --list-probes to show choices"
        ),
    )
    parser.add_argument(
        "--list-probes",
        action="store_true",
        help="print ordered reliability probe indices/names and exit",
    )
    return parser.parse_args()


def source_revision(root: Path = ROOT) -> tuple[str, bool | None]:
    """Return the exact Git revision plus tracked working-tree dirtiness when available."""
    if not shutil.which("git"):
        return "", None
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if head.returncode != 0:
            return "", None
        revision = head.stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return revision, dirty
    except (OSError, subprocess.SubprocessError):
        return "", None


def print_probe_list() -> None:
    for index, name in enumerate(PROBE_ORDER, start=1):
        print(f"{index:02d}  {name}")


def resolve_start_probe(value: str) -> int:
    token = str(value or "").strip()
    if not token:
        return 0
    if token.isdigit():
        index = int(token)
        if not 1 <= index <= len(PROBE_ORDER):
            raise ValueError(
                f"--start-probe index must be between 1 and {len(PROBE_ORDER)}"
            )
        return index - 1
    normalized = token.lower().replace("_", "-")
    try:
        return PROBE_ORDER.index(normalized)
    except ValueError as error:
        raise ValueError(
            f"unknown --start-probe {token!r}; use --list-probes"
        ) from error


def probe_enabled(name: str, start_index: int) -> bool:
    return PROBE_ORDER.index(name) >= start_index


def case_prompt(prompt: str, case_id: str) -> str:
    """Vary the first prompt line so live probes do not all share one cache prefix."""
    return f"Reliability case {case_id}. Follow only this case.\n\n{prompt}"


def create_project(
    parent: Path,
    name: str,
    prompt: str = PROMPT,
    validator: str = VALIDATOR,
    policy: str = POLICY,
) -> Path:
    project = parent / name
    project.mkdir(parents=True, exist_ok=False)
    (project / "prompt.md").write_text(case_prompt(prompt, name), encoding="utf-8")
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
    workflow: Path | None = None,
) -> list[str]:
    effective_sandbox = settings.sandbox if sandbox is None else sandbox
    validator = "ai" if ai_only else str(project / "validation.py")
    command = [
        sys.executable,
        str(RUNNER),
        "--backend", "qwen",
        "--command", settings.command,
        "--project-root", str(project),
        "--retry-delay", "0" if timeout_probe else str(LIVE_RETRY_DELAY_SECONDS),
        "--retry-max-delay", str(LIVE_RETRY_MAX_DELAY_SECONDS),
        "--json-events",
        "--no-ui-project-register",
    ]
    if script:
        command.extend(["--script", str(script)])
    else:
        command.extend(["--goal-file", str(project / "prompt.md")])
        if workflow is None:
            command.extend(["--validator", validator])
        elif workflow_uses_stage(workflow, "validate_file"):
            command.extend(["--validator", str(project / "validation.py")])
        elif ai_only and workflow_uses_stage(workflow, "validate_ai"):
            command.extend(["--validator", "ai"])
    if not timeout_probe:
        command.extend(["--agent-timeout", whole_seconds_arg(settings.agent_timeout)])
        command.extend(["--planning-timeout", whole_seconds_arg(settings.planning_timeout)])
    if effective_sandbox:
        command.append("--sandbox")
    if workflow is not None and script is None:
        command.extend(["--workflow", str(workflow)])
    if resume:
        command.append("--resume")
    else:
        command.append("--force-new")
    if timeout_probe:
        command.extend([
            "--planning-timeout", "1",
            "--agent-timeout", "1",
            "--stage-retries", "2",
        ])
    if final_ai:
        command.extend([
            "--validator-prompt" if ai_only else "--ai-validator-prompt",
            case_prompt(FINAL_AI_PROMPT, f"{project.name}-final-ai"),
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


def builtin_final_ai_contract(workflow: str) -> tuple[int, int, bool]:
    """Return and verify the bundled Final AI contract."""
    if workflow not in {"ai", "mixed"}:
        raise ValueError(f"workflow/{workflow} has no Final AI contract")
    from runner.workflow.loader import load_workflow

    validators = [
        node for node in load_workflow(WORKFLOWS[workflow])
        if node.get("name") == "validate_ai" and node.get("type") == "ai_validator"
    ]
    if len(validators) != 1:
        raise RuntimeError(f"workflow/{workflow} must contain exactly one validate_ai stage")
    validator = validators[0]
    runs = int(validator.get("runs", 1))
    required = int(validator.get("required_passes") or (runs // 2 + 1))
    yolo = validator.get("ai_validator_yolo") is True
    if (runs, required, yolo) != (
        BUILTIN_FINAL_AI_RUNS,
        BUILTIN_FINAL_AI_REQUIRED_PASSES,
        True,
    ):
        raise RuntimeError(
            f"workflow/{workflow} Final AI contract mismatch: "
            f"runs={runs}, required_passes={required}, yolo={yolo}"
        )
    return runs, required, yolo


def _discover_openai_model(port: int) -> str:
    connection = http.client.HTTPConnection("127.0.0.1", int(port), timeout=5)
    try:
        connection.request("GET", "/v1/models")
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(
                f"model discovery failed: HTTP {response.status}: "
                f"{body.decode('utf-8', errors='replace')[-500:]}"
            )
    finally:
        connection.close()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("model discovery returned invalid JSON") from error
    items = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise RuntimeError("model discovery response has no data array")
    for item in items:
        if isinstance(item, dict):
            model = str(item.get("id") or "").strip()
            if model:
                return model
    raise RuntimeError("model discovery returned no usable model id")


def relative_existing_path(child: Path, root: Path) -> str:
    """Return child relative to root using filesystem identity for alias-safe paths."""
    child = Path(child)
    root = Path(root)
    try:
        return child.relative_to(root).as_posix()
    except ValueError:
        pass

    if not child.exists() or not root.exists():
        raise ValueError(f"{child} is not under {root}")

    for ancestor in (child, *child.parents):
        try:
            if os.path.samefile(ancestor, root):
                return child.relative_to(ancestor).as_posix()
        except OSError:
            continue
    raise ValueError(f"{child} is not under {root}")


def _write_live_review_probe_workflow(
    path: Path,
    *,
    backend: str = "",
    model: str = "",
) -> None:
    backend_name = str(backend or "").strip()
    model_name = str(model or "").strip()
    if bool(backend_name) != bool(model_name):
        raise ValueError("live Stage backend/model override must be an atomic pair")
    override = (
        f"    backend: {backend_name}\n"
        f"    model: {json.dumps(model_name)}\n"
        if backend_name
        else ""
    )
    path.write_text(
        """stages:
  review:
    type: base
    profile: review
    prompt: common/review.md
"""
        + override
        + """    error_policy:
      retries: 2
    max_failures: 3
flow:
  - review
""",
        encoding="utf-8",
    )


def _assert_live_review_stage_result(
    stage: dict[str, object],
    backend: str,
) -> None:
    if (
        stage.get("status") != "pass"
        or stage.get("kind") != "review"
        or stage.get("next") != "done"
        or stage.get("route") != "next"
    ):
        raise RuntimeError(
            f"real {backend} Review Stage Probe expected PASS -> done: {stage!r}"
        )


def _assert_live_stage_backend_model_events(
    root: Path,
    stage: dict[str, object],
    backend: str,
    model: str,
) -> None:
    work_dir = Path(str(stage.get("work_dir") or ""))
    try:
        relative_work = relative_existing_path(work_dir, root)
    except ValueError as error:
        raise RuntimeError(
            f"{backend} Stage Probe returned invalid work_dir: {work_dir}"
        ) from error
    model_events = [
        event for event in runner_events(root, relative_work)
        if event.get("type") in {"model.prompt", "model.result"}
    ]
    if not model_events:
        raise RuntimeError(
            f"real {backend} Stage backend/model override emitted no model events"
        )
    if any(str(event.get("backend") or "") != backend for event in model_events):
        raise RuntimeError(
            f"{backend} Stage backend override mismatch: {model_events!r}"
        )
    if any(str(event.get("model") or "") != model for event in model_events):
        raise RuntimeError(
            f"{backend} Stage model override mismatch: "
            f"expected {model!r}, events={model_events!r}"
        )


def _select_live_alternate_backend(
    root: Path,
    primary_backend: str,
) -> tuple[str, str] | None:
    """Pick the first runnable registered backend with at least one selectable model."""
    from runner.agent import available_models, backend_names, default_command
    from runner.plugins.registry import discover_plugins

    discover_plugins()
    for backend in backend_names():
        if backend == primary_backend:
            continue
        command = default_command(backend)
        if not (Path(command).is_file() or shutil.which(command) is not None):
            continue
        try:
            models = available_models(backend, root)
        except Exception:
            continue
        if models:
            return backend, models[0]
    return None


def stage_probe_live_preflight(settings: Settings) -> dict[str, object]:
    """Exercise real Stage transport plus Stage-local backend/model overrides."""
    tool = ROOT / "tool" / "stage_probe.py"

    def run_probe(
        root: Path,
        workflow: Path,
        mode: str,
        log: Path,
        *,
        keep_work: bool = False,
    ) -> dict[str, object]:
        command = [
            sys.executable,
            str(tool),
            "--project-root", str(root),
            "--workflow", str(workflow),
            "--stage", "review",
            "--backend", "qwen",
            "--command", settings.command,
            "--probe-mode", mode,
        ]
        if mode == "stage":
            command += [
                "--input",
                "REVIEW_STAGE_PROBE_OK is the complete deliverable and executor evidence. "
                "Verify that this exact non-empty deliverable is present and consistent, then decide immediately.",
            ]
        if keep_work:
            command.append("--keep-work")
        code = run_command(command, log, min(settings.run_timeout, max(180.0, settings.agent_timeout + 60)))
        raw = [line.strip() for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        if not raw:
            raise RuntimeError(f"Stage Probe {mode} produced no output")
        try:
            payload = json.loads(raw[-1])
        except json.JSONDecodeError as error:
            raise RuntimeError(f"Stage Probe {mode} returned invalid JSON: {_tail_text(raw[-1])}") from error
        if code != 0 or not isinstance(payload, dict):
            raise RuntimeError(f"Stage Probe {mode} failed: code={code}, payload={payload!r}")
        return payload

    with tempfile.TemporaryDirectory(prefix="ai-runner-stage-probe-live-") as directory:
        root = Path(directory) / "project"
        root.mkdir()
        workflow = Path(directory) / "stage-probe.yaml"
        _write_live_review_probe_workflow(workflow)
        ping = run_probe(root, workflow, "agent_ping", Path(directory) / "agent-ping.log")
        if str(ping.get("output", "")).strip() != "AGENT_PING_OK":
            raise RuntimeError(f"real Agent Ping contract mismatch: {ping!r}")

        ping_data = ping.get("data") if isinstance(ping.get("data"), dict) else {}
        baseline_model = str(ping_data.get("model") or "").strip() or _discover_openai_model(settings.api_port)
        _write_live_review_probe_workflow(
            workflow,
            backend="qwen",
            model=baseline_model,
        )
        stage = run_probe(
            root,
            workflow,
            "stage",
            Path(directory) / "real-stage.log",
            keep_work=True,
        )
        _assert_live_review_stage_result(stage, "qwen")
        _assert_live_stage_backend_model_events(
            root,
            stage,
            "qwen",
            baseline_model,
        )
        result: dict[str, object] = {
            "agent_ping": True,
            "real_stage_status": stage.get("status"),
            "real_stage_next": stage.get("next"),
            "stage_backend": "qwen",
            "stage_model": baseline_model,
            "alternate_stage": {
                "available": False,
                "tested": False,
                "reason": "no_runnable_backend",
            },
        }

        alternate = _select_live_alternate_backend(root, "qwen")
        if alternate is None:
            return result
        alternate_backend, alternate_model = alternate
        _write_live_review_probe_workflow(
            workflow,
            backend=alternate_backend,
            model=alternate_model,
        )
        alternate_stage = run_probe(
            root,
            workflow,
            "stage",
            Path(directory) / f"{alternate_backend}-stage.log",
            keep_work=True,
        )
        _assert_live_review_stage_result(alternate_stage, alternate_backend)
        _assert_live_stage_backend_model_events(
            root,
            alternate_stage,
            alternate_backend,
            alternate_model,
        )
        result["alternate_stage"] = {
            "available": True,
            "tested": True,
            "backend": alternate_backend,
            "status": alternate_stage.get("status"),
            "model": alternate_model,
        }
        return result


def _plan_review_template() -> dict[str, object]:
    from runner.runtime.run_state import Task
    from runner.workflow.stages import PlanStage

    tasks = [
        Task(
            id="contract-task",
            title="Contract task",
            description="Validate dynamic Plan child contract.",
            acceptance_criteria=["Review child is configured safely."],
            deliverable="Contract evidence",
        )
    ]
    children = PlanStage._plan_child_stages(tasks)
    review = next(
        (item for item in children if item.get("profile") == "review"),
        None,
    )
    if not isinstance(review, dict):
        raise RuntimeError("Plan Stage did not generate an AI Review child")
    return review


def builtin_review_error_policy_contract() -> dict[str, int]:
    """Verify dynamic Plan Review children keep the finite fail-soft policy."""
    review = _plan_review_template()
    policy = review.get("error_policy")
    retries = policy.get("retries") if isinstance(policy, dict) else None
    if retries != 2:
        raise RuntimeError(
            f"dynamic Plan Review error_policy mismatch: expected retries=2, got {retries!r}"
        )
    return {workflow: int(retries) for workflow in ("file", "ai", "mixed")}


def builtin_review_max_failures_contract() -> dict[str, int]:
    """Verify dynamic Plan Review children keep the bounded semantic FAIL loop."""
    review = _plan_review_template()
    maximum = review.get("max_failures")
    if maximum != 3:
        raise RuntimeError(
            f"dynamic Plan Review max_failures mismatch: expected 3, got {maximum!r}"
        )
    return {workflow: int(maximum) for workflow in ("file", "ai", "mixed")}


def builtin_readonly_safety_contract() -> dict[str, dict[str, str | None]]:
    """Verify static read-only stages and dynamic Plan Review children use observe."""
    from runner.workflow.loader import load_workflow

    expected = {
        "file": {"planning": "observe"},
        "ai": {"planning": "observe", "validate_ai": "observe"},
        "mixed": {"planning": "observe", "validate_ai": "observe"},
    }
    observed: dict[str, dict[str, str | None]] = {}
    for workflow, stages in expected.items():
        loaded = load_workflow(WORKFLOWS[workflow])
        by_name = {str(node.get("name", "")): node for node in loaded}
        observed[workflow] = {}
        for stage, expected_value in stages.items():
            actual = by_name.get(stage, {}).get("readonly_safety")
            observed[workflow][stage] = actual if isinstance(actual, str) else None
            if actual != expected_value:
                raise RuntimeError(
                    f"workflow/{workflow} {stage} readonly_safety mismatch: "
                    f"expected {expected_value!r}, got {actual!r}"
                )
        from runner.workflow.registry import create_stage
        template = dict(_plan_review_template())
        template.pop("task_id", None)
        template.pop("task_complete", None)
        dynamic_review = create_stage({
            "name": "dynamic_review_contract",
            **template,
        }).readonly_safety
        observed[workflow]["dynamic_review"] = dynamic_review
        if dynamic_review != "observe":
            raise RuntimeError(
                f"workflow/{workflow} dynamic Review readonly_safety mismatch: "
                f"expected 'observe', got {dynamic_review!r}"
            )
    return observed


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
        if observe:
            observe()
        return process.returncode or 0
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()


def _tail_text(text: str, limit: int = 1200) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[-limit:]


def semantic_probe_timeout(settings: Settings) -> float:
    """Bound semantic routing probes independently from the 24H harness timeout."""
    estimated = (settings.agent_timeout * 3) + (settings.planning_timeout * 3) + 120
    return min(settings.run_timeout, max(1200.0, min(3600.0, estimated)))


def probe_timeout_diagnostic(project: Path, log: Path) -> str:
    state_path = project / ".ai-task-runner" / "state.json"
    state_summary = ""
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state_summary = json.dumps(
            {
                "stage": state.get("stage"),
                "cycle": state.get("cycle"),
                "current": state.get("current"),
                "workflow_position": state.get("workflow_position"),
                "transition_previous": state.get("transition_previous"),
                "validator_output": _tail_text(str(state.get("validator_output") or ""), 800),
            },
            ensure_ascii=False,
            default=str,
        )
    except (OSError, json.JSONDecodeError):
        state_summary = "state unavailable"

    try:
        console_tail = _tail_text(log.read_text(encoding="utf-8", errors="replace"), 2400)
    except OSError:
        console_tail = "console unavailable"
    return f"state={state_summary}; console_tail={console_tail}"


def qwen_sandbox_required(settings: Settings, hours: float = 0) -> bool:
    return settings.sandbox or (hours > 0 and settings.soak_sandbox_every > 0)


def qwen_sandbox_log_diagnostic(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lowered = text.lower()
    if not any(marker in lowered for marker in QWEN_SANDBOX_ERROR_MARKERS):
        return ""
    return (
        "Qwen sandbox unavailable: Docker daemon/image access failed. "
        "Start Docker Desktop or disable sandbox probes with --soak-sandbox-every 0. "
        "Recent evidence: "
        + _tail_text(text)
    )


def qwen_sandbox_preflight(settings: Settings, hours: float = 0) -> None:
    if not qwen_sandbox_required(settings, hours):
        return
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError(
            "Qwen sandbox unavailable: docker command not found. "
            "Install/start Docker Desktop or disable sandbox probes with --soak-sandbox-every 0."
        )
    try:
        result = subprocess.run(
            [docker, "info"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(
            "Qwen sandbox unavailable: Docker daemon not reachable. "
            "Start Docker Desktop or disable sandbox probes with --soak-sandbox-every 0. "
            f"Detail: {error}"
        ) from error
    if result.returncode != 0:
        raise RuntimeError(
            "Qwen sandbox unavailable: Docker daemon not reachable. "
            "Start Docker Desktop or disable sandbox probes with --soak-sandbox-every 0. "
            "Recent evidence: "
            + _tail_text(result.stdout)
        )


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


def runner_events(
    project: Path, work_dir: str = ".ai-task-runner"
) -> list[dict[str, object]]:
    return jsonl_events(project / work_dir / "log.txt")


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


def prompt_records(project: Path, work_dir: str = ".ai-task-runner") -> list[PromptRecord]:
    """Correlate model.prompt log events with bounded history prompt snapshots."""
    work = project / work_dir
    current_stage = ""
    result: list[PromptRecord] = []
    for event in jsonl_events(work / "log.txt"):
        if event.get("type") == "runner.stage":
            action = event.get("action")
            stage = str(event.get("stage", ""))
            if action == "start":
                current_stage = stage
            elif action == "finish" and stage == current_stage:
                current_stage = ""
            continue
        if event.get("type") != "model.prompt":
            continue
        call_id = str(event.get("call_id", ""))
        path = work / "debug" / "history" / f"{call_id}-prompt.txt"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        result.append(PromptRecord(
            current_stage,
            call_id,
            str(event.get("session", "")),
            str(event.get("session_mode", "")),
            text,
        ))
    return result


def stage_prompt_records(project: Path, stage: str) -> list[PromptRecord]:
    return [record for record in prompt_records(project) if record.stage == stage]


def stage_result_sessions(project: Path, stage: str) -> list[str]:
    current_stage = ""
    sessions: list[str] = []
    for event in runner_events(project):
        if event.get("type") == "runner.stage":
            action = event.get("action")
            name = str(event.get("stage", ""))
            if action == "start":
                current_stage = name
            elif action == "finish" and name == current_stage:
                current_stage = ""
        elif (
            current_stage == stage
            and event.get("type") == "model.result"
            and not event.get("error")
            and event.get("session")
        ):
            sessions.append(str(event["session"]))
    return sessions


def assert_prompt_transport_contract(project: Path) -> None:
    """Lock shared-control prompt transport without brittle token thresholds."""
    records = prompt_records(project)
    if not records:
        raise RuntimeError("prompt audit found no model.prompt history")
    static_markers = (
        "Goal (global constraints only):",
        "Goal (context/global constraints only):",
        "Current TODO is the only executable scope.",
        "Evidence order:",
        "Decision:",
        "Project root:",
    )
    for record in records:
        text = record.text
        if text.startswith("RUNNER_SHARED_STAGE_CONTROL"):
            if "mode: recover" in text:
                raise RuntimeError(
                    f"fresh recover omitted stage instructions: {record.stage}"
                )
            if record.session_mode != "resume":
                raise RuntimeError(
                    f"shared same-session control did not resume existing session: {record.stage}"
                )
            if "mode: continue" not in text and "mode: retry" not in text:
                raise RuntimeError(
                    f"shared same-session control has unexpected mode: {record.stage}"
                )
            if any(value in text for value in static_markers):
                raise RuntimeError(
                    f"shared same-session control resent static stage context: {record.stage}"
                )
        if "mode: retry" in text and "previous_error:" not in text:
            raise RuntimeError(
                f"shared retry omitted previous failure evidence: {record.stage}"
            )
        if "mode: recover" in text and record.session_mode == "resume":
            raise RuntimeError(
                f"recover control unexpectedly reused an existing session: {record.stage}"
            )


def assert_builtin_topology(project: Path, workflow: str) -> None:
    starts = [
        str(event.get("stage", ""))
        for event in runner_events(project)
        if event.get("type") == "runner.stage" and event.get("action") == "start"
    ]
    expected_validators = {
        "file": {"validate_file"},
        "ai": {"validate_ai"},
        "mixed": {"validate_file", "validate_ai"},
    }[workflow]
    validators = {name for name in starts if name.startswith("validate_")}
    execute_runs = [name for name in starts if name.endswith("_execute")]
    review_runs = [name for name in starts if name.endswith("_review")]

    state = read_state(project)
    tasks = state.get("tasks")
    task_count = len(tasks) if isinstance(tasks, list) else 0
    incomplete = (
        [
            str(item.get("title") or item.get("id") or index)
            for index, item in enumerate(tasks)
            if isinstance(item, dict) and item.get("status") != "completed"
        ]
        if isinstance(tasks, list)
        else ["<missing durable tasks>"]
    )
    expanded = state.get("expanded_workflow")
    expanded_names = {
        str(item.get("name", ""))
        for item in expanded
        if isinstance(item, dict)
    } if isinstance(expanded, list) else set()

    invalid_dynamic_children = (
        "planning" not in starts
        or task_count < 1
        or len(execute_runs) < task_count
        or len(review_runs) < task_count
        or bool(incomplete)
        or not any(name.endswith("_execute") for name in expanded_names)
        or not any(name.endswith("_review") for name in expanded_names)
    )
    if validators != expected_validators or invalid_dynamic_children:
        raise RuntimeError(
            f"workflow/{workflow} topology mismatch: "
            f"validators={sorted(validators)}, durable_tasks={task_count}, "
            f"incomplete={incomplete}, execute_runs={len(execute_runs)}, "
            f"review_runs={len(review_runs)}, expanded={sorted(expanded_names)}"
        )


def observed_session(project: Path, session_id: str, mode: str) -> bool:
    return any(
            event.get("type") == "model.prompt"
            and event.get("session") == session_id
            and event.get("session_mode") == mode
        for event in runner_events(project)
    )


def final_validation_sessions(
    project: Path, work_dir: str = ".ai-task-runner"
) -> set[str]:
    sessions: set[str] = set()
    validating = False
    for event in runner_events(project, work_dir):
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


def _latest_harness_log(project: Path) -> Path | None:
    root = project.parent / "_harness-logs"
    try:
        matches = sorted(
            root.glob(f"{project.name}-*.jsonl"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
    except OSError:
        return None
    return matches[0] if matches else None


def assert_state_completed(
    project: Path,
    code: int,
    work_dir: str = ".ai-task-runner",
) -> None:
    work = project / work_dir
    state = read_json(work / "state.json")
    if code != 0 or state.get("completed") is not True:
        validator_output = str(state.get("validator_output") or "").strip()
        harness_log = _latest_harness_log(project)
        diagnostic = (
            probe_timeout_diagnostic(project, harness_log)
            if harness_log is not None
            else "console_tail=unavailable"
        )
        raise RuntimeError(
            "run failed: "
            f"exit={code}, stage={state.get('stage')}, cycle={state.get('cycle')}, "
            f"current={state.get('current')}, workflow_position={state.get('workflow_position')}, "
            f"transition_previous={state.get('transition_previous')!r}, "
            f"validator_output={validator_output[-1200:]!r}; {diagnostic}"
        )
    required = (
        work / "log.txt",
        work / "debug" / "last-prompt.txt",
        work / "debug" / "last-result.txt",
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError("missing diagnostics: " + ", ".join(missing))
    stale = [
        path.name for path in (
            work / "runner-process.json",
            work / "stop.request",
            work / "active-process",
        )
        if path.exists()
    ]
    if stale:
        raise RuntimeError("completed run left stale runtime control files: " + ", ".join(stale))


def copy_example_project(source: Path, root: Path, name: str = "example-smoke-probe") -> Path:
    project = root / name
    shutil.copytree(
        source,
        project,
        ignore=shutil.ignore_patterns(".ai-task-runner", "__pycache__"),
    )
    return project


def example_smoke_probe(
    settings: Settings,
    root: Path,
    source: Path,
    workflow: Path | None = None,
    name: str = "example-smoke-probe",
) -> Path:
    project = copy_example_project(source.resolve(), root, name)
    ai_only = workflow is not None and not workflow_uses_stage(workflow, "validate_file")
    code = run_command(
        runner_command(settings, project, workflow=workflow, ai_only=ai_only),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_state_completed(project, code)
    return project


def workflow_uses_stage(workflow: Path, name: str) -> bool:
    from runner.workflow.loader import load_workflow

    return any(item.get("name") == name for item in load_workflow(workflow))


def example_smoke_cases(args: argparse.Namespace) -> list[ExampleSmokeCase]:
    cases: list[ExampleSmokeCase] = []
    if args.example_smoke_project is not None:
        cases.append(
            ExampleSmokeCase(
                args.example_smoke_project,
                args.example_smoke_workflow,
                "example-smoke-probe",
            )
        )

    projects = list(args.example_smoke_matrix_project)
    workflows = list(args.example_smoke_matrix_workflow) or [None]
    for project in projects:
        for workflow in workflows:
            cases.append(
                ExampleSmokeCase(
                    project,
                    workflow,
                    f"example-smoke-{_slug(project)}-{_slug(workflow)}",
                )
            )
    return cases


def validate_example_smoke_cases(cases: list[ExampleSmokeCase]) -> None:
    names = set()
    for case in cases:
        source = case.source.resolve()
        if (
            not source.is_dir()
            or not (source / "prompt.md").is_file()
            or not (source / "validation.py").is_file()
        ):
            raise SystemExit(
                f"example smoke project must contain prompt.md and validation.py: {source}"
            )
        if case.workflow is not None and not case.workflow.is_file():
            raise SystemExit(f"example smoke workflow must be an existing YAML file: {case.workflow}")
        if case.name in names:
            raise SystemExit(f"duplicate example smoke case name: {case.name}")
        names.add(case.name)


def _slug(path: Path | None) -> str:
    if path is None:
        return "default"
    base = path.parent.name if path.name == "project" else path.stem
    chars = [char.lower() if char.isalnum() else "-" for char in base]
    return "-".join("".join(chars).split("-")) or "case"


def api_retry_classification_preflight() -> None:
    """Prove API retry loops only transient RunnerError failures."""
    import runner.api as api_module
    from runner.api import RunRequest
    from runner.errors import RunnerError

    with tempfile.TemporaryDirectory(prefix="ai-runner-api-retry-") as directory:
        root = Path(directory)
        request = RunRequest(
            goal="retry classification probe",
            project_root=str(root),
            validator="ai",
            retry_delay=0,
        )
        original_execute = api_module.execute
        calls: list[bool] = []

        def deterministic(config):
            calls.append(bool(config.resume))
            raise RunnerError("saved dynamic child cursor is outside the expanded Workflow")

        api_module.execute = deterministic
        try:
            try:
                api_module.run(request)
            except RunnerError:
                pass
            else:
                raise RuntimeError("deterministic RunnerError was unexpectedly retried/completed")
        finally:
            api_module.execute = original_execute
        if calls != [False]:
            raise RuntimeError(f"deterministic RunnerError retry contract failed: {calls}")

        state = root / ".ai-task-runner" / "state.json"
        calls.clear()

        def transient(config):
            calls.append(bool(config.resume))
            state.parent.mkdir(parents=True, exist_ok=True)
            if len(calls) == 1:
                state.write_text('{"completed":false,"stage":"validating"}', encoding="utf-8")
                error = RunnerError("temporary backend outage")
                error.transient = True
                raise error
            state.write_text('{"completed":true,"stage":"completed"}', encoding="utf-8")
            return 0

        api_module.execute = transient
        try:
            result = api_module.run(request)
        finally:
            api_module.execute = original_execute
        if not result.completed or calls != [False, True]:
            raise RuntimeError(f"transient RunnerError resume contract failed: {calls}")


def task_array_recovery_preflight() -> None:
    """Prove Planning can recover a complete TaskArray from a broken object envelope."""
    from types import SimpleNamespace

    from runner.workflow.stages.plan_stage import parse_plan_tasks

    payload = [{
        "title": "Create artifact",
        "description": "Create the requested artifact.",
        "deliverable": "artifact.txt",
        "acceptance_criteria": ["artifact.txt exists"],
    }]
    malformed = '{"tasks":' + json.dumps(payload)  # deliberately missing outer }
    context = SimpleNamespace(state=SimpleNamespace(cycle=4))
    tasks = parse_plan_tasks(malformed, context, minimum=1)
    if len(tasks) != 1 or tasks[0].id != "c04-t001" or tasks[0].title != "Create artifact":
        raise RuntimeError("TaskArray structured-output recovery contract failed")


def session_expiry_recovery_preflight() -> None:
    """Prove an unavailable durable Qwen session resets to Fresh and resumes from Runner state."""
    agent = ROOT / "tests" / "session_expired_agent.py"
    if not agent.is_file():
        raise RuntimeError(f"session-expiry probe agent is missing: {agent}")
    with tempfile.TemporaryDirectory(prefix="ai-runner-session-expiry-") as directory:
        container = Path(directory)
        root = container / "project"
        root.mkdir()
        # Fake-agent counters are deliberately outside project_root so read-only
        # Planning cannot mistake probe bookkeeping for an AI file mutation.
        state_dir = container / "probe-state"
        command = [
            sys.executable, str(RUNNER),
            "--backend", "qwen",
            "--command", subprocess.list2cmdline([sys.executable, str(agent)]),
            "--project-root", str(root),
            "--goal", "Create done.txt and validate it.",
            "--validator", "ai",
            "--stage-retries", "2",
            "--retry-delay", "0",
            "--retry-max-delay", "0",
            "--agent-timeout", "30",
            "--planning-timeout", "30",
            "--force-new",
            "--no-ui-project-register",
            "--json-events",
        ]
        previous = os.environ.get("SESSION_TEST_STATE_DIR")
        os.environ["SESSION_TEST_STATE_DIR"] = str(state_dir)
        try:
            code = run_command(command, console_log(root, "console.jsonl"), 60)
        finally:
            if previous is None:
                os.environ.pop("SESSION_TEST_STATE_DIR", None)
            else:
                os.environ["SESSION_TEST_STATE_DIR"] = previous
        assert_state_completed(root, code)
        if not (root / "done.txt").is_file():
            raise RuntimeError("expired-session recovery did not complete from durable Runner state")
        events = runner_events(root)
        stage_recovery = [
            event for event in events
            if event.get("type") == "runner.recovery"
            and event.get("action") == "retry"
            and int(event.get("retry") or 0) >= 1
            and str(event.get("retry_mode") or "") in {"retry", "recover"}
            and "HTTP 503" in str(event.get("error") or "")
        ]
        if not stage_recovery:
            raise RuntimeError(
                "production CLI transient Stage failure emitted no runner.recovery/retry evidence"
            )
        reset_indexes = [
            index for index, event in enumerate(events)
            if event.get("type") == "model.result"
            and event.get("session") == "old-session"
            and "session_recovery_action=reset_session" in str(event.get("error", ""))
        ]
        if not reset_indexes:
            raise RuntimeError("expired-session recovery did not record reset_session evidence")
        fresh_seen = any(
            index > reset_indexes[-1]
            and event.get("type") == "model.prompt"
            and event.get("session_mode") == "new"
            for index, event in enumerate(events)
        )
        if not fresh_seen:
            raise RuntimeError("expired-session recovery did not continue in a Fresh Session")


def workflow_dryrun_preflight() -> list[dict[str, object]]:
    """Exercise representative Workflow routing deterministically before live Qwen calls."""
    tool_workflows = [
        ROOT / "tool" / "workflow" / name
        for name in (
            "01_default_ai.yaml",
            "02_ai_with_review_gate.yaml",
            "03_file_validation.yaml",
            "04_mixed_with_review_gate.yaml",
            "05_review_vote_3_choose_2.yaml",
            "06_custom_task_producer.yaml",
            "11_multi_validators_anywhere.yaml",
        )
    ]
    workflows = [
        *WORKFLOWS.values(),
        RUNNER_WORKFLOWS["dynamic_handoff"],
        RUNNER_WORKFLOWS["ralphy_ai_validate"],
        ROOT / "examples" / "custom_workflow_latest.yaml",
        *tool_workflows,
    ]
    tool = ROOT / "tool" / "workflow_dryrun.py"
    results: list[dict[str, object]] = []
    def run_one(workflow: Path) -> dict[str, object]:
        if not workflow.is_file():
            raise RuntimeError(f"dry-run preflight workflow missing: {workflow}")
        completed = subprocess.run(
            [sys.executable, str(tool), str(workflow), "--matrix", "--json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-4000:]
            raise RuntimeError(f"workflow dry-run preflight failed for {workflow}: {detail}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"workflow dry-run returned invalid JSON for {workflow}") from error
        if payload.get("closed") is not True:
            raise RuntimeError(f"workflow dry-run did not close: {workflow}")
        return payload

    for workflow in workflows:
        results.append(run_one(workflow))

    with tempfile.TemporaryDirectory(prefix="ai-runner-12-stage-") as directory:
        path = Path(directory) / "workflow.yaml"
        stage_lines = []
        flow_lines = []
        for index in range(1, 13):
            name = f"s{index:02d}"
            stage_lines.extend([
                f"  {name}:",
                "    type: command",
                f'    command: ["{{python}}", -c, "print(\'{name}\')"]',
            ])
            target = {5: "s03", 9: "s07", 10: "s08"}.get(index)
            if target:
                stage_lines.extend([
                    "    routes:",
                    f"      fail: {target}",
                ])
            flow_lines.append(f"  - {name}")
        path.write_text(
            "stages:\n" + "\n".join(stage_lines) + "\nflow:\n"
            + "\n".join(flow_lines) + "\n",
            encoding="utf-8",
        )
        twelve = run_one(path)
        twelve["workflow"] = "synthetic://12-stage-composability"
        results.append(twelve)

    multi = next(
        (item for item in results if str(item.get("workflow", "")).endswith("11_multi_validators_anywhere.yaml")),
        None,
    )
    multi_features = multi.get("features", {}) if isinstance(multi, dict) else {}
    if (
        not isinstance(multi_features, dict)
        or int(multi_features.get("file_validations", 0)) < 2
        or int(multi_features.get("ai_validations", 0)) < 2
        or multi_features.get("validation_not_last") is not True
    ):
        raise RuntimeError("multi-validator dry-run preflight did not cover arbitrary validator placement")

    custom = next(
        (item for item in results if str(item.get("workflow", "")).endswith("custom_workflow_latest.yaml")),
        None,
    )
    features = custom.get("features", {}) if isinstance(custom, dict) else {}
    if (
        not isinstance(features, dict)
        or not features.get("task_producer")
        or not features.get("dynamic_producer")
    ):
        raise RuntimeError(
            "custom Dynamic Producer dry-run preflight did not cover producer-defined dynamic child Workflow"
        )
    return results


def workflow_dryrun_negative_preflight() -> None:
    """Prove dry-run rejects invalid schema and detects a non-converging loop."""
    tool = ROOT / "tool" / "workflow_dryrun.py"
    with tempfile.TemporaryDirectory(prefix="ai-runner-dryrun-negative-") as directory:
        root = Path(directory)
        invalid = root / "invalid.yaml"
        invalid.write_text(
            "stages:\n  work:\n    type: base\n    profile: execute\n    unsupported_option: true\nflow: [work]\n",
            encoding="utf-8",
        )
        invalid_run = subprocess.run(
            [sys.executable, str(tool), str(invalid), "--matrix", "--json"],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        if invalid_run.returncode != 2 or "DRYRUN_ERROR" not in invalid_run.stderr:
            raise RuntimeError("workflow dry-run failed to reject an invalid Stage option")

        looping = root / "loop.yaml"
        scenario = root / "loop-scenario.yaml"
        looping.write_text(
            """stages:
  check:
    type: command
    command: [python, -c, "print('CHECK')"]
    routes:
      fail: check
flow:
  - check
""",
            encoding="utf-8",
        )
        scenario.write_text(
            "default: pass\nstages:\n  check: fail\n", encoding="utf-8"
        )
        loop_run = subprocess.run(
            [
                sys.executable, str(tool), str(looping), "--scenario", str(scenario),
                "--max-steps", "8", "--json",
            ],
            cwd=ROOT, text=True, capture_output=True, timeout=30,
        )
        if loop_run.returncode != 1:
            raise RuntimeError("workflow dry-run failed to reject a non-converging result-edge loop")
        try:
            payload = json.loads(loop_run.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError("negative workflow dry-run returned invalid JSON") from error
        if "did not converge" not in str(payload.get("error", "")):
            raise RuntimeError("workflow dry-run did not report its convergence limit")


def stage_result_mapping_preflight() -> None:
    """Prove immutable Review/Validator booleans map to Runner PASS/FAIL correctly."""
    from runner.workflow.stages import (
        AIValidatorStage,
        AIValidatorStageSpec,
        BaseStage,
        BaseStageSpec,
    )

    review = BaseStage(BaseStageSpec(name="review", profile="review"))
    validator = AIValidatorStage(AIValidatorStageSpec(name="validate_ai"))
    checks = [
        (review.result_status({"completed": True}), "pass", "review true"),
        (review.result_status({"completed": False}), "fail", "review false"),
        (validator.result_status({"passed": True}), "pass", "validator true"),
        (validator.result_status({"passed": False}), "fail", "validator false"),
    ]
    wrong = [label for actual, expected, label in checks if actual != expected]
    if wrong:
        raise RuntimeError("stage verdict mapping contract failed: " + ", ".join(wrong))


def _deep_preflight_root(base: Path, minimum: int = 300) -> Path:
    root = base
    index = 0
    while len(str(root)) <= minimum:
        root = root / (f"segment-{index}-" + "x" * 38)
        index += 1
    from runner.utils import io_path

    io_path(root).mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def _long_path_temp_root(prefix: str, minimum: int):
    """Create and clean a deep temp tree using the same long-path-safe I/O contract.

    tempfile.TemporaryDirectory ultimately calls shutil.rmtree() with the normal
    non-extended root path. On Windows, cleanup can therefore fail after a
    successful >MAX_PATH preflight with WinError 145 because descendants cannot
    be removed. Keep the logical path for the test, but always clean through
    runner.utils.remove_path(), which applies the extended-length prefix.
    """
    from runner.utils import remove_path

    base = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield _deep_preflight_root(base, minimum)
    finally:
        remove_path(base)


def runtime_long_path_preflight() -> None:
    """Exercise core resource/state/snapshot I/O beyond traditional Windows MAX_PATH."""
    from runner.resources import read_text, write_text
    from runner.runtime.run_state import RunState, StateStore
    from runner.utils import copy_path, digest, remove_path
    from runner.resources import freeze_run_resource, load_run_resource

    with _long_path_temp_root("ai-runner-long-path-", 300) as root:
        source = root / "source.txt"
        write_text(source, "deep")
        if read_text(source)[0] != "deep":
            raise RuntimeError("long-path resource read/write contract failed")
        copied = root / "nested" / "copy.txt"
        copy_path(source, copied)
        if digest(copied) != digest(source):
            raise RuntimeError("long-path copy/digest contract failed")
        remove_path(copied)
        if copied.exists():
            raise RuntimeError("long-path remove contract failed")

        work = root / ".ai-task-runner"
        store = StateStore(root, work)
        store.save(RunState(run_id="long-path", goal="probe", project_root=str(root)))
        resumed = store.load_or_create("", resume=True, force_new=False)
        if resumed.run_id != "long-path":
            raise RuntimeError("long-path state save/resume contract failed")

        goal = root / "goal.md"
        write_text(goal, "goal")
        freeze_run_resource(goal, root, ".ai-task-runner", "goal")
        loaded = load_run_resource(root, ".ai-task-runner", "goal")
        if loaded is None or loaded[1] != "goal":
            raise RuntimeError("long-path frozen run-resource contract failed")


def readonly_long_path_preflight() -> None:
    """Prove the reusable read-only baseline restores deep paths and follows valid writes."""
    from types import SimpleNamespace
    from runner.bootstrap import runtime_scope
    from runner.config.runtime import RuntimeConfig
    from runner.plugins.safety import SafetyHook

    class ProbeSafetyHook(SafetyHook):
        def _protected(self, root):
            return []

    from runner.resources import read_text, write_text
    from runner.utils import io_path

    with _long_path_temp_root("ai-runner-readonly-long-", 260) as root:
        work = root / ".ai-task-runner"
        io_path(work).mkdir(parents=True, exist_ok=True)
        target = root / "value.txt"
        write_text(target, "v1")
        hook = ProbeSafetyHook()

        def context(mode: str, actor: str):
            return SimpleNamespace(root=root, work=work, mode=mode, actor=actor)

        first = hook.before_execution(context("readonly", "review"))
        baseline = first.backup
        write_text(target, "bad")
        violations = hook.after_execution(context("readonly", "review"), first)
        if read_text(target)[0] != "v1" or not violations:
            raise RuntimeError("long-path read-only restore contract failed")

        write = hook.before_execution(context("write", "task"))
        write_text(target, "v2")
        hook.after_execution(context("write", "task"), write)
        second = hook.before_execution(context("readonly", "validator"))
        if second.backup != baseline:
            raise RuntimeError("read-only snapshot cache was not reused")
        write_text(target, "bad2")
        hook.after_execution(context("readonly", "validator"), second)
        if read_text(target)[0] != "v2":
            raise RuntimeError("read-only snapshot cache did not track legitimate writes")

        observe_config = RuntimeConfig(
            goal="readonly observe preflight",
            project_root=str(root),
            validator="ai",
            readonly_safety="observe",
        )
        with runtime_scope(observe_config):
            observed = hook.before_execution(context("readonly", "review"))
            write_text(target, "observed")
            violations = hook.after_execution(context("readonly", "review"), observed)
            if read_text(target)[0] != "observed" or not any(
                "observed and not restored" in violation.message
                for violation in violations
            ):
                raise RuntimeError("read-only observe mode restored an ordinary change")

            class ProtectedProbeSafetyHook(SafetyHook):
                def _protected(self, root):
                    return [target]

            protected_hook = ProtectedProbeSafetyHook()
            protected = protected_hook.before_execution(context("readonly", "review"))
            write_text(target, "protected-bad")
            protected_hook.after_execution(context("readonly", "review"), protected)
            if read_text(target)[0] != "observed":
                raise RuntimeError("read-only observe mode failed to restore protected data")


def technical_artifact_safety_preflight() -> None:
    """Prove caches/build/IDE metadata cannot cause protected-path semantic reroutes."""
    from runner.plugins.safety import restore_changed, snapshot

    with tempfile.TemporaryDirectory(prefix="ai-runner-safety-artifacts-") as temporary:
        protected = Path(temporary) / "tools"
        protected.mkdir()
        source = protected / "helper.py"
        source.write_text("VALUE = 1\n", encoding="utf-8")
        saved = snapshot([protected])

        ignored = (
            ".git/index", ".vs/state.bin", ".vscode/settings.json",
            ".pytest_cache/state", "__pycache__/helper.cpython-310.pyc",
            "bin/app.dll", "obj/app.obj", "TestResults/result.trx",
        )
        for relative in ignored:
            path = protected / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("runtime", encoding="utf-8")
        if restore_changed(saved):
            raise RuntimeError("technical artifacts were treated as protected source changes")

        saved = snapshot([protected])
        source.write_text("changed\n", encoding="utf-8")
        generated = protected / "bin" / "app.dll"
        generated.write_text("keep-generated", encoding="utf-8")
        changed = restore_changed(saved)
        if changed != [str(protected)] or source.read_text(encoding="utf-8") != "VALUE = 1\n":
            raise RuntimeError("real protected source mutation was not restored")
        if generated.read_text(encoding="utf-8") != "keep-generated":
            raise RuntimeError("protected restore removed an ignored build artifact")

        dotfile = protected / ".gitignore"
        dotfile.write_text("before\n", encoding="utf-8")
        saved = snapshot([protected])
        dotfile.write_text("after\n", encoding="utf-8")
        if restore_changed(saved) != [str(protected)] or dotfile.read_text(encoding="utf-8") != "before\n":
            raise RuntimeError("project dotfiles were incorrectly blanket-ignored")


def loop_detection_contract_preflight() -> None:
    """Lock Qwen loop classification plus the shared Stage retry/session contract."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from runner.agent import BaseBackend, should_reset_session
    from runner.config.defaults import DEFAULT_PER_SESSION_ATTEMPTS
    from runner.config.runtime import RuntimeConfig

    message = (
        "Loop detection halted the run "
        "(consecutive_identical_tool_calls: repeated call)."
    )
    diagnostics = BaseBackend.extract_diagnostics([], message)
    if diagnostics.get("loop_type") != "consecutive_identical_tool_calls":
        raise RuntimeError("Qwen loop diagnostic classification contract changed")
    if not should_reset_session(message):
        raise RuntimeError("Qwen loop signal no longer requests a Fresh Session")
    if DEFAULT_PER_SESSION_ATTEMPTS != 2:
        raise RuntimeError(
            "shared per-session retry budget changed; update the reliability contract"
        )
    config = RuntimeConfig()
    if config.stage_retries != -1:
        raise RuntimeError("unattended Stage retry default is no longer unlimited")
    if config.retry_delay < 0 or config.retry_max_delay < config.retry_delay:
        raise RuntimeError("shared retry delay contract is invalid")


RESUME_PROBE_PAUSE = '''from __future__ import annotations
import time
time.sleep(3)
'''

RESUME_TASK_PRODUCER = '''from __future__ import annotations
import json

print(json.dumps({
    "tasks": [
        {
            "id": "resume",
            "title": "Resume probe task",
            "description": "Exercise durable dynamic child Workflow resume.",
            "deliverable": "health.txt with expected content.",
            "acceptance_criteria": ["The resumed child Workflow completes."]
        }
    ],
    "stages": [
        {
            "name": "execute_first",
            "type": "base",
            "profile": "execute",
            "task_id": "resume",
            "status": "Execute before forced restart"
        },
        {
            "name": "pause",
            "type": "command",
            "task_id": "resume",
            "status": "Holding durable resume checkpoint",
            "command": "{python} resume_pause.py"
        },
        {
            "name": "execute_second",
            "type": "base",
            "profile": "execute",
            "task_id": "resume",
            "task_complete": True,
            "status": "Continue same session after restart"
        }
    ]
}, ensure_ascii=False))
'''

RESUME_PROBE_WORKFLOW = '''stages:
  discover:
    type: command
    status: Creating deterministic resume TODO
    command: "{python} task_producer.py"
    produces: tasks

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"

flow:
  - discover
  - validate_file
'''


def resume_probe(settings: Settings, root: Path) -> None:
    project = create_project(root, "resume-probe")
    (project / "task_producer.py").write_text(RESUME_TASK_PRODUCER, encoding="utf-8")
    (project / "resume_pause.py").write_text(RESUME_PROBE_PAUSE, encoding="utf-8")
    workflow = project / "resume-workflow.yaml"
    workflow.write_text(RESUME_PROBE_WORKFLOW, encoding="utf-8")
    first_log = console_log(project, "first-console.jsonl")
    first_log.parent.mkdir(parents=True, exist_ok=True)
    command = runner_command(settings, project, workflow=workflow)
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
    process = subprocess.Popen(command, **options)
    deadline = time.monotonic() + settings.run_timeout
    interrupted_session = ""
    try:
        while process.poll() is None and time.monotonic() < deadline:
            state = read_state(project)
            session = state.get("ai_session_id")
            expanded = state.get("expanded_workflow")
            position = state.get("workflow_position")
            current_name = ""
            if (
                isinstance(expanded, list)
                and isinstance(position, int)
                and 0 <= position < len(expanded)
                and isinstance(expanded[position], dict)
            ):
                current_name = str(expanded[position].get("name", ""))
            if (
                isinstance(session, str)
                and session
                and state.get("completed") is not True
                and current_name.endswith("__pause")
            ):
                interrupted_session = session
                terminate(process)
                break
            time.sleep(0.05)
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()
    if not interrupted_session:
        state = read_state(project)
        raise RuntimeError(
            "could not capture the deterministic durable resume checkpoint "
            f"(stage={state.get('stage')}, workflow_position={state.get('workflow_position')}, "
            f"completed={state.get('completed')}, expanded={bool(state.get('expanded_workflow'))})"
        )

    saw_resume = False

    def observe_resume() -> None:
        nonlocal saw_resume
        saw_resume = saw_resume or observed_session(
            project, interrupted_session, "resume"
        )

    code = run_command(
        runner_command(settings, project, resume=True, workflow=workflow),
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


def stop_request_resume_probe(settings: Settings, root: Path) -> None:
    """Exercise the detached-UI stop.request contract and durable resume."""
    project = create_project(root, "stop-request-resume-probe")
    first_log = console_log(project, "first-console.jsonl")
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
    process = subprocess.Popen(runner_command(settings, project), **options)
    work = project / ".ai-task-runner"
    stop_request = work / "stop.request"
    marker = work / "runner-process.json"
    checkpoint: dict[str, object] = {}
    deadline = time.monotonic() + settings.run_timeout
    try:
        while process.poll() is None and time.monotonic() < deadline:
            state = read_state(project)
            current = state.get("ai_session_id")
            if marker.is_file() and isinstance(current, str) and current:
                checkpoint = dict(state)
                stop_request.write_text("stop\n", encoding="utf-8")
                break
            time.sleep(0.1)
        if not checkpoint:
            raise RuntimeError("stop.request probe could not capture a durable resumable checkpoint")
        code = process.wait(timeout=min(settings.run_timeout, 30))
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()
    if code != 130:
        raise RuntimeError(f"stop.request did not stop Supervisor cleanly: exit={code}")
    if marker.exists() or stop_request.exists():
        raise RuntimeError("stop.request cleanup left stale runtime control files")

    stopped = read_state(project)
    if stopped.get("completed") is True:
        raise RuntimeError("stop.request incorrectly marked the run completed")
    if checkpoint.get("run_id") and stopped.get("run_id") != checkpoint.get("run_id"):
        raise RuntimeError(
            "stop.request replaced durable run state: "
            f"before={checkpoint.get('run_id')!r}, after={stopped.get('run_id')!r}"
        )
    for field in ("current", "cycle", "workflow_position"):
        before = checkpoint.get(field)
        after = stopped.get(field)
        if isinstance(before, int) and isinstance(after, int) and after < before:
            raise RuntimeError(
                f"stop.request regressed durable {field}: before={before}, after={after}"
            )
    if checkpoint.get("ai_session_id") and not stopped.get("ai_session_id"):
        raise RuntimeError("stop.request lost the durable AI session checkpoint")

    resumed = run_command(
        runner_command(settings, project, resume=True),
        console_log(project, "resume-console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, resumed)

    # Same-session model transport is intentionally validated by resume_probe(),
    # which stops at a deterministic checkpoint that is guaranteed to require
    # another AI call. This detached stop probe may stop after the current AI
    # Stage has already checkpointed and while a command/validator is active;
    # requiring a new model.prompt(session_mode=resume) here is a race-prone
    # false failure even when durable stop/resume is correct.


def custom_dynamic_producer_probe(settings: Settings, root: Path) -> None:
    """Prove a non-Plan Python Stage can produce a durable dynamic child Workflow."""
    project = create_project(root, "custom-task-producer-probe")
    (project / "task_producer.py").write_text(CUSTOM_DYNAMIC_PRODUCER, encoding="utf-8")
    workflow = project / "workflow.yaml"
    workflow.write_text(CUSTOM_DYNAMIC_WORKFLOW, encoding="utf-8")
    code = run_command(
        runner_command(settings, project, workflow=workflow),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code)
    state = read_state(project)
    tasks = state.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != 1:
        raise RuntimeError("custom Dynamic Producer did not install exactly one durable Task")
    if tasks[0].get("status") != "completed":
        raise RuntimeError("custom Dynamic Producer task did not complete")


def builtin_workflow_probe(settings: Settings, root: Path, workflow: str) -> None:
    project = create_project(root, f"system-{workflow}-probe")
    ai_validation = workflow in {"ai", "mixed"}
    expected_ai_sessions = (
        builtin_final_ai_contract(workflow)[0] if ai_validation else 0
    )
    code = run_command(
        runner_command(
            settings,
            project,
            final_ai=ai_validation,
            ai_only=workflow == "ai",
            workflow=WORKFLOWS[workflow],
        ),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code)
    assert_builtin_topology(project, workflow)
    assert_prompt_transport_contract(project)
    if ai_validation:
        sessions = final_validation_sessions(project)
        if len(sessions) < expected_ai_sessions:
            raise RuntimeError(
                f"workflow/{workflow} reused Final AI validation sessions: "
                f"expected {expected_ai_sessions}, got {len(sessions)}"
            )


DYNAMIC_SESSION_ROUTER_PROMPT = """You are a deterministic Dynamic Handoff coordinator.

Goal:
{{ goal }}

Previous Stage result:
{{ previous }}

Choose exactly one next Stage: main_role.
Do not perform the selected Stage's work yourself.
"""

DYNAMIC_SESSION_ROLE_PROMPT = """You are the selected Dynamic Handoff role.

Goal:
{{ goal }}

Assigned responsibility:
{{ instructions }}

Handoff context:
{{ previous }}

Follow the assigned responsibility exactly. Do not use tools or modify files.
"""

DYNAMIC_SESSION_WORKFLOW = """stages:
  coordinator:
    type: handoff
    prompt: dynamic_router.md
    targets: [main_role]
    session_policy: role
    error_policy:
      retries: 2

  main_role:
    type: base
    prompt: dynamic_role.md
    instructions: Always return exactly MAIN_DONE.
    session_policy: main
    routes:
      pass: main_gate

  main_gate:
    type: command
    command: "{python} main_gate.py"
    routes:
      fail: main_role
      pass: stable_role

  stable_role:
    type: base
    prompt: dynamic_role.md
    instructions: Always return exactly STABLE_DONE.
    session_policy: role
    routes:
      pass: stable_gate

  stable_gate:
    type: command
    command: "{python} stable_gate.py"
    routes:
      fail: stable_role
      pass: fresh_role

  fresh_role:
    type: base
    prompt: dynamic_role.md
    instructions: Always return exactly FRESH_DONE.
    session_policy: fresh
    routes:
      pass: final_gate

  final_gate:
    type: command
    command: "{python} final_gate.py"
    routes:
      pass: done

flow:
  - coordinator
  - main_role
  - main_gate
  - stable_role
  - stable_gate
  - fresh_role
  - final_gate
"""


def dynamic_handoff_session_policy_probe(settings: Settings, root: Path) -> None:
    """Exercise Dynamic Handoff plus main/role/fresh session transport with real Qwen."""
    project = create_project(
        root,
        "dynamic-handoff-session-policy-probe",
        prompt="Exercise Dynamic Handoff session policies and finish the deterministic route.",
    )
    (project / "dynamic_router.md").write_text(
        DYNAMIC_SESSION_ROUTER_PROMPT, encoding="utf-8"
    )
    (project / "dynamic_role.md").write_text(
        DYNAMIC_SESSION_ROLE_PROMPT, encoding="utf-8"
    )
    (project / "main_gate.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "counter = Path('main-gate.count')\n"
        "value = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0\n"
        "value += 1\n"
        "counter.write_text(str(value), encoding='utf-8')\n"
        "print(f'MAIN_GATE_{value}')\n"
        "raise SystemExit(1 if value == 1 else 0)\n",
        encoding="utf-8",
    )
    (project / "stable_gate.py").write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "counter = Path('stable-gate.count')\n"
        "value = int(counter.read_text(encoding='utf-8')) if counter.exists() else 0\n"
        "value += 1\n"
        "counter.write_text(str(value), encoding='utf-8')\n"
        "print(f'STABLE_GATE_{value}')\n"
        "raise SystemExit(1 if value == 1 else 0)\n",
        encoding="utf-8",
    )
    (project / "final_gate.py").write_text(
        "print('DYNAMIC_FINAL_GATE_PASS')\n", encoding="utf-8"
    )
    workflow = project / "workflow.yaml"
    workflow.write_text(DYNAMIC_SESSION_WORKFLOW, encoding="utf-8")

    # Fail before a real backend call if the live fixture drifts from the current
    # production Workflow/Prompt contract.
    from runner.workflow.loader import load_workflow
    loaded = load_workflow(workflow)
    by_name = {str(item.get("name", "")): item for item in loaded}
    for name in ("coordinator", "main_role", "stable_role", "fresh_role"):
        prompt = Path(str(by_name.get(name, {}).get("prompt") or ""))
        if not prompt.is_absolute() or not prompt.is_file():
            raise RuntimeError(
                f"Dynamic Handoff live fixture prompt did not resolve: {name} -> {prompt}"
            )

    code = run_command(
        runner_command(settings, project, workflow=workflow),
        console_log(project, "console.jsonl"),
        semantic_probe_timeout(settings),
    )
    assert_state_completed(project, code)

    starts = [
        str(event.get("stage", ""))
        for event in runner_events(project)
        if event.get("type") == "runner.stage" and event.get("action") == "start"
    ]
    expected = [
        "coordinator",
        "main_role",
        "main_gate",
        "main_role",
        "main_gate",
        "stable_role",
        "stable_gate",
        "stable_role",
        "stable_gate",
        "fresh_role",
        "final_gate",
    ]
    if starts != expected:
        raise RuntimeError(
            "Dynamic Handoff live routing mismatch: "
            f"expected={expected}, observed={starts}"
        )

    state = read_state(project)
    stage_sessions = state.get("stage_sessions")
    if not isinstance(stage_sessions, dict):
        raise RuntimeError("Dynamic Handoff live state missing stage_sessions")

    main_results = stage_result_sessions(project, "main_role")
    stable_results = stage_result_sessions(project, "stable_role")
    fresh_results = stage_result_sessions(project, "fresh_role")
    if len(main_results) < 2 or len(set(main_results[-2:])) != 1:
        raise RuntimeError(
            "session_policy=main did not reuse the primary Runner session"
        )
    durable_main = str(state.get("ai_session_id") or "")
    if durable_main:
        raise RuntimeError(
            "completed Dynamic Handoff run unexpectedly retained the primary Runner session"
        )
    stable_session = str(stage_sessions.get("stable_role") or "")
    if len(stable_results) < 2 or not stable_session:
        raise RuntimeError(
            "session_policy=role did not run the reusable role more than once"
        )
    if any(session != stable_session for session in stable_results[-2:]):
        raise RuntimeError(
            "session_policy=role did not reuse the same durable role-specific session"
        )
    if "fresh_role" in stage_sessions:
        raise RuntimeError(
            "session_policy=fresh unexpectedly persisted a durable role session"
        )
    if not fresh_results:
        raise RuntimeError("session_policy=fresh produced no real model session evidence")
    if len({main_results[-1], stable_results[-1], fresh_results[-1]}) != 3:
        raise RuntimeError(
            "Dynamic Handoff session policies did not produce isolated session identities"
        )



REVIEW_ROUTING_PROMPT = """Make review.txt contain exactly these two logical lines:
READY
REVIEW_REQUIRED

A standard final newline is allowed.
The one-shot command Stage deterministically seeds review.txt with only READY before
the first Review, regardless of what the first Execute attempted.
After Review FAIL routes back to Execute, preserve READY, add REVIEW_REQUIRED.
Modify review.txt only.
"""

REVIEW_ROUTING_EXECUTION_PROMPT = """This Stage exercises failure routing.
If Runner shared control does not contain Review feedback, do not inspect files, do not use
tools, do not modify anything, and return immediately. A later one-shot seed Stage will
deterministically force the first Review to see the incomplete state.
When Runner shared control feedback from stage review says REVIEW_REQUIRED is missing,
modify only review.txt so it contains READY and REVIEW_REQUIRED as two logical lines,
then return immediately.
Do not inspect unrelated files and do not touch protected files.
"""

REVIEW_ROUTING_REVIEW_PROMPT = """Inspect review.txt only, at most once.
PASS only when its logical lines are exactly READY and REVIEW_REQUIRED, in that order.
Otherwise FAIL and identify REVIEW_REQUIRED as missing when it is absent.
Do not inspect any other file, do not modify anything, and return the Review verdict immediately.
"""

REVIEW_ROUTING_POLICY = """protected_paths:
  - prompt.md
  - validation.py
  - seed_review.py
  - review_gate.py
  - review_execute.md
  - workflow.yaml
instructions:
  always: Work only inside this project root. Modify review.txt only for this probe.
"""

REVIEW_ROUTING_SEED = '''from pathlib import Path
marker = Path(".ai-task-runner") / "review-seeded-once"
if not marker.exists():
    Path("review.txt").write_text("READY\\n", encoding="utf-8")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("seeded\\n", encoding="utf-8")
'''

REVIEW_ROUTING_GATE = '''from pathlib import Path
marker = Path(".ai-task-runner") / "review-gate-failed-once"
if not marker.exists():
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("failed\\n", encoding="utf-8")
    print("REVIEW_REQUIRED is intentionally missing; add REVIEW_REQUIRED to review.txt")
    raise SystemExit(1)
print("REVIEW_GATE_PASSED")
'''


REVIEW_ROUTING_WORKFLOW = '''stages:
  seed:
    type: command
    status: Seeding incomplete Review state
    run_state: executing
    command: "{python} seed_review.py"

  execute:
    type: base
    profile: execute
    status: Executing Review feedback
    prompt: review_execute.md

  review:
    type: command
    status: Forcing deterministic first Review routing failure
    run_state: reviewing
    command: "{python} review_gate.py"
    routes:
      fail: execute

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"
    status: Validating deterministic Review routing probe
    routes:
      fail: execute

flow:
  - execute
  - seed
  - review
  - validate_file
'''


REVIEW_ROUTING_VALIDATOR = '''from __future__ import annotations
import argparse
from pathlib import Path
p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
target = Path(a.project_root).resolve() / "review.txt"
lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
if lines != ["READY", "REVIEW_REQUIRED"]:
    print("VALIDATION_FAILED: review.txt must contain exactly two logical lines: READY and REVIEW_REQUIRED; modify review.txt only")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''


def review_failure_routing_probe(settings: Settings, root: Path) -> None:
    project = create_project(
        root,
        "review-failure-routing-probe",
        REVIEW_ROUTING_PROMPT,
        REVIEW_ROUTING_VALIDATOR,
        policy=REVIEW_ROUTING_POLICY,
    )
    (project / "seed_review.py").write_text(REVIEW_ROUTING_SEED, encoding="utf-8")
    (project / "review_gate.py").write_text(REVIEW_ROUTING_GATE, encoding="utf-8")
    (project / "review_execute.md").write_text(
        REVIEW_ROUTING_EXECUTION_PROMPT, encoding="utf-8"
    )
    workflow = project / "workflow.yaml"
    workflow.write_text(REVIEW_ROUTING_WORKFLOW, encoding="utf-8")

    from runner.workflow.loader import load_workflow
    loaded = load_workflow(workflow)
    loaded_by_name = {str(item.get("name", "")): item for item in loaded}
    if loaded_by_name.get("validate_file", {}).get("routes") != {"fail": "execute"}:
        raise RuntimeError(
            "review failure-routing live fixture lost validate_file.fail -> execute before launch: "
            f"{loaded_by_name.get('validate_file')!r}"
        )

    log = console_log(project, "console.jsonl")
    try:
        code = run_command(
            runner_command(settings, project, workflow=workflow),
            log,
            semantic_probe_timeout(settings),
        )
    except RuntimeError as exc:
        if "runner exceeded harness timeout" not in str(exc):
            raise
        raise RuntimeError(
            "review failure-routing probe exceeded bounded semantic timeout; "
            + probe_timeout_diagnostic(project, log)
        ) from exc
    if code != 0:
        snapshot = project / ".ai-task-runner" / "workflow.snapshot.json"
        frozen_route = None
        try:
            frozen = json.loads(snapshot.read_text(encoding="utf-8"))
            frozen_by_name = {
                str(item.get("name", "")): item
                for item in frozen
                if isinstance(item, dict)
            }
            frozen_route = frozen_by_name.get("validate_file", {}).get("routes")
        except Exception as error:
            frozen_route = f"<snapshot unavailable: {error}>"
        raise RuntimeError(
            "review failure-routing run exited before completion; "
            f"frozen validate_file.routes={frozen_route!r}; "
            + probe_timeout_diagnostic(project, log)
        )
    assert_state_completed(project, code)
    if (project / "review.txt").read_text(encoding="utf-8").splitlines() != ["READY", "REVIEW_REQUIRED"]:
        raise RuntimeError("review failure-routing probe produced unexpected logical lines")
    if not observed_stage_result(project, "review", "fail"):
        raise RuntimeError("review routing probe did not exercise deterministic Review gate FAIL")
    if not observed_stage_result(project, "review", "pass"):
        raise RuntimeError("deterministic Review gate did not PASS after Execute repaired state")
    if not observed_stage_result(project, "validate_file", "pass"):
        raise RuntimeError("review routing probe validator did not PASS repaired state")
    executes = stage_prompt_records(project, "execute")
    if not any(
        "RUNNER_SHARED_STAGE_CONTROL" in record.text
        and "mode: continue" in record.text
        and "REVIEW_REQUIRED" in record.text
        for record in executes
    ):
        raise RuntimeError("deterministic Review gate FAIL did not route feedback back to Execute shared control")
    assert_prompt_transport_contract(project)


FULL_LOOP_EXECUTOR = '''from __future__ import annotations
import argparse
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--state-file", required=True)
a = p.parse_args()

state_path = Path(a.state_file)
state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
target = Path("loop.txt")
lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []

transition = state.get("transition_previous")
transition_text = json.dumps(transition, ensure_ascii=False) if isinstance(transition, dict) else ""
validator_text = str(state.get("validator_output") or "")

changed = False
if "REVIEW_OK" in transition_text and "REVIEW_OK" not in lines:
    if "READY" not in lines:
        lines.append("READY")
    lines.append("REVIEW_OK")
    changed = True

if "VALIDATOR_OK" in validator_text and "VALIDATOR_OK" not in lines:
    if "READY" not in lines:
        lines.append("READY")
    if "REVIEW_OK" not in lines:
        lines.append("REVIEW_OK")
    lines.append("VALIDATOR_OK")
    changed = True

if changed:
    target.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("FULL_LOOP_EXECUTOR_OK")
'''

FULL_LOOP_REVIEW_PROMPT = """Inspect loop.txt only.
PASS when logical lines READY and REVIEW_OK are both present.
VALIDATOR_OK may be present and must not cause failure.
FAIL only when READY or REVIEW_OK is missing, and name the missing logical line.
"""

FULL_LOOP_SEED = '''from pathlib import Path
marker = Path(".ai-task-runner") / "full-loop-seeded-once"
if not marker.exists():
    Path("loop.txt").write_text("READY\\n", encoding="utf-8")
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("seeded\\n", encoding="utf-8")
'''

FULL_LOOP_REVIEW_GATE = '''from pathlib import Path
marker = Path(".ai-task-runner") / "full-loop-review-failed-once"
if not marker.exists():
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("failed\\n", encoding="utf-8")
    print("REVIEW_OK is intentionally missing; add REVIEW_OK to loop.txt")
    raise SystemExit(1)
print("FULL_LOOP_REVIEW_GATE_PASSED")
'''

FULL_LOOP_WORKFLOW = '''stages:
  seed:
    type: command
    command: "{python} seed_loop.py"

  execute:
    type: command
    command: "{python} full_loop_execute.py --state-file {state_file}"

  review:
    type: command
    run_state: reviewing
    command: "{python} full_loop_review_gate.py"
    routes:
      fail: execute

  review_verify:
    type: base
    profile: review
    prompt: full_loop_review.md
    routes:
      fail: execute

  validate_file:
    type: command
    result_kind: validation
    command: "{python} full_loop_validator.py"
    routes:
      fail: execute

flow:
  - execute
  - seed
  - review
  - review_verify
  - validate_file
'''


FULL_LOOP_POLICY = """protected_paths:
  - prompt.md
  - validation.py
  - seed_loop.py
  - full_loop_execute.py
  - full_loop_review_gate.py
  - full_loop_review.md
  - full_loop_validator.py
instructions:
  always: Work only inside this project root. Modify loop.txt only for this probe.
"""

FULL_LOOP_VALIDATOR = '''from pathlib import Path
root = Path(".").resolve()
target = root / "loop.txt"
marker = root / ".ai-task-runner" / "full-loop-validator-failed-once"
lines = target.read_text(encoding="utf-8").splitlines() if target.is_file() else []
if "READY" not in lines or "REVIEW_OK" not in lines:
    print("VALIDATION_FAILED: READY and REVIEW_OK must already be present")
    raise SystemExit(1)
if not marker.exists():
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1", encoding="utf-8")
    print("VALIDATION_FAILED: add VALIDATOR_OK as its own logical line; preserve READY and REVIEW_OK")
    raise SystemExit(1)
if "VALIDATOR_OK" not in lines:
    print("VALIDATION_FAILED: VALIDATOR_OK is missing; add it and preserve existing lines")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''


def complete_closed_loop_probe(settings: Settings, root: Path) -> None:
    """Exercise Review FAIL and Validator FAIL in one real-Qwen linear run."""
    project = create_project(
        root,
        "complete-closed-loop-probe",
        policy=FULL_LOOP_POLICY,
    )
    (project / "seed_loop.py").write_text(FULL_LOOP_SEED, encoding="utf-8")
    (project / "full_loop_execute.py").write_text(
        FULL_LOOP_EXECUTOR, encoding="utf-8"
    )
    (project / "full_loop_review_gate.py").write_text(
        FULL_LOOP_REVIEW_GATE, encoding="utf-8"
    )
    (project / "full_loop_review.md").write_text(
        FULL_LOOP_REVIEW_PROMPT, encoding="utf-8"
    )
    (project / "full_loop_validator.py").write_text(
        FULL_LOOP_VALIDATOR, encoding="utf-8"
    )
    workflow = project / "workflow.yaml"
    workflow.write_text(FULL_LOOP_WORKFLOW, encoding="utf-8")
    log = console_log(project, "console.jsonl")
    try:
        code = run_command(
            runner_command(settings, project, workflow=workflow),
            log,
            semantic_probe_timeout(settings),
        )
    except RuntimeError as exc:
        if "runner exceeded harness timeout" not in str(exc):
            raise
        raise RuntimeError(
            "complete closed-loop probe exceeded bounded semantic timeout; "
            + probe_timeout_diagnostic(project, log)
        ) from exc
    assert_state_completed(project, code)
    lines = (project / "loop.txt").read_text(encoding="utf-8").splitlines()
    if lines != ["READY", "REVIEW_OK", "VALIDATOR_OK"]:
        raise RuntimeError(f"complete closed-loop probe produced unexpected lines: {lines}")
    if not observed_stage_result(project, "review", "fail"):
        raise RuntimeError("complete closed-loop probe did not exercise deterministic Review gate FAIL")
    if not observed_stage_result(project, "review_verify", "pass"):
        raise RuntimeError("complete closed-loop probe Qwen Review did not PASS repaired state")
    if not observed_stage_result(project, "validate_file", "fail"):
        raise RuntimeError("complete closed-loop probe did not exercise Validator FAIL")
    starts = [
        event.get("stage")
        for event in runner_events(project)
        if event.get("type") == "runner.stage" and event.get("action") == "start"
    ]
    if (
        starts.count("execute") < 3
        or starts.count("review") < 2
        or starts.count("review_verify") < 2
        or starts.count("validate_file") < 2
    ):
        raise RuntimeError(
            "complete closed-loop probe did not traverse the expected repeated stages: "
            f"execute={starts.count('execute')}, review={starts.count('review')}, "
            f"review_verify={starts.count('review_verify')}, "
            f"validate_file={starts.count('validate_file')}"
        )
    assert_prompt_transport_contract(project)


def validator_failure_routing_probe(settings: Settings, root: Path) -> None:
    marker = root / "_harness-control" / "validator-first-value.txt"
    validator = f'''from __future__ import annotations
import argparse
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--project-root", required=True)
p.add_argument("--state-file", required=True)
a = p.parse_args()
target = Path(a.project_root).resolve() / "route.txt"
marker = Path({str(marker)!r})
if not marker.exists():
    if not target.is_file() or target.read_text(encoding="utf-8") != {ROUTING_INITIAL!r}:
        print("VALIDATION_FAILED: route.txt must contain exactly {ROUTING_INITIAL} with no trailing whitespace")
        raise SystemExit(1)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(target.read_text(encoding="utf-8"), encoding="utf-8")
    print("VALIDATION_FAILED: replace route.txt content with exactly {ROUTING_FINAL}")
    raise SystemExit(1)
if not target.is_file() or target.read_text(encoding="utf-8") != {ROUTING_FINAL!r}:
    print("VALIDATION_FAILED: route.txt must contain exactly {ROUTING_FINAL} with no trailing whitespace")
    raise SystemExit(1)
print("VALIDATION_PASSED")
'''
    routing_prompt = f"""Create route.txt with exactly `{ROUTING_INITIAL}` and no trailing newline or whitespace.
If the Python Validator later requests replacement content, apply that feedback to
the same file exactly, again with no trailing newline or whitespace, and continue until validation passes.
"""
    project = create_project(
        root, "validator-failure-routing-probe", routing_prompt, validator
    )
    code = run_command(
        runner_command(settings, project),
        console_log(project, "console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code, "route.txt", ROUTING_FINAL)
    state = read_state(project)
    if marker.read_text(encoding="utf-8") != ROUTING_INITIAL or state.get("cycle", 1) < 2:
        raise RuntimeError("validator failure did not route back through another planning cycle")
    planning_prompts = stage_prompt_records(project, "planning")
    if len(planning_prompts) < 2 or not any(
        "RUNNER_SHARED_STAGE_CONTROL" in record.text
        and "mode: continue" in record.text
        and "Validator:" in record.text
        and "VALIDATION_FAILED" in record.text
        for record in planning_prompts[1:]
    ):
        raise RuntimeError("validator failure did not reach Planning through shared feedback control")
    assert_prompt_transport_contract(project)


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
    checkpoint_seen = False
    try:
        while process.poll() is None and time.monotonic() < deadline:
            state = read_state(project)
            tasks = state.get("tasks", [])
            if (
                isinstance(tasks, list) and len(tasks) >= 3
                and state.get("current", 0) >= 1
                and state.get("completed") is not True
            ):
                checkpoint_seen = True
                # Stop first, then establish the baseline from durable state.
                # Reading attempts/mtime before termination races with the live
                # process and can falsely blame resume for work done between
                # observation and taskkill.
                terminate(process)
                break
            time.sleep(0.1)
    finally:
        if process.poll() is None:
            terminate(process)
        stream.close()
    if not checkpoint_seen:
        raise RuntimeError("could not interrupt after the first TODO checkpoint")

    checkpoint = read_state(project)
    checkpoint_tasks = checkpoint.get("tasks", [])
    checkpoint_current = checkpoint.get("current", 0)
    if (
        not isinstance(checkpoint_tasks, list)
        or len(checkpoint_tasks) < 3
        or not isinstance(checkpoint_current, int)
        or checkpoint_current < 1
        or checkpoint_current >= len(checkpoint_tasks)
        or checkpoint.get("completed") is True
    ):
        raise RuntimeError(
            "process did not stop at a resumable multi-TODO checkpoint: "
            f"current={checkpoint_current!r}, completed={checkpoint.get('completed')!r}"
        )

    completed_baseline: list[tuple[int, object, int]] = []
    output_names = ("one.txt", "two.txt", "three.txt")
    for index in range(checkpoint_current):
        task = checkpoint_tasks[index]
        if not isinstance(task, dict) or task.get("status") != "completed":
            raise RuntimeError(
                f"checkpoint TODO {index + 1} is not durably completed before resume"
            )
        output = project / output_names[index]
        if not output.is_file():
            raise RuntimeError(
                f"checkpoint TODO {index + 1} output is missing before resume: {output.name}"
            )
        completed_baseline.append(
            (index, task.get("attempts"), output.stat().st_mtime_ns)
        )

    code = run_command(
        runner_command(settings, project, resume=True),
        console_log(project, "resume-console.jsonl"),
        settings.run_timeout,
    )
    assert_completed(project, code, "three.txt", "THREE")
    state = read_state(project)
    tasks = state.get("tasks", [])
    if len(tasks) < 3:
        raise RuntimeError(f"resume lost TODOs: expected>=3 actual={len(tasks)}")
    incomplete = [
        index + 1 for index, task in enumerate(tasks)
        if task.get("status") != "completed"
    ]
    if incomplete:
        raise RuntimeError(f"resume skipped TODO completion(s): {incomplete}")
    for index, attempts, mtime in completed_baseline:
        if tasks[index].get("attempts") != attempts:
            raise RuntimeError(
                f"resume re-executed checkpointed TODO {index + 1}: "
                f"attempts {attempts!r} -> {tasks[index].get('attempts')!r}"
            )
        current_mtime = (project / output_names[index]).stat().st_mtime_ns
        if current_mtime != mtime:
            raise RuntimeError(
                f"resume modified checkpointed TODO {index + 1} output: "
                f"{output_names[index]} mtime {mtime} -> {current_mtime}"
            )
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
    (projects[0] / "validation.py").write_text(YAML_ARG_VALIDATOR, encoding="utf-8")
    script = batch / "tasks.yaml"
    script.write_text(json.dumps([
        {
            "prompt": case_prompt(PROMPT, f"{name}-item-1"),
            "project_root": projects[0].name,
            "validator": str(projects[0] / "validation.py"),
            "validator_args": ["--case-token", "ITEM-1"],
            "stage_retries": 1,
            "retry_delay": 0,
        },
        {
            "prompt": case_prompt(PROMPT, f"{name}-item-2"),
            "project_root": projects[1].name,
            "validator": str(projects[1] / "validation.py"),
            "ai_validator_prompt": case_prompt(FINAL_AI_PROMPT, f"{name}-item-2-final-ai"),
            "ai_validator_count": 3,
            "ai_validator_required_passes": 2,
        },
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

    def first_item_mtime() -> int | None:
        state_done = read_json(first_state).get("completed") is True
        event_done = any(
            event.get("type") == "script.item_completed"
            and event.get("script_index") == 1
            for event in jsonl_events(first_log)
        )
        health = projects[0] / "health.txt"
        if (state_done or event_done) and health.is_file():
            return health.stat().st_mtime_ns
        return None

    try:
        while process.poll() is None and time.monotonic() < deadline:
            first_mtime = first_item_mtime()
            if first_mtime is not None:
                terminate(process)
                break
            time.sleep(0.1)
    finally:
        if first_mtime is None:
            first_mtime = first_item_mtime()
        if process.poll() is None:
            terminate(process)
        stream.close()
    if first_mtime is None:
        exit_code = process.poll()
        diagnostic = qwen_sandbox_log_diagnostic(first_log)
        if diagnostic:
            raise RuntimeError(
                "YAML List first item did not complete because "
                f"{diagnostic}: exit={exit_code}, state={read_json(first_state)}"
            )
        raise RuntimeError(
            "could not interrupt YAML List after its first completed item: "
            f"exit={exit_code}, state={read_json(first_state)}"
        )

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

    second_work = ".ai-task-runner/script/002"
    second_state = read_json(projects[1] / second_work / "state.json")
    try:
        quorum = json.loads(str(second_state.get("validator_output", "")))
    except json.JSONDecodeError as error:
        raise RuntimeError("YAML List Final AI quorum evidence is not JSON") from error
    if not (
        quorum.get("passed") is True
        and quorum.get("required_passes") == 2
        and quorum.get("passes", 0) >= 2
        and len(quorum.get("runs", [])) == 3
        and len(final_validation_sessions(projects[1], second_work)) >= 3
    ):
        raise RuntimeError("YAML List per-item Final AI 3/2 quorum was not honored")

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


def yaml_list_endurance_probe(
    settings: Settings,
    root: Path,
    items: int,
) -> None:
    """Run several real-Qwen YAML items in one CLI process to catch accumulated state leaks."""
    if items <= 0:
        return
    batch = root / "yaml-list-endurance-probe"
    batch.mkdir()
    projects: list[Path] = []
    payload: list[dict[str, object]] = []
    for index in range(1, items + 1):
        project = create_project(batch, f"item-{index:03d}")
        projects.append(project)
        payload.append({
            "prompt": case_prompt(PROMPT, f"yaml-endurance-{index:03d}"),
            "project_root": project.name,
            "validator": str(project / "validation.py"),
            "stage_retries": 1,
            "retry_delay": 0,
        })
    script = batch / "tasks.yaml"
    script.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log = console_log(batch, "console.jsonl")
    code = run_command(
        runner_command(settings, batch, script=script),
        log,
        settings.run_timeout * max(1, items),
    )
    if code != 0:
        raise RuntimeError(f"YAML endurance process failed: exit={code}")
    for index, project in enumerate(projects, 1):
        assert_completed(
            project,
            code,
            work_dir=f".ai-task-runner/script/{index:03d}",
        )
    events = jsonl_events(log)
    completed = {
        int(event.get("script_index"))
        for event in events
        if event.get("type") == "script.item_completed"
        and isinstance(event.get("script_index"), int)
    }
    expected = set(range(1, items + 1))
    if completed != expected or any(
        event.get("type") == "script.item_failed" for event in events
    ):
        raise RuntimeError(
            f"YAML endurance item evidence mismatch: expected={sorted(expected)} "
            f"completed={sorted(completed)}"
        )


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



API_RECOVERY_SHORT_OUTAGE_SECONDS = 5.0
API_RECOVERY_LONG_HTTP_OUTAGE_SECONDS = 45.0
API_RECOVERY_STATUS_CODES = (429, 502, 503)
API_RECOVERY_ARM_TIMEOUT_SECONDS = 30.0

API_RECOVERY_ARM_SCRIPT = f'''from pathlib import Path
import time

root = Path(".ai-task-runner")
marker = root / "api-outage-armed"
active = root / "api-outage-active"
root.mkdir(parents=True, exist_ok=True)
marker.write_text("armed\\n", encoding="utf-8")
deadline = time.monotonic() + {API_RECOVERY_ARM_TIMEOUT_SECONDS!r}
while not active.is_file():
    if time.monotonic() >= deadline:
        raise SystemExit("API outage harness did not acknowledge arm marker")
    time.sleep(0.05)
'''

API_RECOVERY_WARMUP_PROMPT = """Establish the Runner session for the API recovery probe.
Do not modify files. Return exactly WARMUP_READY.
"""

API_RECOVERY_EXECUTE_PROMPT = f"""The API outage gate has already been armed.
Create a UTF-8 file named health.txt containing exactly this text, with no trailing newline:
{EXPECTED}

Modify health.txt only and return immediately after the file is correct.
"""

API_RECOVERY_WORKFLOW = '''stages:
  warmup:
    type: base
    profile: generic
    prompt: api_warmup.md
    session_policy: main

  arm:
    type: command
    command: "{python} api_outage_arm.py"

  execute:
    type: base
    profile: execute
    prompt: api_execute.md
    session_policy: main

  validate_file:
    type: command
    result_kind: validation
    command: "{python} {validator} --project-root {project_root} --state-file {state_file} {validator_args}"

flow:
  - warmup
  - arm
  - execute
  - validate_file
'''


def _prepare_api_recovery_fixture(project: Path) -> tuple[Path, Path, Path]:
    """Create a deterministic boundary immediately before the AI call under outage."""
    (project / "api_warmup.md").write_text(API_RECOVERY_WARMUP_PROMPT, encoding="utf-8")
    (project / "api_execute.md").write_text(API_RECOVERY_EXECUTE_PROMPT, encoding="utf-8")
    (project / "api_outage_arm.py").write_text(API_RECOVERY_ARM_SCRIPT, encoding="utf-8")
    workflow = project / "api-recovery-workflow.yaml"
    workflow.write_text(API_RECOVERY_WORKFLOW, encoding="utf-8")

    from runner.workflow.loader import load_workflow

    loaded = load_workflow(workflow)
    names = [str(item.get("name") or "") for item in loaded]
    if names != ["warmup", "arm", "execute", "validate_file"]:
        raise RuntimeError(f"API disconnect fixture topology drifted: {names!r}")
    runtime = project / ".ai-task-runner"
    return workflow, runtime / "api-outage-armed", runtime / "api-outage-active"


def _structured_recovery_event(event: dict[str, object]) -> bool:
    kind = str(event.get("type") or "")
    action = str(event.get("action") or "")
    if kind == "runner.retry" and action == "retry":
        return True
    return (
        kind == "runner.recovery"
        and action == "retry"
        and int(event.get("retry") or 0) >= 1
        and str(event.get("retry_mode") or "") in {"retry", "recover"}
    )


def recovery_backoff_observation(root: Path) -> dict[str, object]:
    """Summarize durable StageExecutor retry waits without retaining retry history."""
    waits: list[float] = []
    for path in root.rglob("log.txt"):
        if path.parent.name != ".ai-task-runner":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(event, dict)
                or event.get("type") != "runner.recovery"
                or event.get("action") != "retry"
            ):
                continue
            value = event.get("wait_seconds")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                waits.append(float(value))
    return {
        "count": len(waits),
        "min_wait_seconds": min(waits) if waits else None,
        "max_wait_seconds": max(waits) if waits else None,
        "configured_max_seconds": LIVE_RETRY_MAX_DELAY_SECONDS,
        "cap_reached": bool(waits and max(waits) >= LIVE_RETRY_MAX_DELAY_SECONDS),
    }


def _assert_recovery_wait_bounds(events: list[dict[str, object]]) -> None:
    waits = [
        float(event["wait_seconds"])
        for event in events
        if (
            event.get("type") == "runner.recovery"
            and event.get("action") == "retry"
            and isinstance(event.get("wait_seconds"), (int, float))
            and not isinstance(event.get("wait_seconds"), bool)
        )
    ]
    invalid = [
        value
        for value in waits
        if value <= 0 or value > LIVE_RETRY_MAX_DELAY_SECONDS
    ]
    if invalid:
        raise RuntimeError(
            "Runner recovery wait escaped configured bounds: "
            f"waits={waits!r}, max={LIVE_RETRY_MAX_DELAY_SECONDS}"
        )


def _proxy_recovery_observed(
    session_id: str,
    proxy,
    successes_before_outage: int,
) -> bool:
    return bool(
        session_id
        and proxy.failures > 0
        and not proxy.fail
        and not proxy.disconnect
        and proxy.successes > successes_before_outage
    )


def _assert_controlled_api_session_rotation(
    session_id: str,
    session_rotated: bool,
    events: list[dict[str, object]],
) -> None:
    """Allow bounded Fresh Session rotation only when Runner evidence proves ownership."""
    fresh_events = [
        event for event in events
        if event.get("type") == "runner.session" and event.get("action") == "fresh"
    ]
    if not session_rotated and not fresh_events:
        return

    recovery_modes = [
        str(event.get("retry_mode") or "")
        for event in events
        if _structured_recovery_event(event)
    ]
    if not fresh_events:
        raise RuntimeError(
            "API outage replaced the session without controlled Runner fresh-session evidence"
        )
    if "recover" not in recovery_modes:
        raise RuntimeError(
            "API outage rotated Fresh Session without runner.recovery mode=recover evidence"
        )
    if not any(
        str(event.get("previous_session") or "") == session_id
        for event in fresh_events
    ):
        raise RuntimeError(
            "API outage Fresh Session evidence does not match the observed pre-outage session"
        )


def api_recovery_probe(
    settings: Settings,
    root: Path,
    name: str = "api-recovery-probe",
    *,
    outage_seconds: float = API_RECOVERY_SHORT_OUTAGE_SECONDS,
    disconnect: bool = False,
    status_code: int = 502,
) -> bool:
    with (
        transient_proxy(settings.api_port) as proxy,
        # Disable Qwen CLI's own HTTP retry here so the injected outage reaches
        # StageExecutor. This probe is specifically for Runner same-session
        # retry/backoff/recovery, not the backend client's internal retry loop.
        qwen_test_endpoint(settings.sandbox, proxy.port, max_retries=0),
    ):
        project = create_project(root, name)
        workflow, outage_marker, outage_active_marker = _prepare_api_recovery_fixture(project)
        log = console_log(project, "console.jsonl")
        log.parent.mkdir(parents=True, exist_ok=True)
        stream = log.open("w", encoding="utf-8")
        probe_env = os.environ.copy()
        # This probe owns the recovery boundary. Qwen Code can independently
        # enable persistent unattended retry; force it off here so injected
        # outages must escape to StageExecutor / runner.api.
        probe_env["QWEN_CODE_UNATTENDED_RETRY"] = "0"
        options: dict[str, object] = {
            "cwd": ROOT,
            "stdin": subprocess.DEVNULL,
            "stdout": stream,
            "stderr": subprocess.STDOUT,
            "text": True,
            "env": probe_env,
        }
        if os.name == "nt":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(
            runner_command(settings, project, workflow=workflow),
            **options,
        )
        deadline = time.monotonic() + settings.run_timeout
        session_id = ""
        outage_until = 0.0
        successes_before_outage = 0
        recovered = False
        session_rotated = False
        try:
            while process.poll() is None and time.monotonic() < deadline:
                state = read_state(project)
                current_session = state.get("ai_session_id")
                outage_armed = (
                    outage_marker is not None
                    and outage_marker.is_file()
                )
                if (
                    not session_id
                    and outage_armed
                    and isinstance(current_session, str)
                    and current_session
                ):
                    session_id = current_session
                    successes_before_outage = proxy.successes
                    proxy.disconnect = disconnect
                    proxy.status_code = status_code
                    proxy.fail = not disconnect
                    outage_until = time.monotonic() + outage_seconds
                    outage_active_marker.write_text("active\n", encoding="utf-8")
                if (
                    (proxy.fail or proxy.disconnect)
                    and proxy.failures > 0
                    and time.monotonic() >= outage_until
                ):
                    proxy.fail = False
                    proxy.disconnect = False
                recovered = recovered or _proxy_recovery_observed(
                    session_id,
                    proxy,
                    successes_before_outage,
                )
                if (
                    not recovered
                    and session_id
                    and isinstance(current_session, str)
                    and current_session
                    and current_session != session_id
                ):
                    # Do not decide here whether rotation was legal. Polling is
                    # intentionally racy with fast retry/recovery. Record the
                    # observation and validate it once against durable Runner
                    # session/recovery events after the child exits.
                    session_rotated = True
                time.sleep(0.1)
        finally:
            proxy.fail = False
            proxy.disconnect = False
            if process.poll() is None:
                terminate(process)
            stream.close()
        code = process.returncode or 0
        assert_completed(project, code)
        # The final successful upstream request can complete the run between two
        # 100ms polling iterations. Re-read proxy counters after process exit so
        # a clean recovery is not lost merely because the child exited quickly.
        recovered = recovered or _proxy_recovery_observed(
            session_id,
            proxy,
            successes_before_outage,
        )
        events = runner_events(project)
        console_events = jsonl_events(log)
        # Recovery/session evidence is validated after process exit from the
        # durable probe-owned JSON stream plus production event log.
        all_events = [*console_events, *events]
        _assert_recovery_wait_bounds(all_events)
        evidence = "\n".join(json.dumps(event, ensure_ascii=False) for event in all_events)
        if not session_id or not recovered or "verdict=RESET_SESSION" in evidence:
            raise RuntimeError(
                "API outage did not recover cleanly: "
                f"session={bool(session_id)}, recovered={recovered}, "
                f"failures={proxy.failures}, successes_before={successes_before_outage}, "
                f"successes_after={proxy.successes}, disconnect={disconnect}, "
                f"armed={bool(outage_marker and outage_marker.is_file())}"
            )

        # StageExecutor intentionally bounds failures per session. A 5s
        # injected outage can span the 2s retry and legitimately consume that
        # budget, so short and long outages share the same controlled-rotation
        # contract instead of encoding timing as a semantic guarantee.
        _assert_controlled_api_session_rotation(
            session_id,
            session_rotated,
            all_events,
        )
        # Real Qwen may absorb/retry transport failures below StageExecutor even
        # with SDK retry knobs minimized. This probe owns end-to-end outage
        # resilience and bounded-session continuity, not the exact recovery layer.
        # StageExecutor structured recovery is proved separately by the production
        # CLI session_expiry_recovery_preflight above. If we do observe a
        # runner.recovery/runner.retry event here, it is useful extra evidence but
        # not mandatory for a valid backend-level self-recovery.
        final_state = read_state(project)
        if str(final_state.get("last_error") or ""):
            raise RuntimeError("successful API recovery left stale last_error in durable state")
        return True


def long_http_recovery_probe(
    settings: Settings,
    root: Path,
    outage_seconds: float,
) -> tuple[int, ...]:
    """Exercise all supported transient HTTP statuses through one recovery path."""
    for status_code in API_RECOVERY_STATUS_CODES:
        api_recovery_probe(
            settings,
            root,
            f"api-long-http-{status_code}-probe",
            outage_seconds=outage_seconds,
            status_code=status_code,
        )
    return API_RECOVERY_STATUS_CODES


def _soak_transient_status_code(run_number: int, every: int) -> int:
    if every <= 0:
        return API_RECOVERY_STATUS_CODES[0]
    occurrence = max(0, run_number // every - 1)
    return API_RECOVERY_STATUS_CODES[occurrence % len(API_RECOVERY_STATUS_CODES)]


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


def _rss_bytes() -> int:
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(counters)
            handle = ctypes.windll.kernel32.GetCurrentProcess()
            if ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            ):
                return int(counters.WorkingSetSize)
        except (AttributeError, OSError, ValueError):
            return 0
        return 0

    status = Path("/proc/self/status")
    if status.is_file():
        try:
            for line in status.read_text(encoding="utf-8").splitlines():
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
        except (OSError, ValueError, IndexError):
            pass
    try:
        import resource
        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return value if sys.platform == "darwin" else value * 1024
    except (ImportError, ValueError):
        return 0


def _handle_count() -> int:
    if os.name != "nt":
        return -1
    try:
        import ctypes
        from ctypes import wintypes

        count = wintypes.DWORD()
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if ctypes.windll.kernel32.GetProcessHandleCount(handle, ctypes.byref(count)):
            return int(count.value)
    except (AttributeError, OSError, ValueError):
        pass
    return -1


def _tree_bytes(root: Path) -> int:
    total = 0
    try:
        files = root.rglob("*")
        for path in files:
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return total


def resource_snapshot(
    root: Path,
    *,
    include_run_root_bytes: bool = False,
) -> dict[str, int]:
    result = {
        "rss_bytes": _rss_bytes(),
        "threads": threading.active_count(),
        "handles": _handle_count(),
        "active_process_markers": sum(
            1 for path in root.rglob("active-process.txt") if path.is_file()
        ),
        "project_state_json_bytes": 0,
        "project_stage_sessions": 0,
        "project_dynamic_groups": 0,
        "project_dynamic_task_groups": 0,
        "project_review_failures": 0,
        "project_transition_history": 0,
        "project_expanded_workflow_stages": 0,
        "project_debug_history_bytes": 0,
    }
    if include_run_root_bytes:
        result["run_root_bytes"] = _tree_bytes(root)
    return result


def project_state_metrics(project: Path) -> dict[str, int]:
    work = project / ".ai-task-runner"
    state_path = work / "state.json"
    state = read_json(state_path)
    def count_mapping(name: str) -> int:
        value = state.get(name)
        return len(value) if isinstance(value, dict) else 0

    expanded = state.get("expanded_workflow")
    try:
        state_bytes = state_path.stat().st_size
    except OSError:
        state_bytes = 0
    return {
        "project_state_json_bytes": int(state_bytes),
        "project_stage_sessions": count_mapping("stage_sessions"),
        "project_dynamic_groups": count_mapping("dynamic_groups"),
        "project_dynamic_task_groups": count_mapping("dynamic_task_groups"),
        "project_review_failures": count_mapping("review_failures"),
        "project_transition_history": (
            len(state.get("transition_history"))
            if isinstance(state.get("transition_history"), list)
            else 0
        ),
        "project_expanded_workflow_stages": len(expanded) if isinstance(expanded, list) else 0,
        "project_debug_history_bytes": _tree_bytes(work / "debug" / "history"),
    }


def _resource_maximum(
    current: dict[str, int],
    sample: dict[str, int],
) -> dict[str, int]:
    keys = set(current) | set(sample)
    return {
        key: max(int(current.get(key, -1)), int(sample.get(key, -1)))
        for key in keys
    }


def _record_resource_snapshot(
    root: Path,
    run_number: int,
    sample: dict[str, int],
) -> None:
    record = {
        "timestamp": time.time(),
        "run_number": run_number,
        **sample,
    }
    with (root / "resource-observation.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def soak(settings: Settings, root: Path, hours: float) -> SoakResult:
    started = time.monotonic()
    deadline = started + hours * 3600
    baseline = resource_snapshot(root, include_run_root_bytes=True)
    maximum = dict(baseline)
    _record_resource_snapshot(root, 0, baseline)
    result = SoakResult(resource_start=baseline, resource_max=maximum)
    while time.monotonic() < deadline:
        run_number = result.completed + 1
        sandboxed = settings.sandbox or every_nth(settings.soak_sandbox_every, run_number)
        run_settings = replace(settings, sandbox=sandboxed)

        if every_nth(settings.soak_timeout_every, run_number):
            with run_endpoint(settings, sandboxed):
                timeout_probe(run_settings, root, f"soak-timeout-{run_number:04d}")
            result = replace(result, timeout_probes=result.timeout_probes + 1)

        if every_nth(settings.soak_transient_api_every, run_number):
            status_code = _soak_transient_status_code(
                run_number,
                settings.soak_transient_api_every,
            )
            api_recovery_probe(
                run_settings,
                root,
                f"soak-api-{status_code}-{run_number:04d}",
                status_code=status_code,
            )
            status_counts = dict(result.transient_status_counts)
            status_counts[status_code] = status_counts.get(status_code, 0) + 1
            result = replace(
                result,
                transient_recoveries=result.transient_recoveries + 1,
                transient_status_counts=status_counts,
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
            expected_ai_sessions = builtin_final_ai_contract("mixed")[0]
            if len(final_validation_sessions(project)) < expected_ai_sessions:
                raise RuntimeError(
                    f"soak-{run_number:04d} did not use {expected_ai_sessions} "
                    "Final AI sessions"
                )
        result = replace(
            result,
            completed=result.completed + 1,
            mixed_validations=mixed_validations,
            sandbox_runs=result.sandbox_runs + int(sandboxed),
        )
        sample = resource_snapshot(root)
        sample.update(project_state_metrics(project))
        maximum = _resource_maximum(maximum, sample)
        _record_resource_snapshot(root, run_number, sample)
        result = replace(result, resource_max=maximum, resource_end=sample)
        if settings.pause:
            time.sleep(min(settings.pause, max(0, deadline - time.monotonic())))
    final_sample = resource_snapshot(root, include_run_root_bytes=True)
    maximum = _resource_maximum(maximum, final_sample)
    _record_resource_snapshot(root, result.completed, final_sample)
    return replace(
        result,
        elapsed_seconds=time.monotonic() - started,
        resource_max=maximum,
        resource_end=final_sample,
    )


def require_resource_bounds(result: SoakResult) -> None:
    """Fail soak on clearly unbounded per-run state/process growth.

    run_root_bytes is intentionally excluded: the harness retains a new Project
    directory per soak iteration, so total run-root size is expected to grow.
    These are conservative safety rails, not product-size limits.
    """
    start = result.resource_start or {}
    maximum = result.resource_max or {}
    end = result.resource_end or {}
    failures: list[str] = []

    if int(end.get("active_process_markers", 0)) != 0:
        failures.append(
            f"active process markers remain: {end.get('active_process_markers')}"
        )

    thread_start = int(start.get("threads", 0))
    thread_end = int(end.get("threads", 0))
    if thread_start and thread_end > thread_start + 16:
        failures.append(f"thread count grew {thread_start} -> {thread_end}")

    handle_start = int(start.get("handles", -1))
    handle_end = int(end.get("handles", -1))
    if handle_start >= 0 and handle_end >= 0 and handle_end > handle_start + 128:
        failures.append(f"Windows handle count grew {handle_start} -> {handle_end}")

    rss_start = int(start.get("rss_bytes", 0))
    rss_end = int(end.get("rss_bytes", 0))
    if rss_start and rss_end > rss_start + 512 * 1024 * 1024:
        failures.append(
            f"harness RSS grew by {(rss_end - rss_start) / (1024 * 1024):.1f} MiB"
        )

    ceilings = {
        "project_state_json_bytes": 8 * 1024 * 1024,
        "project_stage_sessions": 2048,
        "project_dynamic_groups": 2048,
        "project_dynamic_task_groups": 2048,
        "project_review_failures": 2048,
        "project_transition_history": MAX_TRANSITION_HISTORY,
        "project_expanded_workflow_stages": 4096,
        "project_debug_history_bytes": 128 * 1024 * 1024,
    }
    for key, ceiling in ceilings.items():
        value = int(maximum.get(key, 0))
        if value > ceiling:
            failures.append(f"{key} exceeded safety rail: {value} > {ceiling}")

    if failures:
        raise RuntimeError("soak resource bounds failed: " + "; ".join(failures))


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
            if control.disconnect:
                control.failures += 1
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                self.connection.close()
                return
            if control.fail:
                control.failures += 1
                payload = json.dumps({
                    "error": {
                        "message": f"temporary live-test HTTP {control.status_code} outage"
                    }
                }).encode("utf-8")
                self.send_response(control.status_code)
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
                # Publish success before the response body becomes observable by the caller.
                # Otherwise Windows may schedule the client immediately after wfile.write()
                # while this handler has not incremented the counter yet, making the
                # reliability probe nondeterministically fail despite a successful proxy.
                control.successes += 1
                self.wfile.write(payload)
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


def runner_ownership_preflight(root: Path) -> None:
    """Exercise the real cross-process project/work-dir ownership lock."""
    from runner.runtime.supervisor import _acquire_run_lock, _release_run_lock

    work = root / "ownership-preflight" / ".ai-task-runner"
    work.mkdir(parents=True, exist_ok=True)
    lock = work / "run.lock"
    token = _acquire_run_lock(lock)
    code = """
from pathlib import Path
import sys
from runner.runtime.supervisor import _acquire_run_lock
path = Path(sys.argv[1])
try:
    _acquire_run_lock(path)
except RuntimeError:
    raise SystemExit(0)
raise SystemExit(3)
"""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    try:
        duplicate = subprocess.run(
            [sys.executable, "-c", code, str(lock)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if duplicate.returncode != 0:
            raise RuntimeError(
                "duplicate Runner ownership was not rejected: "
                f"exit={duplicate.returncode} stderr={duplicate.stderr[-1000:]}"
            )
    finally:
        _release_run_lock(lock, token)

    reacquired = _acquire_run_lock(lock)
    _release_run_lock(lock, reacquired)
    if lock.exists():
        raise RuntimeError("Runner ownership lock was not released cleanly")


def windows_orphan_cleanup_preflight(root: Path) -> None:
    """On Windows, exercise real taskkill-based descendant cleanup with the bounded path."""
    if os.name != "nt":
        return
    from runner.runtime.process_runner import ACTIVE_PROCESS_FILE
    from runner.runtime.supervisor import cleanup_orphans

    work = root / "windows-orphan-preflight"
    work.mkdir(parents=True, exist_ok=True)
    state = work / "state.json"
    state.write_text("{}", encoding="utf-8")
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(300)"],
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    marker = work / ACTIVE_PROCESS_FILE
    marker.write_text(f"{os.getpid()} {child.pid}", encoding="ascii")
    try:
        started = time.monotonic()
        cleanup_orphans([state], os.getpid())
        elapsed = time.monotonic() - started
        if elapsed > 15:
            raise RuntimeError(f"Windows orphan cleanup exceeded bounded time: {elapsed:.1f}s")
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("Windows orphan cleanup left the child alive") from error
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def main() -> int:
    args = arguments()
    if args.list_probes:
        print_probe_list()
        return 0
    try:
        start_probe = resolve_start_probe(args.start_probe)
    except ValueError as error:
        raise SystemExit(str(error)) from error

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
        or args.long_http_outage_seconds <= 0
        or args.long_api_outage_seconds <= 0
        or args.single_process_yaml_items < 0
        or not 1 <= args.api_port <= 65535
    ):
        raise SystemExit(
            "hours/pause/soak-* frequency values must be non-negative; "
            "run-timeout, agent-timeout, planning-timeout, long HTTP/API outage, "
            "single-process YAML items, and api-port must be valid"
        )
    if args.example_smoke_matrix_workflow and not args.example_smoke_matrix_project:
        raise SystemExit(
            "--example-smoke-matrix-workflow requires --example-smoke-matrix-project"
        )
    example_cases = example_smoke_cases(args)
    validate_example_smoke_cases(example_cases)
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
    revision, source_dirty = source_revision()
    print(f"LIVE_RUN_ROOT={run_root}", flush=True)
    print(
        f"SOURCE_REVISION={revision or '<unavailable>'} "
        f"DIRTY={source_dirty if source_dirty is not None else '<unknown>'}",
        flush=True,
    )
    if start_probe:
        print(
            f"START_PROBE={start_probe + 1:02d} {PROBE_ORDER[start_probe]}",
            flush=True,
        )

    stage_probe_live: dict[str, object] = {}
    dryrun_results: list[dict[str, object]] = []
    review_error_policy: dict[str, object] = {}
    review_max_failures: dict[str, object] = {}
    readonly_contract: dict[str, object] = {}
    transient_observed = False
    soak_result = SoakResult()
    example_results: list[tuple[ExampleSmokeCase, Path]] = []

    if probe_enabled("ownership-lock", start_probe):
        runner_ownership_preflight(run_root)
        print("PASS cross-process Runner ownership lock preflight", flush=True)
    if probe_enabled("windows-orphan-cleanup", start_probe):
        windows_orphan_cleanup_preflight(run_root)
        if os.name == "nt":
            print("PASS bounded Windows orphan taskkill preflight", flush=True)
    if probe_enabled("qwen-sandbox", start_probe):
        qwen_sandbox_preflight(settings, args.hours)
        if qwen_sandbox_required(settings, args.hours):
            print("PASS Qwen sandbox Docker preflight", flush=True)
    if probe_enabled("api-retry-classification", start_probe):
        api_retry_classification_preflight()
        print("PASS API transient/deterministic retry classification preflight", flush=True)
    if probe_enabled("task-array-recovery", start_probe):
        task_array_recovery_preflight()
        print("PASS malformed Task envelope -> complete TaskArray recovery preflight", flush=True)
    if probe_enabled("session-expiry-recovery", start_probe):
        session_expiry_recovery_preflight()
        print("PASS expired-session -> Fresh Session durable recovery preflight", flush=True)
    if probe_enabled("stage-probe-live", start_probe):
        stage_probe_live = stage_probe_live_preflight(settings)
        alternate_stage = stage_probe_live.get("alternate_stage")
        alternate_tested = (
            isinstance(alternate_stage, dict)
            and alternate_stage.get("tested") is True
        )
        suffix = " + alternate Stage backend/model" if alternate_tested else ""
        print(
            "PASS real-Qwen isolated Agent Ping + Review Stage Probe"
            f"{suffix} preflight",
            flush=True,
        )
        if not alternate_tested and isinstance(alternate_stage, dict):
            print(
                "SKIP alternate Stage backend/model probe: "
                f"{alternate_stage.get('reason') or 'unavailable'}",
                flush=True,
            )
    if probe_enabled("workflow-dryrun", start_probe):
        dryrun_results = workflow_dryrun_preflight()
        print(
            f"PASS workflow dry-run preflight ({sum(int(item.get('paths_total', 0)) for item in dryrun_results)} deterministic paths)",
            flush=True,
        )
    if probe_enabled("review-error-policy", start_probe):
        review_error_policy = builtin_review_error_policy_contract()
        print("PASS built-in Review retries=2 -> fail-soft Skip contract preflight", flush=True)
    if probe_enabled("review-max-failures", start_probe):
        review_max_failures = builtin_review_max_failures_contract()
        print("PASS built-in Review max_failures=3 semantic FAIL cap preflight", flush=True)
    if probe_enabled("readonly-safety", start_probe):
        readonly_contract = builtin_readonly_safety_contract()
        print("PASS built-in Workflow readonly_safety observe contract preflight", flush=True)
    if probe_enabled("workflow-dryrun-negative", start_probe):
        workflow_dryrun_negative_preflight()
        print("PASS workflow dry-run negative/error preflight", flush=True)
    if probe_enabled("stage-result-mapping", start_probe):
        stage_result_mapping_preflight()
        print("PASS Review/Validator boolean verdict mapping preflight", flush=True)
    if probe_enabled("loop-detection", start_probe):
        loop_detection_contract_preflight()
        print("PASS Qwen loop-detection + bounded Planning retry preflight", flush=True)
    if probe_enabled("runtime-long-path", start_probe):
        runtime_long_path_preflight()
        print("PASS >MAX_PATH runtime resource/state/copy preflight", flush=True)
    if probe_enabled("readonly-long-path", start_probe):
        readonly_long_path_preflight()
        print("PASS >MAX_PATH reusable read-only snapshot preflight", flush=True)
    if probe_enabled("technical-artifact-safety", start_probe):
        technical_artifact_safety_preflight()
        print("PASS protected-path technical-artifact ignore preflight", flush=True)

    with qwen_test_endpoint(settings.sandbox, settings.api_port):
        if probe_enabled("resume", start_probe):
            resume_probe(settings, run_root)
            print("PASS resume/process-restart probe", flush=True)
        if probe_enabled("stop-request-resume", start_probe):
            stop_request_resume_probe(settings, run_root)
            print("PASS detached-UI stop.request/resume probe", flush=True)
        for workflow in ("file", "ai", "mixed"):
            probe_name = f"workflow-{workflow}"
            if probe_enabled(probe_name, start_probe):
                builtin_workflow_probe(settings, run_root, workflow)
                print(f"PASS workflow/{workflow} topology + prompt contract probe", flush=True)
        if probe_enabled("dynamic-handoff-session-policy", start_probe):
            dynamic_handoff_session_policy_probe(settings, run_root)
            print("PASS Dynamic Handoff main/role/fresh session-policy live probe", flush=True)
        if probe_enabled("custom-dynamic-producer", start_probe):
            custom_dynamic_producer_probe(settings, run_root)
            print("PASS custom Python Dynamic Producer -> dynamic child Workflow probe", flush=True)
        if probe_enabled("review-failure-routing", start_probe):
            review_failure_routing_probe(settings, run_root)
            print("PASS Review FAIL -> Execute shared-feedback routing probe", flush=True)
        if probe_enabled("complete-closed-loop", start_probe):
            complete_closed_loop_probe(settings, run_root)
            print("PASS complete Review FAIL -> Execute -> Validator FAIL -> Execute -> closure probe", flush=True)
        if probe_enabled("validator-failure-routing", start_probe):
            validator_failure_routing_probe(settings, run_root)
            print("PASS validator FAIL -> Planning shared-feedback routing probe", flush=True)
        if probe_enabled("file-protection", start_probe):
            file_protection_probe(settings, run_root)
            print("PASS protected-file policy probe", flush=True)
        if probe_enabled("api-502", start_probe):
            transient_observed = api_recovery_probe(settings, run_root)
            print("PASS HTTP 502 transient API/bounded-session recovery probe", flush=True)
        if probe_enabled("api-429", start_probe):
            api_recovery_probe(
                settings, run_root, "api-rate-limit-429-probe",
                outage_seconds=API_RECOVERY_SHORT_OUTAGE_SECONDS, status_code=429,
            )
            print("PASS HTTP 429 rate-limit bounded-session recovery probe", flush=True)
        if probe_enabled("api-503", start_probe):
            api_recovery_probe(
                settings, run_root, "api-service-unavailable-503-probe",
                outage_seconds=API_RECOVERY_SHORT_OUTAGE_SECONDS, status_code=503,
            )
            print("PASS HTTP 503 service-unavailable bounded-session recovery probe", flush=True)
        if probe_enabled("api-long-http", start_probe):
            statuses = long_http_recovery_probe(
                settings,
                run_root,
                args.long_http_outage_seconds,
            )
            print(
                "PASS long HTTP "
                + "/".join(str(code) for code in statuses)
                + f"/{args.long_http_outage_seconds:g}s bounded-session recovery probe",
                flush=True,
            )
        if probe_enabled("api-disconnect", start_probe):
            api_recovery_probe(
                settings,
                run_root,
                "api-disconnect-3m-probe",
                outage_seconds=args.long_api_outage_seconds,
                disconnect=True,
            )
            print(
                f"PASS API disconnect/{args.long_api_outage_seconds:g}s bounded-session recovery probe",
                flush=True,
            )
        if probe_enabled("multi-todo-resume", start_probe):
            multi_todo_resume_probe(settings, run_root)
            print("PASS multi-TODO/checkpoint resume probe", flush=True)
        if probe_enabled("yaml-list-resume", start_probe):
            yaml_list_resume_probe(settings, run_root)
            print("PASS YAML List/resume + validator_args + per-item Final AI 3/2 probe", flush=True)
        if probe_enabled("yaml-list-endurance", start_probe):
            yaml_list_endurance_probe(settings, run_root, args.single_process_yaml_items)
            if args.single_process_yaml_items:
                print(
                    f"PASS single-process YAML endurance ({args.single_process_yaml_items} items)",
                    flush=True,
                )
        if probe_enabled("final-ai-quorum", start_probe):
            final_ai_quorum_probe(settings, run_root, mixed=False)
            print("PASS Final AI 3/2 quorum probe", flush=True)
        if probe_enabled("timeout-recovery-budget", start_probe):
            timeout_probe(settings, run_root)
            print("PASS timeout/recovery-budget probe", flush=True)
        if probe_enabled("soak", start_probe):
            soak_result = soak(settings, run_root, args.hours) if args.hours else SoakResult()
            if args.hours and soak_result.elapsed_seconds < args.hours * 3600:
                raise RuntimeError("soak ended before the requested wall-clock duration")
            if args.hours:
                require_resource_bounds(soak_result)
            if args.high_density and args.hours:
                require_dense_coverage(soak_result)
        if args.require_transient and probe_enabled("api-502", start_probe) and not transient_observed:
            raise RuntimeError("no real transient API recovery was observed")
        if probe_enabled("example-smoke", start_probe):
            for case in example_cases:
                project = example_smoke_probe(
                    settings,
                    run_root,
                    case.source,
                    case.workflow,
                    case.name,
                )
                example_results.append((case, project))
                print(f"PASS copied-example real-agent smoke {case.name}", flush=True)
    summary = {
        "passed": True,
        "source_revision": revision,
        "source_dirty": source_dirty,
        "sandbox": settings.sandbox,
        "high_density": args.high_density,
        "hours_requested": args.hours,
        "agent_timeout": settings.agent_timeout,
        "planning_timeout": settings.planning_timeout,
        "start_probe": {
            "index": start_probe + 1,
            "name": PROBE_ORDER[start_probe],
        },
        "protected_file_probe": probe_enabled("file-protection", start_probe),
        "runner_ownership_preflight": probe_enabled("ownership-lock", start_probe),
        "windows_orphan_cleanup_preflight": (
            os.name == "nt" and probe_enabled("windows-orphan-cleanup", start_probe)
        ),
        "api_retry_classification_preflight": probe_enabled("api-retry-classification", start_probe),
        "task_array_recovery_preflight": probe_enabled("task-array-recovery", start_probe),
        "session_expiry_recovery_preflight": probe_enabled("session-expiry-recovery", start_probe),
        "http_429_recovered": probe_enabled("api-429", start_probe),
        "http_502_recovered": probe_enabled("api-502", start_probe),
        "http_503_recovered": probe_enabled("api-503", start_probe),
        "single_process_yaml_items": args.single_process_yaml_items,
        "stage_probe_live_preflight": stage_probe_live,
        "workflow_dryrun_preflight": probe_enabled("workflow-dryrun", start_probe),
        "builtin_review_error_policy_contract": review_error_policy,
        "builtin_review_max_failures_contract": review_max_failures,
        "builtin_readonly_safety_contract": readonly_contract,
        "workflow_dryrun_negative_preflight": probe_enabled("workflow-dryrun-negative", start_probe),
        "stage_result_mapping_preflight": probe_enabled("stage-result-mapping", start_probe),
        "runtime_long_path_preflight": probe_enabled("runtime-long-path", start_probe),
        "readonly_long_path_preflight": probe_enabled("readonly-long-path", start_probe),
        "technical_artifact_safety_preflight": probe_enabled("technical-artifact-safety", start_probe),
        "stop_request_resume_probe": probe_enabled("stop-request-resume", start_probe),
        "workflow_dryrun_paths": sum(int(item.get("paths_total", 0)) for item in dryrun_results),
        "loop_detection_contract_preflight": probe_enabled("loop-detection", start_probe),
        "builtin_workflow_contracts": [
            workflow for workflow in ("file", "ai", "mixed")
            if probe_enabled(f"workflow-{workflow}", start_probe)
        ],
        "dynamic_handoff_session_policy_probe": probe_enabled("dynamic-handoff-session-policy", start_probe),
        "custom_dynamic_producer_probe": probe_enabled("custom-dynamic-producer", start_probe),
        "review_failure_routing_probe": probe_enabled("review-failure-routing", start_probe),
        "validator_failure_routing_probe": probe_enabled("validator-failure-routing", start_probe),
        "yaml_list_resume_probe": probe_enabled("yaml-list-resume", start_probe),
        "yaml_list_item_runtime_options_probe": probe_enabled("yaml-list-resume", start_probe),
        "yaml_list_final_ai_quorum_probe": probe_enabled("yaml-list-resume", start_probe),
        "soak_runs_completed": soak_result.completed,
        "soak_elapsed_seconds": round(soak_result.elapsed_seconds, 3),
        "soak_final_ai_every": settings.soak_final_ai_every,
        "soak_mixed_validation_runs": soak_result.mixed_validations,
        "soak_transient_api_every": settings.soak_transient_api_every,
        "soak_transient_recovery_runs": soak_result.transient_recoveries,
        "soak_transient_status_counts": {
            str(code): int(soak_result.transient_status_counts.get(code, 0))
            for code in API_RECOVERY_STATUS_CODES
        },
        "soak_timeout_every": settings.soak_timeout_every,
        "soak_timeout_probe_runs": soak_result.timeout_probes,
        "soak_yaml_every": settings.soak_yaml_every,
        "soak_yaml_runs": soak_result.yaml_runs,
        "soak_sandbox_every": settings.soak_sandbox_every,
        "soak_sandbox_runs": soak_result.sandbox_runs,
        "resource_observation": {
            "start": soak_result.resource_start,
            "max": soak_result.resource_max,
            "end": soak_result.resource_end,
        },
        "recovery_backoff_observation": recovery_backoff_observation(run_root),
        "transient_observed": transient_observed,
        "long_http_outage_seconds": args.long_http_outage_seconds,
        "long_http_status_codes": list(API_RECOVERY_STATUS_CODES),
        "long_http_recovered": probe_enabled("api-long-http", start_probe),
        "long_api_outage_seconds": args.long_api_outage_seconds,
        "long_api_disconnect_recovered": probe_enabled("api-disconnect", start_probe),
        "example_smoke": bool(example_results),
        "example_smoke_runs": len(example_results),
        "example_smoke_source": (
            "" if not example_results else str(example_results[0][0].source.resolve())
        ),
        "example_smoke_project": "" if not example_results else str(example_results[0][1]),
        "example_smoke_workflow": (
            ""
            if not example_results or example_results[0][0].workflow is None
            else str(example_results[0][0].workflow.resolve())
        ),
        "example_smoke_cases": [
            {
                "name": case.name,
                "source": str(case.source.resolve()),
                "workflow": "" if case.workflow is None else str(case.workflow.resolve()),
                "project": str(project),
            }
            for case, project in example_results
        ],
        "run_root": str(run_root),
    }
    (run_root / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
