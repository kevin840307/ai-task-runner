from __future__ import annotations

import json
import subprocess
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from product_settings import GlobalSettingsStore
import task_backend


try:
    from .agent_capability_service import AgentCapabilityService
    from .agent_settings_service import AgentSettingsService
    from .chat_agent_service import ChatAgentService
    from .chat_ask import demo_questions
    from .chat_service import ChatService
    from .project_preferences import ProjectPreferences
    from .chat_system_capabilities import system_capabilities
    from .task_draft_service import TaskDraftService
    from .task_service import TaskService
    from .task_run_service import TaskRunService
    from .task_upload_service import TaskUploadService
    from .project_runtime_state import ProjectRuntimeMixin
    from .workflow_builder_state import WorkflowBuilderMixin
    from .workflow_studio_state import WorkflowStudioMixin
    from .server_support import is_loopback_host
except ImportError:
    from agent_capability_service import AgentCapabilityService
    from agent_settings_service import AgentSettingsService
    from chat_agent_service import ChatAgentService
    from chat_ask import demo_questions
    from chat_service import ChatService
    from project_preferences import ProjectPreferences
    from chat_system_capabilities import system_capabilities
    from task_draft_service import TaskDraftService
    from task_service import TaskService
    from task_run_service import TaskRunService
    from task_upload_service import TaskUploadService
    from project_runtime_state import ProjectRuntimeMixin
    from workflow_builder_state import WorkflowBuilderMixin
    from workflow_studio_state import WorkflowStudioMixin
    from server_support import is_loopback_host


class UIState(ProjectRuntimeMixin, WorkflowStudioMixin, WorkflowBuilderMixin):
    def _task_workflow_requirements(self, project: Path, workflow: str) -> dict:
        selected = str(workflow or "").strip()
        default = {"exists": False, "requires_python_validator": False, "has_ai_validator": False}
        if not selected:
            return default
        try:
            rows = self.studio_files(project).get("workflows", [])
        except (OSError, ValueError):
            rows = []
        for row in rows:
            aliases = {
                str(row.get("id") or ""),
                str(row.get("name") or ""),
                str(row.get("display_name") or ""),
                str(row.get("reference") or ""),
                str(row.get("path") or ""),
            }
            if selected in aliases:
                return {
                    "exists": True,
                    "requires_python_validator": bool(row.get("requires_python_validator")),
                    "has_ai_validator": bool(row.get("has_ai_validator")),
                }
        candidate = Path(selected).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return {"exists": True, **self._workflow_requirements(candidate.resolve())}
        return default

    def _task_workflow_path(self, project: Path, workflow: str) -> Path:
        selected = str(workflow or "").strip()
        if not selected:
            raise ValueError("Task Workflow is required")
        for row in self.studio_files(project).get("workflows", []):
            aliases = {
                str(row.get("id") or ""),
                str(row.get("name") or ""),
                str(row.get("display_name") or ""),
                str(row.get("reference") or ""),
                str(row.get("path") or ""),
            }
            if selected in aliases:
                path = Path(str(row.get("path") or "")).expanduser().resolve()
                if path.is_file():
                    return path
        candidate = Path(selected).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            return candidate.resolve()
        raise ValueError("Selected Task Workflow does not exist")

    def _task_backend_default(self, project: Path) -> str:
        return str(self.backend_catalog(project).get("default") or "").strip()

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = Path(repo_root).expanduser().resolve()
        self.ui_root = self.repo_root / "ui"
        self.static_root = self.ui_root / "static"
        self.projects_file = self.ui_root / "data" / "projects.json"
        self.workflow_visibility_file = self.ui_root / "data" / "workflow_visibility.json"
        self.global_settings = GlobalSettingsStore(self.ui_root / "data" / "settings.json")
        self.projects_file.parent.mkdir(parents=True, exist_ok=True)
        self._chat_lock = threading.RLock()
        self._projects_lock = threading.RLock()
        self._runtime_lock = threading.RLock()
        self._edit_lock = threading.RLock()
        self._launch_lock = threading.RLock()
        self._builder_lock = threading.RLock()
        self._process_module = subprocess
        self._workflow_requirement_cache: dict[str, tuple[int, int, dict]] = {}
        self._workflow_catalog_cache: dict | None = None
        self.chat_service = ChatService()
        self.chat_agent = ChatAgentService(self.repo_root)
        self.agent_capabilities = AgentCapabilityService(self.repo_root)
        self.agent_settings = AgentSettingsService(self.repo_root)
        self.project_preferences = ProjectPreferences()
        self.task_drafts = TaskDraftService(
            self.repo_root,
            workflow_requirements=self._task_workflow_requirements,
        )
        self.task_uploads = TaskUploadService()
        self.tasks = TaskService(
            workflow_requirements=self._task_workflow_requirements,
            uploads=self.task_uploads,
        )
        if not self.projects_file.exists():
            self._write_projects([])
        self.ensure_project_ids()
        if not self.workflow_visibility_file.exists():
            self._atomic_json(self.workflow_visibility_file, {})
        self.task_runs = TaskRunService(
            self.tasks,
            execution_settings=lambda: self.global_settings.get()["execution"],
            preferences=self.project_preferences.get,
            backend_default=self._task_backend_default,
            resolve_workflow=self._task_workflow_path,
            launch=self.launch,
            read_runtime=self.read_runtime,
            stop_runtime=self.stop,
            resume_runtime=self.resume,
            validate_merge=task_backend.validate_merge,
        )
        self.task_runs.recover([
            Path(row["path"]).resolve()
            for row in self.projects()
            if row.get("exists")
        ])

    def chat_workflows(self, project: Path) -> list[dict]:
        """Project Chat projection of the canonical Workflow Studio catalog."""
        return [
            {
                "id": item["id"],
                "name": item["display_name"],
                "path": item["path"],
                "scope": item["scope"],
                "requires_python_validator": bool(item.get("requires_python_validator")),
                "has_ai_validator": bool(item.get("has_ai_validator")),
            }
            for item in self.studio_files(project).get("workflows", [])
            if not item.get("hidden")
        ]

    def delete_chat_session(self, project: Path, session_id: str) -> dict:
        session = str(session_id or "").strip()
        if self.chat_agent.status(
            project,
            self.chat_service,
            session_id=session,
        )["busy"]:
            raise ValueError("Stop or wait for the active Chat turn before deleting this Chat")
        value = self.chat_service.delete_session(project, session)
        self.task_drafts.discard_session(project, session)
        return value



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
            if parsed.path == "/api/settings":
                return self._json(self.state.global_settings.get())
            if parsed.path == "/api/projects":
                query = parse_qs(parsed.query)
                return self._json(
                    self.state.projects_payload(
                        exclude_runtime_path=query.get("exclude_runtime", [""])[0]
                    )
                )
            if parsed.path == "/api/project/preferences":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.project_preferences.get(project))
            if parsed.path == "/api/chat/system-capabilities":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(system_capabilities(self.state.studio_files(project)))
            if parsed.path == "/api/chat/settings-catalog":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                preferences = self.state.project_preferences.get(project)
                agent = str(
                    query.get("agent", [""])[0]
                    or preferences.get("agent")
                    or self.state.backend_catalog(project).get("default")
                    or ""
                ).strip()
                model = str(
                    query.get("model", [""])[0]
                    or preferences.get("model")
                    or ""
                ).strip()
                value = self.state.agent_settings.get(
                    project,
                    agent,
                    model,
                    refresh=query.get("refresh", ["0"])[0] == "1",
                )
                workflows = self.state.chat_workflows(project)
                backend_catalog = self.state.backend_catalog(project)
                return self._json({
                    **value,
                    "agents": backend_catalog.get("backends", []),
                    "default_agent": backend_catalog.get("default", ""),
                    "workflows": workflows,
                })
            if parsed.path == "/api/chat/capabilities":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                preferences = self.state.project_preferences.get(project)
                agent = str(
                    query.get("agent", [""])[0]
                    or preferences.get("agent")
                    or self.state.backend_catalog(project).get("default")
                    or ""
                ).strip()
                return self._json(self.state.agent_capabilities.get(
                    project,
                    agent,
                    refresh=query.get("refresh", ["0"])[0] == "1",
                ))
            if parsed.path == "/api/tasks":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.task_runs.list(project))
            if parsed.path == "/api/chat/sessions":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.chat_service.sessions(project))
            if parsed.path == "/api/chat/messages":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.chat_service.messages(
                    project,
                    query.get("session_id", [""])[0],
                ))
            if parsed.path == "/api/chat/ask":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.chat_service.ask(
                    project,
                    query.get("session_id", [""])[0],
                ))
            if parsed.path == "/api/chat/queue":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.chat_agent.status(
                    project,
                    self.state.chat_service,
                    session_id=query.get("session_id", [""])[0],
                ))
            if parsed.path == "/api/chat/events":
                query = parse_qs(parsed.query)
                project = self._project({"project": query.get("project", [""])[0]})
                return self._json(self.state.chat_service.events(
                    project,
                    query.get("session_id", [""])[0],
                    after=query.get("after", ["0"])[0],
                ))
            if parsed.path == "/api/backends":
                query = parse_qs(parsed.query)
                project = self._optional_project(query.get("project", [""])[0])
                include_models = query.get("models", ["0"])[0] == "1"
                return self._json(
                    self.state.backend_catalog(project, include_models=include_models)
                )
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
            query = parse_qs(parsed.query)
            self._api_error(
                exc,
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_request",
                retryable=False,
                request_id=query.get("request_id", [""])[0],
            )
        except Exception as exc:
            query = parse_qs(parsed.query)
            self._api_error(
                exc,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                code="internal_error",
                retryable=True,
                request_id=query.get("request_id", [""])[0],
                prefix="UI request failed: ",
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        body: dict = {}
        try:
            if parsed.path == "/api/tasks/upload/stage":
                length = int(self.headers.get("Content-Length", "0") or 0)
                if length > 12 * 1024 * 1024:
                    raise ValueError("Uploaded file is too large")
            body = self._body()
            if parsed.path == "/api/settings":
                return self._json(self.state.global_settings.update(body))
            if parsed.path == "/api/projects/add":
                project_info = self.state.add_project(str(body.get("path", "")))
                project = Path(project_info["path"]).resolve()
                if not self.state.project_preferences.get(project).get("exists"):
                    defaults = self.state.global_settings.get()["defaults"]
                    self.state.project_preferences.update(project, {
                        "agent": defaults["agent"],
                        "model": defaults["model"],
                        "mode": defaults["mode"],
                        "reasoning": defaults["reasoning"],
                        "workflow": defaults["workflow"],
                    })
                return self._json(project_info)
            if parsed.path == "/api/projects/remove":
                self.state.remove_project(str(body.get("path", "")))
                return self._json({"ok": True})
            if parsed.path == "/api/projects/rename":
                return self._json(self.state.rename_project(str(body.get("path", "")), str(body.get("name", ""))))
            if parsed.path == "/api/projects/pick":
                return self._pick_folder()
            if parsed.path == "/api/files/pick":
                return self._pick_file(
                    str(body.get("kind", "file")),
                    project=str(body.get("project", "")),
                    current=str(body.get("current", "")),
                )
            if parsed.path == "/api/tasks/upload/stage":
                project = self._project(body)
                return self._json(self.state.task_uploads.stage(
                    project,
                    item_id=body.get("item_id"),
                    kind=body.get("kind"),
                    filename=body.get("filename"),
                    content_base64=body.get("content_base64"),
                ))
            if parsed.path == "/api/tasks/upload/cancel":
                project = self._project(body)
                return self._json(self.state.task_uploads.cancel(
                    project,
                    body.get("path"),
                ))
            if parsed.path == "/api/project/preferences":
                project = self._project(body)
                before = self.state.project_preferences.get(project)
                value = self.state.project_preferences.update(project, body)
                if (
                    str(before.get("agent") or "") != str(value.get("agent") or "")
                    or str(before.get("model") or "") != str(value.get("model") or "")
                ):
                    self.state.agent_capabilities.invalidate(project)
                    self.state.agent_settings.invalidate(project)
                return self._json(value)
            if parsed.path == "/api/chat/task-draft":
                project = self._project(body)
                session_id = str(body.get("session_id", ""))
                self.state.chat_service.messages(project, session_id)
                preferences = self.state.project_preferences.get(project)
                backend = str(preferences.get("agent") or "").strip()
                if not backend:
                    backend = str(
                        self.state.backend_catalog(project).get("default") or ""
                    ).strip()
                return self._json(self.state.task_drafts.generate(
                    project,
                    spec=str(body.get("spec", "")),
                    draft_mode=str(body.get("mode", "")),
                    backend=backend,
                    model=str(preferences.get("model") or ""),
                    reasoning=str(preferences.get("reasoning") or ""),
                    workflow=str(preferences.get("workflow") or ""),
                    request_id=str(body.get("request_id", "")),
                    session_id=session_id,
                ))
            if parsed.path == "/api/chat/task-draft/update":
                project = self._project(body)
                session_id = str(body.get("session_id", ""))
                self.state.chat_service.messages(project, session_id)
                return self._json(self.state.task_drafts.update(
                    project,
                    str(body.get("draft_id", "")),
                    body.get("draft"),
                    session_id=session_id,
                ))
            if parsed.path == "/api/chat/task-draft/dismiss":
                project = self._project(body)
                session_id = str(body.get("session_id", ""))
                self.state.chat_service.messages(project, session_id)
                return self._json(self.state.task_drafts.dismiss(
                    project,
                    str(body.get("draft_id", "")),
                    session_id=session_id,
                ))
            if parsed.path == "/api/tasks/create-from-draft":
                project = self._project(body)
                session_id = str(body.get("session_id", ""))
                self.state.chat_service.messages(project, session_id)
                draft = self.state.task_drafts.get(
                    project,
                    str(body.get("draft_id", "")),
                    session_id=session_id,
                )
                identity = self.state.project_identity(project)
                return self._json(self.state.tasks.create(
                    project,
                    draft.get("draft"),
                    request_id=str(body.get("request_id", "")),
                    project_id=identity["project_id"],
                ))
            if parsed.path == "/api/tasks/validate-draft":
                project = self._project(body)
                return self._json(self.state.tasks.validate(
                    project,
                    body.get("draft"),
                ))
            if parsed.path == "/api/tasks/yaml/dump":
                project = self._project(body)
                return self._json(self.state.tasks.dump_yaml(
                    project,
                    body.get("draft"),
                ))
            if parsed.path == "/api/tasks/yaml/parse":
                project = self._project(body)
                return self._json(self.state.tasks.parse_yaml(
                    project,
                    body.get("content"),
                ))
            if parsed.path == "/api/tasks/create":
                project = self._project(body)
                identity = self.state.project_identity(project)
                return self._json(self.state.tasks.create(
                    project,
                    body.get("draft"),
                    request_id=str(body.get("request_id", "")),
                    project_id=identity["project_id"],
                ))
            if parsed.path == "/api/tasks/update":
                project = self._project(body)
                expected_updated_at = body.get("expected_updated_at")
                return self._json(self.state.tasks.update(
                    project,
                    str(body.get("task_id", "")),
                    body.get("draft"),
                    request_id=str(body.get("request_id", "")),
                    expected_updated_at=expected_updated_at,
                ))
            if parsed.path == "/api/tasks/delete":
                project = self._project(body)
                return self._json(self.state.tasks.delete(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/tasks/goal":
                project = self._project(body)
                identity = self.state.project_identity(project)
                return self._json(self.state.task_runs.start_goal(
                    project,
                    str(body.get("spec", "")),
                    request_id=str(body.get("request_id", "")),
                    project_id=identity["project_id"],
                ))
            if parsed.path == "/api/tasks/run":
                project = self._project(body)
                return self._json(self.state.task_runs.start(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/tasks/stop":
                project = self._project(body)
                return self._json(self.state.task_runs.stop(
                    project,
                    str(body.get("task_id", "")),
                ))
            if parsed.path == "/api/tasks/resume":
                project = self._project(body)
                return self._json(self.state.task_runs.resume(
                    project,
                    str(body.get("task_id", "")),
                ))
            if parsed.path == "/api/tasks/reset":
                project = self._project(body)
                return self._json(self.state.task_runs.reset(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/tasks/rerun":
                project = self._project(body)
                return self._json(self.state.task_runs.rerun(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/tasks/merge":
                project = self._project(body)
                return self._json(self.state.task_runs.merge(
                    project,
                    str(body.get("task_id", "")),
                ))
            if parsed.path == "/api/tasks/publish":
                project = self._project(body)
                return self._json(self.state.task_runs.publish(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/tasks/cleanup":
                project = self._project(body)
                return self._json(self.state.task_runs.cleanup(
                    project,
                    str(body.get("task_id", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/chat/turn":
                project = self._project(body)
                preferences = self.state.project_preferences.get(project)
                backend = str(preferences.get("agent") or "").strip()
                if not backend:
                    backend = str(
                        self.state.backend_catalog(project).get("default") or ""
                    ).strip()
                return self._json(self.state.chat_agent.turn(
                    project,
                    self.state.chat_service,
                    session_id=str(body.get("session_id", "")),
                    message=str(body.get("message", "")),
                    backend=backend,
                    model=str(preferences.get("model") or ""),
                    mode=str(preferences.get("mode") or "auto"),
                    reasoning=str(preferences.get("reasoning") or ""),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/chat/turn/cancel":
                project = self._project(body)
                return self._json(self.state.chat_agent.cancel_turn(
                    project,
                    self.state.chat_service,
                    session_id=str(body.get("session_id", "")),
                ))
            if parsed.path == "/api/chat/ask/demo":
                project = self._project(body)
                return self._json(self.state.chat_service.create_ask(
                    project,
                    str(body.get("session_id", "")),
                    request_id=str(body.get("request_id", "")),
                    turn_id=str(body.get("request_id", "")),
                    questions=demo_questions(),
                ))
            if parsed.path in {"/api/chat/ask/submit", "/api/chat/ask/cancel"}:
                project = self._project(body)
                session_id = str(body.get("session_id", ""))
                value = self.state.chat_agent.complete_ask(
                    project,
                    self.state.chat_service,
                    session_id=session_id,
                    ask_id=str(body.get("ask_id", "")),
                    request_id=str(body.get("request_id", "")),
                    answers=body.get("answers"),
                    cancelled=parsed.path.endswith("/cancel"),
                )
                queue = self.state.chat_agent.drain(
                    project,
                    self.state.chat_service,
                    session_id=session_id,
                )
                return self._json({**value, **queue})
            if parsed.path == "/api/chat/queue/drain":
                return self._json(self.state.chat_agent.drain(
                    self._project(body),
                    self.state.chat_service,
                    session_id=str(body.get("session_id", "")),
                ))
            if parsed.path == "/api/chat/queue/update":
                project = self._project(body)
                value = self.state.chat_service.update_queue_item(
                    project,
                    str(body.get("session_id", "")),
                    str(body.get("queue_item_id", "")),
                    str(body.get("message", "")),
                )
                return self._json({
                    **value,
                    "busy": self.state.chat_agent.status(
                        project,
                        self.state.chat_service,
                        session_id=str(body.get("session_id", "")),
                    )["busy"],
                })
            if parsed.path == "/api/chat/queue/delete":
                project = self._project(body)
                value = self.state.chat_service.delete_queue_item(
                    project,
                    str(body.get("session_id", "")),
                    str(body.get("queue_item_id", "")),
                )
                return self._json({
                    **value,
                    "busy": self.state.chat_agent.status(
                        project,
                        self.state.chat_service,
                        session_id=str(body.get("session_id", "")),
                    )["busy"],
                })
            if parsed.path == "/api/chat/session/create":
                return self._json(self.state.chat_service.create_session(
                    self._project(body),
                    title=str(body.get("title", "")),
                    request_id=str(body.get("request_id", "")),
                ))
            if parsed.path == "/api/chat/session/select":
                return self._json(self.state.chat_service.select_session(
                    self._project(body),
                    str(body.get("session_id", "")),
                ))
            if parsed.path == "/api/chat/session/rename":
                return self._json(self.state.chat_service.rename_session(
                    self._project(body),
                    str(body.get("session_id", "")),
                    str(body.get("title", "")),
                ))
            if parsed.path == "/api/chat/session/delete":
                return self._json(self.state.delete_chat_session(
                    self._project(body),
                    str(body.get("session_id", "")),
                ))
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
                return self._json(self.state.stop(self._project(body)))
            if parsed.path == "/api/project/resume":
                self.state.resume(self._project(body))
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
            if parsed.path == "/api/studio/stage/source":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_stage_source(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
                    str(body.get("mode", "")),
                    project,
                    fields=body.get("fields"),
                    source=str(body.get("source", "")),
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
            if parsed.path == "/api/studio/path/test":
                project = self._optional_project(str(body.get("project", "")))
                return self._json(self.state.studio_path_test(
                    str(body.get("id", "")),
                    str(body.get("stage", "")),
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
                    probe_mode=str(body.get("probe_mode", "stage")),
                    test_scenario=str(body.get("test_scenario", "pass")),
                    graph=body.get("graph"),
                    test_id=str(body.get("test_id", "")),
                ))
            if parsed.path == "/api/studio/stage/test/cancel":
                return self._json(self.state.studio_stage_test_cancel(str(body.get("test_id", ""))))
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
            self._api_error(
                exc,
                status=HTTPStatus.BAD_REQUEST,
                code="invalid_request",
                retryable=False,
                request_id=str(body.get("request_id", "")),
            )
        except Exception as exc:
            self._api_error(
                exc,
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
                code="internal_error",
                retryable=True,
                request_id=str(body.get("request_id", "")),
                prefix="UI request failed: ",
            )

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

    def _pick_file(
        self,
        kind: str = "file",
        *,
        project: str = "",
        current: str = "",
    ) -> None:
        try:
            import tkinter as tk
            from tkinter import filedialog

            initialdir = ""
            current_path = Path(str(current or "")).expanduser()
            if current_path.is_file():
                initialdir = str(current_path.resolve().parent)
            else:
                project_path = Path(str(project or "")).expanduser()
                if project_path.is_dir():
                    project_path = project_path.resolve()
                    prompt_root = project_path / ".ai-task-runner" / "assets" / "prompts"
                    initialdir = str(
                        prompt_root if kind == "markdown" and prompt_root.is_dir()
                        else project_path
                    )

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            if kind == "python":
                filetypes = [("Python validation", "*.py"), ("All files", "*.*")]
                title = "Choose File Validator"
            elif kind == "markdown":
                filetypes = [("Markdown prompt", "*.md"), ("Text prompt", "*.txt"), ("All files", "*.*")]
                title = "Choose AI Validator Prompt"
            else:
                filetypes = [("All files", "*.*")]
                title = "Choose file"
            options = {"title": title, "filetypes": filetypes}
            if initialdir:
                options["initialdir"] = initialdir
            path = filedialog.askopenfilename(**options)
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

    def _api_error(
        self,
        exc: BaseException,
        *,
        status: HTTPStatus,
        code: str,
        retryable: bool,
        request_id: str = "",
        prefix: str = "",
    ) -> None:
        message = prefix + str(exc)
        self._json(
            {
                "code": str(code),
                "message": message,
                "retryable": bool(retryable),
                "request_id": str(request_id or "").strip(),
            },
            status=status,
        )

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
        self.state = state
        self.port = self.server_address[1]
