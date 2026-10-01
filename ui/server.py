from __future__ import annotations

import json
import subprocess
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


try:
    from .project_runtime_state import ProjectRuntimeMixin
    from .workflow_builder_state import WorkflowBuilderMixin
    from .workflow_studio_state import WorkflowStudioMixin
    from .server_support import is_loopback_host
except ImportError:
    from project_runtime_state import ProjectRuntimeMixin
    from workflow_builder_state import WorkflowBuilderMixin
    from workflow_studio_state import WorkflowStudioMixin
    from server_support import is_loopback_host


class UIState(ProjectRuntimeMixin, WorkflowStudioMixin, WorkflowBuilderMixin):
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
        if not self.projects_file.exists():
            self._write_projects([])
        if not self.workflow_visibility_file.exists():
            self._atomic_json(self.workflow_visibility_file, {})



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
                return self._json(self.state.studio_generate_workflow(str(body.get("request", "")), str(body.get("backend", "")), str(body.get("filename", ""))))
            if parsed.path == "/api/studio/generate/validate":
                return self._json(self.state.studio_generate_validate(str(body.get("job_id", "")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_generate_save(project, str(body.get("job_id", "")), str(body.get("filename", body.get("name", ""))), str(body.get("destination", "global")), str(body.get("workflow", "")) if "workflow" in body else None, body.get("prompts", [])))
            if parsed.path == "/api/studio/generate/cancel":
                return self._json(self.state.studio_generate_cancel(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/generate/discard":
                return self._json(self.state.studio_generate_discard(str(body.get("job_id", ""))))
            if parsed.path == "/api/studio/workflow/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_workflow_create(str(body.get("name", "")), str(body.get("destination", "global")), project))
            if parsed.path == "/api/studio/prompt/create":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_prompt_create(str(body.get("name", "")), str(body.get("destination", "global")), project))
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
                return self._json(self.state.studio_import(str(body.get("kind", "")), str(body.get("name", "")), str(body.get("content", "")), str(body.get("destination", "global")), project))
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
            if parsed.path == "/api/studio/graph/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_graph_save(
                    str(body.get("id", "")),
                    body.get("graph", {}),
                    str(body.get("hash", "")),
                    project,
                ))
            if parsed.path == "/api/studio/stage/validate":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_save(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
                    body.get("fields", {}),
                    str(body.get("hash", "")),
                    project,
                    validate_only=True,
                ))
            if parsed.path == "/api/studio/stage/save":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_save(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
                    body.get("fields", {}),
                    str(body.get("hash", "")),
                    project,
                ))
            if parsed.path == "/api/studio/stage/test":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_test(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
                    str(body.get("input", "")),
                    project,
                    backend=str(body.get("backend", "")),
                    graph=body.get("graph"),
                ))
            if parsed.path == "/api/studio/stage/add":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_add(str(body.get("id", "")), str(body.get("stage", "")), str(body.get("type", "base")), str(body.get("hash", "")), project, status=str(body.get("status", "")), prompt=str(body.get("prompt", "")), command=str(body.get("command", "")), add_to_flow=bool(body.get("add_to_flow", True))))
            if parsed.path == "/api/studio/stage/delete":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_delete(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
                    str(body.get("hash", "")),
                    project,
                ))
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
