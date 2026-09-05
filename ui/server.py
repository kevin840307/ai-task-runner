from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

UI_STATE_DIR = ".ai-task-runner/ui"
MESSAGES_FILE = "messages.jsonl"
RUNTIME_DIR = ".ai-task-runner"


class UIState:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.ui_root = repo_root / "ui"
        self.static_root = self.ui_root / "static"
        self.projects_file = self.ui_root / "data" / "projects.json"
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.projects_file.exists():
            self._write_projects([])

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
            result.append({"name": item.get("name") or Path(path).name or path, "path": path})
        return result

    def add_project(self, path: str) -> dict:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("Project folder does not exist")
        items = [p for p in self.projects() if os.path.normcase(p["path"]) != os.path.normcase(str(resolved))]
        project = {"name": resolved.name or str(resolved), "path": str(resolved)}
        items.insert(0, project)
        self._write_projects(items)
        return project

    def remove_project(self, path: str) -> None:
        key = os.path.normcase(os.path.abspath(path))
        self._write_projects([p for p in self.projects() if os.path.normcase(os.path.abspath(p["path"])) != key])

    def _write_projects(self, items: list[dict]) -> None:
        tmp = self.projects_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.projects_file)

    def runtime_dir(self, project: Path) -> Path:
        return project / RUNTIME_DIR

    def read_runtime(self, project: Path) -> dict:
        runtime = self.runtime_dir(project)
        state = self._read_json(runtime / "state.json") or {}
        marker = self._read_json(runtime / "runner-process.json") or {}
        stream = self._display_stream(self._read_text(runtime / "stream.log", limit=12000))
        pid = marker.get("supervisor_pid")
        running = bool(pid and self._pid_alive(int(pid)))
        stale = bool(marker and not running)
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        current = int(state.get("current", 0) or 0)
        current_task = ""
        if tasks and 0 <= current < len(tasks):
            task = tasks[current]
            if isinstance(task, dict):
                current_task = str(task.get("title") or task.get("id") or "")
        return {
            "running": running,
            "stale": stale,
            "pid": pid,
            "worker_pid": marker.get("worker_pid"),
            "stage": state.get("stage") or "",
            "task": current_task,
            "current": current + 1 if tasks else 0,
            "total": len(tasks),
            "completed": bool(state.get("completed")),
            "last_error": state.get("last_error") or "",
            "stream": stream,
            "updated_at": state.get("last_activity_at") or marker.get("started_at") or 0,
        }

    def messages(self, project: Path) -> list[dict]:
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

    def append_message(self, project: Path, role: str, content: str) -> None:
        folder = project / UI_STATE_DIR
        folder.mkdir(parents=True, exist_ok=True)
        row = {"role": role, "content": content, "time": time.time()}
        with (folder / MESSAGES_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    def launch(self, project: Path, goal: str | None, *, mode: str, backend: str = "", validator: str = "", workflow: str = "") -> None:
        runtime = self.read_runtime(project)
        if runtime["running"]:
            raise ValueError("This project already has an active runtime")
        command = [sys.executable, str(self.repo_root / "ai_task_runner.py"), "--project-root", str(project)]
        if mode == "resume":
            command.append("--resume")
        else:
            if not goal:
                raise ValueError("Goal is required")
            command += ["--goal", goal]
            if mode == "rerun":
                command.append("--force-new")
        if backend:
            command += ["--backend", backend]
        if validator:
            command += ["--validator", validator]
        if workflow:
            command += ["--workflow", workflow]
        kwargs: dict = {
            "cwd": str(self.repo_root),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "close_fds": True,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        else:
            kwargs["start_new_session"] = True
        subprocess.Popen(command, **kwargs)

    def stop(self, project: Path) -> None:
        runtime = self.runtime_dir(project)
        runtime.mkdir(parents=True, exist_ok=True)
        (runtime / "stop.request").write_text("stop\n", encoding="utf-8")


    @classmethod
    def _display_stream(cls, raw: str) -> str:
        """Return UI-safe live activity without reasoning/thinking fields."""
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
                if not cls._looks_private_reasoning(line):
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
        if cls._looks_private_reasoning(key):
            return
        if isinstance(value, dict):
            event_type = str(value.get("type", "")).lower()
            if cls._looks_private_reasoning(event_type):
                return
            preferred = ("content", "text", "output", "command", "name", "tool")
            used = False
            for field in preferred:
                if field in value and not cls._looks_private_reasoning(field):
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
        if isinstance(value, str) and value.strip() and not cls._looks_private_reasoning(value):
            out.append(value)

    @staticmethod
    def _looks_private_reasoning(text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ("reasoning", "thinking", "chain_of_thought", "chain-of-thought", "analysis"))

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
        return str((self.state.static_root / clean).resolve())

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/projects":
            return self._json({"projects": self.state.projects()})
        if parsed.path.startswith("/api/project/"):
            return self._project_get(parsed.path)
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            body = self._body()
            if parsed.path == "/api/projects/add":
                project = self.state.add_project(str(body.get("path", "")))
                return self._json(project)
            if parsed.path == "/api/projects/remove":
                self.state.remove_project(str(body.get("path", "")))
                return self._json({"ok": True})
            if parsed.path == "/api/projects/pick":
                return self._pick_folder()
            if parsed.path == "/api/project/message":
                project = self._project(body)
                text = str(body.get("message", "")).strip()
                if not text:
                    raise ValueError("Message is empty")
                self.state.append_message(project, "user", text)
                self.state.launch(
                    project,
                    text,
                    mode="run",
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
            if parsed.path == "/api/project/rerun":
                project = self._project(body)
                last = next((m["content"] for m in reversed(self.state.messages(project)) if m.get("role") == "user"), "")
                self.state.launch(project, last, mode="rerun", backend=str(body.get("backend", "")), validator=str(body.get("validator", "")), workflow=str(body.get("workflow", "")))
                return self._json({"ok": True})
            self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"error": f"UI request failed: {exc}"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)

    def _project_get(self, path: str) -> None:
        from urllib.parse import parse_qs
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
        return self._json(self.state.add_project(path))

    def _project(self, body: dict) -> Path:
        path = str(body.get("project", "")).strip()
        if not path:
            raise ValueError("Project is required")
        project = Path(path).expanduser().resolve()
        if not project.is_dir():
            raise ValueError("Project folder does not exist")
        return project

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
