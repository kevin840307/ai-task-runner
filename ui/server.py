from __future__ import annotations

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

UI_STATE_DIR = ".ai-task-runner/ui"
MESSAGES_FILE = "messages.jsonl"
CHAT_STATE_FILE = "chat-state.json"
RUNTIME_DIR = ".ai-task-runner"
EDITABLE_SUFFIXES = {".yaml", ".yml", ".md"}
SYSTEM_SCOPES = {"system"}


def _background_process_kwargs() -> dict:
    """Launch long-running UI child processes without opening a console window."""
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        flags = (
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
        if flags:
            kwargs["creationflags"] = flags
        try:
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
            startup.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
            kwargs["startupinfo"] = startup
        except AttributeError:
            pass
    else:
        kwargs["start_new_session"] = True
    return kwargs


class _IndentedSafeDumper(yaml.SafeDumper):
    def increase_indent(self, flow=False, indentless=False):  # noqa: ANN001
        return super().increase_indent(flow, False)


class UIState:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root.resolve()
        self.ui_root = self.repo_root / "ui"
        self.static_root = self.ui_root / "static"
        self.projects_file = self.ui_root / "data" / "projects.json"
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        self._chat_lock = threading.RLock()
        self._projects_lock = threading.RLock()
        self._lifecycle_lock = threading.RLock()
        self._edit_lock = self._lifecycle_lock
        self._launch_lock = self._lifecycle_lock
        if not self.projects_file.exists():
            self._write_projects([])

    # ------------------------------ projects/runtime/chat ------------------------------
    def projects(self) -> list[dict]:
        try:
            rows = json.loads(self.projects_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            rows = []
        result: list[dict] = []
        seen: set[str] = set()
        for item in rows if isinstance(rows, list) else []:
            path = str(item.get("path", "")).strip()
            if not path:
                continue
            key = os.path.normcase(os.path.abspath(path))
            if key in seen:
                continue
            seen.add(key)
            project_path = Path(path)
            result.append({
                "name": item.get("name") or project_path.name or path,
                "path": path,
                "exists": project_path.is_dir(),
                "runtime_status": self._project_runtime_status(project_path),
            })
        return result

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

    def add_project(self, path: str) -> dict:
        with self._projects_lock:
            resolved = Path(path).expanduser().resolve()
            if not resolved.is_dir():
                raise ValueError("Project folder does not exist")
            items = [p for p in self.projects() if os.path.normcase(p["path"]) != os.path.normcase(str(resolved))]
            project = {"name": resolved.name or str(resolved), "path": str(resolved)}
            items.insert(0, project)
            self._write_projects(items)
            return project

    def remove_project(self, path: str) -> None:
        with self._projects_lock:
            key = os.path.normcase(os.path.abspath(path))
            target = next((p for p in self.projects() if os.path.normcase(os.path.abspath(p["path"])) == key), None)
            if target and Path(target["path"]).is_dir() and self.read_runtime(Path(target["path"])).get("running"):
                raise ValueError("Stop the active runtime before removing this project")
            self._write_projects([p for p in self.projects() if os.path.normcase(os.path.abspath(p["path"])) != key])

    def _write_projects(self, items: list[dict]) -> None:
        # Persist identity only; existence/runtime status are live filesystem data.
        rows = [
            {"name": str(item.get("name") or Path(str(item.get("path") or "")).name), "path": str(item.get("path") or "")}
            for item in items
            if str(item.get("path") or "").strip()
        ]
        tmp = self.projects_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.projects_file)

    def runtime_dir(self, project: Path) -> Path:
        return project / RUNTIME_DIR

    @staticmethod
    def _task_mark(state: dict, index: int, task: dict) -> str:
        if task.get("status") == "completed":
            return "x"
        if index == int(state.get("current", 0) or 0) and not state.get("completed"):
            return ">"
        return " "

    def _project_runtime_status(self, project: Path) -> str:
        if not project.is_dir():
            return "missing"
        runtime = self.runtime_dir(project)
        state = self._read_json(runtime / "state.json") or {}
        marker = self._read_json(runtime / "runner-process.json") or {}
        pid = marker.get("supervisor_pid")
        try:
            pid_value = int(pid or 0)
        except (TypeError, ValueError):
            pid_value = 0
        if pid_value and self._pid_alive(pid_value):
            return "running"
        if bool(state.get("completed")):
            return "completed"
        if marker and state:
            return "interrupted"
        if state:
            return "stopped"
        return "idle"

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

    def read_runtime(self, project: Path) -> dict:
        runtime = self.runtime_dir(project)
        state = self._read_json(runtime / "state.json") or {}
        marker = self._read_json(runtime / "runner-process.json") or {}
        stream = self._display_stream(self._read_text(runtime / "stream.log", limit=12000))
        pid = marker.get("supervisor_pid")
        try:
            pid_value = int(pid or 0)
        except (TypeError, ValueError):
            pid_value = 0
        running = bool(pid_value and self._pid_alive(pid_value))
        stale = bool(marker and not running)
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        console, console_snapshot_exists = self._console_view(runtime, state)
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
        if not running and bool(state.get("completed")):
            self.sync_completion(project)
        return {
            "running": running,
            "run_id": state.get("run_id") or "",
            "stale": stale,
            "pid": pid,
            "worker_pid": marker.get("worker_pid"),
            "stage": state.get("stage") or "",
            "task": current_task,
            "current": current + 1 if tasks else 0,
            "total": len(tasks),
            "completed": bool(state.get("completed")),
            "has_state": bool(state),
            "resumable": bool(state and not state.get("completed")),
            "resettable": resettable,
            "last_error": state.get("last_error") or "",
            "stream": stream,
            "cli_lines": [str(line) for line in console.get("lines", [])],
            "cli_tasks": console.get("tasks", []) if isinstance(console.get("tasks"), list) else [],
            "cli_status": str(console.get("status") or ""),
            "cli_detail": str(console.get("detail") or ""),
            "completed_count": int(console.get("completed_count") or 0),
            "console_snapshot_exists": console_snapshot_exists,
            "updated_at": state.get("last_activity_at") or marker.get("started_at") or 0,
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

    def launch_message(self, project: Path, message: str, *, backend: str = "", validator: str = "", workflow: str = "") -> None:
        """Start one Workflow task from an immutable UI request snapshot.

        A completed prior run is reset automatically. An interrupted/stopped run
        must be explicitly Continued or Reset so a new task cannot silently
        discard recoverable state.
        """
        with self._chat_lock, self._lifecycle_lock:
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
                validator=validator,
                workflow=workflow,
                request_mode="workflow",
            )
            try:
                self.launch(
                    project,
                    None,
                    mode="run",
                    backend=backend,
                    validator=request["validator"],
                    workflow=request["workflow"],
                    goal_file=request["prompt_file"],
                )
            except Exception:
                # A failed launch must not leave a fake user message or an orphan request snapshot.
                folder = Path(request["request_dir"])
                for child in folder.iterdir() if folder.is_dir() else ():
                    try:
                        child.unlink()
                    except OSError:
                        pass
                try:
                    folder.rmdir()
                except OSError:
                    pass
                raise
            self.append_message(project, "user", message)

    def launch(
        self,
        project: Path,
        goal: str | None,
        *,
        mode: str,
        backend: str = "",
        validator: str = "",
        workflow: str = "",
        goal_file: str = "",
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
            if backend:
                command += ["--backend", backend]
            if validator:
                command += ["--validator", validator]
            if workflow:
                command += ["--workflow", workflow]
            kwargs = _background_process_kwargs()
            kwargs["cwd"] = str(self.repo_root)
            subprocess.Popen(command, **kwargs)

    def _create_run_request(
        self,
        project: Path,
        message: str,
        *,
        backend: str = "",
        validator: str = "",
        workflow: str = "",
        request_mode: str = "workflow",
    ) -> dict:
        text = str(message or "").strip()
        if not text:
            raise ValueError("Message is empty")
        workflow_path = Path(workflow).expanduser().resolve() if workflow else None
        if workflow_path is not None:
            allowed = {os.path.normcase(str(path)) for path in self._known_workflow_paths(project)}
            if os.path.normcase(str(workflow_path)) not in allowed:
                raise ValueError("Selected Workflow is outside the allowed System / Custom / Project workflow roots")
            if not workflow_path.is_file():
                raise ValueError(f"Workflow not found: {workflow_path}")
        requirements = self._workflow_requirements(workflow_path) if workflow_path else {"requires_python_validator": False, "has_ai_validator": False}
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

        request_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        request_dir = project / UI_STATE_DIR / "requests" / request_id
        request_dir.mkdir(parents=True, exist_ok=False)
        prompt_file = request_dir / "prompt.md"
        prompt_file.write_text(text.rstrip() + "\n", encoding="utf-8")
        manifest = {
            "schema_version": 1,
            "request_id": request_id,
            "created_at": time.time(),
            "project": str(project),
            "backend": backend or "",
            "mode": request_mode,
            "workflow": str(workflow_path) if workflow_path else "",
            "prompt_file": str(prompt_file),
            "validator": validator_value,
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
        with self._lifecycle_lock:
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

    # ------------------------------ workflow studio ------------------------------
    def studio_files(self, project: Path | None = None) -> dict:
        workflows: list[dict] = []
        prompts: list[dict] = []
        roots: list[tuple[str, Path]] = [
            ("system", self.repo_root / "runner" / "workflow" / "system"),
            ("custom", self.repo_root / "runner" / "workflow" / "custom"),
        ]
        prompt_roots: list[tuple[str, Path]] = [
            ("system", self.repo_root / "runner" / "prompts" / "stages"),
            ("system", self.repo_root / "runner" / "prompts" / "system"),
            ("custom", self.repo_root / "runner" / "prompts" / "custom"),
        ]
        if project is not None:
            roots.append(("project", project))
            prompt_roots.append(("project", project / "prompts"))

        seen: set[str] = set()
        for scope, root in roots:
            if not root.is_dir():
                continue
            candidates = root.rglob("*.yaml") if scope != "project" else root.glob("*.yaml")
            for path in candidates:
                if scope == "project" and not (path.name == ".ai-task-runner.yaml" or "workflow" in path.name.lower()):
                    continue
                item = self._studio_item(path, scope, "workflow")
                if item["id"] not in seen:
                    seen.add(item["id"])
                    workflows.append(item)
            for path in (root.rglob("*.yml") if scope != "project" else root.glob("*.yml")):
                if scope == "project" and "workflow" not in path.name.lower():
                    continue
                item = self._studio_item(path, scope, "workflow")
                if item["id"] not in seen:
                    seen.add(item["id"])
                    workflows.append(item)

        seen.clear()
        for scope, root in prompt_roots:
            if not root.is_dir():
                continue
            for path in root.rglob("*.md"):
                item = self._studio_item(path, scope, "prompt")
                if item["id"] not in seen:
                    seen.add(item["id"])
                    prompts.append(item)

        order = {"system": 0, "custom": 1, "project": 2}
        return {
            "workflows": sorted(workflows, key=lambda x: (order.get(x["scope"], 9), x["name"].lower())),
            "prompts": sorted(prompts, key=lambda x: (order.get(x["scope"], 9), x["name"].lower())),
            "guard": self.edit_guard(),
        }

    @staticmethod
    def _ast_dict_paths(node, prefix: str = "") -> list[str]:
        result: list[str] = []
        if not isinstance(node, ast.Dict):
            return result
        for key_node, value_node in zip(node.keys, node.values):
            if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                continue
            path = f"{prefix}.{key_node.value}" if prefix else key_node.value
            result.append(path)
            result.extend(UIState._ast_dict_paths(value_node, path))
        return result

    @staticmethod
    def _ast_function_return(tree: ast.AST, name: str):
        for node in getattr(tree, "body", []):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                for child in ast.walk(node):
                    if isinstance(child, ast.Return):
                        return child.value
        return None

    def _stage_prompt_tag_paths(self) -> list[str]:
        """Read the stable Stage prompt context contract without importing Runner."""
        context_file = self.repo_root / "runner" / "prompts" / "context.py"
        try:
            tree = ast.parse(context_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise ValueError(f"Cannot read prompt context contract: {exc}") from exc
        paths = self._ast_dict_paths(self._ast_function_return(tree, "build_stage_prompt_context"))
        task_fields = self._ast_dict_paths(self._ast_function_return(tree, "_task_data"))
        paths.extend(f"task.{key}" for key in task_fields if "." not in key)
        return paths

    def _loader_prompt_contracts(self) -> dict[str, list[str]]:
        """Discover dedicated System Prompt variables from literal render_prompt calls.

        `system/rules.md` and `system/structured_output_retry.md` are not Stage
        prompts. They are rendered by prompt loader helpers with their own values.
        Parse that contract statically so Workflow Studio does not import Runner Core
        and does not show false Prompt warnings when those files are inspected.
        """
        loader_file = self.repo_root / "runner" / "prompts" / "loader.py"
        prompt_root = (self.repo_root / "runner" / "prompts").resolve()
        try:
            tree = ast.parse(loader_file.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            return {}
        contracts: dict[str, list[str]] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "render_prompt":
                continue
            if len(node.args) < 2 or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            paths = self._ast_dict_paths(node.args[1])
            if not paths:
                continue
            path = (prompt_root / node.args[0].value).resolve()
            contracts[os.path.normcase(str(path))] = paths
        return contracts

    def _prompt_tag_paths(self, prompt_path: Path | None = None) -> tuple[list[str], str]:
        if prompt_path is not None:
            dedicated = self._loader_prompt_contracts().get(os.path.normcase(str(prompt_path.resolve())))
            if dedicated:
                return dedicated, "loader"
        return self._stage_prompt_tag_paths(), "stage"

    def studio_prompt_tags(self, file_id: str = "", project: Path | None = None) -> dict:
        """Return valid insertable variables for the selected Prompt contract."""
        prompt_path: Path | None = None
        if str(file_id or "").strip():
            path, kind, _scope = self._resolve_studio_file(file_id, project)
            if kind != "prompt":
                raise ValueError("Prompt tags are available only for Prompt files")
            prompt_path = path
        paths, contract = self._prompt_tag_paths(prompt_path)
        seen: set[str] = set()
        tags = []
        descriptions = {
            "goal": "Current user goal / requirement.",
            "stage": "Current Stage key.",
            "project.root": "Current project root path.",
            "task.title": "Current task title when running per-task flow.",
            "task.description": "Current task description.",
            "task.acceptance_criteria": "Current task acceptance criteria.",
            "previous.output": "Previous Stage output, bounded by the runtime.",
            "previous.status": "Previous Stage result status.",
            "previous.data": "Structured data returned by the previous Stage.",
            "validation.feedback": "Latest validator feedback.",
            "workflow.validator_feedback": "Current workflow validator feedback.",
            "rules": "Runner AI rules for the project.",
            "always_instructions": "User-enforced always instructions.",
            "plugin_rules": "Plugin-provided Runner rules used by system/rules.md.",
            "error": "Structured-output parser feedback used by the retry Prompt.",
        }
        for key in paths:
            if not key or key in seen:
                continue
            seen.add(key)
            tags.append({
                "key": key,
                "label": key.replace("_", " ").replace(".", " · ").title(),
                "description": descriptions.get(key, f"Runtime prompt context: {key}."),
            })
        source = str(prompt_path) if prompt_path is not None else str(self.repo_root / "runner" / "prompts" / "context.py")
        return {"tags": tags, "source": source, "contract": contract}

    def _check_prompt_content(self, content: str, prompt_path: Path | None = None) -> dict:
        """Validate Jinja syntax and variables against the actual Prompt contract."""
        env = Environment(autoescape=False)
        try:
            parsed = env.parse(content)
        except Exception as exc:
            line = int(getattr(exc, "lineno", 0) or 0)
            return {"ok": False, "summary": str(exc), "line": line, "unknown": [], "contract": "syntax"}
        paths, contract = self._prompt_tag_paths(prompt_path)
        variables = set(meta.find_undeclared_variables(parsed))
        allowed = {key.split(".", 1)[0] for key in paths}
        unknown = sorted(variables - allowed)
        return {
            "ok": not unknown,
            "summary": "Prompt valid" if not unknown else f"Unknown prompt variable(s): {', '.join(unknown)}",
            "unknown": unknown,
            "contract": contract,
        }

    def _validate_prompt_before_write(self, path: Path, content: str) -> dict:
        check = self._check_prompt_content(content, path)
        if not check["ok"]:
            raise ValueError("Prompt validation failed: " + check["summary"])
        return check

    def studio_prompt_check(self, file_id: str, content: str, project: Path | None = None) -> dict:
        path, kind, _scope = self._resolve_studio_file(file_id, project)
        if kind != "prompt":
            raise ValueError("Prompt check is available only for Prompt files")
        return self._check_prompt_content(content, path)

    def studio_workflow_create(self, name: str, destination: str, project: Path | None = None) -> dict:
        """Create one blank workflow without touching Runner/Core code."""
        with self._edit_lock:
            self._require_editable()
            raw = str(name or "").strip()
            if not raw:
                raise ValueError("Workflow name is required")
            if "/" in raw or "\\" in raw or raw in {".", ".."}:
                raise ValueError("Workflow name must be a file name, not a path")
            if not raw.lower().endswith((".yaml", ".yml")):
                raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
                raise ValueError("Workflow file name contains unsupported characters")
            destination = str(destination or "custom").strip().lower()
            if destination == "project":
                if project is None:
                    raise ValueError("Select a Project before creating a Project workflow")
                target = (project / raw).resolve()
                if not self._is_within(target, project.resolve()):
                    raise ValueError("Workflow path is outside the Project")
            elif destination == "custom":
                root = (self.repo_root / "runner" / "workflow" / "custom").resolve()
                root.mkdir(parents=True, exist_ok=True)
                target = (root / raw).resolve()
                if not self._is_within(target, root):
                    raise ValueError("Workflow path is outside the Custom Workflow folder")
            else:
                raise ValueError("Workflow destination must be project or custom")
            if target.exists():
                raise ValueError(f"Workflow already exists: {target.name}")
            content = "stages:\n  planning:\n    type: plan\n\nflow:\n  - planning\n"
            self._validate_workflow_before_write(target, content)
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)
            except FileExistsError as exc:
                raise ValueError(f"Workflow already exists: {target.name}") from exc
            scope = "project" if destination == "project" else "custom"
            item = self._studio_item(target, scope, "workflow")
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_read(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        content = path.read_text(encoding="utf-8")
        stat = path.stat()
        return {
            **self._studio_item(path, scope, kind),
            "content": content,
            "hash": self._hash_text(content),
            "mtime": stat.st_mtime,
            "guard": self.edit_guard(),
        }

    def studio_save(self, file_id: str, content: str, expected_hash: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            guard = self.edit_guard()
            if not guard["editable"]:
                names = ", ".join(p["name"] for p in guard["active_projects"])
                raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if path.suffix.lower() not in EDITABLE_SUFFIXES:
                raise ValueError("Unsupported file type")
            current = path.read_text(encoding="utf-8")
            current_hash = self._hash_text(current)
            if expected_hash and expected_hash != current_hash:
                raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")
            if kind == "workflow":
                self._validate_workflow_before_write(path, content)
            elif kind == "prompt":
                self._validate_prompt_before_write(path, content)
            self._atomic_write(path, content)
            return self.studio_read(file_id, project)

    def studio_visual(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            raise ValueError("Visual designer is available only for workflow YAML")
        content = path.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Workflow YAML root must be a mapping")
        stages_raw = data.get("stages") or {}
        if not isinstance(stages_raw, dict):
            stages_raw = {}
        stages = []
        for name, cfg in stages_raw.items():
            config = cfg if isinstance(cfg, dict) else {}
            stages.append({
                "name": str(name),
                **config,
                "type": str(config.get("type") or "base"),
                "status": str(config.get("status") or ""),
                "prompt": str(config.get("prompt") or ""),
                "recover": config.get("recover") if isinstance(config.get("recover"), list) else [],
            })
        flow_raw = data.get("flow") or []
        flow = []
        if isinstance(flow_raw, list):
            for item in flow_raw:
                if isinstance(item, str):
                    flow.append({"stage": item})
                elif isinstance(item, dict):
                    flow.append(dict(item))
        return {
            "id": file_id,
            "name": path.name,
            "scope": scope,
            "hash": self._hash_text(content),
            "stages": stages,
            "flow": flow,
            "guard": self.edit_guard(),
        }

    def studio_visual_save(self, file_id: str, flow: list, expected_hash: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            guard = self.edit_guard()
            if not guard["editable"]:
                names = ", ".join(p["name"] for p in guard["active_projects"])
                raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind != "workflow":
                raise ValueError("Visual designer is available only for workflow YAML")
            content = path.read_text(encoding="utf-8")
            current_hash = self._hash_text(content)
            if expected_hash and expected_hash != current_hash:
                raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")
            try:
                data = yaml.safe_load(content) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("Workflow YAML root must be a mapping")
            normalized = []
            for item in flow if isinstance(flow, list) else []:
                if isinstance(item, str) and item.strip():
                    normalized.append(item.strip())
                elif isinstance(item, dict) and str(item.get("stage", "")).strip():
                    clean = dict(item)
                    clean["stage"] = str(clean["stage"]).strip()
                    normalized.append(clean if len(clean) > 1 else clean["stage"])
            flow_text = yaml.safe_dump({"flow": normalized}, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip() + "\n"
            lines = content.splitlines(keepends=True)
            start = next((i for i, line in enumerate(lines) if line.startswith("flow:") and not line[:1].isspace()), None)
            if start is None:
                separator = "" if not content or content.endswith("\n") else "\n"
                updated = content + separator + flow_text
            else:
                end = len(lines)
                for i in range(start + 1, len(lines)):
                    line = lines[i]
                    if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
                        end = i
                        break
                updated = "".join(lines[:start]) + flow_text + "".join(lines[end:])
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return self.studio_read(file_id, project)

    def studio_stage_save(
        self,
        file_id: str,
        stage_name: str,
        fields: dict,
        expected_hash: str,
        project: Path | None = None,
        *,
        flow_index: int | None = None,
        scope: str = "",
        flow_fields: dict | None = None,
        validate_only: bool = False,
    ) -> dict:
        """Patch or validate direct Stage/Flow fields without rewriting unrelated YAML/comments."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope_name = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope_name)
            if kind != "workflow":
                raise ValueError("Stage editor is available only for workflow YAML")
            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            if not isinstance(stages, dict) or stage_name not in stages:
                raise ValueError(f"Stage not found: {stage_name}")

            allowed = {
                "type", "status", "run_state", "actor", "mode", "prompt",
                "continuation_prompt", "instructions", "detail", "produces",
                "session_key", "parser", "cwd", "result_kind", "validator", "command",
                "allow_project_read", "track_changes", "tolerate_restored_changes",
                "fresh_session_each_run", "fresh_session_on_start", "skip_on_error",
                "repair_plan", "structured_retries", "structured_fresh_retries",
                "retry", "runs", "required_passes", "min_tasks", "timeout",
                "recover", "clean_work",
            }
            if not isinstance(fields, dict):
                raise ValueError("Stage fields must be an object")
            clean: dict = {}
            for key, value in fields.items():
                if key not in allowed:
                    raise ValueError(f"Unsupported Stage field: {key}")
                clean[key] = value
            self._validate_stage_editor_fields(clean)
            updated = self._patch_stage_fields(content, stage_name, clean)
            parsed_after_fields = self._load_workflow_yaml(updated)
            final_stage = (parsed_after_fields.get("stages") or {}).get(stage_name, {}) if isinstance(parsed_after_fields, dict) else {}
            if isinstance(final_stage, dict) and final_stage.get("type") == "command" and not final_stage.get("command"):
                raise ValueError("Command Stage requires a command")

            if flow_index is not None:
                parsed = self._load_workflow_yaml(updated)
                flow = parsed.get("flow") if isinstance(parsed, dict) else None
                if not isinstance(flow, list) or not 0 <= flow_index < len(flow):
                    raise ValueError("Flow step no longer exists; reload Workflow Studio")
                current = flow[flow_index]
                current_name = current if isinstance(current, str) else str(current.get("stage", "")) if isinstance(current, dict) else ""
                if current_name != stage_name:
                    raise ValueError("Flow changed on disk; reload Workflow Studio")
                row = dict(current) if isinstance(current, dict) else {"stage": stage_name}
                row["stage"] = stage_name
                updates = dict(flow_fields or {})
                updates["scope"] = scope or None
                allowed_flow = {"scope", "label", "restart_at", "repeat", "fresh_after_same_failures", "status", "prompt"}
                unknown_flow = sorted(str(key) for key in updates if key not in allowed_flow)
                if unknown_flow:
                    raise ValueError(f"Unsupported Flow field: {', '.join(unknown_flow)}")
                self._validate_flow_editor_fields(updates, flow, flow_index, final_stage)
                for key, value in updates.items():
                    if value in (None, ""):
                        row.pop(key, None)
                    else:
                        row[key] = value
                flow[flow_index] = row if len(row) > 1 else stage_name
                updated = self._replace_flow_block(updated, flow)

            validation = self._validate_workflow_before_write(path, updated)
            if validate_only:
                return {"ok": True, "summary": "Validation passed", "output": validation.get("output", "")[-20000:]}
            self._atomic_write(path, updated)
            return {"file": self.studio_read(file_id, project), "visual": self.studio_visual(file_id, project)}

    def studio_stage_add(
        self,
        file_id: str,
        stage_name: str,
        stage_type: str,
        expected_hash: str,
        project: Path | None = None,
        *,
        status: str = "",
        prompt: str = "",
        command: str = "",
        add_to_flow: bool = True,
    ) -> dict:
        """Insert one Stage with minimal YAML churn, then optionally append it to flow."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope_name = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope_name)
            if kind != "workflow":
                raise ValueError("Stages can be added only to workflow YAML")
            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            name = str(stage_name or "").strip()
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", name):
                raise ValueError("Stage key must start with a letter/underscore and contain only letters, numbers, _ or -")
            stage_type = str(stage_type or "base").strip()
            if stage_type not in {"base", "task", "review", "ai_validator", "command", "plan"}:
                raise ValueError("Unsupported Stage type")
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            if isinstance(stages, dict) and name in stages:
                raise ValueError(f"Stage already exists: {name}")
            if stage_type == "command" and not str(command or "").strip():
                raise ValueError("Command Stage requires a command")
            if stage_type == "base" and not str(prompt or "").strip():
                raise ValueError("Base Stage requires a Prompt")
            if str(prompt or "").strip() and self._resolve_prompt_reference(path, str(prompt).strip()) is None:
                raise ValueError(f"Prompt not found: {str(prompt).strip()}")

            config: dict = {"type": stage_type}
            if status.strip(): config["status"] = status.strip()
            if prompt.strip(): config["prompt"] = prompt.strip()
            if stage_type == "command": config["command"] = command.strip()
            if stage_type == "ai_validator": config.setdefault("validator", "ai")
            updated = self._insert_stage_block(content, name, config)
            if add_to_flow:
                parsed = self._load_workflow_yaml(updated)
                flow = parsed.get("flow") if isinstance(parsed, dict) else []
                flow = list(flow) if isinstance(flow, list) else []
                flow.append(name)
                updated = self._replace_flow_block(updated, flow)
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return {"file": self.studio_read(file_id, project), "visual": self.studio_visual(file_id, project)}

    def studio_check(self, file_id: str, content: str, project: Path | None = None) -> dict:
        _path, kind, _scope = self._resolve_studio_file(file_id, project)
        if kind != "workflow":
            return {"ok": True, "summary": "Markdown"}
        try:
            value = yaml.safe_load(content)
            if value is not None and not isinstance(value, dict):
                return {"ok": False, "summary": "YAML root must be a mapping", "line": 1, "column": 1}
            return {"ok": True, "summary": "YAML valid"}
        except yaml.YAMLError as exc:
            mark = getattr(exc, "problem_mark", None)
            line = int(getattr(mark, "line", 0)) + 1 if mark is not None else 0
            column = int(getattr(mark, "column", 0)) + 1 if mark is not None else 0
            message = getattr(exc, "problem", None) or str(exc).splitlines()[0]
            return {"ok": False, "summary": str(message), "line": line, "column": column}

    @staticmethod
    def _validate_stage_editor_fields(fields: dict) -> None:
        stage_type = fields.get("type")
        if stage_type is not None and stage_type not in {"base", "task", "review", "ai_validator", "command", "plan"}:
            raise ValueError("Unsupported Stage type")
        mode = fields.get("mode")
        if mode not in (None, "", "readonly", "write"):
            raise ValueError("Stage mode must be readonly or write")
        parser = fields.get("parser")
        if parser not in (None, "", "review", "validation"):
            raise ValueError("Stage parser must be review or validation")
        produces = fields.get("produces")
        if produces not in (None, "", "tasks"):
            raise ValueError("Stage produces must be tasks when specified")
        for key in ("retry", "structured_retries", "structured_fresh_retries", "runs", "required_passes", "min_tasks"):
            value = fields.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError(f"Stage {key} must be an integer")
            minimum = -1 if key == "retry" else (1 if key in {"runs", "min_tasks"} else 0)
            if value < minimum:
                raise ValueError(f"Stage {key} must be >= {minimum}")
        timeout = fields.get("timeout")
        if timeout is not None and (not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout < 0):
            raise ValueError("Stage timeout must be a non-negative number")

    @staticmethod
    def _validate_flow_editor_fields(updates: dict, flow: list, index: int, stage: dict) -> None:
        scope = updates.get("scope")
        if scope not in (None, "", "task"):
            raise ValueError("Flow scope must be task when specified")
        label = updates.get("label")
        if label is not None and (not isinstance(label, str) or not label.strip()):
            raise ValueError("Flow label must be a non-empty string")
        status = updates.get("status")
        if status is not None and (not isinstance(status, str) or not status.strip()):
            raise ValueError("Flow status must be a non-empty string")
        prompt = updates.get("prompt")
        if prompt is not None and (not isinstance(prompt, str) or not prompt.strip()):
            raise ValueError("Flow prompt must be a non-empty string")
        restart_at = updates.get("restart_at")
        if restart_at:
            allowed = set()
            for item in flow[: index + 1]:
                name = item if isinstance(item, str) else item.get("stage") if isinstance(item, dict) else None
                if isinstance(name, str) and name:
                    allowed.add(name)
            if restart_at not in allowed:
                raise ValueError("restart_at must reference this or an earlier Flow stage")
        for key in ("repeat", "fresh_after_same_failures"):
            value = updates.get(key)
            if value is None:
                continue
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"Flow {key} must be a positive integer")
        recover = stage.get("recover") if isinstance(stage, dict) else None
        if updates.get("fresh_after_same_failures") is not None and not recover:
            raise ValueError("fresh_after_same_failures requires recover stages")
        if isinstance(updates.get("repeat"), int) and updates["repeat"] > 1 and not recover:
            raise ValueError("repeat > 1 requires recover stages")

    def _require_editable(self) -> None:
        guard = self.edit_guard()
        if not guard["editable"]:
            names = ", ".join(p["name"] for p in guard["active_projects"])
            raise ValueError(f"Cannot edit workflow/prompt while runtime is active: {names}")

    def _require_hash(self, content: str, expected_hash: str) -> None:
        if expected_hash and expected_hash != self._hash_text(content):
            raise ValueError("File changed on disk. Reload before saving to avoid overwriting another editor.")

    @staticmethod
    def _load_workflow_yaml(content: str) -> dict:
        try:
            data = yaml.safe_load(content) or {}
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("Workflow YAML root must be a mapping")
        return data

    @staticmethod
    def _stage_bounds(lines: list[str], stage_name: str) -> tuple[int, int]:
        stages_start = next((i for i, line in enumerate(lines) if re.match(r"^stages:\s*(?:#.*)?$", line.rstrip("\r\n"))), None)
        if stages_start is None:
            raise ValueError("Workflow has no top-level stages mapping")
        stage_pattern = re.compile(rf"^  {re.escape(stage_name)}:(?:\s*&[^\s#]+)?\s*(?:#.*)?$")
        start = next((i for i in range(stages_start + 1, len(lines)) if stage_pattern.match(lines[i].rstrip("\r\n"))), None)
        if start is None:
            raise ValueError(f"Stage uses unsupported YAML key syntax: {stage_name}")
        end = len(lines)
        for i in range(start + 1, len(lines)):
            text = lines[i]
            if re.match(r"^  [^\s#][^:]*:", text) or (text.strip() and not text[:1].isspace() and not text.lstrip().startswith("#")):
                end = i
                break
        return start, end

    @classmethod
    def _patch_stage_fields(cls, content: str, stage_name: str, fields: dict) -> str:
        lines = content.splitlines(keepends=True)
        newline = "\r\n" if "\r\n" in content else "\n"
        for key, value in fields.items():
            start, end = cls._stage_bounds(lines, stage_name)
            field_pattern = re.compile(rf"^    {re.escape(key)}:\s*")
            field_start = next((i for i in range(start + 1, end) if field_pattern.match(lines[i])), None)
            field_end = field_start
            if field_start is not None:
                field_end = end
                for i in range(field_start + 1, end):
                    candidate = lines[i]
                    leading = len(candidate) - len(candidate.lstrip(" "))
                    if (
                        re.match(r"^    [A-Za-z_][A-Za-z0-9_-]*:\s*", candidate)
                        or (candidate.lstrip().startswith("#") and leading <= 4)
                        or not candidate.strip()
                        or (candidate.strip() and not candidate[:1].isspace())
                    ):
                        field_end = i
                        break
            replacement: list[str] = []
            if value is not None:
                dumped = yaml.dump({key: value}, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
                replacement = [f"    {line}{newline}" for line in dumped.splitlines()]
            if field_start is not None:
                lines[field_start:field_end] = replacement
            elif replacement:
                _start, end = cls._stage_bounds(lines, stage_name)
                lines[end:end] = replacement
        return "".join(lines)

    @classmethod
    def _insert_stage_block(cls, content: str, stage_name: str, config: dict) -> str:
        newline = "\r\n" if "\r\n" in content else "\n"
        dumped = yaml.dump(config, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip("\n")
        block = f"  {stage_name}:{newline}" + "".join(f"    {line}{newline}" for line in dumped.splitlines())
        lines = content.splitlines(keepends=True)
        stages_start = next((i for i, line in enumerate(lines) if re.match(r"^stages:\s*(?:#.*)?$", line.rstrip("\r\n"))), None)
        if stages_start is None:
            prefix = f"stages:{newline}{block}{newline}"
            return prefix + content
        end = len(lines)
        for i in range(stages_start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
                end = i
                break
        prefix_blank = [] if end == 0 or (end > 0 and not lines[end - 1].strip()) else [newline]
        lines[end:end] = prefix_blank + [block]
        return "".join(lines)

    @staticmethod
    def _replace_flow_block(content: str, flow: list) -> str:
        normalized = []
        for item in flow if isinstance(flow, list) else []:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
            elif isinstance(item, dict) and str(item.get("stage", "")).strip():
                clean = dict(item)
                clean["stage"] = str(clean["stage"]).strip()
                normalized.append(clean if len(clean) > 1 else clean["stage"])
        flow_text = yaml.dump({"flow": normalized}, Dumper=_IndentedSafeDumper, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip() + "\n"
        lines = content.splitlines(keepends=True)
        start = next((i for i, line in enumerate(lines) if line.startswith("flow:") and not line[:1].isspace()), None)
        if start is None:
            separator = "" if not content or content.endswith("\n") else "\n"
            return content + separator + flow_text
        end = len(lines)
        for i in range(start + 1, len(lines)):
            line = lines[i]
            if line.strip() and not line[:1].isspace() and not line.lstrip().startswith("#"):
                end = i
                break
        return "".join(lines[:start]) + flow_text + "".join(lines[end:])

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def _validate_workflow_before_write(self, path: Path, content: str) -> dict:
        """Run prompt-reference checks and the real dry-run before any Workflow write."""
        self._load_workflow_yaml(content)
        self._validate_workflow_prompt_refs(path, content)
        path.parent.mkdir(parents=True, exist_ok=True)
        suffix = path.suffix if path.suffix.lower() in {".yaml", ".yml"} else ".yaml"
        temporary = path.with_name(f".{path.stem}.ui-validate-{uuid.uuid4().hex[:8]}{suffix}")
        temporary.write_text(content, encoding="utf-8")
        try:
            command = [sys.executable, str(self.repo_root / "tool" / "workflow_dryrun.py"), str(temporary), "--matrix", "--json", "--max-steps", "500"]
            try:
                result = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=45)
            except subprocess.TimeoutExpired as exc:
                raise ValueError("Workflow validation timed out after 45 seconds") from exc
            output = (result.stdout or result.stderr or "").strip()
            if result.returncode != 0:
                raise ValueError("Workflow validation failed: " + output[-12000:])
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("Workflow validation returned invalid JSON") from exc
            if not payload.get("closed"):
                raise ValueError("Workflow validation matrix did not reach closure")
            return {"ok": True, "output": output, "payload": payload}
        finally:
            try:
                temporary.unlink()
            except OSError:
                pass

    def _require_studio_writable(self, scope: str) -> None:
        if scope in SYSTEM_SCOPES:
            raise ValueError("System workflow/prompt is read only. Create or import a Custom copy to edit it.")

    def _workflow_requirements(self, path: Path | None) -> dict:
        result = {"requires_python_validator": False, "has_ai_validator": False}
        if path is None or not path.is_file():
            return result
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return result
        stages = data.get("stages") if isinstance(data, dict) else {}
        flow = data.get("flow") if isinstance(data, dict) else []
        if not isinstance(stages, dict) or not isinstance(flow, list):
            return result
        seen: set[tuple[str, str]] = set()

        def visit(item) -> None:
            if isinstance(item, str):
                name, overrides = item, {}
            elif isinstance(item, dict):
                name, overrides = str(item.get("stage", "")), {k: v for k, v in item.items() if k != "stage"}
            else:
                return
            cfg = dict(stages.get(name) or {}) if isinstance(stages.get(name), dict) else {}
            cfg.update(overrides)
            signature = (name, json.dumps(cfg, ensure_ascii=False, sort_keys=True, default=str))
            if signature in seen:
                return
            seen.add(signature)
            stage_type = str(cfg.get("type") or "base")
            if stage_type == "ai_validator":
                result["has_ai_validator"] = True
            command = cfg.get("command")
            command_text = " ".join(command) if isinstance(command, list) else str(command or "")
            if stage_type == "command" and str(cfg.get("result_kind") or "") == "validation" and "{validator}" in command_text:
                result["requires_python_validator"] = True
            recover = cfg.get("recover")
            if isinstance(recover, list):
                for child in recover:
                    visit(child)

        for row in flow:
            visit(row)
        return result

    def _resolve_prompt_reference(self, workflow_path: Path, reference: str) -> Path | None:
        value = str(reference or "").strip()
        if not value:
            return None
        raw = Path(value).expanduser()
        candidates = [raw] if raw.is_absolute() else [
            workflow_path.parent / raw,
            self.repo_root / "runner" / "prompts" / raw,
        ]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except OSError:
                continue
            if resolved.is_file() and resolved.suffix.lower() == ".md":
                return resolved
        return None

    def _workflow_prompt_refs(self, content: str) -> list[tuple[str, str]]:
        data = self._load_workflow_yaml(content)
        stages = data.get("stages") or {}
        flow = data.get("flow") or []
        refs: list[tuple[str, str]] = []
        if not isinstance(stages, dict):
            return refs
        for name, config in stages.items():
            if not isinstance(config, dict):
                continue
            stage_type = str(config.get("type") or "base")
            if stage_type == "base" and not str(config.get("prompt") or "").strip():
                refs.append((str(name), "<required>"))
            for key in ("prompt", "continuation_prompt"):
                value = config.get(key)
                if isinstance(value, str) and value.strip():
                    refs.append((str(name), value.strip()))
            recover = config.get("recover")
            if isinstance(recover, list):
                for item in recover:
                    if isinstance(item, dict):
                        for key in ("prompt", "continuation_prompt"):
                            value = item.get(key)
                            if isinstance(value, str) and value.strip():
                                refs.append((f"{name}.recover", value.strip()))
        if isinstance(flow, list):
            for index, item in enumerate(flow):
                if isinstance(item, dict):
                    name = str(item.get("stage") or f"flow[{index}]")
                    for key in ("prompt", "continuation_prompt"):
                        value = item.get(key)
                        if isinstance(value, str) and value.strip():
                            refs.append((name, value.strip()))
        return refs

    def _validate_workflow_prompt_refs(self, workflow_path: Path, content: str) -> None:
        missing: list[str] = []
        for stage, reference in self._workflow_prompt_refs(content):
            if reference == "<required>":
                missing.append(f"{stage}: Prompt is required")
            elif self._resolve_prompt_reference(workflow_path, reference) is None:
                missing.append(f"{stage}: {reference}")
        if missing:
            raise ValueError("Workflow references missing Prompt(s): " + "; ".join(missing[:12]))

    def _known_workflow_paths(self, project: Path | None = None) -> list[Path]:
        roots = [self.repo_root / "runner" / "workflow" / "system", self.repo_root / "runner" / "workflow" / "custom"]
        paths: list[Path] = []
        for root in roots:
            if not root.is_dir():
                continue
            for suffix in ("*.yaml", "*.yml"):
                for path in root.rglob(suffix):
                    if "prompts" not in path.parts:
                        paths.append(path.resolve())
        known_projects = [Path(row["path"]).resolve() for row in self.projects() if row.get("exists")]
        if project is not None and project.resolve() not in known_projects:
            known_projects.append(project.resolve())
        for root in known_projects:
            for suffix in ("*.yaml", "*.yml"):
                for path in root.glob(suffix):
                    if path.name == ".ai-task-runner.yaml" or "workflow" in path.name.lower():
                        paths.append(path.resolve())
        result: list[Path] = []
        seen: set[str] = set()
        for path in paths:
            key = os.path.normcase(str(path))
            if key not in seen:
                seen.add(key); result.append(path)
        return result

    def _prompt_usages(self, prompt_path: Path, project: Path | None = None) -> list[str]:
        target = prompt_path.resolve()
        usages: list[str] = []
        for workflow in self._known_workflow_paths(project):
            try:
                content = workflow.read_text(encoding="utf-8")
            except OSError:
                continue
            for stage, reference in self._workflow_prompt_refs(content):
                resolved = self._resolve_prompt_reference(workflow, reference)
                if resolved is not None and os.path.normcase(str(resolved)) == os.path.normcase(str(target)):
                    usages.append(f"{workflow.name} · {stage}")
        return sorted(set(usages))

    def studio_prompt_create(self, name: str, destination: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            self._require_editable()
            raw = str(name or "").strip()
            if not raw:
                raise ValueError("Prompt name is required")
            if "/" in raw or "\\" in raw or raw in {".", ".."}:
                raise ValueError("Prompt name must be a file name, not a path")
            if not raw.lower().endswith(".md"):
                raw += ".md"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.md", raw, re.IGNORECASE):
                raise ValueError("Prompt file name contains unsupported characters")
            destination = str(destination or "custom").strip().lower()
            if destination == "project":
                if project is None:
                    raise ValueError("Select a Project before creating a Project Prompt")
                root = (project / "prompts").resolve(); root.mkdir(parents=True, exist_ok=True); scope = "project"
            elif destination == "custom":
                root = (self.repo_root / "runner" / "prompts" / "custom").resolve(); root.mkdir(parents=True, exist_ok=True); scope = "custom"
            else:
                raise ValueError("Prompt destination must be project or custom")
            target = (root / raw).resolve()
            if not self._is_within(target, root):
                raise ValueError("Prompt path is outside the selected Prompt folder")
            if target.exists():
                raise ValueError(f"Prompt already exists: {target.name}")
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write("# Prompt\n\n{{goal}}\n")
            item = self._studio_item(target, scope, "prompt")
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_delete(self, file_id: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            usages = self._prompt_usages(path, project) if kind == "prompt" else []
            if usages:
                raise ValueError("Prompt is still used by Workflow Stage(s): " + "; ".join(usages[:12]))
            try:
                path.unlink()
            except OSError as exc:
                raise ValueError(f"Cannot delete {kind}: {exc}") from exc
            return {"ok": True, "kind": kind, "name": path.name}

    @staticmethod
    def _normalize_studio_asset_name(kind: str, name: str) -> str:
        raw = str(name or "").strip()
        if not raw:
            raise ValueError(f"{kind.title()} name is required")
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise ValueError(f"{kind.title()} name must be a file name, not a path")
        if kind == "workflow":
            if not raw.lower().endswith((".yaml", ".yml")):
                raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
                raise ValueError("Workflow file name contains unsupported characters")
        elif kind == "prompt":
            if not raw.lower().endswith(".md"):
                raw += ".md"
            if not re.fullmatch(r"[A-Za-z0-9_. -]+\.md", raw, re.IGNORECASE):
                raise ValueError("Prompt file name contains unsupported characters")
        else:
            raise ValueError("Unsupported Studio asset kind")
        return raw

    def _studio_scope_root(self, kind: str, scope: str, project: Path | None) -> Path:
        if scope == "custom":
            root = self.repo_root / "runner" / ("workflow" if kind == "workflow" else "prompts") / "custom"
        elif scope == "project":
            if project is None:
                raise ValueError("Select a Project before modifying a Project asset")
            root = project if kind == "workflow" else project / "prompts"
        else:
            raise ValueError("System assets cannot be renamed in place")
        root = root.resolve(); root.mkdir(parents=True, exist_ok=True)
        return root

    def studio_rename(self, file_id: str, name: str, project: Path | None = None) -> dict:
        """Rename one writable Studio asset without changing its scope or content."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind == "prompt":
                usages = self._prompt_usages(path, project)
                if usages:
                    raise ValueError("Prompt is still referenced; update Workflow references before rename: " + "; ".join(usages[:12]))
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._studio_scope_root(kind, scope, project)
            target = (root / raw).resolve()
            if not self._is_within(target, root):
                raise ValueError("Renamed asset path is outside the allowed scope")
            if target == path:
                item = self._studio_item(path, scope, kind)
                return {"item": item, "file": self.studio_read(item["id"], project)}
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {target.name}")
            content = path.read_text(encoding="utf-8")
            if kind == "workflow":
                self._validate_workflow_before_write(target, content)
            else:
                self._validate_prompt_before_write(target, content)
            try:
                path.rename(target)
            except OSError as exc:
                raise ValueError(f"Cannot rename {kind}: {exc}") from exc
            item = self._studio_item(target, scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_duplicate(self, file_id: str, name: str, project: Path | None = None) -> dict:
        """Create an independent copy. System assets duplicate to Custom; others keep scope."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            target_scope = "custom" if scope in SYSTEM_SCOPES else scope
            raw = self._normalize_studio_asset_name(kind, name)
            root = self._studio_scope_root(kind, target_scope, project)
            target = (root / raw).resolve()
            if not self._is_within(target, root):
                raise ValueError("Duplicated asset path is outside the allowed scope")
            if target.exists():
                raise ValueError(f"{kind.title()} already exists: {target.name}")
            content = path.read_text(encoding="utf-8")
            if kind == "workflow":
                self._validate_workflow_before_write(target, content)
            else:
                self._validate_prompt_before_write(target, content)
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)
            except FileExistsError as exc:
                raise ValueError(f"{kind.title()} already exists: {target.name}") from exc
            item = self._studio_item(target, target_scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    @staticmethod
    def _stage_reference_paths(value, stage_name: str, path: str = "workflow") -> list[str]:
        refs: list[str] = []
        if isinstance(value, dict):
            for key, child in value.items():
                current = f"{path}.{key}"
                if key in {"stage", "restart_at"} and isinstance(child, str) and child == stage_name:
                    refs.append(current)
                if key in {"recover", "flow"} and isinstance(child, list):
                    for index, item in enumerate(child):
                        item_path = f"{current}[{index}]"
                        if isinstance(item, str) and item == stage_name:
                            refs.append(item_path)
                        elif isinstance(item, (dict, list)):
                            refs.extend(UIState._stage_reference_paths(item, stage_name, item_path))
                    continue
                if isinstance(child, (dict, list)):
                    refs.extend(UIState._stage_reference_paths(child, stage_name, current))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                if isinstance(child, (dict, list)):
                    refs.extend(UIState._stage_reference_paths(child, stage_name, f"{path}[{index}]"))
        return refs

    @staticmethod
    def _remove_stage_definition_block(content: str, stage_name: str) -> str:
        try:
            root = yaml.compose(content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Workflow YAML is invalid: {exc}") from exc
        if not isinstance(root, yaml.nodes.MappingNode):
            raise ValueError("Workflow YAML root must be a mapping")
        stage_mapping = None
        for key_node, value_node in root.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and key_node.value == "stages":
                stage_mapping = value_node
                break
        if not isinstance(stage_mapping, yaml.nodes.MappingNode):
            raise ValueError("Workflow stages mapping is missing")
        start = end = None
        for key_node, value_node in stage_mapping.value:
            if isinstance(key_node, yaml.nodes.ScalarNode) and str(key_node.value) == stage_name:
                start = key_node.start_mark.line
                end = max(key_node.end_mark.line, value_node.end_mark.line)
                break
        if start is None or end is None:
            raise ValueError(f"Stage not found: {stage_name}")
        lines = content.splitlines(keepends=True)
        del lines[start:end]
        return "".join(lines)

    def studio_stage_delete(self, file_id: str, stage_name: str, expected_hash: str, project: Path | None = None, *, flow_index: int | None = None) -> dict:
        """Atomically remove one Flow invocation and its Stage definition when no other references remain."""
        with self._edit_lock:
            self._require_editable()
            path, kind, scope = self._resolve_studio_file(file_id, project)
            self._require_studio_writable(scope)
            if kind != "workflow":
                raise ValueError("Stage definitions exist only in Workflow YAML")
            content = path.read_text(encoding="utf-8")
            self._require_hash(content, expected_hash)
            data = self._load_workflow_yaml(content)
            stages = data.get("stages") if isinstance(data, dict) else None
            flow = data.get("flow") if isinstance(data, dict) else None
            if not isinstance(stages, dict) or stage_name not in stages:
                raise ValueError(f"Stage not found: {stage_name}")
            if not isinstance(flow, list):
                flow = []
            if flow_index is None or flow_index < 0 or flow_index >= len(flow):
                raise ValueError("A valid Flow invocation is required to delete the Stage definition")
            selected = flow[flow_index]
            selected_name = selected if isinstance(selected, str) else str(selected.get("stage", "")) if isinstance(selected, dict) else ""
            if selected_name != stage_name:
                raise ValueError("Selected Flow invocation no longer matches the Stage")
            next_flow = list(flow); del next_flow[flow_index]
            next_data = dict(data); next_stages = dict(stages); next_stages.pop(stage_name, None); next_data["stages"] = next_stages; next_data["flow"] = next_flow
            refs = self._stage_reference_paths(next_data, stage_name)
            if refs:
                raise ValueError("Stage definition is still referenced by: " + ", ".join(refs[:8]))
            without_stage = self._remove_stage_definition_block(content, stage_name)
            updated = self._replace_flow_block(without_stage, next_flow)
            self._validate_workflow_before_write(path, updated)
            self._atomic_write(path, updated)
            return {"file": self.studio_read(file_id, project), "visual": self.studio_visual(file_id, project)}

    def studio_export(self, file_id: str, project: Path | None = None) -> dict:
        path, kind, scope = self._resolve_studio_file(file_id, project)
        return {
            "schema_version": 1,
            "kind": kind,
            "name": path.name,
            "scope": scope,
            "content": path.read_text(encoding="utf-8"),
        }

    def studio_import(self, kind: str, name: str, content: str, destination: str, project: Path | None = None) -> dict:
        with self._edit_lock:
            self._require_editable()
            kind = str(kind or "").strip().lower()
            if kind not in {"workflow", "prompt"}:
                raise ValueError("Import kind must be workflow or prompt")
            destination = str(destination or "custom").strip().lower()
            if destination == "project":
                if project is None:
                    raise ValueError("Select a Project before importing to Project")
                root = project.resolve() if kind == "workflow" else (project / "prompts").resolve()
                if kind == "prompt": root.mkdir(parents=True, exist_ok=True)
                scope = "project"
            elif destination == "custom":
                root = (self.repo_root / "runner" / "workflow" / "custom").resolve() if kind == "workflow" else (self.repo_root / "runner" / "prompts" / "custom").resolve()
                root.mkdir(parents=True, exist_ok=True); scope = "custom"
            else:
                raise ValueError("Import destination must be project or custom")
            raw = str(name or "").strip()
            suffix = ".yaml" if kind == "workflow" else ".md"
            if not raw:
                raw = f"imported-{kind}{suffix}"
            if kind == "workflow" and not raw.lower().endswith((".yaml", ".yml")):
                raw += ".yaml"
            if kind == "prompt" and not raw.lower().endswith(".md"):
                raw += ".md"
            if "/" in raw or "\\" in raw or raw in {".", ".."}:
                raise ValueError("Imported asset name must be a file name")
            target = (root / raw).resolve()
            if not self._is_within(target, root):
                raise ValueError("Import path is outside the destination folder")
            if target.exists():
                raise ValueError(f"Asset already exists: {target.name}")
            text = str(content or "")
            if not text.strip():
                raise ValueError("Imported content is empty")
            if kind == "workflow":
                self._validate_workflow_before_write(target, text)
            else:
                try:
                    self._validate_prompt_before_write(target, text)
                except ValueError as exc:
                    raise ValueError("Invalid Prompt template: " + str(exc).removeprefix("Prompt validation failed: ")) from exc
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            item = self._studio_item(target, scope, kind)
            return {"item": item, "file": self.studio_read(item["id"], project)}

    def studio_validate(
        self,
        file_id: str,
        project: Path | None = None,
        *,
        content: str | None = None,
        flow: object | None = None,
    ) -> dict:
        """Validate the current Workflow draft without writing it.

        YAML mode can pass ``content`` while Visual mode can pass the current ``flow``.
        The real Workflow file remains untouched; the existing dry-run gate receives only
        a temporary validation copy.
        """
        path, kind, _ = self._resolve_studio_file(file_id, project)
        draft = path.read_text(encoding="utf-8") if content is None else str(content)
        if kind == "prompt":
            check = self._check_prompt_content(draft, path)
            if not check["ok"]:
                return {**check, "summary": "Prompt validation failed", "output": check["summary"]}
            return {**check, "summary": "Prompt validation passed", "output": ""}
        if kind != "workflow":
            raise ValueError("Only Workflow or Prompt files can be validated")
        if flow is not None:
            if not isinstance(flow, list):
                return {"ok": False, "summary": "Validation failed", "output": "Workflow flow must be a list"}
            draft = self._replace_flow_block(draft, flow)
        try:
            result = self._validate_workflow_before_write(path, draft)
        except ValueError as exc:
            return {"ok": False, "summary": "Validation failed", "output": str(exc)}
        return {"ok": True, "summary": "Validation passed", "output": result.get("output", "")[-20000:]}

    def _builder_root(self) -> Path:
        """UI-owned Workflow Builder workspace, independent from every user Project."""
        return (self.ui_root / "data" / "workflow-builder").resolve()

    def _builder_active_path(self) -> Path:
        return self._builder_root() / "active.json"

    def _builder_set_active(self, job_id: str) -> None:
        self._atomic_json(self._builder_active_path(), {
            "schema_version": 1,
            "job_id": str(job_id),
            "updated_at": time.time(),
        })

    def _builder_clear_active(self, job_id: str = "") -> None:
        path = self._builder_active_path()
        if not path.is_file():
            return
        if job_id:
            current = self._read_json(path) or {}
            if str(current.get("job_id") or "") != str(job_id):
                return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _builder_active_job_id(self) -> str:
        payload = self._read_json(self._builder_active_path()) or {}
        job_id = str(payload.get("job_id") or "").strip()
        if not re.fullmatch(r"[a-f0-9]{12}", job_id):
            self._builder_clear_active()
            return ""
        if not self._builder_job_root(job_id).is_dir():
            self._builder_clear_active(job_id)
            return ""
        return job_id

    def _builder_job_root(self, job_id: str) -> Path:
        value = str(job_id or "").strip()
        if not re.fullmatch(r"[a-f0-9]{12}", value):
            raise ValueError("Invalid Workflow Builder job id")
        root = self._builder_root()
        path = (root / value).resolve()
        if not self._is_within(path, root):
            raise ValueError("Workflow Builder job is outside the UI draft root")
        return path

    @staticmethod
    def _atomic_json(path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _workflow_output_paths(self, project: Path | None, name: str, destination: str) -> tuple[str, str, Path, Path]:
        raw = str(name or "").strip()
        if not raw:
            raise ValueError("Workflow name is required")
        if "/" in raw or "\\" in raw or raw in {".", ".."}:
            raise ValueError("Workflow name must be a file name, not a path")
        if not raw.lower().endswith((".yaml", ".yml")):
            raw += ".workflow.yaml" if "workflow" not in raw.lower() else ".yaml"
        if not re.fullmatch(r"[A-Za-z0-9_. -]+\.ya?ml", raw, re.IGNORECASE):
            raise ValueError("Workflow file name contains unsupported characters")
        destination = str(destination or "custom").strip().lower()
        if destination == "custom":
            output_workflow = (self.repo_root / "runner" / "workflow" / "custom" / raw).resolve()
            output_prompt_dir = (self.repo_root / "runner" / "prompts" / "custom").resolve()
        elif destination == "project":
            if project is None:
                raise ValueError("Open a Project before saving to Current Project")
            output_workflow = (project / raw).resolve()
            output_prompt_dir = (project / "prompts").resolve()
        else:
            raise ValueError("Workflow destination must be project or custom")
        return raw, destination, output_workflow, output_prompt_dir

    def studio_draft_info(self) -> dict:
        builder_root = self.repo_root / "workflow_builder"
        builder = builder_root / "run.py"
        workflow = builder_root / "workflow_builder.yaml"
        prompt = builder_root / "prompt.md"
        validator = builder_root / "validation.py"
        publisher = builder_root / "publish.py"
        available = all(path.is_file() for path in (builder, workflow, prompt, validator, publisher))
        workspace_root = self._builder_root()
        return {
            "available": available,
            "builder": str(builder),
            "workflow": str(workflow),
            "prompt": str(prompt),
            "validator": str(validator),
            "publisher": str(publisher),
            "workspace_root": str(workspace_root),
            "workspace_pattern": str(workspace_root / "<new-job-id>"),
            "message": "AI Workflow Builder is ready." if available else "AI Workflow Builder files are incomplete.",
        }

    def studio_generate_workflow(
        self,
        request: str,
        backend: str = "",
    ) -> dict:
        """Start a brand-new validated draft job in the UI-owned workspace.

        Workflow generation is deliberately independent from the selected Project.
        The Builder Runner receives the job directory itself as its isolated
        ``--project-root`` so generation also works when no Project exists.
        Generate never creates a real Workflow asset; Save is the publish boundary.
        """
        with self._lifecycle_lock:
            info = self.studio_draft_info()
            if not info.get("available"):
                raise ValueError(info.get("message") or "AI Workflow Builder is unavailable")
            request = str(request or "").strip()
            if not request:
                raise ValueError("Workflow requirements are required")

            base = self._builder_root()
            base.mkdir(parents=True, exist_ok=True)

            # Exactly one Generator job may exist at a time. Browser refresh/close does
            # not own the lifecycle; active.json does. If a job already exists, return
            # it instead of accidentally launching a second AI run.
            active_job_id = self._builder_active_job_id()
            if active_job_id:
                active = self.studio_generate_status(active_job_id)
                if active.get("state") == "cancelled":
                    shutil.rmtree(self._builder_job_root(active_job_id), ignore_errors=True)
                    self._builder_clear_active(active_job_id)
                else:
                    return {**active, "ok": True, "existing": True}

            # Terminal, unregistered leftovers are disposable. Never remove active.json
            # here; it is the single source of truth for the current Generator job.
            for job in list(base.iterdir()):
                if job.is_dir():
                    shutil.rmtree(job, ignore_errors=True)

            job_id = uuid.uuid4().hex[:12]
            job_root = self._builder_job_root(job_id)
            job_root.mkdir(parents=True, exist_ok=False)
            status = {
                "schema_version": 1,
                "job_id": job_id,
                "state": "queued",
                "message": "Preparing Workflow Builder",
                "request": request,
                "backend": str(backend or ""),
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            self._atomic_json(job_root / "status.json", status)
            self._builder_set_active(job_id)
            command = [
                sys.executable,
                str(self.repo_root / "workflow_builder" / "run.py"),
                # The job itself is an isolated temporary Runner project. It is not
                # the currently selected user Project and does not require one.
                "--project-root", str(job_root),
                "--request", request,
                "--draft-only",
                "--job-dir", str(job_root),
            ]
            if backend:
                command += ["--backend", backend]
            kwargs = _background_process_kwargs()
            kwargs["cwd"] = str(self.repo_root)
            try:
                subprocess.Popen(command, **kwargs)
            except Exception as exc:
                status.update({"state": "failed", "message": str(exc), "updated_at": time.time()})
                self._atomic_json(job_root / "status.json", status)
                raise
            return {"ok": True, "job_id": job_id, "state": "queued", "message": "Workflow Builder started. No Workflow has been created yet.", "workspace": str(job_root)}

    def studio_generate_active(self) -> dict:
        """Return the single active Generator job so a reopened UI can resume it."""
        with self._lifecycle_lock:
            job_id = self._builder_active_job_id()
            if not job_id:
                return {"ok": True, "active": False, "workspace_root": str(self._builder_root())}
            payload = self.studio_generate_status(job_id)
            if payload.get("state") == "cancelled":
                shutil.rmtree(self._builder_job_root(job_id), ignore_errors=True)
                self._builder_clear_active(job_id)
                return {"ok": True, "active": False, "workspace_root": str(self._builder_root())}
            status = self._read_json(self._builder_job_root(job_id) / "status.json") or {}
            return {
                **payload,
                "active": True,
                "request": str(status.get("request") or ""),
                "backend": str(status.get("backend") or ""),
                "workspace": str(self._builder_job_root(job_id)),
            }

    def _builder_paths(self, job_root: Path, status: dict) -> tuple[Path, Path, dict]:
        result = status.get("result") if isinstance(status.get("result"), dict) else (self._read_json(job_root / "result.json") or {})
        workflow = Path(str(result.get("draft_workflow") or job_root / "draft" / "workflow.yaml")).resolve()
        prompts = Path(str(result.get("draft_prompt_dir") or job_root / "draft" / "prompts")).resolve()
        if not self._is_within(workflow, job_root) or not self._is_within(prompts, job_root):
            raise ValueError("Workflow Builder draft paths are invalid")
        return workflow, prompts, result

    @staticmethod
    def _builder_visual(workflow_text: str) -> dict:
        try:
            data = yaml.safe_load(workflow_text) or {}
        except yaml.YAMLError:
            return {"stages": [], "flow": []}
        stages = data.get("stages") if isinstance(data, dict) and isinstance(data.get("stages"), dict) else {}
        flow = data.get("flow") if isinstance(data, dict) and isinstance(data.get("flow"), list) else []
        rows = []
        for name, cfg in stages.items():
            cfg = cfg if isinstance(cfg, dict) else {}
            rows.append({"name": str(name), "type": str(cfg.get("type") or "base"), "status": str(cfg.get("status") or ""), "prompt": str(cfg.get("prompt") or "")})
        return {"stages": rows, "flow": flow}

    def _builder_preview(self, job_root: Path, status: dict) -> dict:
        workflow, prompts, result = self._builder_paths(job_root, status)
        if not workflow.is_file():
            raise ValueError("Workflow Builder draft Workflow is missing")
        workflow_text = workflow.read_text(encoding="utf-8", errors="replace")[:240000]
        rows: list[dict] = []
        if prompts.is_dir():
            for path in sorted(p for p in prompts.rglob("*") if p.is_file())[:30]:
                rows.append({"name": path.relative_to(prompts).as_posix(), "content": path.read_text(encoding="utf-8", errors="replace")[:120000]})
        return {"workflow": workflow_text, "prompts": rows, "validation": str(result.get("validation") or "")[-12000:], "visual": self._builder_visual(workflow_text)}

    def _builder_apply_edits(self, job_root: Path, status: dict, workflow_content: str | None, prompt_rows: object) -> tuple[Path, Path]:
        workflow, prompts, _ = self._builder_paths(job_root, status)
        if workflow_content is not None:
            workflow.write_text(str(workflow_content), encoding="utf-8")
        if isinstance(prompt_rows, list):
            for row in prompt_rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip().replace("\\", "/")
                if not name or name.startswith("/") or ".." in Path(name).parts:
                    raise ValueError("Invalid generated Prompt name")
                target = (prompts / name).resolve()
                if not self._is_within(target, prompts):
                    raise ValueError("Generated Prompt is outside the draft Prompt directory")
                if not target.is_file():
                    raise ValueError(f"Generated Prompt not found: {name}")
                content = str(row.get("content") or "")
                check = self._check_prompt_content(content, target)
                if not check.get("ok"):
                    raise ValueError(f"Prompt validation failed ({name}): {check.get('summary')}")
                target.write_text(content, encoding="utf-8")
        return workflow, prompts

    def _builder_validate_draft(self, job_root: Path, workflow: Path, prompts: Path) -> dict:
        command = [sys.executable, str(self.repo_root / "workflow_builder" / "validation.py"), "--project-root", str(job_root), "--draft-workflow", str(workflow), "--draft-prompt-dir", str(prompts)]
        result = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=60)
        output = (result.stdout or result.stderr or "").strip()
        if result.returncode != 0:
            raise ValueError("Workflow draft validation failed: " + output[-12000:])
        return {"ok": True, "output": output[-12000:]}

    def studio_generate_status(self, job_id: str) -> dict:
        job_root = self._builder_job_root(job_id)
        status = self._read_json(job_root / "status.json")
        if not status:
            raise ValueError("Workflow Builder draft was not found")
        state = str(status.get("state") or "queued")
        pid = int(status.get("pid") or 0)
        if state in {"queued", "running", "cancelling"}:
            age = max(0.0, time.time() - float(status.get("updated_at") or status.get("created_at") or time.time()))
            stale = (pid and not self._pid_alive(pid)) or (not pid and age >= 30)
            if stale:
                terminal = "cancelled" if state == "cancelling" else "failed"
                message = "Workflow generation cancelled" if terminal == "cancelled" else "Workflow Builder process stopped unexpectedly"
                status.update({"state": terminal, "message": message, "updated_at": time.time()})
                self._atomic_json(job_root / "status.json", status)
                state = terminal
        if state in {"ready", "failed", "cancelled"} and not status.get("runtime_cleared"):
            # Only the isolated Builder runtime is disposable. Never reset or stop a
            # user Project as a side effect of Workflow generation.
            shutil.rmtree(job_root / RUNTIME_DIR, ignore_errors=True)
            status["runtime_cleared"] = True
            status["updated_at"] = time.time()
            self._atomic_json(job_root / "status.json", status)
        payload = {"ok": state != "failed", "job_id": job_id, "state": state, "message": str(status.get("message") or state), "workspace": str(job_root)}
        if state == "ready":
            payload["draft"] = self._builder_preview(job_root, status)
        return payload

    def studio_generate_validate(self, job_id: str, workflow_content: str | None, prompt_rows: object) -> dict:
        with self._lifecycle_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") != "ready":
                raise ValueError("Workflow Builder draft is not ready to validate")
            workflow, prompts = self._builder_apply_edits(job_root, status, workflow_content, prompt_rows)
            result = self._builder_validate_draft(job_root, workflow, prompts)
            status["message"] = "Draft validation passed"
            status["updated_at"] = time.time()
            self._atomic_json(job_root / "status.json", status)
            result["draft"] = self._builder_preview(job_root, status)
            return result

    def studio_generate_save(self, project: Path | None, job_id: str, name: str, destination: str, workflow_content: str | None = None, prompt_rows: object = None) -> dict:
        with self._lifecycle_lock:
            # Publishing mutates a real Workflow/Prompt asset, so keep the existing
            # global edit guard here even though draft generation itself is independent.
            self._require_editable()
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") != "ready":
                raise ValueError("Workflow Builder draft is not ready to Save")
            raw, destination, output_workflow, output_prompt_dir = self._workflow_output_paths(project, name, destination)
            if output_workflow.exists():
                raise ValueError(f"Workflow already exists: {output_workflow.name}")
            draft_workflow, draft_prompt_dir = self._builder_apply_edits(job_root, status, workflow_content, prompt_rows)
            self._builder_validate_draft(job_root, draft_workflow, draft_prompt_dir)
            command = [sys.executable, str(self.repo_root / "workflow_builder" / "publish.py"), "--project-root", str(job_root), "--draft-workflow", str(draft_workflow), "--draft-prompt-dir", str(draft_prompt_dir), "--output-workflow", str(output_workflow), "--output-prompt-dir", str(output_prompt_dir)]
            result_process = subprocess.run(command, cwd=self.repo_root, capture_output=True, text=True, timeout=75)
            if result_process.returncode != 0:
                raise ValueError("Workflow draft publish failed: " + (result_process.stdout or result_process.stderr or "")[-12000:])
            scope = "custom" if destination == "custom" else "project"
            item = self._studio_item(output_workflow, scope, "workflow")
            file_data = self.studio_read(item["id"], project)
            shutil.rmtree(job_root, ignore_errors=True)
            self._builder_clear_active(job_id)
            return {"ok": True, "workflow": str(output_workflow), "prompt_dir": str(output_prompt_dir), "item": item, "file": file_data, "message": f"Workflow {raw} saved"}

    def studio_generate_cancel(self, job_id: str) -> dict:
        with self._lifecycle_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            state = str(status.get("state") or "")
            if state not in {"queued", "running", "cancelling"}:
                return {"ok": True, "state": state or "cancelled"}
            (job_root / "cancel.request").write_text("cancel\n", encoding="utf-8")
            runtime = job_root / RUNTIME_DIR
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "stop.request").write_text("stop\n", encoding="utf-8")
            status.update({"state": "cancelling", "message": "Cancelling Workflow generation…", "updated_at": time.time()})
            self._atomic_json(job_root / "status.json", status)
            return {"ok": True, "state": "cancelling", "message": "Cancelling Workflow generation…"}

    def studio_generate_discard(self, job_id: str) -> dict:
        with self._lifecycle_lock:
            job_root = self._builder_job_root(job_id)
            status = self._read_json(job_root / "status.json") or {}
            if status.get("state") in {"queued", "running", "cancelling"}:
                raise ValueError("Cancel the running Workflow generation before Discard")
            shutil.rmtree(job_root, ignore_errors=True)
            self._builder_clear_active(job_id)
            return {"ok": True, "message": "Workflow draft discarded"}

    def _studio_item(self, path: Path, scope: str, kind: str) -> dict:
        resolved = path.resolve()
        readonly = scope in SYSTEM_SCOPES
        item = {
            "id": self._encode_file_id(resolved, kind, scope),
            "name": path.name,
            "path": str(resolved),
            "scope": scope,
            "group": "System" if readonly else ("Custom" if scope == "custom" else "Project"),
            "kind": kind,
            "readonly": readonly,
            "deletable": not readonly,
        }
        if kind == "workflow":
            item.update(self._workflow_requirements(resolved))
        return item

    @staticmethod
    def _encode_file_id(path: Path, kind: str, scope: str) -> str:
        raw = json.dumps({"path": str(path), "kind": kind, "scope": scope}, separators=(",", ":"), ensure_ascii=False)
        return raw.encode("utf-8").hex()

    def _resolve_studio_file(self, file_id: str, project: Path | None) -> tuple[Path, str, str]:
        try:
            payload = json.loads(bytes.fromhex(file_id).decode("utf-8"))
            path = Path(str(payload["path"])).resolve()
            kind = str(payload["kind"])
            scope = str(payload["scope"])
        except Exception as exc:
            raise ValueError("Invalid workflow file id") from exc
        if not path.is_file() or path.suffix.lower() not in EDITABLE_SUFFIXES:
            raise ValueError("Workflow/prompt file does not exist")

        valid = False
        if scope == "system" and kind == "workflow":
            valid = self._is_within(path, (self.repo_root / "runner" / "workflow" / "system").resolve())
        elif scope == "custom" and kind == "workflow":
            tool_root = (self.repo_root / "runner" / "workflow" / "custom").resolve()
            prompt_root = (self.repo_root / "runner" / "prompts" / "custom").resolve()
            valid = self._is_within(path, tool_root) and not self._is_within(path, prompt_root)
        elif scope == "system" and kind == "prompt":
            system_prompt_roots = (
                (self.repo_root / "runner" / "prompts" / "stages").resolve(),
                (self.repo_root / "runner" / "prompts" / "system").resolve(),
            )
            valid = any(self._is_within(path, root) for root in system_prompt_roots)
        elif scope == "custom" and kind == "prompt":
            valid = self._is_within(path, (self.repo_root / "runner" / "prompts" / "custom").resolve())
        elif scope == "project" and project is not None and kind == "workflow":
            valid = path.parent == project.resolve() and (path.name == ".ai-task-runner.yaml" or "workflow" in path.name.lower())
        elif scope == "project" and project is not None and kind == "prompt":
            prompt_root = (project / "prompts").resolve()
            valid = prompt_root.exists() and self._is_within(path, prompt_root)

        if not valid:
            raise ValueError("File is outside allowed workflow/prompt roots")
        return path, kind, scope

    @staticmethod
    def _is_within(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    @staticmethod
    def _hash_text(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

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
    def _pid_alive(pid: int) -> bool:
        if pid <= 0:
            return False
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
            except (OSError, subprocess.SubprocessError):
                return False
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
                return self._json({"projects": self.state.projects()})
            if parsed.path == "/api/backends":
                return self._json(self.state.backend_catalog())
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
                    validator=str(body.get("validator", "")),
                    workflow=str(body.get("workflow", "")),
                )
                return self._json({"ok": True})
            if parsed.path == "/api/project/stop":
                self.state.stop(self._project(body))
                return self._json({"ok": True})
            if parsed.path == "/api/project/resume":
                project = self._project(body)
                self.state.launch(project, None, mode="resume", backend=str(body.get("backend", "")), validator=str(body.get("validator", "")), workflow=str(body.get("workflow", "")))
                return self._json({"ok": True})
            if parsed.path == "/api/project/reset":
                return self._json(self.state.reset_runtime(self._project(body)))
            if parsed.path == "/api/project/rerun":
                project = self._project(body)
                last = next((m["content"] for m in reversed(self.state.messages(project)) if m.get("role") == "user"), "")
                if not last:
                    raise ValueError("No previous task to rerun")
                self.state.reset_runtime(project)
                request = self.state._create_run_request(
                    project,
                    last,
                    backend=str(body.get("backend", "")),
                    validator=str(body.get("validator", "")),
                    workflow=str(body.get("workflow", "")),
                    request_mode="workflow",
                )
                self.state.launch(
                    project,
                    None,
                    mode="run",
                    backend=str(body.get("backend", "")),
                    validator=request["validator"],
                    workflow=request["workflow"],
                    goal_file=request["prompt_file"],
                )
                return self._json({"ok": True})
            if parsed.path == "/api/studio/generate":
                return self._json(self.state.studio_generate_workflow(str(body.get("request", "")), str(body.get("backend", ""))))
            if parsed.path == "/api/studio/generate/validate":
                return self._json(self.state.studio_generate_validate(str(body.get("job_id", "")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_generate_save(project, str(body.get("job_id", "")), str(body.get("name", "")), str(body.get("destination", "custom")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/cancel":
                return self._json(self.state.studio_generate_cancel(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/generate/discard":
                return self._json(self.state.studio_generate_discard(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/workflow/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_workflow_create(str(body.get("name", "")), str(body.get("destination", "custom")), project))
            if parsed.path == "/api/studio/prompt/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_prompt_create(str(body.get("name", "")), str(body.get("destination", "custom")), project))
            if parsed.path == "/api/studio/delete":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_delete(str(body.get("id", "")), project))
            if parsed.path == "/api/studio/rename":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_rename(str(body.get("id", "")), str(body.get("name", "")), project))
            if parsed.path == "/api/studio/duplicate":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_duplicate(str(body.get("id", "")), str(body.get("name", "")), project))
            if parsed.path == "/api/studio/import":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_import(str(body.get("kind", "")), str(body.get("name", "")), str(body.get("content", "")), str(body.get("destination", "custom")), project))
            if parsed.path == "/api/studio/prompt/check":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_prompt_check(str(body.get("id", "")), str(body.get("content", "")), project))
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
            filetypes = [("Python validation", "*.py"), ("All files", "*.*")] if kind == "python" else [("All files", "*.*")]
            path = filedialog.askopenfilename(title="Choose file", filetypes=filetypes)
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        return


class UIServer(ThreadingHTTPServer):
    def __init__(self, repo_root: Path, host: str, port: int) -> None:
        state = UIState(repo_root)
        handler = type("BoundHandler", (Handler,), {"state": state})
        super().__init__((host, port), handler)
        self.port = self.server_address[1]
