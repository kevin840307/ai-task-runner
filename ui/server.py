from __future__ import annotations
import csv

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
import uuid
import yaml
from jinja2 import Environment, meta
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from project_registry import path_key, project_file_lock

try:
    from .workflow_folder_package import export_folder_package, import_folder_package, inspect_folder_package
    from .workflow_graph import build_workflow_graph
    from .workflow_storage import (iter_project_packages, project_package_for_asset, project_package_folders, project_package_prompt_dir, project_package_workflow_dir, project_workflow_root)
except ImportError:  # direct ui/main.py execution
    from workflow_folder_package import export_folder_package, import_folder_package, inspect_folder_package
    from workflow_graph import build_workflow_graph
    from workflow_storage import (iter_project_packages, project_package_for_asset, project_package_folders, project_package_prompt_dir, project_package_workflow_dir, project_workflow_root)

try:
    from .workflow_builder_state import WorkflowBuilderMixin
    from .workflow_studio_state import WorkflowStudioMixin
    from .server_support import background_process_kwargs as _background_process_kwargs, is_loopback_host
except ImportError:
    from workflow_builder_state import WorkflowBuilderMixin
    from workflow_studio_state import WorkflowStudioMixin
    from server_support import background_process_kwargs as _background_process_kwargs, is_loopback_host

UI_STATE_DIR = ".ai-task-runner/ui"
MESSAGES_FILE = "messages.jsonl"
CHAT_STATE_FILE = "chat-state.json"
LAUNCH_STATE_FILE = "launching.json"
LAUNCH_RESERVATION_GRACE = 30.0
RUNTIME_DIR = ".ai-task-runner"
EDITABLE_SUFFIXES = {".yaml", ".yml", ".md"}
SYSTEM_SCOPES = {"system"}
PROJECTS_PAYLOAD_CACHE_SECONDS = 1.5



class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
        return super().increase_indent(flow, False)


class UIState(WorkflowStudioMixin, WorkflowBuilderMixin):
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ui_root = self.repo_root / "ui"
        self.static_root = self.ui_root / "static"
        self.projects_file = self.ui_root / "data" / "projects.json"
        self.workflow_visibility_file = self.ui_root / "data" / "workflow_visibility.json"
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        self._chat_lock = threading.RLock()
        self._projects_lock = threading.RLock()
        self._runtime_lock = threading.RLock()
        self._edit_lock = threading.RLock()
        self._launch_lock = threading.RLock()
        self._builder_lock = threading.RLock()
        self._process_module = subprocess
        self._workflow_requirement_cache: dict[str, tuple[int, int, dict]] = {}
        self._projects_payload_cache: tuple[int, float, dict] | None = None
        if not self.projects_file.exists():
            self._write_projects([])
        if not self.workflow_visibility_file.exists():
            self._atomic_json(self.workflow_visibility_file, {})

    # ------------------------------ projects/runtime/chat ------------------------------
    @staticmethod
    def _project_path_key(path: str | Path) -> str:
        return path_key(path)

    @staticmethod
    def _project_display_path(path: str | Path) -> str:
        return str(Path(path).expanduser().resolve())

    def projects_payload(self) -> dict:
        # Runtime status is live process/state data. Do not cache it using only
        # projects.json mtime: that can replay a pre-run/pre-stop status on the
        # next sidebar poll and make rows visibly oscillate.
        projects = self.projects()
        running = sum(1 for item in projects if item.get("runtime_status") == "running")
        return {
            "projects": projects,
            "meta": {
                "total": len(projects),
                "running": running,
                "suggested_poll_ms": self._project_poll_interval_ms(len(projects), running),
            },
        }

    @staticmethod
    def _project_poll_interval_ms(total: int, running: int) -> int:
        if total >= 20 or running >= 10:
            return 12000
        if total >= 10 or running >= 5:
            return 10000
        return 8000

    def projects(self) -> list[dict]:
        try:
            rows = json.loads(self.projects_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rows = []
        project_rows = rows if isinstance(rows, list) else []
        # Take the Windows process snapshot only when at least one tracked
        # Project has runtime process evidence. Idle-only lists avoid tasklist.
        alive_pids = self._process_snapshot() if self._projects_need_process_snapshot(project_rows) else None
        result: list[dict] = []
        seen: set[str] = set()
        for item in project_rows:
            if not isinstance(item, dict):
                continue
            raw_path = str(item.get("path", "")).strip()
            if not raw_path:
                continue
            path = self._project_display_path(raw_path)
            key = self._project_path_key(path)
            if key in seen:
                continue
            seen.add(key)
            project_path = Path(path)
            summary = self._project_runtime_summary(project_path, alive_pids)
            result.append({
                "name": item.get("name") or project_path.name or path,
                "path": path,
                "exists": project_path.is_dir(),
                "runtime_status": summary["status"],
                "runtime_stage": summary["stage"],
                "runtime_completed_count": summary["completed_count"],
                "runtime_total": summary["total"],
            })
        return result

    def _projects_need_process_snapshot(self, rows: list[dict]) -> bool:
        for item in rows:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            project = Path(path)
            runtime = self.runtime_dir(project)
            if (runtime / "runner-process.json").is_file() or self._launch_state_path(project).exists():
                return True
        return False

    def environment_check(self) -> dict:
        """Run the standalone local environment checker used by both CLI and UI."""
        tool = self.repo_root / "tool" / "environment_check.py"
        if not tool.is_file():
            raise ValueError(f"Environment check tool not found: {tool}")
        try:
            result = subprocess.run(
                [sys.executable, str(tool), "--repo-root", str(self.repo_root), "--json"],
                cwd=self.repo_root,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Environment check failed: {exc}") from exc
        output = (result.stdout or "").strip()
        try:
            data = json.loads(output)
        except json.JSONDecodeError as exc:
            detail = (result.stderr or output or "No output")[-4000:]
            raise ValueError(f"Environment check returned invalid output: {detail}") from exc
        if not isinstance(data, dict):
            raise ValueError("Environment check returned invalid result")
        return data

    def backend_catalog(self) -> dict:
        """Return backend names without importing Runner Core into the UI."""
        names: set[str] = set()
        backends_root = self.repo_root / "runner" / "backends"
        for path in backends_root.glob("*.py") if backends_root.is_dir() else ():
            if path.name.startswith("_"):
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except (OSError, SyntaxError):
                continue
            for node in tree.body:
                if not isinstance(node, ast.ClassDef):
                    continue
                for child in node.body:
                    if not isinstance(child, (ast.Assign, ast.AnnAssign)):
                        continue
                    target = child.targets[0] if isinstance(child, ast.Assign) and child.targets else getattr(child, "target", None)
                    value = child.value if isinstance(child, (ast.Assign, ast.AnnAssign)) else None
                    if isinstance(target, ast.Name) and target.id == "name" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                        if value.value.strip():
                            names.add(value.value.strip())
        default = ""
        defaults = self.repo_root / "runner" / "config" / "defaults.py"
        try:
            tree = ast.parse(defaults.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "DEFAULT_BACKEND" for t in node.targets):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        default = node.value.value.strip()
                        break
        except (OSError, SyntaxError):
            pass
        if default:
            names.add(default)
        return {"default": default, "backends": sorted(names)}

    def execution_mode_catalog(self) -> dict:
        """Return the Runner-owned top-level orchestration catalog."""
        tool = self.repo_root / "tool" / "execution_mode_catalog.py"
        try:
            completed = subprocess.run(
                [sys.executable, str(tool)],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Execution mode catalog unavailable: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise ValueError("Execution mode catalog failed: " + detail[-2000:])
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Execution mode catalog returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Execution mode catalog must be an object")
        return payload

    def workflow_catalog(self) -> dict:
        """Return the Runner-owned Stage/editor contract without importing Core."""
        tool = self.repo_root / "tool" / "workflow_catalog.py"
        try:
            completed = subprocess.run(
                [sys.executable, str(tool)],
                cwd=str(self.repo_root),
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Workflow catalog unavailable: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise ValueError("Workflow catalog failed: " + detail[-2000:])
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Workflow catalog returned invalid JSON") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("stage_types"), dict):
            raise ValueError("Workflow catalog is missing stage_types")
        return payload

    def _supported_stage_types(self) -> set[str]:
        tool = self.repo_root / "tool" / "workflow_catalog.py"
        if not tool.is_file():
            return {"base", "task", "review", "ai_validator", "command", "plan"}
        return set(self.workflow_catalog().get("stage_types", {}))

    def add_project(self, path: str) -> dict:
        with self._projects_lock, project_file_lock(self.projects_file):
            resolved = Path(path).expanduser().resolve()
            if not resolved.is_dir():
                raise ValueError("Project folder does not exist")
            key = self._project_path_key(resolved)
            items = [p for p in self.projects() if self._project_path_key(p["path"]) != key]
            project = {"name": resolved.name or str(resolved), "path": str(resolved)}
            items.insert(0, project)
            self._write_projects_unlocked(items)
            return project

    def remove_project(self, path: str) -> None:
        with self._projects_lock, project_file_lock(self.projects_file):
            key = self._project_path_key(path)
            target = next((p for p in self.projects() if self._project_path_key(p["path"]) == key), None)
            if target and Path(target["path"]).is_dir() and self.read_runtime(Path(target["path"])).get("running"):
                raise ValueError("Stop the active runtime before removing this project")
            self._write_projects_unlocked([p for p in self.projects() if self._project_path_key(p["path"]) != key])

    def rename_project(self, path: str, name: str) -> dict:
        label = " ".join(str(name or "").split())
        if not label:
            raise ValueError("Project name is required")
        if len(label) > 120:
            raise ValueError("Project name is too long")
        with self._projects_lock, project_file_lock(self.projects_file):
            key = self._project_path_key(path)
            rows = self.projects()
            renamed: dict | None = None
            for item in rows:
                if self._project_path_key(item["path"]) != key:
                    continue
                item["name"] = label
                renamed = {"name": label, "path": item["path"]}
                break
            if not renamed:
                raise ValueError("Project is not in the sidebar")
            self._write_projects_unlocked(rows)
            return renamed

    def _write_projects(self, items: list[dict]) -> None:
        with self._projects_lock, project_file_lock(self.projects_file):
            self._write_projects_unlocked(items)

    def _write_projects_unlocked(self, items: list[dict]) -> None:
        # Persist identity only; existence/runtime status are live filesystem data.
        rows = []
        seen: set[str] = set()
        for item in items:
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            display_path = self._project_display_path(path)
            key = self._project_path_key(display_path)
            if key in seen:
                continue
            seen.add(key)
            rows.append({"name": str(item.get("name") or Path(display_path).name), "path": display_path})
        tmp = self.projects_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.projects_file)
        self._projects_payload_cache = None

    def runtime_dir(self, project: Path) -> Path:
        return project / RUNTIME_DIR

    def _launch_state_path(self, project: Path) -> Path:
        return project / UI_STATE_DIR / LAUNCH_STATE_FILE

    @staticmethod
    def _marker_pid(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _active_launch_reservation(self, project: Path, alive_pids: set[int] | None = None) -> dict:
        """Return a live UI launch reservation, removing stale reservations."""
        path = self._launch_state_path(project)
        marker = self._read_json(path)
        if marker is None:
            if not path.exists():
                return {}
            try:
                modified_at = path.stat().st_mtime
                age = max(0.0, time.time() - modified_at)
            except OSError:
                return {}
            # Another UI process may be between exclusive create and JSON write.
            if age <= LAUNCH_RESERVATION_GRACE:
                return {"created_at": modified_at}
            try:
                path.unlink()
            except OSError:
                pass
            return {}

        child_pid = self._marker_pid(marker.get("child_pid"))
        owner_pid = self._marker_pid(marker.get("owner_pid"))
        try:
            created_at = float(marker.get("created_at") or 0.0)
        except (TypeError, ValueError):
            created_at = 0.0
        age = max(0.0, time.time() - created_at) if created_at else float("inf")
        if child_pid:
            # launching.json only bridges the short gap between Popen and the
            # supervisor-owned runner-process.json. Never let a recycled PID
            # keep a project "running" indefinitely.
            active = bool(
                age <= LAUNCH_RESERVATION_GRACE
                and self._pid_alive(child_pid, alive_pids)
            )
        else:
            active = bool(
                owner_pid
                and age <= LAUNCH_RESERVATION_GRACE
                and self._pid_alive(owner_pid, alive_pids)
            )
        if active:
            return marker
        try:
            path.unlink()
        except OSError:
            pass
        return {}

    def _reserve_launch(self, project: Path, mode: str) -> tuple[str, dict]:
        path = self._launch_state_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        payload = {
            "token": token,
            "owner_pid": os.getpid(),
            "child_pid": 0,
            "created_at": time.time(),
            "mode": mode,
        }
        for _ in range(2):
            if self._active_launch_reservation(project):
                raise ValueError("This project already has an active runtime")
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                continue
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, ensure_ascii=False)
            except Exception:
                try:
                    path.unlink()
                except OSError:
                    pass
                raise
            return token, payload
        raise ValueError("This project already has an active runtime")

    def _update_launch_reservation(self, project: Path, token: str, payload: dict) -> None:
        path = self._launch_state_path(project)
        current = self._read_json(path) or {}
        if current.get("token") != token:
            raise ValueError("Launch reservation was lost before Runner startup")
        tmp = path.with_name(f"{path.name}.{token}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _clear_launch_reservation(self, project: Path, token: str = "") -> None:
        path = self._launch_state_path(project)
        if token:
            marker = self._read_json(path) or {}
            if marker.get("token") not in {None, token}:
                return
        try:
            path.unlink()
        except OSError:
            pass

    @staticmethod
    def _task_mark(state: dict, index: int, task: dict) -> str:
        if task.get("status") == "completed":
            return "x"
        if index == int(state.get("current", 0) or 0) and not state.get("completed"):
            return ">"
        return " "

    def _runtime_display(self, project: Path) -> tuple[Path, Path, dict, dict]:
        """Resolve the Runner-owned runtime currently visible for one Project.

        Direct runs use the root runtime. YAML List runs publish only a small
        script pointer in the root console snapshot; the child keeps the real
        durable state under ``script/NNN``. The UI follows that pointer instead
        of inventing a second aggregate workflow state.
        """
        runtime = self.runtime_dir(project)
        script_view = self._read_json(runtime / "console-view.json") or {}
        display_runtime = runtime
        if script_view.get("mode") == "script":
            child_root = str(script_view.get("child_project_root") or "").strip()
            child_work = str(script_view.get("child_work_dir") or "").strip()
            work = Path(child_work) if child_work else Path()
            if child_root and child_work and Path(child_root).is_absolute() and not work.is_absolute() and ".." not in work.parts:
                display_runtime = Path(child_root).resolve() / work
        state = self._read_json(display_runtime / "state.json") or {}
        return runtime, display_runtime, script_view, state

    @staticmethod
    def _script_completed(script_view: dict) -> bool:
        if script_view.get("mode") != "script":
            return False
        index = int(script_view.get("script_index") or 0)
        total = int(script_view.get("script_total") or 0)
        return bool(total and index == total and script_view.get("script_status") == "completed")

    def _project_runtime_status(self, project: Path, alive_pids: set[int] | None = None) -> str:
        return str(self._project_runtime_summary(project, alive_pids)["status"])

    def _project_runtime_summary(self, project: Path, alive_pids: set[int] | None = None) -> dict:
        if not project.is_dir():
            return {"status": "missing", "stage": "", "completed_count": 0, "total": 0}
        runtime, _, script_view, state = self._runtime_display(project)
        marker = self._read_json(runtime / "runner-process.json") or {}
        pid_value = self._marker_pid(marker.get("supervisor_pid"))
        status = "idle"
        if pid_value and self._pid_alive(pid_value, alive_pids):
            self._clear_launch_reservation(project)
            status = "running"
        elif self._active_launch_reservation(project, alive_pids):
            status = "running"
        else:
            completed = self._script_completed(script_view) if script_view.get("mode") == "script" else bool(state.get("completed"))
            if completed:
                status = "completed"
            elif marker and state:
                status = "interrupted"
            elif state:
                status = "stopped"
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        completed_count = sum(1 for task in tasks if isinstance(task, dict) and task.get("status") == "completed")
        stage = str(state.get("stage") or "")
        if script_view.get("mode") == "script":
            index = int(script_view.get("script_index") or 0)
            total = int(script_view.get("script_total") or 0)
            prefix = f"Script {index}/{total}" if index and total else "Script"
            stage = f"{prefix} · {stage}" if stage else prefix
        return {
            "status": status,
            "stage": stage,
            "completed_count": completed_count,
            "total": len(tasks),
        }

    def _fallback_console_view(self, state: dict, status_hint: str = "", detail_hint: str = "") -> dict:
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        completed_count = 0
        view_tasks: list[dict] = []
        for index, raw in enumerate(tasks):
            task = raw if isinstance(raw, dict) else {}
            mark = self._task_mark(state, index, task)
            if task.get("status") == "completed":
                completed_count += 1
            title = str(task.get("title") or task.get("id") or f"Task {index + 1}")
            view_tasks.append({
                "index": index + 1,
                "id": str(task.get("id") or ""),
                "title": title,
                "status": str(task.get("status") or "pending"),
                "attempts": int(task.get("attempts") or 0),
                "mark": mark,
                "line": f"  [{mark}] {index + 1}. {title}",
            })
        status = str(status_hint or state.get("stage") or "準備中")
        detail = str(detail_hint or state.get("last_error") or "")
        cycle = int(state.get("cycle") or 1)
        lines = [
            f"AI Task Runner  Cycle {cycle}  Progress {completed_count}/{len(view_tasks)}",
            "",
            *[item["line"] for item in view_tasks],
            "",
            f"  {{spinner}} {status}",
        ]
        if detail:
            lines.append(f"    {' '.join(detail.splitlines())}")
        return {
            "schema_version": 1,
            "run_id": str(state.get("run_id") or ""),
            "cycle": cycle,
            "current": int(state.get("current") or 0),
            "completed": bool(state.get("completed")),
            "completed_count": completed_count,
            "total": len(view_tasks),
            "status": " ".join(status.splitlines()),
            "detail": " ".join(detail.splitlines()),
            "tasks": view_tasks,
            "lines": lines,
            "fallback": True,
        }

    def _console_view(self, runtime: Path, state: dict) -> tuple[dict, bool]:
        path = runtime / "console-view.json"
        console = self._read_json(path) or {}
        state_tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        valid = isinstance(console, dict) and isinstance(console.get("lines"), list)
        if valid and state.get("run_id") and console.get("run_id") != state.get("run_id"):
            valid = False
        if valid and state_tasks:
            console_tasks = console.get("tasks") or []
            if len(console_tasks) != len(state_tasks):
                valid = False
            elif int(console.get("current") or 0) != int(state.get("current") or 0):
                valid = False
            elif bool(console.get("completed")) != bool(state.get("completed")):
                valid = False
            else:
                for raw, shown in zip(state_tasks, console_tasks):
                    if not isinstance(raw, dict) or not isinstance(shown, dict):
                        valid = False
                        break
                    if (
                        str(raw.get("status") or "pending") != str(shown.get("status") or "pending")
                        or int(raw.get("attempts") or 0) != int(shown.get("attempts") or 0)
                        or str(raw.get("title") or "") != str(shown.get("title") or "")
                    ):
                        valid = False
                        break
        if valid:
            return console, path.is_file()
        return self._fallback_console_view(
            state,
            str(console.get("status") or "") if isinstance(console, dict) else "",
            str(console.get("detail") or "") if isinstance(console, dict) else "",
        ), False

    @staticmethod
    def _normalize_model(value: str) -> str:
        model = str(value or "").strip()
        if len(model) > 200 or any(ord(ch) < 32 for ch in model):
            raise ValueError("Model name is invalid")
        return model

    @classmethod
    def _model_cli_args(cls, value: str) -> list[str]:
        model = cls._normalize_model(value)
        return [] if not model else ["--agent-arg=--model", f"--agent-arg={model}"]

    def _latest_run_request(self, project: Path) -> dict:
        requests = project / UI_STATE_DIR / "requests"
        if not requests.is_dir():
            return {}
        candidates: list[tuple[int, Path]] = []
        for path in requests.glob("*/request.json"):
            try:
                candidates.append((path.stat().st_mtime_ns, path))
            except OSError:
                continue
        for _, path in sorted(candidates, reverse=True):
            data = self._read_json(path) or {}
            if isinstance(data, dict):
                return data
        return {}

    def read_runtime(self, project: Path) -> dict:
        runtime, display_runtime, script_view, state = self._runtime_display(project)
        marker = self._read_json(runtime / "runner-process.json") or {}
        request = self._latest_run_request(project)
        stream = self._display_stream(self._read_text(display_runtime / "stream.log", limit=12000))
        supervisor_pid = self._marker_pid(marker.get("supervisor_pid"))
        supervisor_running = bool(supervisor_pid and self._pid_alive(supervisor_pid))
        if supervisor_running:
            self._clear_launch_reservation(project)
            launch = {}
        else:
            launch = self._active_launch_reservation(project)
        launching = bool(launch)
        running = supervisor_running or launching
        stale = bool(marker and not supervisor_running and not launching)
        pid = marker.get("supervisor_pid") if supervisor_running else (launch.get("child_pid") or launch.get("owner_pid") or marker.get("supervisor_pid"))
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        console, console_snapshot_exists = self._console_view(display_runtime, state)
        script_mode = script_view.get("mode") == "script"
        script_index = int(script_view.get("script_index") or 0) if script_mode else 0
        script_total = int(script_view.get("script_total") or 0) if script_mode else 0
        script_completed = self._script_completed(script_view) if script_mode else False
        if script_mode:
            script_label = f"Script {script_index}/{script_total}" if script_index and script_total else "Script"
            child_lines = [str(line) for line in console.get("lines", [])]
            console = dict(console)
            console["lines"] = [f"AI Task Runner  {script_label}", "", *child_lines]
            console_snapshot_exists = console_snapshot_exists or (runtime / "console-view.json").is_file()
        resettable = bool(
            not running
            and runtime.exists()
            and any(child.name != "ui" for child in runtime.iterdir())
        )
        current = int(state.get("current", 0) or 0)
        current_task = ""
        if tasks and 0 <= current < len(tasks):
            task = tasks[current]
            if isinstance(task, dict):
                current_task = str(task.get("title") or task.get("id") or "")
        completed = script_completed if script_mode else bool(state.get("completed"))
        resumable = bool(state and not completed)
        if not running and completed and not script_mode:
            self.sync_completion(project)
        return {
            "running": running,
            "launching": launching,
            "run_id": state.get("run_id") or "",
            "stale": stale,
            "pid": pid,
            "worker_pid": marker.get("worker_pid"),
            "stage": state.get("stage") or "",
            "task": current_task,
            "current": current + 1 if tasks else 0,
            "total": len(tasks),
            "completed": completed,
            "has_state": bool(state),
            "resumable": resumable,
            "resettable": resettable,
            "script_mode": script_mode,
            "script_index": script_index,
            "script_total": script_total,
            "script_status": str(script_view.get("script_status") or "") if script_mode else "",
            "input_prompt": str(state.get("goal") or script_view.get("prompt_preview") or ""),
            "last_error": state.get("last_error") or "",
            "stream": stream,
            "cli_lines": [str(line) for line in console.get("lines", [])],
            "cli_tasks": console.get("tasks", []) if isinstance(console.get("tasks"), list) else [],
            "cli_status": str(console.get("status") or ""),
            "cli_detail": str(console.get("detail") or ""),
            "completed_count": int(console.get("completed_count") or 0),
            "console_snapshot_exists": console_snapshot_exists,
            "started_at": marker.get("started_at") or launch.get("created_at") or 0,
            "updated_at": state.get("last_activity_at") or script_view.get("updated_at") or marker.get("started_at") or launch.get("created_at") or 0,
            "backend": str(request.get("backend") or ""),
            "model": str(request.get("model") or ""),
            "workflow": str(request.get("workflow") or ""),
            "execution_mode": str(request.get("execution_mode") or "linear"),
            "validator": str(request.get("validator") or ""),
        }

    def active_projects(self) -> list[dict]:
        active: list[dict] = []
        for item in self.projects():
            path = Path(item["path"])
            if not path.is_dir():
                continue
            info = self.read_runtime(path)
            if info.get("running"):
                active.append({"name": item["name"], "path": item["path"], "pid": info.get("pid")})
        return active

    def edit_guard(self) -> dict:
        active = self.active_projects()
        return {
            "editable": not active,
            "active_projects": active,
            "reason": "" if not active else "Workflow and prompt editing is locked while any tracked project is running.",
        }

    def messages(self, project: Path) -> list[dict]:
        self.sync_completion(project)
        path = project / UI_STATE_DIR / MESSAGES_FILE
        if not path.exists():
            return []
        rows: list[dict] = []
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and item.get("role") in {"user", "assistant", "system"}:
                        rows.append(item)
        except OSError:
            return []
        return rows[-200:]

    def append_message(self, project: Path, role: str, content: str, *, run_id: str = "") -> None:
        with self._chat_lock:
            folder = project / UI_STATE_DIR
            folder.mkdir(parents=True, exist_ok=True)
            row = {"role": role, "content": content, "time": time.time()}
            if run_id:
                row["run_id"] = run_id
            with (folder / MESSAGES_FILE).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def clear_chat_history(self, project: Path, *, reset_stopped: bool = False) -> dict:
        """Clear persisted UI conversation history.

        A stopped/interrupted task remains resumable by default. When the UI
        explicitly asks to clear a stopped task too, reset Runner-owned runtime
        state in the same lock order used by launch_message so reopening the UI
        cannot leave the composer locked by hidden resumable state.
        """
        with self._chat_lock, self._runtime_lock:
            runtime = self.read_runtime(project)
            if runtime.get("running"):
                raise ValueError("Cannot clear chat history while this Project is running")
            reset = bool(reset_stopped and runtime.get("resumable"))
            if reset:
                self._reset_runtime_locked(project)

            folder = project / UI_STATE_DIR
            messages_path = folder / MESSAGES_FILE
            try:
                messages_path.unlink()
            except FileNotFoundError:
                pass

            runtime_state = self._read_json(self.runtime_dir(project) / "state.json") or {}
            run_id = str(runtime_state.get("run_id") or "").strip()
            if run_id and bool(runtime_state.get("completed")):
                self._write_chat_state(project, {
                    "last_assistant_run_id": run_id,
                    "updated_at": time.time(),
                    "history_cleared_at": time.time(),
                })
            else:
                try:
                    (folder / CHAT_STATE_FILE).unlink()
                except FileNotFoundError:
                    pass
            return {"ok": True, "runtime_reset": reset}

    def sync_completion(self, project: Path) -> bool:
        with self._chat_lock:
            runtime_dir = self.runtime_dir(project)
            state = self._read_json(runtime_dir / "state.json") or {}
            run_id = str(state.get("run_id") or "").strip()
            if not run_id or not bool(state.get("completed")):
                return False
            marker = self._read_json(project / UI_STATE_DIR / CHAT_STATE_FILE) or {}
            if marker.get("last_assistant_run_id") == run_id:
                return False
            result = self._read_text(runtime_dir / "debug" / "last-result.txt", limit=40000).strip()
            if not result:
                result = "Run completed."
            self.append_message(project, "assistant", result, run_id=run_id)
            self._write_chat_state(project, {"last_assistant_run_id": run_id, "updated_at": time.time()})
            return True

    def _write_chat_state(self, project: Path, value: dict) -> None:
        folder = project / UI_STATE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / CHAT_STATE_FILE
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def launch_message(self, project: Path, message: str, *, backend: str = "", model: str = "", validator: str = "", workflow: str = "", ai_validator_prompt_file: str = "", readonly_safety: str = "restore") -> None:
        """Start one Workflow task from an immutable UI request snapshot.

        A completed prior run is reset automatically. An interrupted/stopped run
        must be explicitly Continued or Reset so a new task cannot silently
        discard recoverable state.
        """
        with self._chat_lock, self._runtime_lock:
            if not str(workflow or "").strip():
                raise ValueError("Select a Workflow before Run")
            runtime = self.read_runtime(project)
            if runtime.get("running"):
                raise ValueError("This project already has an active runtime")
            if runtime.get("resumable"):
                raise ValueError("Previous task is stopped or interrupted. Continue it or Reset before starting a new task.")
            if runtime.get("completed") or runtime.get("stale"):
                self._reset_runtime_locked(project)
            request = self._create_run_request(
                project,
                message,
                backend=backend,
                model=model,
                validator=validator,
                workflow=workflow,
                ai_validator_prompt_file=ai_validator_prompt_file,
                readonly_safety=readonly_safety,
                request_mode="workflow",
            )
            try:
                self.launch(
                    project,
                    None,
                    mode="run",
                    backend=backend,
                    model=request["model"],
                    validator=request["validator"],
                    workflow=request["workflow"],
                    execution_mode=request.get("execution_mode", "linear"),
                    goal_file=request["prompt_file"],
                    ai_validator_prompt_file=request.get("ai_validator_prompt_file", ""),
                    readonly_safety=request.get("readonly_safety", "restore"),
                )
            except Exception:
                # A failed launch must not leave a fake user message or an orphan
                # request snapshot, including nested validator resources.
                shutil.rmtree(Path(request["request_dir"]), ignore_errors=True)
                raise
            self.append_message(project, "user", message)

    def rerun_last(self, project: Path, *, backend: str = "", model: str = "", validator: str = "", workflow: str = "", ai_validator_prompt_file: str = "", readonly_safety: str = "restore") -> None:
        """Atomically reset and relaunch the last user task within this UI process."""
        with self._chat_lock, self._runtime_lock:
            runtime = self.read_runtime(project)
            if runtime.get("running"):
                raise ValueError("This project already has an active runtime")
            last = next((m["content"] for m in reversed(self.messages(project)) if m.get("role") == "user"), "")
            if not last:
                raise ValueError("No previous task to rerun")
            self._reset_runtime_locked(project)
            request = self._create_run_request(
                project, last, backend=backend, model=model, validator=validator, workflow=workflow,
                ai_validator_prompt_file=ai_validator_prompt_file, readonly_safety=readonly_safety,
                request_mode="workflow",
            )
            try:
                self.launch(
                    project, None, mode="run", backend=backend, model=request["model"],
                    validator=request["validator"], workflow=request["workflow"],
                    execution_mode=request.get("execution_mode", "linear"),
                    goal_file=request["prompt_file"],
                    ai_validator_prompt_file=request.get("ai_validator_prompt_file", ""),
                    readonly_safety=request.get("readonly_safety", "restore"),
                )
            except Exception:
                folder = Path(request["request_dir"])
                shutil.rmtree(folder, ignore_errors=True)
                raise

    def launch(
        self,
        project: Path,
        goal: str | None,
        *,
        mode: str,
        backend: str = "",
        model: str = "",
        validator: str = "",
        workflow: str = "",
        execution_mode: str = "linear",
        goal_file: str = "",
        ai_validator_prompt_file: str = "",
        readonly_safety: str = "restore",
    ) -> None:
        with self._launch_lock:
            runtime = self.read_runtime(project)
            if runtime["running"]:
                raise ValueError("This project already has an active runtime")
            command = [sys.executable, str(self.repo_root / "ai_task_runner.py"), "--project-root", str(project)]
            if mode == "resume":
                command.append("--resume")
            else:
                if goal_file:
                    command += ["--goal-file", goal_file]
                elif goal:
                    command += ["--goal", goal]
                else:
                    raise ValueError("Goal is required")
                if mode == "rerun":
                    command.append("--force-new")
            command += ["--execution-mode", str(execution_mode or "linear")]
            if backend:
                command += ["--backend", backend]
            command += self._model_cli_args(model)
            if validator:
                command += ["--validator", validator]
            if workflow:
                command += ["--workflow", workflow]
            if ai_validator_prompt_file:
                command += ["--ai-validator-prompt-file", ai_validator_prompt_file]
            if readonly_safety == "observe":
                command += ["--readonly-safety", "observe"]
            token, reservation = self._reserve_launch(project, mode)
            try:
                kwargs = _background_process_kwargs()
                kwargs["cwd"] = str(self.repo_root)
                process = subprocess.Popen(command, **kwargs)
            except Exception:
                self._clear_launch_reservation(project, token)
                raise
            reservation["child_pid"] = self._marker_pid(getattr(process, "pid", 0))
            try:
                self._update_launch_reservation(project, token, reservation)
            except (OSError, ValueError):
                # The pre-launch owner reservation is already durable. Do not report
                # a failed launch after Popen succeeded; Runner will shortly publish
                # runner-process.json and take over runtime identity.
                pass

    def _create_run_request(
        self,
        project: Path,
        message: str,
        *,
        backend: str = "",
        model: str = "",
        validator: str = "",
        workflow: str = "",
        ai_validator_prompt_file: str = "",
        readonly_safety: str = "restore",
        request_mode: str = "workflow",
    ) -> dict:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Message is empty")
        workflow_path = Path(workflow).expanduser().resolve() if workflow else None
        if workflow_path is not None:
            allowed = {path_key(path) for path in self._known_workflow_paths(project)}
            if path_key(workflow_path) not in allowed:
                raise ValueError("Selected Workflow is outside the allowed System / Custom / Project workflow roots")
            if not workflow_path.is_file():
                raise ValueError(f"Workflow not found: {workflow_path}")
        requirements = self._workflow_requirements(workflow_path) if workflow_path else {"requires_python_validator": False, "has_ai_validator": False}
        model_value = self._normalize_model(model)
        readonly_safety_value = str(readonly_safety or "restore").strip() or "restore"
        if readonly_safety_value not in {"restore", "observe"}:
            raise ValueError("readonly_safety must be restore or observe")
        validator_value = str(validator or "").strip()
        if requirements["requires_python_validator"]:
            if not validator_value:
                raise ValueError("This Workflow uses Python validation. Select validation.py before Run.")
            validator_path = Path(validator_value).expanduser()
            if not validator_path.is_absolute():
                validator_path = (project / validator_path).resolve()
            else:
                validator_path = validator_path.resolve()
            if not validator_path.is_file():
                raise ValueError(f"Python validator not found: {validator_value}")
            validator_value = str(validator_path)
        else:
            # Hidden/stale UI values must never change a workflow that does not request file validation.
            validator_value = ""

        ai_prompt_source = str(ai_validator_prompt_file or "").strip()
        ai_prompt_path = None
        if requirements["has_ai_validator"] and ai_prompt_source:
            ai_prompt_path = Path(ai_prompt_source).expanduser()
            if not ai_prompt_path.is_absolute():
                ai_prompt_path = (project / ai_prompt_path).resolve()
            else:
                ai_prompt_path = ai_prompt_path.resolve()
            if not ai_prompt_path.is_file():
                raise ValueError(f"AI validator prompt not found: {ai_prompt_source}")
        elif not requirements["has_ai_validator"]:
            ai_prompt_source = ""

        request_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        request_dir = project / UI_STATE_DIR / "requests" / request_id
        request_dir.mkdir(parents=True, exist_ok=False)
        prompt_file = request_dir / "prompt.md"
        prompt_file.write_text(text.rstrip() + "\n", encoding="utf-8")
        ai_prompt_snapshot = ""
        if ai_prompt_path is not None:
            resources_dir = request_dir / "resources"
            resources_dir.mkdir(parents=True, exist_ok=True)
            ai_prompt_snapshot_path = resources_dir / "ai_validation.md"
            ai_prompt_snapshot_path.write_text(ai_prompt_path.read_text(encoding="utf-8-sig"), encoding="utf-8")
            ai_prompt_snapshot = str(ai_prompt_snapshot_path)
        manifest = {
            "schema_version": 1,
            "request_id": request_id,
            "created_at": time.time(),
            "project": str(project),
            "backend": backend or "",
            "model": model_value,
            "mode": request_mode,
            "execution_mode": "linear",
            "workflow": str(workflow_path) if workflow_path else "",
            "prompt_file": str(prompt_file),
            "validator": validator_value,
            "ai_validator_prompt_file": ai_prompt_snapshot,
            "readonly_safety": readonly_safety_value,
            "requires_python_validator": bool(requirements["requires_python_validator"]),
            "has_ai_validator": bool(requirements["has_ai_validator"]),
        }
        tmp = request_dir / "request.json.tmp"
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, request_dir / "request.json")
        return {**manifest, "request_dir": str(request_dir)}

    def stop(self, project: Path) -> None:
        runtime = self.runtime_dir(project)
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "stop.request").write_text("stop\n", encoding="utf-8")

    def reset_runtime(self, project: Path) -> dict:
        """Clear Runner-owned state for a new task while preserving UI history."""
        with self._runtime_lock:
            if self.read_runtime(project).get("running"):
                raise ValueError("Stop the active runtime before Reset")
            removed = self._reset_runtime_locked(project)
            return {"ok": True, "removed": removed}

    def _reset_runtime_locked(self, project: Path) -> list[str]:
        runtime = self.runtime_dir(project)
        if not runtime.exists():
            return []
        removed: list[str] = []
        for child in list(runtime.iterdir()):
            if child.name == "ui":
                continue
            try:
                if child.is_symlink() or child.is_file():
                    child.unlink()
                else:
                    shutil.rmtree(child)
                removed.append(child.name)
            except OSError as exc:
                raise ValueError(f"Cannot reset runtime artifact {child.name}: {exc}") from exc
        return sorted(removed)

    def _custom_asset_root(self, kind: str) -> Path:
        kind = str(kind or "").strip().lower()
        if kind == "workflow":
            return (self.repo_root / "runner" / "workflow" / "custom").resolve()
        if kind == "prompt":
            return (self.repo_root / "runner" / "prompts" / "custom").resolve()
        raise ValueError("Custom asset kind must be workflow or prompt")

    @staticmethod
    def _is_technical_folder_part(part: str) -> bool:
        value = str(part or "").strip().lower()
        return (
            not value
            or value.startswith(".")
            or value in {"__pycache__", "__pypackages__", "node_modules"}
            or value.endswith(".egg-info")
        )

    @staticmethod
    def _normalize_custom_folder(folder: str) -> str:
        raw = str(folder or "").strip().replace("\\", "/")
        if not raw or raw in {".", "/"}:
            return ""
        if raw.startswith("/") or re.match(r"^[A-Za-z]:", raw):
            raise ValueError("Custom folder must be relative to the Custom root")
        parts = [part.strip() for part in raw.split("/") if part.strip()]
        if not parts or any(part in {".", ".."} for part in parts):
            raise ValueError("Custom folder cannot contain . or ..")
        if any(UIState._is_technical_folder_part(part) for part in parts):
            raise ValueError("Custom folder contains a reserved technical directory")
        if any(not re.fullmatch(r"[A-Za-z0-9_. -]+", part) for part in parts):
            raise ValueError("Custom folder contains unsupported characters")
        return "/".join(parts)

    def studio_custom_folders(self, kind: str) -> list[str]:
        root = self._custom_asset_root(kind)
        root.mkdir(parents=True, exist_ok=True)
        folders = [""]
        for path in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: str(p).lower()):
            rel = path.relative_to(root).as_posix()
            if rel and not any(self._is_technical_folder_part(part) for part in Path(rel).parts):
                folders.append(rel)
        return folders

    def studio_custom_folder_create(self, kind: str, folder: str) -> dict:
        with self._edit_lock:
            self._require_editable()
            rel = self._normalize_custom_folder(folder)
            if not rel:
                raise ValueError("Folder name is required")
            root = self._custom_asset_root(kind)
            target = (root / Path(rel)).resolve()
            if not self._is_within(target, root):
                raise ValueError("Custom folder is outside the Custom root")
            target.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "folder": rel, "folders": self.studio_custom_folders(kind)}


    def _workflow_visibility(self) -> dict[str, bool]:
        try:
            raw = json.loads(self.workflow_visibility_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {os.path.normcase(os.path.abspath(str(path))): bool(hidden) for path, hidden in raw.items() if str(path).strip()}

    def workflow_hidden(self, path: Path) -> bool:
        return bool(self._workflow_visibility().get(os.path.normcase(os.path.abspath(str(path.resolve()))), False))

    def studio_set_workflow_hidden(self, file_id: str, hidden: bool, project: Path | None = None) -> dict:
        with self._edit_lock:
            path, kind, scope = self._resolve_studio_file(file_id, project)
            if kind != "workflow":
                raise ValueError("Visibility can only be changed for Workflow files")
            values = self._workflow_visibility()
            key = os.path.normcase(os.path.abspath(str(path.resolve())))
            if hidden:
                values[key] = True
            else:
                values.pop(key, None)
            self._atomic_json(self.workflow_visibility_file, values)
            return self._studio_item(path, scope, kind)

    # ------------------------------ live stream helpers ------------------------------
    @classmethod
    def _display_stream(cls, raw: str) -> str:
        if not raw.strip():
            return ""
        visible: list[str] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                if not cls._looks_like_reasoning_line(line):
                    visible.append(line)
                continue
            cls._collect_visible(value, visible, parent_key="")
        compact: list[str] = []
        for item in visible:
            text = " ".join(str(item).split()).strip()
            if text and (not compact or compact[-1] != text):
                compact.append(text)
        return "\n".join(compact)[-12000:]

    @classmethod
    def _collect_visible(cls, value: object, out: list[str], parent_key: str) -> None:
        key = parent_key.lower().replace("-", "_")
        if cls._is_private_reasoning_key(key):
            return
        if isinstance(value, dict):
            event_type = str(value.get("type", "")).lower().replace("-", "_")
            if cls._is_private_reasoning_key(event_type):
                return
            preferred = ("content", "text", "output", "command", "name", "tool")
            used = False
            for field in preferred:
                if field in value and not cls._is_private_reasoning_key(field):
                    cls._collect_visible(value[field], out, field)
                    used = True
            if not used:
                for field, child in value.items():
                    if field in {"id", "session_id", "timestamp", "usage", "metadata"}:
                        continue
                    cls._collect_visible(child, out, str(field))
            return
        if isinstance(value, list):
            for child in value:
                cls._collect_visible(child, out, parent_key)
            return
        if isinstance(value, str) and value.strip():
            out.append(value)

    @staticmethod
    def _is_private_reasoning_key(text: str) -> bool:
        normalized = text.lower().replace("-", "_").strip()
        return normalized in {"reasoning", "thinking", "analysis", "chain_of_thought"} or normalized.startswith(("reasoning_", "thinking_", "analysis_", "chain_of_thought_"))

    @staticmethod
    def _looks_like_reasoning_line(text: str) -> bool:
        lowered = text.lstrip().lower()
        return lowered.startswith(("reasoning:", "thinking:", "analysis:", "chain-of-thought:", "chain_of_thought:"))

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    @staticmethod
    def _read_text(path: Path, limit: int) -> str:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return text[-limit:]

    @staticmethod
    def _process_snapshot() -> set[int] | None:
        """Return one Windows PID snapshot for a whole UI polling cycle."""
        if os.name != "nt":
            return None
        try:
            result = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode != 0:
                return None
            pids: set[int] = set()
            for row in csv.reader(result.stdout.splitlines()):
                if len(row) < 2:
                    continue
                try:
                    pids.add(int(row[1]))
                except (TypeError, ValueError):
                    continue
            return pids
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    @staticmethod
    def _pid_alive(pid: int, alive_pids: set[int] | None = None) -> bool:
        if pid <= 0:
            return False
        if alive_pids is not None:
            return pid in alive_pids
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                output = result.stdout.strip().lower()
                return bool(output and "no tasks are running" not in output and str(pid) in output)
            except (OSError, subprocess.SubprocessError, ValueError):
                # A failed Windows process probe is "unknown", not proof that
                # the process died. Fail safe for one polling cycle to avoid
                # RUN -> STOP/INT -> RUN sidebar flicker on transient tasklist
                # failures; a later successful snapshot will correct status.
                return True
        try:
            os.kill(pid, 0)
            return True
        except PermissionError:
            return True
        except OSError:
            return False


class Handler(SimpleHTTPRequestHandler):
    state: UIState

    def translate_path(self, path: str) -> str:
        clean = urlparse(path).path.lstrip("/") or "index.html"
        root = self.state.static_root.resolve()
        candidate = (root / clean).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return str(root / "__invalid_static_path__")
        return str(candidate)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/projects":
                return self._json(self.state.projects_payload())
            if parsed.path == "/api/backends":
                return self._json(self.state.backend_catalog())
            if parsed.path == "/api/workflow/catalog":
                return self._json(self.state.workflow_catalog())
            if parsed.path == "/api/execution-modes":
                return self._json(self.state.execution_mode_catalog())
            if parsed.path == "/api/environment/check":
                return self._json(self.state.environment_check())
            if parsed.path == "/api/studio/files":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_files(project))
            if parsed.path == "/api/studio/file":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_read(query.get("id", [""])[0], project))
            if parsed.path == "/api/studio/guard":
                return self._json(self.state.edit_guard())
            if parsed.path == "/api/studio/prompt-tags":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_prompt_tags(query.get("id", [""])[0], project))
            if parsed.path == "/api/studio/visual":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_visual(query.get("id", [""])[0], project))
            if parsed.path == "/api/studio/export":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_export(query.get("id", [""])[0], project))
            if parsed.path == "/api/studio/graph":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                return self._json(self.state.studio_graph(query.get("id", [""])[0], project))
            if parsed.path == "/api/studio/draft":
                return self._json(self.state.studio_draft_info())
            if parsed.path == "/api/studio/generate/active":
                return self._json(self.state.studio_generate_active())
            if parsed.path == "/api/studio/generate/status":
                query = parse_qs(parsed.query)
                return self._json(self.state.studio_generate_status(query.get("job_id", [""])[0]))
            if parsed.path.startswith("/api/project/"):
                return self._project_get(parsed.path)
            return super().do_GET()
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"UI request failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/projects/add":
                return self._json(self.state.add_project(str(body.get("path", ""))))
            if parsed.path == "/api/projects/remove":
                self.state.remove_project(str(body.get("path", "")))
                return self._json({"ok": True})
            if parsed.path == "/api/projects/rename":
                return self._json(self.state.rename_project(str(body.get("path", "")), str(body.get("name", ""))))
            if parsed.path == "/api/projects/pick":
                return self._pick_folder()
            if parsed.path == "/api/files/pick":
                return self._pick_file(str(body.get("kind", "file")))
            if parsed.path == "/api/project/message":
                project = self._project(body)
                text = str(body.get("message", "")).strip()
                if not text:
                    raise ValueError("Message is empty")
                self.state.launch_message(
                    project,
                    text,
                    backend=str(body.get("backend", "")),
                    model=str(body.get("model", "")),
                    validator=str(body.get("validator", "")),
                    workflow=str(body.get("workflow", "")),
                    ai_validator_prompt_file=str(body.get("ai_validator_prompt_file", "")),
                    readonly_safety=str(body.get("readonly_safety", "restore")),
                )
                return self._json({"ok": True})
            if parsed.path == "/api/project/history/clear":
                return self._json(self.state.clear_chat_history(
                    self._project(body),
                    reset_stopped=bool(body.get("reset_stopped")),
                ))
            if parsed.path == "/api/project/stop":
                self.state.stop(self._project(body))
                return self._json({"ok": True})
            if parsed.path == "/api/project/resume":
                project = self._project(body)
                request = self.state._latest_run_request(project)
                self.state.launch(
                    project,
                    None,
                    mode="resume",
                    backend=str(request.get("backend") or ""),
                    model=str(request.get("model") or ""),
                    validator=str(request.get("validator") or ""),
                    workflow=str(request.get("workflow") or ""),
                    execution_mode=str(request.get("execution_mode") or "linear"),
                    readonly_safety=str(request.get("readonly_safety") or "restore"),
                )
                return self._json({"ok": True})
            if parsed.path == "/api/project/reset":
                return self._json(self.state.reset_runtime(self._project(body)))
            if parsed.path == "/api/project/rerun":
                self.state.rerun_last(
                    self._project(body),
                    backend=str(body.get("backend", "")),
                    model=str(body.get("model", "")),
                    validator=str(body.get("validator", "")),
                    workflow=str(body.get("workflow", "")),
                    ai_validator_prompt_file=str(body.get("ai_validator_prompt_file", "")),
                    readonly_safety=str(body.get("readonly_safety", "restore")),
                )
                return self._json({"ok": True})
            if parsed.path == "/api/studio/generate":
                return self._json(self.state.studio_generate_workflow(str(body.get("request", "")), str(body.get("backend", "")), str(body.get("folder", "")), str(body.get("filename", ""))))
            if parsed.path == "/api/studio/generate/validate":
                return self._json(self.state.studio_generate_validate(str(body.get("job_id", "")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_generate_save(project, str(body.get("job_id", "")), str(body.get("folder", "")), str(body.get("filename", body.get("name", ""))), str(body.get("destination", "custom")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/cancel":
                return self._json(self.state.studio_generate_cancel(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/generate/discard":
                return self._json(self.state.studio_generate_discard(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/custom-folder/create":
                return self._json(self.state.studio_custom_folder_create(str(body.get("kind", "")), str(body.get("folder", ""))))
            if parsed.path == "/api/studio/workflow/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_workflow_create(str(body.get("name", "")), str(body.get("destination", "custom")), project, str(body.get("folder", ""))))
            if parsed.path == "/api/studio/prompt/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_prompt_create(str(body.get("name", "")), str(body.get("destination", "custom")), project, str(body.get("folder", ""))))
            if parsed.path == "/api/studio/delete":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_delete(str(body.get("id", "")), project))
            if parsed.path == "/api/studio/rename":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_rename(str(body.get("id", "")), str(body.get("name", "")), project))
            if parsed.path == "/api/studio/duplicate":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_duplicate(str(body.get("id", "")), str(body.get("name", "")), project, str(body.get("folder", ""))))
            if parsed.path == "/api/studio/import/inspect":
                return self._json(self.state.studio_folder_inspect(str(body.get("content", ""))))
            if parsed.path == "/api/studio/import":
                if str(body.get("kind", "")).strip().lower() == "workflow_folder":
                    return self._json(self.state.studio_folder_import(str(body.get("content", ""))))
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_import(str(body.get("kind", "")), str(body.get("name", "")), str(body.get("content", "")), str(body.get("destination", "custom")), project, str(body.get("folder", ""))))
            if parsed.path == "/api/studio/prompt/check":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_prompt_check(str(body.get("id", "")), str(body.get("content", "")), project))
            if parsed.path == "/api/studio/visibility":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_set_workflow_hidden(str(body.get("id", "")), bool(body.get("hidden", False)), project))
            if parsed.path == "/api/studio/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_save(str(body.get("id", "")), str(body.get("content", "")), str(body.get("hash", "")), project))
            if parsed.path == "/api/studio/validate":
                project = self._optional_project(str(body.get("project", "")))
                content = str(body.get("content", "")) if "content" in body else None
                flow = body.get("flow") if "flow" in body else None
                return self._json(self.state.studio_validate(str(body.get("id", "")), project, content=content, flow=flow))
            if parsed.path == "/api/studio/visual/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_visual_save(str(body.get("id", "")), body.get("flow", []), str(body.get("hash", "")), project))
            if parsed.path == "/api/studio/stage/validate":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_save(
                    str(body.get("id", "")), str(body.get("stage", "")), body.get("fields", {}), str(body.get("hash", "")), project,
                    flow_index=body.get("flow_index"), scope=str(body.get("scope", "")), flow_fields=body.get("flow_fields", {}), validate_only=True,
                ))
            if parsed.path == "/api/studio/stage/save":
                project = self._optional_project(str(body.get("project", "")))
                flow_index = body.get("flow_index")
                flow_index = int(flow_index) if flow_index is not None else None
                return self._json(self.state.studio_stage_save(str(body.get("id", "")), str(body.get("stage", "")), body.get("fields", {}), str(body.get("hash", "")), project, flow_index=flow_index, scope=str(body.get("scope", "")), flow_fields=body.get("flow_fields", {})))
            if parsed.path == "/api/studio/stage/add":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_add(str(body.get("id", "")), str(body.get("stage", "")), str(body.get("type", "base")), str(body.get("hash", "")), project, status=str(body.get("status", "")), prompt=str(body.get("prompt", "")), command=str(body.get("command", "")), add_to_flow=bool(body.get("add_to_flow", True))))
            if parsed.path == "/api/studio/stage/delete":
                project = self._optional_project(str(body.get("project", "")))
                flow_index = body.get("flow_index")
                flow_index = int(flow_index) if flow_index is not None else None
                return self._json(self.state.studio_stage_delete(str(body.get("id", "")), str(body.get("stage", "")), str(body.get("hash", "")), project, flow_index=flow_index))
            if parsed.path == "/api/studio/check":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_check(str(body.get("id", "")), str(body.get("content", "")), project))
            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"UI request failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _project_get(self, path: str) -> None:
        query = parse_qs(urlparse(self.path).query)
        project = self._project({"project": query.get("project", [""])[0]})
        if path == "/api/project/runtime":
            return self._json(self.state.read_runtime(project))
        if path == "/api/project/messages":
            return self._json({"messages": self.state.messages(project)})
        self.send_error(HTTPStatus.NOT_FOUND)

    def _pick_folder(self) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            path = filedialog.askdirectory(title="Open project folder")
            root.destroy()
        except Exception as exc:
            raise ValueError(f"Folder picker unavailable: {exc}") from exc
        if not path:
            return self._json({"cancelled": True})
        return self._json({"cancelled": False, "path": str(Path(path).expanduser().resolve())})

    def _pick_file(self, kind: str = "file") -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if kind == "python":
                filetypes = [("Python validation", "*.py"), ("All files", "*.*")]
                title = "Choose Python validation"
            elif kind == "markdown":
                filetypes = [("Markdown prompt", "*.md"), ("Text prompt", "*.txt"), ("All files", "*.*")]
                title = "Choose AI validation prompt"
            else:
                filetypes = [("All files", "*.*")]
                title = "Choose file"
            path = filedialog.askopenfilename(title=title, filetypes=filetypes)
            root.destroy()
        except Exception as exc:
            raise ValueError(f"File picker unavailable: {exc}") from exc
        if not path:
            return self._json({"cancelled": True})
        return self._json({"cancelled": False, "path": str(Path(path).expanduser().resolve())})

    def _project(self, body: dict) -> Path:
        path = str(body.get("project", "")).strip()
        if not path:
            raise ValueError("Project is required")
        project = Path(path).expanduser().resolve()
        if not project.is_dir():
            raise ValueError("Project folder does not exist")
        return project

    def _optional_project(self, path: str) -> Path | None:
        return self._project({"project": path}) if path.strip() else None

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def _json(self, data: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            # Browsers routinely cancel polling/fetch requests during refresh,
            # navigation, or page close. The client is already gone, so there
            # is no error response left to send and no server fault to report.
            return

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        return


class UIServer(ThreadingHTTPServer):
    def __init__(self, repo_root: Path, host: str, port: int, *, allow_remote: bool = False) -> None:
        if not is_loopback_host(host) and not allow_remote:
            raise ValueError("Refusing non-loopback UI bind without explicit allow_remote=True")
        state = UIState(repo_root)
        handler = type("BoundHandler", (Handler,), {"state": state})
        super().__init__((host, port), handler)
        self.port = self.server_address[1]
