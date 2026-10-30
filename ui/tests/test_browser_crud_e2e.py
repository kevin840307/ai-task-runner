from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from ui.chat_ask import demo_questions
from ui.server import UIState
from ui.task_draft_service import TaskDraftService

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

BROWSER_REQUIRED = os.environ.get("AI_TASK_RUNNER_BROWSER_REQUIRED") == "1"
BROWSER_DEFAULT_TIMEOUT_MS = 8_000



def _chromium_executable() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and Path(configured).exists():
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _browser_unavailable() -> bool:
    return sync_playwright is None or not BROWSER_REQUIRED


def _launch_browser(playwright):
    executable = _chromium_executable()
    kwargs = {"headless": True, "args": ["--no-sandbox"]}
    if executable:
        kwargs["executable_path"] = executable
    return playwright.chromium.launch(**kwargs)


def _load_main_ui_document(page, html: str) -> None:
    # Use a real HTTP origin so localStorage/history/relative fetch behave like
    # production. <base href> alone does not change about:blank's opaque origin.
    page.route(
        "http://local.test/",
        lambda route: route.fulfill(status=200, content_type="text/html", body=html),
    )
    page.goto("http://local.test/", wait_until="domcontentloaded")


def _install_main_ui_styles(page, static_root: Path) -> None:
    """Install CSS in the same cascade order as production styles.css."""
    manifest = (static_root / "styles.css").read_text(encoding="utf-8")
    imports = re.findall(r'@import url\("([^"]+)"\);', manifest)
    assert imports, "styles.css must own the production stylesheet order"
    for href in imports:
        relative = href[2:] if href.startswith("./") else href
        page.add_style_tag(path=str(static_root / relative))


def _install_main_ui_scripts(page, static_root: Path) -> None:
    # app.js is a real ES module. Route the module graph through the same HTTP
    # origin as the document instead of injecting app.js as a classic script.
    for relative in ("app.js", "js/ui-lifecycle.js", "js/workflow-generator.js", "js/project-chat.js", "js/task-workspace.js", "js/task-runtime-panel.js", "js/tasks-board.js"):
        source = static_root / relative
        page.route(
            f"http://local.test/{relative}",
            lambda route, _request, source=source: route.fulfill(
                status=200,
                content_type="text/javascript",
                body=source.read_text(encoding="utf-8"),
            ),
        )
    page.add_script_tag(path=str(static_root / "js" / "ui-bootstrap.js"))
    page.add_script_tag(path=str(static_root / "js" / "i18n.js"))
    page.add_script_tag(path=str(static_root / "js" / "ui-dialogs.js"))
    page.add_script_tag(path=str(static_root / "js" / "studio-support.js"))
    page.add_script_tag(url="http://local.test/app.js", type="module")


def _boot_main_ui(page, expected_project: str = "Fixture Project") -> None:
    # app.js performs its production bootstrap immediately as an ES module.
    page.wait_for_function(
        "(name) => document.querySelector('#projectName')?.textContent === name",
        arg=expected_project,
        timeout=8000,
    )


def _write_fixture_repo(root: Path) -> UIState:
    (root / "ui" / "data").mkdir(parents=True)
    (root / "ui" / "data" / "projects.json").write_text(
        json.dumps([{"name": "Fixture Project", "path": str(root)}]),
        encoding="utf-8",
    )
    for relative in (
        "runner/assets/workflows",
        "runner/assets/prompts/common",
        "runner/agent",
        "runner/config",
        "tool",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    prompts = root / "runner" / "assets" / "prompts" / "common"
    (prompts / "generic.md").write_text("{{ goal }}\n{{ instructions }}\n", encoding="utf-8")
    (prompts / "execution.md").write_text("{{ goal }}\n", encoding="utf-8")
    (prompts / "review.md").write_text("{{ goal }}\n", encoding="utf-8")
    (root / "runner" / "agent" / "qwen.py").write_text(
        "class QwenBackend:\n    name='qwen'\n",
        encoding="utf-8",
    )
    (root / "runner" / "config" / "defaults.py").write_text(
        "DEFAULT_BACKEND='qwen'\n",
        encoding="utf-8",
    )
    (root / "runner" / "prompting.py").write_text(
        "def build_stage_prompt_context(ctx, stage, previous=None):\n"
        "    return {'goal':'','project':{'root':''},'task':{'title':''},'stage':stage}\n"
        "def render_prompt(name, values=None): return ''\n"
        "def ai_rules(root): return ''\n",
        encoding="utf-8",
    )
    (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
        "stages:\n"
        "  execute:\n"
        "    type: base\n"
        "    profile: execute\n"
        "    prompt: common/execution.md\n"
        "flow:\n"
        "  - execute\n",
        encoding="utf-8",
    )
    (root / "tool" / "workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed':True,'valid':True,'paths_passed':1,'paths_total':1}))\n",
        encoding="utf-8",
    )
    state = UIState(root)
    # Keep the broad browser suite deterministic in English; the localization
    # contract below explicitly exercises zh-TW and en at runtime.
    state.global_settings.update({"language": "en"})

    def browser_task_draft_runner(**kwargs):
        spec = str(kwargs.get("spec", ""))
        if spec == "mock:error":
            raise ValueError("Browser TaskDraft backend failure")
        if spec == "mock:invalid":
            raise ValueError("TaskDraft generator returned invalid structured data")
        count = 2 if kwargs.get("draft_mode") == "list" else 1
        return {
            "draft": {
                "schema_version": 1,
                "title": "Browser generated draft",
                "project": str(root),
                "items": [
                    {
                        "title": f"Draft item {index + 1}",
                        "prompt": f"Do browser item {index + 1}",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "auto",
                    }
                    for index in range(count)
                ],
            }
        }

    state.task_drafts = TaskDraftService(root, runner=browser_task_draft_runner)
    return state


def _bridge_for(state: UIState):
    def bridge(method: str, url: str, body_json: str):
        try:
            body = json.loads(body_json or "{}")
            parsed = urlparse(url)
            query = parse_qs(parsed.query)
            path = parsed.path
            project_value = query.get("project", [""])[0]
            project = Path(project_value) if project_value else None
            if method == "GET":
                if path == "/api/settings":
                    data = state.global_settings.get()
                elif path == "/api/projects":
                    data = {
                        "projects": state.projects(
                            exclude_runtime_path=query.get("exclude_runtime", [""])[0]
                        )
                    }
                elif path == "/api/project/preferences":
                    data = state.project_preferences.get(project)
                elif path == "/api/tasks":
                    data = state.task_runs.list(project)
                elif path == "/api/tasks/workspace-options":
                    data = state.task_runs.workspace_options(
                        project,
                        current_task_id=query.get("task_id", [""])[0],
                    )
                elif path == "/api/chat/ask":
                    session_id = query.get("session_id", [""])[0]
                    data = state.chat_service.ask(project, session_id)
                elif path == "/api/chat/events":
                    session_id = query.get("session_id", [""])[0]
                    data = state.chat_service.events(
                        project,
                        session_id,
                        after=query.get("after", ["0"])[0],
                    )
                elif path == "/api/chat/queue":
                    session_id = query.get("session_id", [""])[0]
                    queue = getattr(state, "_browser_chat_queue", {}).get(session_id, [])
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    busy = bool(busy_map.get(session_id, False))
                    data = {
                        "session_id": session_id,
                        "items": list(queue),
                        "dispatching": None,
                        "busy": busy,
                        "status": "busy" if busy else "idle",
                    }
                elif path == "/api/chat/system-capabilities":
                    data = {
                        "capabilities": [
                            {
                                "token": "@ask-demo", "name": "ask-demo", "description": "Ask demo",
                                "kind": "chat_test_command", "source": "Chat",
                                "user_invocable": True, "enabled": True,
                                "permission": "explicit", "availability": "available",
                            },
                            {
                                "token": "@goal", "name": "goal", "description": "Run goal",
                                "kind": "runner_command", "source": "Runner",
                                "user_invocable": True, "enabled": True,
                                "permission": "explicit", "availability": "available",
                            },
                            {
                                "token": "@task", "name": "task", "description": "Generate TaskDraft",
                                "kind": "runner_command", "source": "Runner",
                                "user_invocable": True, "enabled": True,
                                "permission": "explicit", "availability": "available",
                            },
                            {
                                "token": "@task-single", "name": "task-single", "description": "Generate one TaskDraft item",
                                "kind": "runner_command", "source": "Runner",
                                "user_invocable": True, "enabled": True,
                                "permission": "explicit", "availability": "available",
                            },
                            {
                                "token": "@task-list", "name": "task-list", "description": "Generate TaskDraft list",
                                "kind": "runner_command", "source": "Runner",
                                "user_invocable": True, "enabled": True,
                                "permission": "explicit", "availability": "available",
                            },
                        ]
                    }
                elif path == "/api/chat/settings-catalog":
                    selected_agent = query.get("agent", ["qwen"])[0] or "qwen"
                    selected_model = query.get("model", [""])[0]
                    if selected_agent == "opencode":
                        models = ["openai/gpt-5.2"]
                        reasoning = [
                            {"id": "low", "label": "Low", "native": "openai/gpt-5.2#low", "description": "Low", "default": False},
                            {"id": "deep", "label": "Deep", "native": "openai/gpt-5.2#deep", "description": "Deep", "default": True},
                        ] if selected_model else []
                    else:
                        models = ["qwen/model-a"]
                        reasoning = [
                            {"id": "low", "label": "Low", "native": "low", "description": "Low", "default": False},
                            {"id": "medium", "label": "Medium", "native": "medium", "description": "Medium", "default": True},
                            {"id": "high", "label": "High", "native": "high", "description": "High", "default": False},
                        ]
                    data = {
                        "agent": selected_agent,
                        "agents": ["qwen", "opencode"],
                        "default_agent": "qwen",
                        "models": models,
                        "modes": [
                            {"id": "read", "native": "native-read", "description": "Read only", "supported": True, "unsafe": False},
                            {"id": "auto", "native": "native-auto", "description": "Safe automatic approvals", "supported": True, "unsafe": False},
                            {"id": "yolo", "native": "native-yolo", "description": "Approve all tools", "supported": True, "unsafe": True},
                        ],
                        "reasoning": reasoning,
                        "features": {
                            "ask": selected_agent == "opencode",
                            "ask_transport": "question_api" if selected_agent == "opencode" else "",
                            "queue_mode": "service_fifo",
                            "detail": "Native Ask available" if selected_agent == "opencode" else "Native Ask unavailable",
                        },
                        "workflows": state.chat_workflows(project),
                        "cached": False,
                    }
                elif path == "/api/chat/capabilities":
                    selected_agent = query.get("agent", ["qwen"])[0] or "qwen"
                    if selected_agent == "opencode":
                        capabilities = [
                            {
                                "token": "/review", "name": "review", "description": "Review code",
                                "kind": "skill", "source": "project", "user_invocable": True,
                                "enabled": True, "permission": "ask", "availability": "available",
                            },
                            {
                                "token": "/deploy", "name": "deploy", "description": "Deploy through OpenCode",
                                "kind": "skill", "source": "project", "user_invocable": True,
                                "enabled": True, "permission": "ask", "availability": "available",
                            },
                        ]
                    else:
                        capabilities = [
                            {
                                "token": "/btw", "name": "btw", "description": "Qwen side question",
                                "kind": "command", "source": "builtin", "user_invocable": True,
                                "enabled": True, "permission": "available", "availability": "available",
                            },
                            {
                                "token": "/qreview", "name": "qreview", "description": "Qwen review skill",
                                "kind": "skill", "source": "project", "user_invocable": True,
                                "enabled": True, "permission": "available", "availability": "available",
                            },
                            {
                                "token": "/hidden", "name": "hidden", "description": "Hidden skill",
                                "kind": "skill", "source": "user", "user_invocable": False,
                                "enabled": False, "permission": "deny", "availability": "disabled",
                            },
                        ]
                    data = {
                        "agent": selected_agent,
                        "capabilities": capabilities,
                        "cached": False,
                    }
                elif path == "/api/chat/sessions":
                    data = state.chat_service.sessions(project)
                elif path == "/api/chat/messages":
                    data = state.chat_service.messages(project, query.get("session_id", [""])[0])
                elif path == "/api/project/messages":
                    data = {"messages": []}
                elif path == "/api/project/runs":
                    data = {"runs": state.run_history(project) if project is not None else []}
                elif path == "/api/project/runtime":
                    override = getattr(state, "_browser_runtime_override", None)
                    data = dict(override) if isinstance(override, dict) else state.read_runtime(project)
                    data["recent_transitions"] = [
                        {
                            "stage": "execute", "status": "pass", "target": "review",
                            "cycle": 1, "kind": "task", "timestamp": 1.0,
                        },
                        {
                            "stage": "review", "status": "fail", "target": "execute",
                            "cycle": 1, "kind": "review", "timestamp": 2.0,
                        },
                    ]
                elif path == "/api/workflow/catalog":
                    data = {"stage_types": {}, "node_options": {}}
                elif path == "/api/environment/check":
                    data = {
                        "ok": True,
                        "status": "pass",
                        "checks": [
                            {"name": "Python", "status": "pass", "detail": "Ready"},
                            {"name": "Backend", "status": "pass", "detail": "Ready"},
                        ],
                    }
                elif path == "/api/backends":
                    data = {
                        "backends": ["qwen", "opencode"],
                        "default": "qwen",
                        "models": {},
                    }
                elif path == "/api/studio/files":
                    data = state.studio_files(project)
                elif path == "/api/studio/file":
                    data = state.studio_read(query.get("id", [""])[0], project)
                elif path == "/api/studio/visual":
                    data = state.studio_visual(query.get("id", [""])[0], project)
                elif path == "/api/studio/guard":
                    data = state.edit_guard()
                elif path == "/api/studio/prompt-tags":
                    data = state.studio_prompt_tags(query.get("id", [""])[0], None)
                elif path == "/api/studio/generate/active":
                    data = {"active": False}
                else:
                    raise ValueError(f"Unhandled browser E2E GET {path}")
            else:
                if path == "/api/settings":
                    data = state.global_settings.update(body)
                elif path == "/api/projects/add":
                    data = state.add_project(str(body.get("path", "")))
                    added_project = Path(data["path"]).resolve()
                    if not state.project_preferences.get(added_project).get("exists"):
                        defaults = state.global_settings.get()["defaults"]
                        state.project_preferences.update(added_project, {
                            "agent": defaults["agent"],
                            "model": defaults["model"],
                            "mode": defaults["mode"],
                            "reasoning": defaults["reasoning"],
                            "workflow": defaults["workflow"],
                        })
                elif path == "/api/projects/rename":
                    data = state.rename_project(str(body.get("path", "")), str(body.get("name", "")))
                elif path == "/api/projects/remove":
                    state.remove_project(str(body.get("path", "")))
                    data = {"ok": True}
                elif path == "/api/project/preferences":
                    data = state.project_preferences.update(Path(body["project"]), body)
                elif path == "/api/chat/task-draft":
                    project_path = Path(body["project"])
                    session_id = str(body.get("session_id", ""))
                    state.chat_service.messages(project_path, session_id)
                    data = state.task_drafts.generate(
                        project_path,
                        spec=str(body.get("spec", "")),
                        draft_mode=str(body.get("mode", "auto")),
                        backend="qwen",
                        workflow="workflow.yaml",
                        request_id=str(body.get("request_id", "")),
                        session_id=session_id,
                    )
                elif path == "/api/chat/task-draft/update":
                    project_path = Path(body["project"])
                    session_id = str(body.get("session_id", ""))
                    state.chat_service.messages(project_path, session_id)
                    data = state.task_drafts.update(
                        project_path,
                        str(body.get("draft_id", "")),
                        body.get("draft"),
                        session_id=session_id,
                    )
                elif path == "/api/chat/task-draft/dismiss":
                    project_path = Path(body["project"])
                    session_id = str(body.get("session_id", ""))
                    state.chat_service.messages(project_path, session_id)
                    data = state.task_drafts.dismiss(
                        project_path,
                        str(body.get("draft_id", "")),
                        session_id=session_id,
                    )
                elif path == "/api/tasks/upload/stage":
                    data = state.task_uploads.stage(
                        Path(body["project"]),
                        item_id=body.get("item_id"),
                        kind=body.get("kind"),
                        filename=body.get("filename"),
                        content_base64=body.get("content_base64"),
                    )
                elif path == "/api/tasks/upload/cancel":
                    data = state.task_uploads.cancel(
                        Path(body["project"]),
                        body.get("path"),
                    )
                elif path == "/api/tasks/validate-draft":
                    data = state.tasks.validate(
                        Path(body["project"]),
                        body.get("draft"),
                    )
                elif path == "/api/tasks/yaml/dump":
                    data = state.tasks.dump_yaml(
                        Path(body["project"]),
                        body.get("draft"),
                    )
                elif path == "/api/tasks/yaml/parse":
                    data = state.tasks.parse_yaml(
                        Path(body["project"]),
                        body.get("content"),
                    )
                elif path == "/api/tasks/goal":
                    project_path = Path(body["project"])
                    spec = str(body.get("spec", "")).strip()
                    request = str(body.get("request_id", "")).strip()
                    if not spec:
                        raise ValueError("@goal spec is required")
                    workflow = str(state.project_preferences.get(project_path).get("workflow") or "").strip() or "workflow.yaml"
                    task = state.tasks.create(
                        project_path,
                        {
                            "title": spec[:160],
                            "items": [{
                                "title": spec[:160],
                                "prompt": spec,
                                "workflow": workflow,
                                "project": str(project_path.resolve()),
                                "workspace": "auto",
                            }],
                        },
                        request_id="browser-goal-create-" + request,
                        project_id=state.project_identity(project_path)["project_id"],
                    )
                    run_request = "browser-goal-run-" + request
                    existing_run = state.tasks.run_request(project_path, run_request)
                    if existing_run is None:
                        run_number = int(task.get("run_count", 0)) + 1
                        workspace = {
                            "task_id": task["task_id"],
                            "run_number": run_number,
                            "requested_mode": "auto",
                            "effective_mode": "worktree",
                            "target_branch": "browser-target",
                            "target_head_sha_at_start": "browser-head",
                            "task_branch": f"local/task/{task['task_id']}-r{run_number}",
                            "task_base_sha": "browser-head",
                            "repository_root": str(project_path.resolve()),
                            "repository_identity": str(project_path.resolve()),
                            "source_project_root": str(project_path.resolve()),
                            "worktree_path": str(project_path / ".browser-worktrees" / task["task_id"]),
                            "project_root": str(project_path.resolve()),
                        }
                        state.tasks.begin_run(
                            project_path, task["task_id"], request_id=run_request, workspace=workspace
                        )
                        state.tasks.transition_run(
                            project_path, task["task_id"], run_number, phase="running", status="ongoing"
                        )
                    data = {
                        **state.tasks.get(project_path, task["task_id"]),
                        "goal_run_started": True,
                        "goal_run_error": "",
                    }
                elif path == "/api/tasks/create":
                    state._browser_last_direct_task_create_draft = json.loads(
                        json.dumps(body.get("draft"))
                    )
                    data = state.tasks.create(
                        Path(body["project"]),
                        body.get("draft"),
                        request_id=str(body.get("request_id", "")),
                        project_id=state.project_identity(Path(body["project"]))["project_id"],
                    )
                elif path == "/api/tasks/create-from-draft":
                    project_path = Path(body["project"])
                    session_id = str(body.get("session_id", ""))
                    state.chat_service.messages(project_path, session_id)
                    canonical = state.task_drafts.get(
                        project_path,
                        str(body.get("draft_id", "")),
                        session_id=session_id,
                    )
                    state._browser_last_create_from_draft = json.loads(
                        json.dumps(canonical["draft"])
                    )
                    data = state.tasks.create(
                        project_path,
                        canonical["draft"],
                        request_id=str(body.get("request_id", "")),
                        project_id=state.project_identity(project_path)["project_id"],
                    )
                elif path == "/api/tasks/update":
                    data = state.tasks.update(
                        Path(body["project"]),
                        str(body.get("task_id", "")),
                        body.get("draft"),
                        request_id=str(body.get("request_id", "")),
                        expected_updated_at=body.get("expected_updated_at"),
                    )
                elif path == "/api/tasks/move-existing":
                    data = state.tasks.move_existing(
                        Path(body["project"]),
                        str(body.get("target_task_id", "")),
                        str(body.get("source_task_id", "")),
                        request_id=str(body.get("request_id", "")),
                        expected_updated_at=body.get("expected_updated_at"),
                    )
                elif path == "/api/tasks/delete":
                    data = state.tasks.delete(
                        Path(body["project"]),
                        str(body.get("task_id", "")),
                        request_id=str(body.get("request_id", "")),
                    )
                elif path == "/api/tasks/reset":
                    data = state.tasks.reset_to_new(
                        Path(body["project"]),
                        str(body.get("task_id", "")),
                        request_id=str(body.get("request_id", "")),
                        action="reset",
                    )
                elif path == "/api/tasks/rerun":
                    actions = getattr(state, "_browser_task_lifecycle_actions", [])
                    actions.append(("rerun", str(body.get("task_id", ""))))
                    state._browser_task_lifecycle_actions = actions
                    data = state.tasks.get(
                        Path(body["project"]),
                        str(body.get("task_id", "")),
                    )
                elif path == "/api/tasks/publish":
                    project_path = Path(body["project"])
                    task_id = str(body.get("task_id", ""))
                    task = state.tasks.get(project_path, task_id)
                    run = task.get("run") or {}
                    result = dict(run.get("workspace_result") or {})
                    source = (result.get("merge_source") or {}).get("workspace") or {}
                    merge = result.get("merge") or {}
                    merge_status = str(merge.get("status") or run.get("phase") or "")
                    branch = (
                        str(source.get("target_branch") or (run.get("workspace") or {}).get("target_branch") or "")
                        if merge_status in {"merged", "no_changes"}
                        else str(source.get("task_branch") or result.get("branch") or (run.get("workspace") or {}).get("task_branch") or "")
                    )
                    snapshot = result.get("snapshot") or {}
                    result["publish"] = {
                        "status": "published",
                        "branch": branch,
                        "sha": str(snapshot.get("task_snapshot_sha") or merge.get("merged_target_head_sha") or ""),
                        "remote": "origin",
                        "detail": "",
                        "request_id": str(body.get("request_id", "")),
                    }
                    actions = getattr(state, "_browser_publish_actions", [])
                    actions.append((task_id, branch))
                    state._browser_publish_actions = actions
                    data = state.tasks.transition_run(
                        project_path,
                        task_id,
                        int(run.get("run_number") or 0),
                        phase=str(run.get("phase") or merge_status),
                        status=str(task.get("status") or "closed"),
                        workspace_result=result,
                    )
                elif path == "/api/tasks/cleanup":
                    project_path = Path(body["project"])
                    task_id = str(body.get("task_id", ""))
                    task = state.tasks.get(project_path, task_id)
                    result = state.tasks.record_workspace_cleanup(
                        project_path,
                        task_id,
                        request_id=str(body.get("request_id", "")),
                        results=[{
                            "status": "cleaned",
                            "branch": str((task.get("run") or {}).get("workspace", {}).get("task_branch") or ""),
                            "worktree_path": str((task.get("run") or {}).get("workspace", {}).get("worktree_path") or ""),
                            "detail": "",
                        }],
                    )
                    actions = getattr(state, "_browser_cleanup_actions", [])
                    actions.append(task_id)
                    state._browser_cleanup_actions = actions
                    data = result
                elif path == "/api/chat/ask/demo":
                    session_id = str(body.get("session_id", ""))
                    data = state.chat_service.create_ask(
                        Path(body["project"]),
                        session_id,
                        request_id=str(body.get("request_id", "")),
                        turn_id=str(body.get("request_id", "")),
                        questions=demo_questions(),
                    )
                elif path == "/api/chat/turn":
                    session_id = str(body.get("session_id", ""))
                    message = str(body.get("message", ""))
                    pending_ask = state.chat_service.ask(Path(body["project"]), session_id).get("ask")
                    if isinstance(pending_ask, dict) and pending_ask.get("status") == "waiting":
                        queues = getattr(state, "_browser_chat_queue", {})
                        queue = queues.setdefault(session_id, [])
                        queue.append({
                            "queue_item_id": f"queue-{len(queue) + 1:032x}",
                            "content": message,
                            "created_at": len(queue) + 1,
                            "status": "queued",
                        })
                        state._browser_chat_queue = queues
                        busy_map = getattr(state, "_browser_chat_busy", {})
                        busy_map[session_id] = True
                        state._browser_chat_busy = busy_map
                        data = {
                            "session_id": session_id,
                            "items": list(queue),
                            "dispatching": None,
                            "busy": True,
                            "status": "waiting_ask",
                        }
                    elif (
                        message == "queue browser message"
                        or bool(getattr(state, "_browser_chat_busy", {}).get(session_id, False))
                    ):
                        queues = getattr(state, "_browser_chat_queue", {})
                        queue = queues.setdefault(session_id, [])
                        queue.append({
                            "queue_item_id": f"queue-{len(queue) + 1:032x}",
                            "content": message,
                            "created_at": len(queue) + 1,
                            "status": "queued",
                        })
                        state._browser_chat_queue = queues
                        busy_map = getattr(state, "_browser_chat_busy", {})
                        busy_map[session_id] = True
                        state._browser_chat_busy = busy_map
                        data = {
                            "session_id": session_id,
                            "items": list(queue),
                            "dispatching": None,
                            "busy": True,
                            "status": "queued",
                        }
                    else:
                        user = state.chat_service.append_message(
                            Path(body["project"]), session_id, "user", message
                        )
                        assistant = state.chat_service.append_message(
                            Path(body["project"]), session_id, "assistant", "Browser Chat reply"
                        )
                        data = {"session_id": session_id, "messages": [user, assistant], "items": [], "busy": False}
                elif path == "/api/chat/turn/cancel":
                    session_id = str(body.get("session_id", ""))
                    queues = getattr(state, "_browser_chat_queue", {})
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    was_busy = bool(busy_map.get(session_id, False))
                    busy_map[session_id] = False
                    state._browser_chat_busy = busy_map
                    data = {
                        "session_id": session_id,
                        "items": list(queues.get(session_id, [])),
                        "dispatching": None,
                        "busy": False,
                        "status": "idle",
                        "cancelled": was_busy,
                        "duplicate": not was_busy,
                    }
                elif path in {"/api/chat/ask/submit", "/api/chat/ask/cancel"}:
                    session_id = str(body.get("session_id", ""))
                    if path.endswith("/submit"):
                        data = state.chat_service.submit_ask(
                            Path(body["project"]),
                            session_id,
                            str(body.get("ask_id", "")),
                            body.get("answers"),
                            request_id=str(body.get("request_id", "")),
                        )
                    else:
                        data = state.chat_service.cancel_ask(
                            Path(body["project"]),
                            session_id,
                            str(body.get("ask_id", "")),
                            request_id=str(body.get("request_id", "")),
                        )
                    queues = getattr(state, "_browser_chat_queue", {})
                    queued = list(queues.get(session_id, []))
                    for item in queued:
                        state.chat_service.append_message(
                            Path(body["project"]), session_id, "user", str(item["content"])
                        )
                        state.chat_service.append_message(
                            Path(body["project"]), session_id, "assistant", "Browser queued reply · " + str(item["content"])
                        )
                    queues[session_id] = []
                    state._browser_chat_queue = queues
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    busy_map[session_id] = False
                    state._browser_chat_busy = busy_map
                    data = {
                        **data,
                        "items": [],
                        "dispatching": None,
                        "busy": False,
                        "status": "idle",
                    }
                elif path == "/api/chat/queue/update":
                    session_id = str(body.get("session_id", ""))
                    queue = getattr(state, "_browser_chat_queue", {}).get(session_id, [])
                    for item in queue:
                        if item["queue_item_id"] == str(body.get("queue_item_id", "")):
                            item["content"] = str(body.get("message", ""))
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    data = {"session_id": session_id, "items": list(queue), "busy": bool(busy_map.get(session_id, False))}
                elif path == "/api/chat/queue/delete":
                    session_id = str(body.get("session_id", ""))
                    queues = getattr(state, "_browser_chat_queue", {})
                    queues[session_id] = [
                        item for item in queues.get(session_id, [])
                        if item["queue_item_id"] != str(body.get("queue_item_id", ""))
                    ]
                    state._browser_chat_queue = queues
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    if not queues[session_id]:
                        busy_map[session_id] = False
                    state._browser_chat_busy = busy_map
                    data = {"session_id": session_id, "items": list(queues[session_id]), "busy": bool(busy_map.get(session_id, False))}
                elif path == "/api/chat/session/create":
                    data = state.chat_service.create_session(
                        Path(body["project"]),
                        title=str(body.get("title", "")),
                        request_id=str(body.get("request_id", "")),
                    )
                elif path == "/api/chat/session/select":
                    if bool(getattr(state, "_browser_chat_select_fail", False)):
                        state._browser_chat_select_fail = False
                        raise ValueError("Injected Chat select failure")
                    data = state.chat_service.select_session(Path(body["project"]), str(body.get("session_id", "")))
                elif path == "/api/chat/session/rename":
                    data = state.chat_service.rename_session(
                        Path(body["project"]), str(body.get("session_id", "")), str(body.get("title", ""))
                    )
                elif path == "/api/chat/session/delete":
                    session_id = str(body.get("session_id", ""))
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    if bool(busy_map.get(session_id, False)):
                        raise ValueError("Stop or wait for the active Chat turn before deleting this Chat")
                    data = state.delete_chat_session(Path(body["project"]), session_id)
                    getattr(state, "_browser_chat_queue", {}).pop(session_id, None)
                    busy_map.pop(session_id, None)
                elif path == "/api/studio/prompt/create":
                    data = state.studio_prompt_create(
                        body.get("name", ""),
                        body.get("destination", "global"),
                        Path(body["project"]) if body.get("project") else project,
                    )
                elif path == "/api/studio/workflow/create":
                    data = state.studio_workflow_create(
                        body.get("name", ""),
                        body.get("destination", "global"),
                        Path(body["project"]) if body.get("project") else project,
                    )
                elif path == "/api/studio/prompt/check":
                    data = state.studio_prompt_check(
                        body.get("id", ""), body.get("content", ""), None
                    )
                elif path == "/api/studio/check":
                    data = state.studio_check(
                        body.get("id", ""), body.get("content", ""), None
                    )
                elif path == "/api/studio/save":
                    data = state.studio_save(
                        body.get("id", ""),
                        body.get("content", ""),
                        body.get("hash", ""),
                        None,
                    )
                elif path == "/api/studio/validate":
                    data = state.studio_validate(
                        body.get("id", ""),
                        None,
                        content=body.get("content"),
                        flow=body.get("flow"),
                    )
                elif path == "/api/studio/stage/add":
                    data = state.studio_stage_add(
                        body.get("id", ""),
                        body.get("stage", ""),
                        body.get("type", "base"),
                        body.get("hash", ""),
                        None,
                        status=body.get("status", ""),
                        prompt=body.get("prompt", ""),
                        command=body.get("command", ""),
                        add_to_flow=body.get("add_to_flow", True),
                    )
                elif path == "/api/studio/stage/save":
                    data = state.studio_stage_save(
                        body.get("id", ""),
                        body.get("stage", ""),
                        body.get("fields", {}),
                        body.get("hash", ""),
                        None,
                    )
                elif path == "/api/studio/stage/delete":
                    data = state.studio_stage_delete(
                        body.get("id", ""),
                        body.get("stage", ""),
                        body.get("hash", ""),
                        None,
                    )
                elif path == "/api/studio/duplicate":
                    data = state.studio_duplicate(
                        body.get("id", ""), body.get("name", ""), None
                    )
                elif path == "/api/studio/rename":
                    data = state.studio_rename(
                        body.get("id", ""), body.get("name", ""), None
                    )
                elif path == "/api/project/rerun":
                    calls = getattr(state, "_browser_runtime_actions", [])
                    calls.append("rerun")
                    state._browser_runtime_actions = calls
                    data = {"ok": True}
                elif path == "/api/studio/delete":
                    data = state.studio_delete(body.get("id", ""), None)
                elif path == "/api/studio/visibility":
                    data = state.studio_set_workflow_hidden(
                        body.get("id", ""), bool(body.get("hidden", False)), None
                    )
                else:
                    raise ValueError(f"Unhandled browser E2E POST {path}")
            return {"status": 200, "data": data}
        except Exception as exc:
            request_id = str(body.get("request_id", "")) if isinstance(body, dict) else ""
            return {
                "status": 400,
                "data": {
                    "code": "invalid_request",
                    "message": str(exc),
                    "retryable": False,
                    "request_id": request_id,
                },
            }

    return bridge


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_lifecycle_reset_and_rerun_require_confirmation() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        project_id = state.project_identity(root)["project_id"]

        def lifecycle_task(title: str, request_id: str, *, status: str, phase: str) -> dict:
            created = state.tasks.create(
                root,
                {
                    "title": title,
                    "items": [{
                        "title": "One",
                        "prompt": "Do lifecycle work",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "worktree",
                    }],
                },
                request_id=request_id,
                project_id=project_id,
            )
            task_id = created["task_id"]
            state.tasks.begin_run(
                root,
                task_id,
                request_id=request_id + "-run",
                workspace={
                    "task_id": task_id,
                    "run_number": 1,
                    "project_root": str(root.parent / "browser-worktrees" / task_id),
                },
            )
            state.tasks.transition_run(
                root,
                task_id,
                1,
                phase=phase,
                status=status,
                completed_item_count=1 if status == "closed" else 0,
            )
            return state.tasks.get(root, task_id)

        paused = lifecycle_task("Paused Reset", "browser-paused-reset", status="paused", phase="stopped")
        failed = lifecycle_task("Failed Rerun", "browser-failed-rerun", status="paused", phase="launch_failed")
        completed = lifecycle_task("Completed Rerun", "browser-completed-rerun", status="closed", phase="worktree_ready")
        ongoing = lifecycle_task("Ongoing Filter", "browser-ongoing-filter", status="ongoing", phase="running")
        closed_move = lifecycle_task("Completed Move", "browser-closed-move", status="closed", phase="worktree_ready")
        state._browser_task_lifecycle_actions = []

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")

            # Final prototype Tasks-page geometry/motion: the Project summary is
            # deliberately narrow so the header never drifts, and Board cards
            # use the same all-property 120ms transition + handle tone.
            project_summary_style = page.locator("#tasksProjectFilterSummary").evaluate(
                """node => ({
                    width: getComputedStyle(node).width,
                    maxWidth: getComputedStyle(node).maxWidth,
                })"""
            )
            assert project_summary_style["width"] == "145px"
            assert project_summary_style["maxWidth"] == "190px"
            assert page.locator(".tasks-view-toggle").evaluate(
                "(node) => getComputedStyle(node).display"
            ) == "flex"
            first_board_card = page.locator(".tasks-board-card").first
            assert first_board_card.evaluate(
                "(node) => getComputedStyle(node).display"
            ) == "block"
            assert "worktree-card" in (first_board_card.get_attribute("class") or "")
            assert "inset" in first_board_card.evaluate(
                "(node) => getComputedStyle(node).boxShadow"
            )
            worktree_tag = first_board_card.locator(".tasks-board-tag.worktree")
            assert worktree_tag.is_visible()
            assert worktree_tag.evaluate(
                "(node) => getComputedStyle(node).borderTopStyle"
            ) == "solid"
            assert first_board_card.evaluate(
                "(node) => getComputedStyle(node).transitionProperty"
            ) == "all"
            assert first_board_card.evaluate(
                "(node) => getComputedStyle(node).transitionDuration"
            ) == "0.12s"
            assert first_board_card.locator(".tasks-board-card-handle").evaluate(
                "(node) => getComputedStyle(node).color"
            ) == "rgb(163, 173, 186)"
            page.set_viewport_size({"width": 820, "height": 800})
            assert page.locator("#tasksProjectFilterSummary").evaluate(
                "(node) => getComputedStyle(node).width"
            ) == "145px"
            page.set_viewport_size({"width": 1280, "height": 800})

            assert page.locator("#tasksRunningCount").inner_text() == "1 Running"
            page.click("#tasksRunningFilterButton")
            assert page.locator("#tasksRunningFilterButton").get_attribute("aria-pressed") == "true"
            assert page.locator("#tasksBoardOngoing .tasks-board-card").filter(has_text=ongoing["task_id"]).is_visible()
            assert page.locator("#tasksBoardPaused .tasks-board-card").filter(has_text=paused["task_id"]).is_hidden()
            page.click("#tasksRunningFilterButton")
            assert page.locator("#tasksRunningFilterButton").get_attribute("aria-pressed") == "false"

            page.locator("[data-tasks-view-mode='list']").click()
            assert page.locator("#tasksListRows .tasks-list-head").all_inner_texts() == [
                "STATUS\nNAME\nTASKS\nRUNTIME\nPROJECT\nPROGRESS"
            ]
            first_list_row = page.locator("#tasksListRows .tasks-list-data").first
            assert "worktree-row" in (first_list_row.get_attribute("class") or "")
            assert "inset" in first_list_row.evaluate(
                "(node) => getComputedStyle(node).boxShadow"
            )
            assert first_list_row.locator(".tasks-list-count").count() == 1
            assert first_list_row.locator(".tasks-list-project").count() == 1
            assert first_list_row.locator(".tasks-list-runtime").count() == 1

            # Final prototype contract: List rows keep a distinct double-click
            # shortcut to Task List, while a normal click on non-New Tasks opens Info.
            paused_list_row = page.locator("#tasksListRows .tasks-list-data").filter(has_text="Paused Reset")
            assert paused_list_row.get_attribute("title") == "Open Task info"
            paused_list_row.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            paused_list_row.dblclick()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            completed_list_row = page.locator("#tasksListRows .tasks-list-data").filter(has_text="Completed Rerun")
            completed_list_row.dblclick()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            completed_task_row = page.locator(".task-workspace-list-row").first
            assert completed_task_row.locator(".task-workspace-drag-grip").inner_text() == "⠿"
            assert completed_task_row.get_attribute("draggable") == "false"
            completed_geometry = completed_task_row.evaluate(
                """node => ({
                    columns: getComputedStyle(node).gridTemplateColumns.split(' ').filter(Boolean).length,
                    columnGap: getComputedStyle(node).columnGap,
                    numberWidth: getComputedStyle(node.querySelector('.task-workspace-list-number')).width,
                    numberHeight: getComputedStyle(node.querySelector('.task-workspace-list-number')).height,
                })"""
            )
            assert completed_geometry == {
                "columns": 4,
                "columnGap": "8px",
                "numberWidth": "28px",
                "numberHeight": "28px",
            }
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.locator("[data-tasks-view-mode='board']").click()

            column_add_box = page.locator("#tasksNewColumnButton").bounding_box()
            page.click("#tasksNewColumnButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            create_menu_box = page.locator("#taskCreateMenu").bounding_box()
            assert column_add_box and create_menu_box
            assert abs((create_menu_box["x"] + create_menu_box["width"]) - (column_add_box["x"] + column_add_box["width"])) <= 2
            assert 4 <= create_menu_box["y"] - (column_add_box["y"] + column_add_box["height"]) <= 8
            assert abs(create_menu_box["width"] - 250) <= 1
            assert page.locator("#taskCreateMenu .task-create-menu-icon").count() == 2
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('#taskCreateMenu')?.hidden === true")

            closed_card = page.locator("#tasksBoardClosed .tasks-board-card").filter(has_text=closed_move["task_id"])

            # Prototype drag feedback: valid targets are highlighted, invalid
            # targets are visibly blocked and explain why.
            closed_card.evaluate(
                """node => {
                    const transfer = new DataTransfer();
                    node.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:transfer}));
                }"""
            )
            assert "allowed" in (page.locator("#tasksBoardNew").get_attribute("class") or "").split()
            assert "blocked" in (page.locator("#tasksBoardOngoing").get_attribute("class") or "").split()
            assert page.locator("#tasksBoardOngoing").evaluate(
                "node => getComputedStyle(node, '::after').content"
            ) == '"不可移到此狀態"'
            closed_card.evaluate(
                """node => node.dispatchEvent(new DragEvent('dragend', {
                    bubbles:true, dataTransfer:new DataTransfer()
                }))"""
            )

            closed_card.evaluate(
                """node => {
                    const zone = document.querySelector('#tasksBoardNew');
                    const transfer = new DataTransfer();
                    node.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:transfer}));
                    zone.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer:transfer}));
                    zone.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}));
                    node.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer:transfer}));
                }"""
            )
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text("Move completed Task back to New?", exact=True).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert state.tasks.get(root, closed_move["task_id"])["status"] == "closed"

            closed_card = page.locator("#tasksBoardClosed .tasks-board-card").filter(has_text=closed_move["task_id"])
            closed_card.evaluate(
                """node => {
                    const zone = document.querySelector('#tasksBoardNew');
                    const transfer = new DataTransfer();
                    node.dispatchEvent(new DragEvent('dragstart', {bubbles:true, dataTransfer:transfer}));
                    zone.dispatchEvent(new DragEvent('dragover', {bubbles:true, cancelable:true, dataTransfer:transfer}));
                    zone.dispatchEvent(new DragEvent('drop', {bubbles:true, cancelable:true, dataTransfer:transfer}));
                    node.dispatchEvent(new DragEvent('dragend', {bubbles:true, dataTransfer:transfer}));
                }"""
            )
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "(taskId) => [...document.querySelectorAll('#tasksBoardNew .tasks-board-card')].some(node => node.dataset.taskId === taskId)",
                arg=closed_move["task_id"],
            )
            assert state.tasks.get(root, closed_move["task_id"])["status"] == "new"

            page.locator("#tasksBoardPaused .tasks-board-card").filter(
                has_text=paused["task_id"]
            ).click()
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            page.click("#taskWorkspaceResetTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text(
                "Reset paused Task and move it to New?", exact=True
            ).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert state.tasks.get(root, paused["task_id"])["status"] == "paused"

            page.click("#taskWorkspaceResetTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("!document.querySelector('#taskWorkspaceResetTask')")
            assert state.tasks.get(root, paused["task_id"])["status"] == "new"
            page.click("#taskWorkspaceClose")
            page.locator("#tasksBoardNew .tasks-board-card").filter(
                has_text=paused["task_id"]
            ).wait_for()

            page.locator("#tasksBoardPaused .tasks-board-card").filter(
                has_text=failed["task_id"]
            ).click()
            page.click("#taskWorkspaceRerunTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text(
                "Rerun this Task from the beginning?", exact=True
            ).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert state._browser_task_lifecycle_actions == []
            page.click("#taskWorkspaceRerunTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_timeout(100)
            assert state._browser_task_lifecycle_actions == [("rerun", failed["task_id"])]
            page.click("#taskWorkspaceClose")

            page.locator("#tasksBoardClosed .tasks-board-card").filter(
                has_text=completed["task_id"]
            ).click()
            page.click("#taskWorkspaceRerunTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text(
                "Rerun this completed Task?", exact=True
            ).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert state._browser_task_lifecycle_actions == [("rerun", failed["task_id"])]
            page.click("#taskWorkspaceRerunTask")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_timeout(100)
            assert state._browser_task_lifecycle_actions == [
                ("rerun", failed["task_id"]),
                ("rerun", completed["task_id"]),
            ]
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_workspace_result_merge_chat_uses_new_session_and_autosizes_prompt() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        active = state.chat_service.sessions(root)["active_session_id"]
        state.chat_service.append_message(root, active, "user", "existing conversation")
        state.chat_service.append_message(root, active, "assistant", "existing reply")
        original_messages = state.chat_service.messages(root, active)["messages"]

        created = state.tasks.create(
            root,
            {
                "title": "Conflict delivery",
                "items": [{
                    "title": "One",
                    "prompt": "Implement one",
                    "workflow": "workflow.yaml",
                    "project": str(root),
                    "workspace": "main",
                }],
            },
            request_id="browser-merge-task",
            project_id=state.project_identity(root)["project_id"],
        )
        task_id = created["task_id"]
        workspace_meta = {
            "task_id": task_id,
            "run_number": 1,
            "requested_mode": "main",
            "effective_mode": "main",
            "target_branch": "future-ui-implementation",
            "target_head_sha_at_start": "abc123",
            "task_branch": f"local/task/{task_id}-r1",
            "task_base_sha": "abc123",
            "repository_root": str(root),
            "repository_identity": str(root / ".git"),
            "source_project_root": str(root),
            "worktree_path": str(root.parent / "worktrees" / f"{task_id}-r1"),
            "project_root": str(root.parent / "worktrees" / f"{task_id}-r1"),
        }
        state.tasks.begin_run(
            root,
            task_id,
            request_id="browser-merge-run",
            workspace=workspace_meta,
        )
        state.tasks.transition_run(
            root,
            task_id,
            1,
            phase="conflict",
            status="paused",
            increment_merge_failure=True,
            workspace_result={
                "snapshot": {
                    "task_snapshot_sha": "def456",
                    "no_changes": False,
                    "created_commit": True,
                },
                "effective_mode": "main",
                "branch": workspace_meta["task_branch"],
                "path": workspace_meta["worktree_path"],
                "merge": {
                    "status": "conflict",
                    "real_merge_failure": True,
                    "conflict_files": ["app.py", "ui/panel.js"],
                    "detail": "automatic merge conflict",
                },
            },
        )

        fallback_created = state.tasks.create(
            root,
            {
                "title": "Fallback delivery",
                "items": [{
                    "title": "Fallback item",
                    "prompt": "Keep retained result",
                    "workflow": "workflow.yaml",
                    "project": str(root),
                    "workspace": "main",
                }],
            },
            request_id="browser-fallback-task",
            project_id=state.project_identity(root)["project_id"],
        )
        fallback_id = fallback_created["task_id"]
        fallback_workspace = {
            **workspace_meta,
            "task_id": fallback_id,
            "task_branch": f"local/task/{fallback_id}-r1",
            "worktree_path": str(root.parent / "worktrees" / f"{fallback_id}-r1"),
            "project_root": str(root.parent / "worktrees" / f"{fallback_id}-r1"),
        }
        state.tasks.begin_run(
            root,
            fallback_id,
            request_id="browser-fallback-run",
            workspace=fallback_workspace,
        )
        state.tasks.transition_run(
            root,
            fallback_id,
            1,
            phase="worktree_ready",
            status="closed",
            increment_merge_failure=True,
            completed_item_count=1,
            workspace_result={
                "snapshot": {
                    "task_snapshot_sha": "fedcba",
                    "no_changes": False,
                    "created_commit": True,
                },
                "effective_mode": "main",
                "branch": fallback_workspace["task_branch"],
                "path": fallback_workspace["worktree_path"],
                "delivery_fallback": {
                    "mode": "isolated_worktree",
                    "reason": "merge_failure_limit_exceeded",
                },
                "merge": {
                    "status": "worktree_ready",
                    "attempt_status": "conflict",
                    "real_merge_failure": True,
                },
            },
        )

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser_instance = _launch_browser(playwright)
            page = browser_instance.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('.tasks-board-card').length === 2")
            page.locator(".tasks-board-card").filter(has_text="Conflict delivery").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            assert page.locator("#taskWorkspaceWorktreeBadge").inner_text() == "MAIN"
            assert page.locator("#taskWorkspaceResultProject").inner_text() == str(root)
            assert page.locator("#taskWorkspaceRun").inner_text() == "Run #1 · Item 1/1"
            assert page.locator("#taskWorkspaceTargetBranch").inner_text() == "future-ui-implementation"
            assert page.locator("#taskWorkspaceBranch").inner_text() == workspace_meta["task_branch"]
            assert page.locator("#taskWorkspacePath").inner_text() == workspace_meta["worktree_path"]
            assert page.locator("#taskWorkspaceMergeStatus").inner_text() == "conflict"
            assert page.locator("#taskWorkspaceMergeFailures").inner_text() == "1"
            assert page.locator("#taskWorkspaceMerge").is_disabled()
            assert page.locator("#taskWorkspaceMergeChat").is_enabled()
            assert "app.py" in page.locator("#taskWorkspaceConflicts").inner_text()

            page.click("#taskWorkspaceClose")
            page.locator(".tasks-board-card").filter(has_text="Fallback delivery").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceMergeStatus')?.textContent === 'worktree_ready'")
            assert page.locator("#taskWorkspaceRun").inner_text() == "Run #1 · Item 1/1"
            assert page.locator("#taskWorkspaceTargetBranch").inner_text() == "future-ui-implementation"
            assert page.locator("#taskWorkspaceMergeFailures").inner_text() == "1"
            assert "isolated_worktree" in page.locator("#taskWorkspaceFallback").inner_text()
            assert "merge_failure_limit_exceeded" in page.locator("#taskWorkspaceFallback").inner_text()
            assert page.locator("#taskWorkspacePublish").is_enabled()
            page.click("#taskWorkspacePublish")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text(
                "Publish completed result to origin?", exact=True
            ).is_visible()
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "document.querySelector('#taskWorkspacePublishState')?.textContent.includes('published')"
            )
            assert getattr(state, "_browser_publish_actions", []) == [
                (fallback_id, fallback_workspace["task_branch"])
            ]
            assert page.locator("#taskWorkspaceCleanupWorktrees").is_enabled()
            assert page.locator("#taskWorkspaceDeleteTask").is_disabled()
            page.click("#taskWorkspaceCleanupWorktrees")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text(
                "Cleanup retained Task worktrees?", exact=True
            ).is_visible()
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "document.querySelector('#taskWorkspaceDeleteTask')?.disabled === false"
            )
            assert getattr(state, "_browser_cleanup_actions", []) == [fallback_id]
            assert page.locator("#taskWorkspaceCleanupWorktrees").count() == 0
            page.click("#taskWorkspaceClose")

            page.locator(".tasks-board-card").filter(has_text="Conflict delivery").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceMergeStatus')?.textContent === 'conflict'")
            page.click("#taskWorkspaceMergeChat")
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            page.wait_for_function("document.querySelector('#projectChatInput')?.value.includes('Merge status: conflict')")

            sessions = state.chat_service.sessions(root)
            assert len(sessions["sessions"]) == 2
            assert sessions["active_session_id"] != active
            assert state.chat_service.messages(root, active)["messages"] == original_messages
            assert state.chat_service.messages(root, sessions["active_session_id"])["messages"] == []

            prompt = page.locator("#projectChatInput").input_value()
            assert f"Task ID: {task_id}" in prompt
            assert workspace_meta["task_branch"] in prompt
            assert workspace_meta["worktree_path"] in prompt
            assert "Conflict files: app.py, ui/panel.js" in prompt
            composer_height = page.locator("#projectChatInput").evaluate(
                "(node) => node.getBoundingClientRect().height"
            )
            assert composer_height > 46
            assert composer_height <= 181
            browser_instance.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_completed_runtime_rerun_requires_confirmation() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        state._browser_runtime_override = {
            "status": "completed",
            "view": {"label": "Completed"},
            "actions": {"run": False, "stop": False, "resume": False, "reset": False, "rerun": True},
            "running": False,
            "completed": True,
            "resumable": False,
            "stale": False,
            "has_state": True,
            "task": "Completed browser task",
            "stage": "",
            "cli_status": "",
            "completed_count": 1,
            "total": 1,
            "run_id": "browser-completed-run",
        }
        state._browser_runtime_actions = []

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("document.querySelector('#chatNav')?.classList.contains('active')")
            page.wait_for_function("!document.querySelector('#rerunButton')?.hidden")
            page.click("#optionsButton")
            page.wait_for_function("!document.querySelector('#optionsPanel')?.hidden")
            page.click("#rerunButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            assert page.locator(".ui-dialog-card").get_by_text("Rerun completed task?", exact=True).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert state._browser_runtime_actions == []

            page.click("#optionsButton")
            page.wait_for_function("!document.querySelector('#optionsPanel')?.hidden")
            page.click("#rerunButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#rerunButton')?.getAttribute('aria-busy') !== 'true'")
            assert state._browser_runtime_actions == ["rerun"]
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_runtime_poll_race_does_not_apply_stale_project_response() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        state.global_settings.update({
            "interface": {"appearance": "dark", "theme": "violet"},
        })
        (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        second = root / "second-project"
        second.mkdir()
        state._write_projects([
            {"name": "Fixture Project", "path": str(root)},
            {"name": "Second Project", "path": str(second)},
        ])

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            first_path = str(root)
            page.evaluate(
                """([firstPath]) => {
                    const baseFetch = window.fetch;
                    window.__staleRuntimeStarted = false;
                    window.fetch = async (url, options = {}) => {
                        const text = String(url);
                        if (
                            !window.__staleRuntimeStarted
                            && text.includes('/api/project/runtime')
                            && text.includes(encodeURIComponent(firstPath))
                        ) {
                            window.__staleRuntimeStarted = true;
                            await new Promise((resolve) => setTimeout(resolve, 600));
                            return {
                                ok: true,
                                status: 200,
                                json: async () => ({
                                    status: 'needs_attention',
                                    view: {label: 'Needs Attention'},
                                    actions: {run:false, stop:false, resume:true, reset:true, rerun:false},
                                    attention_reason: 'STALE_A_RESPONSE',
                                    recommended_actions: ['resume','reset'],
                                    running:false, completed:false, resumable:true, stale:true,
                                    stage:'execute', cli_status:'', completed_count:0, total:1,
                                    recent_transitions: []
                                })
                            };
                        }
                        return baseFetch(url, options);
                    };
                }""",
                [first_path],
            )

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("document.querySelector('#chatNav')?.classList.contains('active')")
            page.wait_for_function("window.__staleRuntimeStarted === true", timeout=5000)
            page.locator("#projectList .project-root").filter(has_text="Second Project").click()
            page.wait_for_function(
                "document.querySelector('#projectName')?.textContent === 'Second Project'"
            )
            page.wait_for_timeout(850)

            assert page.locator("#projectName").inner_text() == "Second Project"
            assert "STALE_A_RESPONSE" not in page.locator("#currentTask").inner_text()
            assert "Needs Attention" not in page.locator("#statusBadge").inner_text()
            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_tasks_board_project_filter_is_local_and_parent_matches_child_project() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        state.global_settings.update({
            "interface": {"theme": "violet", "appearance": "dark"},
        })
        (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        second = root / "second-project"
        second.mkdir()
        third = root / "third-project"
        third.mkdir()
        state._write_projects([
            {"name": "Fixture Project", "path": str(root)},
            {"name": "Second Project", "path": str(second)},
            {"name": "Third Project", "path": str(third)},
        ])
        projects = state.projects()
        root_row = next(row for row in projects if row["name"] == "Fixture Project")
        draft = {
            "title": "Cross-project parent",
            "items": [{
                "title": "Child",
                "prompt": "Child belongs to second filter",
                "workflow": "workflow.yaml",
                "project": str(root),
                "workspace": "auto",
            }],
        }
        created = state.tasks.create(
            root,
            draft,
            request_id="board-cross-project",
            project_id=root_row["project_id"],
        )
        task_path = state.tasks._state_path(root)
        raw = json.loads(task_path.read_text(encoding="utf-8"))
        raw["tasks"][0]["items"][0]["project"] = str(second.resolve())
        task_path.write_text(json.dumps(raw), encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.add_init_script(
                """if (location.origin === 'http://local.test') {
                    localStorage.setItem(
                        'ai-task-runner.ui.bootstrap.v1',
                        JSON.stringify({theme:'violet', appearance:'dark', motion:'full'})
                    );
                }"""
            )
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)

            def install(expected_project: str) -> None:
                page.evaluate(
                    """window.fetch = async (url, options = {}) => {
                        const method = (options.method || 'GET').toUpperCase();
                        const response = await window.__apiBridge(method, String(url), options.body || '{}');
                        return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                    };"""
                )
                _install_main_ui_styles(page, static_root)
                _install_main_ui_scripts(page, static_root)
                _boot_main_ui(page, expected_project)

            def reload_ui(expected_project: str) -> None:
                page.reload(wait_until="domcontentloaded")
                install(expected_project)
                page.wait_for_function("document.documentElement.dataset.theme === 'violet'")
                page.wait_for_function("document.documentElement.dataset.appearance === 'dark'")

            def assert_reload_state(expected_summary: str, baseline: dict) -> None:
                assert page.locator("#projectChatName").inner_text() == "Second Project"
                assert page.locator("#tasksProjectFilterSummary").inner_text() == expected_summary
                assert page.locator("html").get_attribute("data-theme") == "violet"
                assert page.locator("html").get_attribute("data-appearance") == "dark"
                page.wait_for_timeout(220)
                current = page.locator("#tasksBoardView").bounding_box()
                assert current is not None
                for key in ("x", "y", "width", "height"):
                    assert abs(current[key] - baseline[key]) <= 1, (key, baseline, current)

            install("Fixture Project")
            page.wait_for_function("document.documentElement.dataset.theme === 'violet'")
            page.wait_for_function("document.documentElement.dataset.appearance === 'dark'")
            page.locator("#projectList .project-root").filter(has_text="Second Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Second Project'")
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('#tasksBoardNew .tasks-board-card').length === 1")
            assert page.locator("#tasksBoardView .tasks-title-line > .tasks-project-filter").count() == 1
            assert page.locator(".tasks-board-toolbar-left .tasks-project-filter").count() == 0
            task_filter_alignment = page.evaluate(
                """() => {
                    const title = document.querySelector('#tasksBoardView .tasks-title-line h1').getBoundingClientRect();
                    const filter = document.querySelector('#tasksProjectFilterButton').getBoundingClientRect();
                    return {titleCenter: title.top + title.height / 2, filterCenter: filter.top + filter.height / 2};
                }"""
            )
            assert abs(task_filter_alignment["titleCenter"] - task_filter_alignment["filterCenter"]) <= 3
            page.click("#tasksProjectFilterButton")
            second_option = page.locator(".tasks-project-option").filter(has_text="Second Project")
            root_option = page.locator(".tasks-project-option").filter(has_text="Fixture Project")
            assert second_option.evaluate("(node) => node.tagName") == "BUTTON"
            assert second_option.locator(".tasks-project-check").inner_text() == "✓"
            assert second_option.locator(".tasks-project-check").evaluate(
                "(node) => getComputedStyle(node).display"
            ) == "grid"
            assert second_option.get_attribute("aria-pressed") == "true"
            assert root_option.get_attribute("aria-pressed") == "false"
            assert " · main" in second_option.locator("small").inner_text()
            second_option.click()
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'No Project'")
            assert page.locator("#tasksProjectFilterMenu").is_visible()
            assert page.locator("#tasksProjectFilterButton").get_attribute("aria-expanded") == "true"
            assert page.locator(".tasks-project-option").filter(has_text="Second Project").get_attribute("aria-pressed") == "false"
            page.locator(".tasks-project-option").filter(has_text="Second Project").click()
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'Second Project'")
            assert page.locator(".tasks-project-option").filter(has_text="Second Project").get_attribute("aria-pressed") == "true"
            assert page.locator(".tasks-project-option").filter(has_text="Fixture Project").get_attribute("aria-pressed") == "false"
            page.wait_for_function("document.querySelectorAll('#tasksBoardNew .tasks-board-card').length === 1")
            assert page.locator("#tasksBoardNew .tasks-board-card").get_by_text("Cross-project parent").is_visible()
            assert page.locator("#projectChatName").inner_text() == "Second Project"
            assert page.locator("#tasksProjectFilterSummary").inner_text() == "Second Project"
            board_geometry = page.locator("#tasksBoardView").bounding_box()
            assert board_geometry is not None

            reload_ui("Second Project")
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            assert_reload_state("Second Project", board_geometry)

            page.click("#tasksProjectFilterButton")
            third_option = page.locator(".tasks-project-option").filter(has_text="Third Project")
            third_option.focus()
            page.keyboard.press("Enter")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === '2 Projects · 1 Tasks'")
            reload_ui("Second Project")
            page.click("#chatNav")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === '2 Projects · 1 Tasks'")
            assert_reload_state("2 Projects · 1 Tasks", board_geometry)

            page.click("#tasksProjectFilterButton")
            page.click("#tasksProjectFilterAll")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'All Projects · 1 Tasks'")
            reload_ui("Second Project")
            page.click("#chatNav")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'All Projects · 1 Tasks'")
            assert_reload_state("All Projects · 1 Tasks", board_geometry)

            page.click("#tasksProjectFilterButton")
            page.click("#tasksProjectFilterClear")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'No Project'")
            assert page.locator("#tasksBoardNew .tasks-board-card").count() == 0
            reload_ui("Second Project")
            page.click("#chatNav")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent === 'No Project'")
            assert_reload_state("No Project", board_geometry)
            assert page.locator("#tasksBoardNew .tasks-board-card").count() == 0
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_reload_core_task_and_project_entrypoints_have_zero_page_errors() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        workflow = root / "runner" / "assets" / "workflows" / "workflow.yaml"
        workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        second = root / "second-project"
        second.mkdir()
        state._write_projects([
            {"name": "Fixture Project", "path": str(root)},
            {"name": "Second Project", "path": str(second)},
        ])
        project_id = next(
            row["project_id"]
            for row in state.projects()
            if row["name"] == "Fixture Project"
        )
        state.tasks.create(
            root,
            {
                "title": "Smoke task list",
                "items": [
                    {
                        "title": "First",
                        "prompt": "Do first",
                        "workflow": str(workflow),
                        "project": str(root),
                        "workspace": "auto",
                    },
                    {
                        "title": "Second",
                        "prompt": "Do second",
                        "workflow": str(workflow),
                        "project": str(root),
                        "workspace": "auto",
                    },
                ],
            },
            request_id="smoke-task-list",
            project_id=project_id,
        )

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        def install(page, expected_project: str = "Fixture Project") -> None:
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page, expected_project)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            install(page)

            page.reload(wait_until="domcontentloaded")
            install(page)

            # Tasks + New uses the same canonical menu for Task and Task List.
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksNewButton")
            page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.click("#tasksNewButton")
            page.locator("#taskCreateMenu [data-task-create-kind='list']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            # Prototype contract: New Board items open the Task List directly.
            page.locator("#tasksBoardNew .tasks-board-card").filter(has_text="Smoke task list").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceHeaderBack").is_hidden()
            assert page.locator("#taskWorkspaceFooterInfo").is_visible()
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back"
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            # Chat New Task reuses the same create menu/editor.
            page.locator("#projectList .project-root").filter(has_text="Fixture Project").click()
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
            page.click("#projectChatNewTaskButton")
            page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            # Removing the last visible Project must fail open to an empty app,
            # not leave a stale active Project or throw a page error.
            for project_name in ("Second Project", "Fixture Project"):
                row = page.locator(".project-row").filter(has_text=project_name)
                row.locator(".project-menu-button").click()
                page.locator(".project-action-menu-portal").get_by_role(
                    "button", name="Remove project"
                ).click()
                page.locator(".ui-dialog-card").wait_for(state="visible")
                page.locator("[data-dialog-ok]").click()
                page.wait_for_function(
                    "(name) => !Array.from(document.querySelectorAll('.project-row')).some((row) => row.textContent.includes(name))",
                    arg=project_name,
                )

            assert page.locator(".project-row").count() == 0
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_project_chat_delete_cleans_transient_state_and_is_project_scoped() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        second = root / "second-project"
        second.mkdir()
        state.add_project(str(second))
        state.rename_project(str(second), "Second Project")
        state.chat_service.sessions(second)
        state.chat_service.create_session(
            second,
            title="Second preserved",
            request_id="second-chat-preserved",
        )
        second_ids = [
            row["session_id"]
            for row in state.chat_service.sessions(second)["sessions"]
        ]

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser_instance = _launch_browser(playwright)
            page = browser_instance.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page, expected_project="Second Project")

            page.locator("#projectList .project-root").filter(has_text="Fixture Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Fixture Project'")
            for _ in range(2):
                page.click("#newProjectChatButton")
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 3")

            # A failed header selection must restore the canonical active Chat
            # instead of leaving the native select on a stale optimistic value.
            sessions_before_failed_select = state.chat_service.sessions(root)
            active_before_failed_select = sessions_before_failed_select["active_session_id"]
            failed_target = next(
                row["session_id"]
                for row in sessions_before_failed_select["sessions"]
                if row["session_id"] != active_before_failed_select
            )
            state._browser_chat_select_fail = True
            page.select_option("#projectChatSessionSelect", failed_target)
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatSessionSelect')?.value === value",
                arg=active_before_failed_select,
            )
            assert state.chat_service.sessions(root)["active_session_id"] == active_before_failed_select
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('.app-toast.error')).some((n) => n.textContent.includes('Injected Chat select failure'))"
            )

            # Select and delete a middle Chat; the other Project must not change.
            middle_id = state.chat_service.sessions(root)["sessions"][1]["session_id"]
            page.select_option("#projectChatSessionSelect", middle_id)
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatSessionSelect')?.value === value",
                arg=middle_id,
            )
            page.click("#deleteProjectChatButton")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 2")
            assert [
                row["session_id"]
                for row in state.chat_service.sessions(second)["sessions"]
            ] == second_ids

            # A running/busy Chat is fail-closed. It remains present until the
            # active turn is stopped or completes.
            active_id = state.chat_service.sessions(root)["active_session_id"]
            state._browser_chat_busy = {active_id: True}
            page.click("#deleteProjectChatButton")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('.app-toast.error')).some((n) => n.textContent.includes('Stop or wait for the active Chat turn'))"
            )
            assert any(
                row["session_id"] == active_id
                for row in state.chat_service.sessions(root)["sessions"]
            )
            state._browser_chat_busy[active_id] = False

            # A Chat carrying a transient TaskDraft deletes both the durable Chat
            # and that session-scoped transient draft cache.
            page.fill("#projectChatInput", "@task-single delete this draft with chat")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 1")
            draft_card = page.locator(".project-chat-task-draft").first
            draft_id = draft_card.get_attribute("data-draft-id")
            draft_session = draft_card.get_attribute("data-session-id")
            assert draft_session == active_id
            page.click("#deleteProjectChatButton")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 1")
            with pytest.raises(ValueError, match="no longer available"):
                state.task_drafts.get(root, draft_id, session_id=draft_session)
            assert page.locator(".project-chat-task-draft").count() == 0

            # Deleting the final Chat immediately creates a fresh empty Chat.
            last_before = state.chat_service.sessions(root)["active_session_id"]
            page.click("#deleteProjectChatButton")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 1")
            replacement = state.chat_service.sessions(root)
            assert replacement["active_session_id"] != last_before
            assert replacement["sessions"][0]["title"] == "New Chat"

            page.locator("#projectList .project-root").filter(has_text="Second Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Second Project'")
            page.wait_for_function(
                f"document.querySelectorAll('#projectChatSessionSelect option').length === {len(second_ids)}"
            )
            assert [
                row["session_id"]
                for row in state.chat_service.sessions(second)["sessions"]
            ] == second_ids
            browser_instance.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_shared_new_task_menu_creates_task_and_task_list() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        # This flow intentionally exercises production Task validation, where
        # every Task item requires a Workflow. Persist the canonical catalog
        # path rather than a display/name guess so + New resolves the intended
        # Workflow without depending on catalog sort order.
        workflow_root = root / "runner" / "assets" / "workflows"
        workflow_path = workflow_root / "workflow.yaml"
        workflow_path.write_text("stages: {}\n", encoding="utf-8")
        (workflow_root / "mixed.yaml").write_text(
            "stages:\n"
            "  planning:\n"
            "    type: plan\n"
            "  validate_file:\n"
            "    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "  validate_ai:\n"
            "    type: ai_validator\n"
            "    validator: ai\n"
            "flow:\n"
            "  - planning\n"
            "  - validate_file\n"
            "  - validate_ai\n",
            encoding="utf-8",
        )
        state.project_preferences.update(root, {"workflow": str(workflow_path)})
        # Use the same Workflow metadata owner as production so the Editor and
        # Task validation cannot drift apart in this browser fixture.
        state.tasks._workflow_requirements = state._task_workflow_requirements
        state.task_drafts._workflow_requirements = state._task_workflow_requirements
        validator_upload = root / "validator-upload.py"
        validator_upload.write_text("print('uploaded validator')\n", encoding="utf-8")
        ai_upload = root / "ai-upload.md"
        ai_upload.write_text("uploaded AI validator prompt\n", encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.click("#tasksNewButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            assert page.locator("#taskCreateMenu [data-task-create-kind]").count() == 2
            page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceItemTitle'")
            assert page.locator("#taskWorkspaceSave").inner_text() == "Create Task"
            assert page.locator("#taskWorkspaceHeaderBack").is_hidden()
            assert page.locator("#taskWorkspaceHeaderActions").is_hidden()
            assert page.locator("#taskWorkspaceTitle").inner_text() == "New task"
            assert page.locator("#taskWorkspaceMeta").inner_text() == "New Task"
            assert page.locator("#taskWorkspaceDraftTitle").count() == 0
            assert page.locator("#taskWorkspaceProject").is_editable() is True
            assert page.locator(".task-workspace-project-toggle").is_enabled()
            page.locator(".task-workspace-project-toggle").click()
            page.locator(".task-workspace-project-dropdown").wait_for(state="visible")
            assert page.locator(".task-workspace-project-dropdown").is_visible()
            assert page.locator(".task-workspace-project-dropdown-option").count() >= 1
            first_project_option = page.locator(".task-workspace-project-dropdown-option").first
            selected_project_path = first_project_option.locator("small").inner_text()
            first_project_option.click()
            page.wait_for_timeout(80)
            assert page.locator("#taskWorkspaceProject").input_value() == selected_project_path
            assert page.locator(".task-workspace-project-dropdown").is_hidden()
            assert page.locator(".task-workspace-project-toggle").get_attribute("aria-expanded") == "false"

            page.locator(".task-workspace-project-toggle").click()
            page.locator(".task-workspace-project-dropdown").wait_for(state="visible")
            assert page.locator(".task-workspace-project-dropdown").is_visible()
            assert page.locator(".task-workspace-project-dropdown-option.selected").count() == 1
            page.click("#taskWorkspaceItemTitle")
            assert page.locator(".task-workspace-project-dropdown").is_hidden()

            page.locator(".task-workspace-project-toggle").click()
            page.locator(".task-workspace-project-dropdown").wait_for(state="visible")
            assert page.locator(".task-workspace-project-dropdown").is_visible()
            page.keyboard.press("Escape")
            assert page.locator(".task-workspace-project-dropdown").is_hidden()
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator("#taskWorkspaceProject").evaluate("(node) => document.activeElement === node")
            page.fill("#taskWorkspaceItemTitle", "Standalone browser task")
            page.fill("#taskWorkspacePrompt", "Standalone task prompt")

            # X, Escape, backdrop and footer Cancel share the same dirty guard
            # and must preserve the editor while the user chooses Keep editing.
            for close_kind in ("x", "escape", "backdrop", "cancel"):
                if close_kind == "x":
                    page.click("#taskWorkspaceClose")
                elif close_kind == "escape":
                    page.locator("#taskWorkspacePrompt").focus()
                    page.keyboard.press("Escape")
                elif close_kind == "backdrop":
                    page.locator("#taskWorkspaceOverlay").click(position={"x": 8, "y": 8})
                else:
                    page.click("#taskWorkspaceFooterBack")
                page.locator(".ui-dialog-card").wait_for(state="visible")
                assert page.locator(".ui-dialog-card").get_by_text("unsaved TaskDraft edits", exact=False).is_visible()
                page.locator("[data-dialog-cancel]").click()
                assert page.locator("#taskWorkspacePrompt").input_value() == "Standalone task prompt"

            page.click("#taskWorkspaceSave")
            page.wait_for_function(
                "() => document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'"
                " || !!document.querySelector('#taskWorkspaceError:not([hidden])')"
            )
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO", (
                "Create Task did not reach Task Info: "
                + page.locator("#taskWorkspaceError").inner_text()
            )
            created = state.tasks.list(state.repo_root)["tasks"]
            assert len(created) == 1
            assert created[0]["title"] == "Standalone browser task"
            assert created[0]["items"][0]["prompt"] == "Standalone task prompt"
            assert page.locator("#taskWorkspaceEditTask").is_visible()
            page.click("#taskWorkspaceEditTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Info"
            assert page.locator(".task-workspace-foot").evaluate("(node) => getComputedStyle(node).justifyContent") == "flex-end"
            assert page.locator("#taskWorkspaceProject").is_editable() is False
            assert page.locator(".task-workspace-project-toggle").is_disabled()

            assert page.locator("#taskWorkspaceDraftTitle").count() == 0
            page.fill("#taskWorkspaceItemTitle", "Dirty standalone title")
            page.fill("#taskWorkspacePrompt", "Dirty standalone prompt")
            page.locator("[data-workspace-option='main']").click()
            mixed_workflow = str(state.repo_root / "runner" / "assets" / "workflows" / "mixed.yaml")
            page.select_option("#taskWorkspaceWorkflow", mixed_workflow)
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 3"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"

            # Existing Task Edit uses the same capability-aware outer tabs as
            # New Task. Exercise every visible tab, then return to Prompt so
            # the dirty-close matrix below owns the same editable control.
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("[data-task-editor-tab='validator']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-source-card='prompt']").count() == 0
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("""document.querySelector('[data-task-source-card="ai"]') !== null""")
            assert page.locator("[data-task-editor-tab='ai']").get_attribute("aria-selected") == "true"
            page.locator("[data-task-editor-tab='prompt']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")
            assert page.locator("#taskWorkspacePrompt").input_value() == "Dirty standalone prompt"

            for guard_kind in ("header", "footer", "x", "escape", "prompts"):
                if guard_kind == "header":
                    trigger = "#taskWorkspaceHeaderBack"
                    page.click(trigger)
                elif guard_kind == "footer":
                    trigger = "#taskWorkspaceFooterBack"
                    page.click(trigger)
                elif guard_kind == "x":
                    trigger = "#taskWorkspaceClose"
                    page.click(trigger)
                elif guard_kind == "escape":
                    trigger = "#taskWorkspacePrompt"
                    page.locator(trigger).focus()
                    page.keyboard.press("Escape")
                else:
                    trigger = "#taskWorkspaceOpenPrompts"
                    page.click(trigger)
                page.wait_for_function("!document.querySelector('.ui-dialog-card')?.hidden")
                assert page.locator(".ui-dialog-card").get_by_text("unsaved Task edits", exact=False).is_visible()
                page.locator("[data-dialog-cancel]").click()
                page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
                assert page.locator("#taskWorkspaceItemTitle").input_value() == "Dirty standalone title"
                assert page.locator("#taskWorkspacePrompt").input_value() == "Dirty standalone prompt"
                assert page.locator("#taskWorkspaceWorkspace").input_value() == "main"
                assert page.locator("#taskWorkspaceWorkflow").input_value() == mixed_workflow
                page.wait_for_function(
                    "(selector) => document.activeElement === document.querySelector(selector)",
                    arg=trigger,
                )

            page.click("#taskWorkspaceOpenPrompts")
            page.wait_for_function("!document.querySelector('.ui-dialog-card')?.hidden")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
            durable_after_discard = state.tasks.list(state.repo_root)["tasks"][0]
            assert durable_after_discard["title"] == "Standalone browser task"
            assert durable_after_discard["items"][0]["prompt"] == "Standalone task prompt"
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.locator("#projectList .project-root").first.click()
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
            page.click("#projectChatNewTaskButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            page.locator("#taskCreateMenu [data-task-create-kind='list']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceHeaderBack").is_hidden()
            assert page.locator("#taskWorkspaceHeaderActions").is_visible()
            assert page.locator("#taskWorkspaceHeaderCancel").is_visible()
            assert page.locator("#taskWorkspaceHeaderCreateList").is_visible()
            assert page.locator("#taskWorkspaceTitle").inner_text() == "New Task List"
            assert page.locator("#taskWorkspaceMeta").inner_text() == "Draft · not created yet"
            assert page.locator("#taskWorkspaceHeaderCreateList").inner_text() == "Create Task List"
            assert page.locator("#taskWorkspaceHeaderCreateList").is_disabled()
            create_header_box = page.locator("#taskWorkspaceHeaderCreateList").bounding_box()
            cancel_header_box = page.locator("#taskWorkspaceHeaderCancel").bounding_box()
            assert create_header_box and cancel_header_box
            assert abs(create_header_box["height"] - 30) <= 1
            assert abs(cancel_header_box["height"] - 30) <= 1
            assert page.locator("#taskWorkspaceSave").is_hidden()
            assert page.locator(".task-workspace-list-row").count() == 0
            assert page.locator("#taskWorkspaceAddTask").inner_text() == "No tasks yet\n+ Add first task"
            empty_cta_geometry = page.locator("#taskWorkspaceAddTask").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {
                        display: style.display,
                        minHeight: style.minHeight,
                        gap: style.gap,
                        padding: style.padding,
                        strongSize: getComputedStyle(node.querySelector('strong')).fontSize,
                        spanSize: getComputedStyle(node.querySelector('span')).fontSize
                    };
                }"""
            )
            assert empty_cta_geometry == {
                "display": "flex",
                "minHeight": "86px",
                "gap": "10px",
                "padding": "10px 11px",
                "strongSize": "9px",
                "spanSize": "8px",
            }
            assert page.locator(".task-workspace-list-side-card").count() == 2
            assert "Tasks run from top to bottom inside this Task List." in page.locator(".task-workspace-list-intro").inner_text()
            quick_use = page.locator(".task-workspace-list-help")
            assert quick_use.locator("strong").all_inner_texts() == ["Click", "Double-click", "⋯"]
            assert "Click selects a task · Double-click edits it." in quick_use.inner_text()
            assert "Drag the grip to reorder. Right-click or ⋯ for Info / Workflow / Remove." in quick_use.inner_text()
            assert page.locator(".task-workspace-list-tools button").count() == 0
            list_columns = page.locator(".task-workspace-list-page").evaluate("(node) => getComputedStyle(node).gridTemplateColumns")
            assert list_columns.endswith("260px")
            list_shell_box = page.locator("#taskWorkspaceShell").bounding_box()
            assert list_shell_box and abs(list_shell_box["width"] - 920) <= 1
            assert page.locator(".task-workspace-list-main").evaluate("(node) => getComputedStyle(node).padding") == "14px"

            # Standalone Task List Draft footer Cancel shares the canonical
            # dirty-discard guard. Keep editing preserves the Draft; Discard
            # closes the same Drawer shell. Reopen before continuing creation.
            page.fill("#taskWorkspaceDraftTitle", "Dirty footer cancel draft")
            page.click("#taskWorkspaceFooterBack")
            page.wait_for_function("document.querySelector('.ui-dialog-card') !== null")
            assert page.locator(".ui-dialog-card").get_by_text("unsaved TaskDraft edits", exact=False).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            assert page.locator("#taskWorkspaceDraftTitle").input_value() == "Dirty footer cancel draft"
            page.click("#taskWorkspaceFooterBack")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.click("#projectChatNewTaskButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            page.locator("#taskCreateMenu [data-task-create-kind='list']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceDraftTitle'")
            assert page.evaluate("""() => {
                const input = document.querySelector('#taskWorkspaceDraftTitle');
                return input.selectionStart === 0 && input.selectionEnd === input.value.length;
            }""")
            # Let the prior Drawer close RAF and async option loads settle.
            # Focus must remain owned by the new Task List, not jump back to
            # the + New anchor from the previous surface.
            page.wait_for_timeout(120)
            assert page.evaluate("document.activeElement?.id === 'taskWorkspaceDraftTitle'")
            assert page.locator(".task-workspace-list-row").count() == 0
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceItemTitle'")
            # The first child must inherit the workflow already resolved for
            # this Project/Chat. Catalog ordering must never change validation.
            assert page.locator("#taskWorkspaceWorkflow").input_value() == str(workflow_path)
            assert page.locator("#taskWorkspaceSave").inner_text() == "Create task"
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Task List Draft"
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 0
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "First list child")
            page.fill("#taskWorkspacePrompt", "First list prompt")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 1
            assert page.locator("#taskWorkspaceHeaderCreateList").is_enabled()

            # Transient Task List Draft may return to zero items; canonical Tasks may not.
            page.locator(".task-workspace-list-row").first.get_by_role("button", name="Remove").click()
            assert page.locator(".task-workspace-list-row").count() == 0
            assert page.locator("#taskWorkspaceAddTask").inner_text() == "No tasks yet\n+ Add first task"
            assert page.locator("#taskWorkspaceHeaderCreateList").is_disabled()
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "First list child")
            page.fill("#taskWorkspacePrompt", "First list prompt")
            assert page.locator("#taskWorkspaceSave").inner_text() == "Create task"
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 1
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "Second list child")
            page.fill("#taskWorkspacePrompt", "Second list prompt")
            page.select_option("#taskWorkspaceWorkflow", str(workflow_path))
            assert page.locator("#taskWorkspaceSave").inner_text() == "Create task"
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 2
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "Third list child")
            page.fill("#taskWorkspacePrompt", "Third list prompt")
            page.select_option("#taskWorkspaceWorkflow", str(workflow_path))
            assert page.locator("#taskWorkspaceSave").inner_text() == "Create task"
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 3
            assert page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-edit").count() == 1
            assert page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-more").count() == 0
            assert page.locator(".task-workspace-list-row").first.locator(".task-workspace-drag-grip").inner_text() == "⋮⋮"
            task_row_geometry = page.locator(".task-workspace-list-row").first.evaluate(
                """node => {
                    const row = getComputedStyle(node);
                    const number = getComputedStyle(node.querySelector('.task-workspace-list-number'));
                    return {
                        columnGap: row.columnGap,
                        alignItems: row.alignItems,
                        columns: row.gridTemplateColumns.split(' ').filter(Boolean).length,
                        numberDisplay: number.display,
                        numberWidth: number.width,
                        numberHeight: number.height,
                        numberLineHeight: number.lineHeight,
                        titleDisplay: getComputedStyle(node.querySelector('.task-workspace-list-copy strong')).display,
                        titleSize: getComputedStyle(node.querySelector('.task-workspace-list-copy strong')).fontSize,
                        metaDisplay: getComputedStyle(node.querySelector('.task-workspace-list-copy small')).display,
                        metaSize: getComputedStyle(node.querySelector('.task-workspace-list-copy small')).fontSize,
                    };
                }"""
            )
            assert task_row_geometry == {
                "columnGap": "8px",
                "alignItems": "center",
                "columns": 4,
                "numberDisplay": "grid",
                "numberWidth": "28px",
                "numberHeight": "28px",
                "numberLineHeight": "8px",
                "titleDisplay": "block",
                "titleSize": "10px",
                "metaDisplay": "block",
                "metaSize": "8px",
            }

            # Prototype ownership: a normal click on a New Task List Draft row
            # does not select or enter the editor; double-click edits it and
            # Back returns to the same Task List Draft route.
            draft_first_row = page.locator(".task-workspace-list-row").first
            draft_first_row.click()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            assert draft_first_row.get_attribute("aria-selected") == "false"
            assert "selected" not in (draft_first_row.get_attribute("class") or "").split()
            draft_first_row.dblclick()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.locator("#taskWorkspaceItemTitle").input_value() == "First list child"
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")

            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-edit").click()
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceItemTitle'")
            page.fill("#taskWorkspaceItemTitle", "First list child")
            page.fill("#taskWorkspacePrompt", "First list prompt")
            mixed_workflow = str(state.repo_root / "runner" / "assets" / "workflows" / "mixed.yaml")
            page.select_option("#taskWorkspaceWorkflow", mixed_workflow)
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 3"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("[data-task-source-card='validator']").is_visible()
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("""document.querySelector('[data-task-source-card="ai"]') !== null""")
            assert page.locator("[data-task-source-group='ai'] [data-task-source-mode='default']").get_attribute("aria-pressed") == "true"
            assert page.locator("#taskWorkspaceAiValidatorPrompt").count() == 0
            page.locator("[data-task-editor-tab='prompt']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")
            page.fill("#taskWorkspaceItemTitle", "First list child dirty")

            # A dirty child Editor and a dirty parent Task List Draft are two
            # separate discard decisions. Cancelling the parent decision must
            # leave the child Editor and its unsaved values untouched.
            for leave_kind in ("x", "prompts"):
                if leave_kind == "x":
                    page.click("#taskWorkspaceClose")
                else:
                    page.click("#taskWorkspaceOpenPrompts")
                page.wait_for_function("!document.querySelector('.ui-dialog-card')?.hidden")
                assert page.locator(".ui-dialog-card").get_by_text("unsaved Task edits", exact=False).is_visible()
                page.locator("[data-dialog-ok]").click()
                page.wait_for_function(
                    "() => !document.querySelector('.ui-dialog-card')?.hidden && document.querySelector('.ui-dialog-card')?.textContent.includes('unsaved TaskDraft edits')"
                )
                page.locator("[data-dialog-cancel]").click()
                page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
                assert page.locator("#taskWorkspaceItemTitle").input_value() == "First list child dirty"
                assert page.locator("#taskWorkspacePrompt").input_value() == "First list prompt"
                assert page.locator("#taskWorkspaceWorkflow").input_value() == mixed_workflow

            page.fill("#taskWorkspaceItemTitle", "First list child")
            assert page.locator("#taskWorkspaceSave").inner_text() == "Save changes"

            # Prototype ownership: child Save validates the child and stays in
            # the child Editor on field errors; parent Create List is not used
            # as a substitute for saving an item.
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator')?.getAttribute('aria-invalid') === 'true'")
            assert page.locator("[data-task-editor-tab='validator']").get_attribute("aria-selected") == "true"
            assert page.locator(".task-workspace-field-error").get_by_text("File Validator is required", exact=False).is_visible()
            page.locator("[data-task-editor-tab='prompt']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")
            assert page.locator("#taskWorkspacePrompt").input_value() == "First list prompt"
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")

            with page.expect_file_chooser() as chooser:
                page.locator("[data-task-upload-field='validator']").click()
            chooser.value.set_files(str(validator_upload))
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator')?.value.includes('.ai-task-runner')")
            staged_validator = page.locator("#taskWorkspaceValidator").input_value()
            assert state.task_uploads.staged_exists(root, staged_validator) is True
            validator_hint = page.locator("[data-task-source-card='validator'] .task-workspace-file-upload-hint")
            assert validator_hint.is_visible()
            assert "Uploaded · validator-upload.py" in validator_hint.inner_text()
            assert "Managed target path is shown above now" in validator_hint.inner_text()
            manual_validator = str(state.repo_root / "validate.py")
            page.fill("#taskWorkspaceValidator", manual_validator)
            assert page.locator("[data-task-source-card='validator'] .task-workspace-file-upload-hint").count() == 0
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("""document.querySelector('[data-task-source-card="ai"]') !== null""")
            page.locator("[data-task-source-group='ai'] [data-task-source-mode='file']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt')?.getAttribute('aria-invalid') === 'true'")
            assert page.locator(".task-workspace-field-error").get_by_text("AI Validator Prompt file is required", exact=False).is_visible()
            assert page.locator("#taskWorkspaceDraftTitle").count() == 0

            with page.expect_file_chooser() as chooser:
                page.locator("[data-task-upload-field='ai_validator_prompt_file']").click()
            chooser.value.set_files(str(ai_upload))
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt')?.value.includes('.ai-task-runner')")
            managed_ai_prompt = page.locator("#taskWorkspaceAiValidatorPrompt").input_value()
            assert state.task_uploads.staged_exists(root, managed_ai_prompt) is True
            ai_upload_hint = page.locator("[data-task-source-card='ai'] .task-workspace-file-upload-hint")
            assert ai_upload_hint.is_visible()
            assert "Uploaded · ai-upload.md" in ai_upload_hint.inner_text()

            # File -> Write -> File is non-destructive; only Default discards
            # the staged custom AI file.
            page.locator("[data-task-source-group='ai'] [data-task-source-mode='write']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPromptText') !== null")
            assert state.task_uploads.staged_exists(root, managed_ai_prompt) is True
            page.locator("[data-task-source-group='ai'] [data-task-source-mode='file']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == managed_ai_prompt
            assert state.task_uploads.staged_exists(root, managed_ai_prompt) is True

            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 3
            draft_first_row = page.locator(".task-workspace-list-row").first
            draft_first_row.click()
            assert draft_first_row.get_attribute("aria-selected") == "false"
            assert "selected" not in (draft_first_row.get_attribute("class") or "").split()
            draft_first_row.dblclick()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            draft_first_row = page.locator(".task-workspace-list-row").first
            assert draft_first_row.get_attribute("aria-selected") == "false"
            assert "selected" not in (draft_first_row.get_attribute("class") or "").split()

            # Feature parity: Draft reorder is drag-first, with Alt+Arrow as
            # the keyboard path. Prototype keeps the legacy ↑/↓ nodes only as
            # hidden compatibility markup.
            assert page.locator(".task-workspace-list-row").first.get_attribute("draggable") == "true"
            move_up = page.locator(".task-workspace-list-row").get_by_title("Move up")
            move_down = page.locator(".task-workspace-list-row").get_by_title("Move down")
            assert move_up.count() == 3
            assert move_down.count() == 3
            assert all(move_up.nth(i).is_hidden() for i in range(3))
            assert all(move_down.nth(i).is_hidden() for i in range(3))
            page.locator(".task-workspace-list-row").first.drag_to(page.locator(".task-workspace-list-row").nth(2))
            page.wait_for_function(
                "() => document.querySelectorAll('.task-workspace-list-row')[0]?.textContent.includes('Second list child')"
            )
            assert "First list child" in page.locator(".task-workspace-list-row").nth(1).inner_text()
            page.locator(".task-workspace-list-row").nth(1).focus()
            page.keyboard.press("Alt+ArrowUp")
            page.wait_for_function(
                "() => document.querySelectorAll('.task-workspace-list-row')[0]?.textContent.includes('First list child')"
            )
            page.locator(".task-workspace-list-row").last.get_by_role("button", name="Remove").click()
            assert page.locator(".task-workspace-list-row").count() == 2
            assert "Third list child" not in page.locator("#taskWorkspaceBody").inner_text()

            # X / Escape / footer Cancel share the parent TaskDraft dirty guard.
            # Keep editing must preserve the ordered children and their edits.
            for close_kind in ("x", "escape", "cancel"):
                if close_kind == "x":
                    page.click("#taskWorkspaceClose")
                elif close_kind == "escape":
                    page.locator("#taskWorkspaceDraftTitle").focus()
                    page.keyboard.press("Escape")
                else:
                    page.click("#taskWorkspaceFooterBack")
                page.wait_for_function("document.querySelector('.ui-dialog-card') !== null")
                assert page.locator(".ui-dialog-card").get_by_text("unsaved TaskDraft edits", exact=False).is_visible()
                page.locator("[data-dialog-cancel]").click()
                assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
                assert page.locator(".task-workspace-list-row").count() == 2
                assert "First list child" in page.locator(".task-workspace-list-row").first.inner_text()
                assert "Second list child" in page.locator(".task-workspace-list-row").nth(1).inner_text()

            page.fill("#taskWorkspaceDraftTitle", "Chat browser list")

            # Child validation already succeeded through the prototype-owned
            # Save changes action. Parent Create List should now only create the
            # durable Task List, not act as an implicit child save.
            assert page.locator("#taskWorkspaceDraftTitle").input_value() == "Chat browser list"

            # Double activation must still produce exactly one durable Task.
            page.evaluate("const b=document.querySelector('#taskWorkspaceHeaderCreateList'); b.click(); b.click();")
            page.wait_for_function(
                "() => document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO' || Boolean(document.querySelector('#taskWorkspaceError'))"
            )
            create_error = page.locator("#taskWorkspaceError").inner_text() if page.locator("#taskWorkspaceError").count() else ""
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO", create_error
            created = state.tasks.list(state.repo_root)["tasks"]
            assert len(created) == 2
            assert created[1]["kind"] == "task_list"
            assert [item["prompt"] for item in created[1]["items"]] == ["First list prompt", "Second list prompt"]
            assert created[1]["items"][0]["validator"] == manual_validator
            assert created[1]["items"][0]["ai_validator_prompt_file"] == managed_ai_prompt
            assert Path(managed_ai_prompt).read_text(encoding="utf-8") == "uploaded AI validator prompt\n"
            assert state.task_uploads.staged_exists(root, managed_ai_prompt) is False
            assert state.task_uploads.staged_exists(root, staged_validator) is False
            assert created[1]["project"] == str(state.repo_root.resolve())
            assert page.locator("#taskWorkspaceOpenList").is_visible()

            # Info/List/Editor/YAML are routes inside one physical Drawer.
            # Header height, shell width and Close position must not jump and
            # there must never be a second route-specific header.
            def task_workspace_geometry(*, workspace_route: bool):
                # Prototype intentionally animates between a narrow Task Info drawer
                # and the wider List / Editor / YAML workspace. Wait for the width
                # transition to settle before asserting physical geometry.
                page.wait_for_function(
                    """workspaceRoute => {
                        const shell = document.querySelector('#taskWorkspaceShell');
                        if (!shell) return false;
                        const viewport = window.innerWidth;
                        const target = workspaceRoute
                            ? Math.min(920, viewport * 0.94)
                            : Math.min(720, Math.max(620, viewport * 0.46));
                        return Math.abs(shell.getBoundingClientRect().width - target) <= 1.5;
                    }""",
                    arg=workspace_route,
                )
                shell = page.locator("#taskWorkspaceShell").bounding_box()
                head = page.locator("#taskWorkspaceShell .task-workspace-head").bounding_box()
                close = page.locator("#taskWorkspaceClose").bounding_box()
                assert shell and head and close
                assert page.locator("#taskWorkspaceShell .task-workspace-head").count() == 1
                transition = page.locator("#taskWorkspaceShell").evaluate(
                    "(node) => getComputedStyle(node).transition"
                )
                assert "transform" in transition and "width" in transition
                return {
                    "shell_width": shell["width"],
                    "head_height": head["height"],
                    "close_x": close["x"],
                    "close_y": close["y"],
                }

            info_geometry = task_workspace_geometry(workspace_route=False)
            page.click("#taskWorkspaceOpenList")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            list_geometry = task_workspace_geometry(workspace_route=True)
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Info"
            assert page.locator(".task-workspace-foot").evaluate("(node) => getComputedStyle(node).justifyContent") == "flex-end"
            assert page.locator(".task-workspace-foot").evaluate("(node) => getComputedStyle(node).position") == "relative"

            # Prototype Drawer owns keyboard focus. Tab from the last visible
            # footer control wraps to Back; Shift+Tab wraps back to Save.
            page.locator("#taskWorkspaceSave").focus()
            page.keyboard.press("Tab")
            assert page.evaluate("document.activeElement?.id") == "taskWorkspaceHeaderBack"
            page.keyboard.press("Shift+Tab")
            assert page.evaluate("document.activeElement?.id") == "taskWorkspaceSave"

            # Final prototype contract: durable rows collapse Edit/Remove into
            # one ⋯ action and expose the same action set on right-click.
            durable_rows = page.locator(".task-workspace-list-row")
            assert durable_rows.first.locator(".task-workspace-row-edit").count() == 0
            assert durable_rows.first.locator(".task-workspace-row-more").count() == 1
            assert durable_rows.first.locator(".task-workspace-drag-grip").inner_text() == "⠿"
            quick_help = page.locator(".task-workspace-list-help").inner_text()
            assert "Right-click or ⋯ for Info / Workflow / Remove." in quick_help
            durable_rows.first.locator(".task-workspace-row-more").click()
            context_menu = page.locator("#taskWorkspaceContextMenu")
            assert context_menu.is_visible()
            assert context_menu.evaluate("(node) => node.parentElement?.id") == "taskWorkspaceOverlay"
            assert context_menu.locator("[data-task-context-action='edit']").get_attribute("aria-label") == "Edit"
            assert context_menu.get_by_role("button", name="Edit", exact=True).is_enabled()
            assert context_menu.get_by_role("button", name="Info", exact=True).is_enabled()
            assert context_menu.get_by_role("button", name="Open Workflow", exact=True).is_enabled()
            assert context_menu.get_by_role("button", name="Remove", exact=True).is_enabled()

            # Prototype Info is an inline inspector, not "Back to Task Info".
            context_menu.get_by_role("button", name="Info", exact=True).click()
            assert context_menu.is_hidden()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            inspector = page.locator(".task-workspace-list-side-card.info-active")
            assert inspector.is_visible()
            assert inspector.locator("h3").inner_text() == "TASK INFO"
            inspector_labels = inspector.locator(".task-workspace-list-kv>span").all_inner_texts()
            assert inspector_labels == [
                "Task", "Status", "Project", "Workflow", "Prompt",
                "AI validation", "Workspace", "Branch", "Path",
            ]
            assert page.locator(".task-workspace-list-row.selected").count() == 1

            # Prototype reserves a fixed 205x220 placement box so a right-click
            # near the viewport edge never jumps lower than the reference UI.
            durable_rows.first.evaluate(
                """node => node.dispatchEvent(new MouseEvent('contextmenu', {
                    bubbles:true, cancelable:true,
                    clientX:window.innerWidth - 1,
                    clientY:window.innerHeight - 1
                }))"""
            )
            assert context_menu.is_visible()
            assert context_menu.evaluate("(node) => getComputedStyle(node).boxShadow") != "none"
            context_box = context_menu.bounding_box()
            assert context_box
            assert context_box["x"] <= 1440 - 205 - 8 + 1
            assert context_box["y"] <= 900 - 220 - 8 + 1

            # Escape only dismisses the context menu; the shared Drawer remains.
            page.keyboard.press("Escape")
            assert context_menu.is_hidden()
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            durable_rows.nth(1).click(button="right")
            assert context_menu.is_visible()
            context_menu.get_by_role("button", name="Edit", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            editor_geometry = task_workspace_geometry(workspace_route=True)
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")

            page.click("#taskWorkspaceHeaderYaml")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK YAML'")
            yaml_geometry = task_workspace_geometry(workspace_route=True)
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")

            # Feature parity: Move existing is a secondary chooser. Moving the
            # standalone New Task appends its item and retires its Board identity.
            assert page.locator("#taskWorkspaceHeaderMoveExisting").is_enabled()
            page.click("#taskWorkspaceHeaderMoveExisting")
            page.wait_for_function("document.querySelectorAll('.task-workspace-move-option').length === 1")
            move_overlay = page.locator(".task-workspace-move-overlay")
            assert move_overlay.is_visible()
            assert page.locator("#taskWorkspaceMoveTitle").inner_text() == "Move existing Task"
            assert "Move an unused New + Idle Task into this Task List." in move_overlay.inner_text()
            assert "Only unused New tasks can be moved." in move_overlay.inner_text()
            move_dialog_box = page.locator(".task-workspace-move-existing").bounding_box()
            assert move_dialog_box and abs(move_dialog_box["width"] - 620) <= 1

            # All three close operations are user-visible controls and must
            # converge on the same chooser cleanup + focus restoration.
            page.locator(".task-workspace-move-close").click()
            assert page.locator(".task-workspace-move-overlay").count() == 0
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceHeaderMoveExisting'")

            page.click("#taskWorkspaceHeaderMoveExisting")
            page.wait_for_function("document.querySelectorAll('.task-workspace-move-option').length === 1")
            page.get_by_role("button", name="Cancel", exact=True).click()
            assert page.locator(".task-workspace-move-overlay").count() == 0
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceHeaderMoveExisting'")

            page.click("#taskWorkspaceHeaderMoveExisting")
            page.wait_for_function("document.querySelectorAll('.task-workspace-move-option').length === 1")
            page.keyboard.press("Escape")
            assert page.locator(".task-workspace-move-overlay").count() == 0
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            page.wait_for_function("document.activeElement?.id === 'taskWorkspaceHeaderMoveExisting'")
            assert page.locator("#taskWorkspaceHeaderMoveExisting").evaluate("(node) => document.activeElement === node")

            page.click("#taskWorkspaceHeaderMoveExisting")
            page.wait_for_function("document.querySelectorAll('.task-workspace-move-option').length === 1")
            move_option = page.locator(".task-workspace-move-option").first
            assert "Standalone browser task" in move_option.inner_text()
            move_option.click()
            assert page.locator(".task-workspace-move-option.selected").count() == 1
            page.get_by_role("button", name="Move here", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.task-workspace-list-row').length === 3")
            moved_records = state.tasks.list(state.repo_root)["tasks"]
            assert len(moved_records) == 1
            assert moved_records[0]["task_id"] == created[1]["task_id"]
            assert [item["prompt"] for item in moved_records[0]["items"]][-1] == "Standalone task prompt"
            assert page.locator(".task-workspace-move-existing").count() == 0

            # Accepted prototype contract: Task Info is the narrow drawer,
            # while List / Editor / YAML share one wider workspace route.
            assert list_geometry["shell_width"] > info_geometry["shell_width"]
            for geometry in (editor_geometry, yaml_geometry):
                assert abs(geometry["shell_width"] - list_geometry["shell_width"]) <= 1
            for geometry in (list_geometry, editor_geometry, yaml_geometry):
                assert abs(geometry["head_height"] - info_geometry["head_height"]) <= 1
                assert abs(geometry["close_x"] - info_geometry["close_x"]) <= 1
                assert abs(geometry["close_y"] - info_geometry["close_y"]) <= 1

            page.click("#taskWorkspaceFooterBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            final_info_geometry = task_workspace_geometry(workspace_route=False)
            assert abs(final_info_geometry["shell_width"] - info_geometry["shell_width"]) <= 1
            assert abs(final_info_geometry["head_height"] - info_geometry["head_height"]) <= 1
            assert abs(final_info_geometry["close_x"] - info_geometry["close_x"]) <= 1
            assert abs(final_info_geometry["close_y"] - info_geometry["close_y"]) <= 1
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_info_explains_non_new_edit_and_delete_block() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        project_row = state.projects()[0]
        draft = {
            "title": "Running task cannot be deleted",
            "items": [
                {
                    "title": "Child A",
                    "prompt": "Keep runtime state safe",
                    "workflow": "workflow.yaml",
                    "project": str(root),
                    "workspace": "auto",
                },
                {
                    "title": "Child B",
                    "prompt": "Do not expose Add Task while Ongoing",
                    "workflow": "workflow.yaml",
                    "project": str(root),
                    "workspace": "auto",
                },
            ],
        }
        created = state.tasks.create(
            root,
            draft,
            request_id="non-new-delete-block",
            project_id=project_row["project_id"],
        )
        task_path = state.tasks._state_path(root)
        raw = json.loads(task_path.read_text(encoding="utf-8"))
        raw["tasks"][0]["status"] = "ongoing"
        task_path.write_text(json.dumps(raw), encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('#tasksBoardOngoing .tasks-board-card').length === 1")
            page.locator("#tasksBoardOngoing .tasks-board-card").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            assert page.locator(".task-workspace-tab").all_inner_texts() == ["Overview", "Runtime", "Output", "History"]
            assert page.locator(".task-workspace-meta-grid dt").all_inner_texts() == ["Project", "Type", "Items"]
            page.evaluate("window.__taskShell = document.querySelector('#taskWorkspaceShell')")
            normal_shell = page.locator("#taskWorkspaceShell").bounding_box()
            assert normal_shell
            expand_button = page.locator("#taskWorkspaceExpand")
            assert expand_button.get_attribute("aria-pressed") == "false"
            expand_button.click()
            page.wait_for_function(
                "(width) => document.querySelector('#taskWorkspaceShell').getBoundingClientRect().width > width + 8",
                arg=normal_shell["width"],
            )
            expanded_shell = page.locator("#taskWorkspaceShell").bounding_box()
            assert expanded_shell
            assert expanded_shell["width"] > normal_shell["width"]
            assert expanded_shell["x"] + expanded_shell["width"] <= 1441
            assert expand_button.get_attribute("aria-pressed") == "true"
            assert page.evaluate("window.__taskShell === document.querySelector('#taskWorkspaceShell')")
            expand_button.click()
            page.wait_for_function(
                "(width) => Math.abs(document.querySelector('#taskWorkspaceShell').getBoundingClientRect().width - width) <= 2",
                arg=normal_shell["width"],
            )
            collapsed_shell = page.locator("#taskWorkspaceShell").bounding_box()
            assert collapsed_shell
            assert abs(collapsed_shell["width"] - normal_shell["width"]) <= 2

            page.evaluate("window.I18n.setLanguage('zh-TW')")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === '任務資訊'")
            assert page.locator(".task-workspace-tab").all_inner_texts() == ["總覽", "執行狀態", "輸出", "歷史"]
            assert page.locator(".task-workspace-meta-grid dt").all_inner_texts() == ["專案", "類型", "項目"]
            assert page.locator("#taskWorkspaceExpand").get_attribute("title") == "展開任務工作區"
            assert page.locator("#taskWorkspaceClose").get_attribute("aria-label") == "關閉任務工作區"
            page.get_by_role("button", name="執行狀態", exact=True).click()
            assert page.locator(".task-workspace-empty-panel strong").inner_text() == "尚無 Runner 執行狀態"
            page.evaluate("window.I18n.setLanguage('en')")
            page.wait_for_function("document.querySelector('.task-workspace-empty-panel strong')?.textContent === 'No Runner runtime yet'")
            page.get_by_role("button", name="Overview", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            delete_button = page.locator("#taskWorkspaceDeleteTask")
            assert delete_button.is_disabled()
            list_button = page.locator("#taskWorkspaceOpenList")
            assert list_button.is_visible()
            assert list_button.is_enabled()
            restriction = page.locator(".task-workspace-action-note").inner_text()
            assert "Delete is unavailable while this Task has active or resumable lifecycle state." in restriction
            assert "Task List is view-only. Pause this Task before editing runtime-affecting content." in restriction

            list_button.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 2
            assert page.locator(".task-workspace-row-more").count() == 2
            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-more").click()
            readonly_menu = page.locator("#taskWorkspaceContextMenu")
            assert readonly_menu.is_visible()
            assert readonly_menu.get_by_role("button", name="Edit", exact=True).is_disabled()
            assert readonly_menu.get_by_role("button", name="Remove", exact=True).is_disabled()
            page.keyboard.press("Escape")
            assert readonly_menu.is_hidden()
            add_button = page.locator("#taskWorkspaceAddTask")
            yaml_button = page.locator("#taskWorkspaceHeaderYaml")
            assert add_button.is_disabled()
            assert yaml_button.is_disabled()
            assert "Pause this Task before editing" in (add_button.get_attribute("title") or "")
            assert "Pause this Task before editing" in (yaml_button.get_attribute("title") or "")
            assert page.locator("#taskWorkspaceSave").is_hidden()
            assert "Task List is view-only" in page.locator(".task-workspace-action-note").inner_text()
            page.click("#taskWorkspaceFooterBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            assert state.tasks.get(root, created["task_id"])["status"] == "ongoing"
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_info_tabs_render_canonical_runtime_output_and_history() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        project_row = state.projects()[0]
        created = state.tasks.create(
            root,
            {
                "title": "Projected runtime task",
                "items": [
                    {
                        "title": "Child A",
                        "prompt": "First projected item",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "auto",
                    },
                    {
                        "title": "Child B",
                        "prompt": "Second projected item",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "auto",
                    },
                ],
            },
            request_id="projected-runtime-tabs",
            project_id=project_row["project_id"],
        )
        projected = json.loads(json.dumps(created))
        projected.update({
            "status": "ongoing",
            "completed_item_count": 1,
            "runner_runtime": {
                "running": True,
                "status": "running",
                "run_id": "runtime-2",
                "stage": "review",
                "cycle": 4,
                "task": "Child B",
                "current": 2,
                "total": 2,
                "updated_at": 1_700_000_030,
                "backend": "qwen",
                "model": "qwen3-coder",
                "effective_backend": "qwen",
                "effective_model": "qwen3-coder",
                "last_transition": {
                    "stage": "execute",
                    "status": "pass",
                    "target": "review",
                    "kind": "route",
                },
                "recovery": {"status": "running", "retry_mode": "same-session"},
                "cli_lines": ["AI Task Runner", "review: checking projected result"],
                "cli_status": "running",
                "cli_detail": "Review in progress",
                "activity_summary": ["Qwen review", {"kind": "tool", "detail": "validator"}],
                "stream": "fallback stream line",
            },
            "run": {
                "run_number": 2,
                "item_index": 1,
                "phase": "running",
                "started_at": 1_700_000_020,
                "updated_at": 1_700_000_030,
                "error": "",
                "workspace_result": {},
            },
            "history": [
                {
                    "run_number": 1,
                    "item_index": 0,
                    "phase": "worktree_ready",
                    "started_at": 1_700_000_000,
                    "updated_at": 1_700_000_010,
                    "archived_at": 1_700_000_015,
                    "lifecycle_end": "rerun",
                    "error": "",
                    "workspace_result": {"merge": {"status": "worktree_ready"}},
                }
            ],
        })
        state.task_runs.list = lambda _project: {"tasks": [json.loads(json.dumps(projected))]}

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('#tasksBoardOngoing .tasks-board-card').length === 1")
            page.locator("#tasksBoardOngoing .tasks-board-card").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            page.get_by_role("button", name="Runtime", exact=True).click()
            page.wait_for_selector("#taskWorkspaceRuntimePanel")
            runtime_text = page.locator("#taskWorkspaceRuntimePanel").inner_text()
            assert "review" in runtime_text
            assert "2 / 2" in runtime_text
            assert "qwen3-coder" in runtime_text
            assert "execute PASS → review" in runtime_text
            assert "same-session" in runtime_text

            page.get_by_role("button", name="Output", exact=True).click()
            page.wait_for_selector("#taskWorkspaceOutputPanel")
            assert "Review in progress" in page.locator("#taskWorkspaceOutputPanel").inner_text()
            assert "Qwen review" in page.locator("#taskWorkspaceActivityList").inner_text()
            assert "tool · validator" in page.locator("#taskWorkspaceActivityList").inner_text()
            assert "review: checking projected result" in page.locator("#taskWorkspaceCliOutput").inner_text()
            assert "fallback stream line" not in page.locator("#taskWorkspaceCliOutput").inner_text()

            page.get_by_role("button", name="History", exact=True).click()
            page.wait_for_selector("#taskWorkspaceHistoryPanel")
            rows = page.locator("#taskWorkspaceHistoryPanel .task-history-row")
            assert rows.count() == 2
            assert "Run #2" in rows.nth(0).inner_text()
            assert "CURRENT" in rows.nth(0).inner_text()
            assert "Run #1" in rows.nth(1).inner_text()
            assert "worktree ready" in rows.nth(1).inner_text().lower()
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_paused_task_locks_completed_child_and_restarts_edited_current() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        (root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        project_row = state.projects()[0]
        created = state.tasks.create(
            root,
            {
                "title": "Paused editable list",
                "items": [
                    {
                        "title": "Completed child",
                        "prompt": "Frozen completed prompt",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "auto",
                    },
                    {
                        "title": "Current child",
                        "prompt": "Current paused prompt",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "main",
                    },
                    {
                        "title": "Future child",
                        "prompt": "Future prompt",
                        "workflow": "workflow.yaml",
                        "project": str(root),
                        "workspace": "worktree",
                    },
                ],
            },
            request_id="paused-browser-create",
            project_id=project_row["project_id"],
        )
        task_path = state.tasks._state_path(root)
        raw = json.loads(task_path.read_text(encoding="utf-8"))
        raw["tasks"][0]["status"] = "paused"
        raw["tasks"][0]["completed_item_count"] = 1
        task_path.write_text(json.dumps(raw), encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('#tasksBoardPaused .tasks-board-card').length === 1")
            page.locator("#tasksBoardPaused .tasks-board-card").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            list_button = page.locator("#taskWorkspaceOpenList")
            assert list_button.is_enabled()
            assert list_button.inner_text() == "Edit Task List"
            assert page.locator("#taskWorkspaceDeleteTask").is_disabled()

            list_button.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            rows = page.locator(".task-workspace-list-row")
            assert rows.count() == 3
            assert rows.nth(0).locator(".task-workspace-list-state").inner_text() == "COMPLETED"
            assert rows.nth(1).locator(".task-workspace-list-state").inner_text() == "CURRENT"
            assert rows.nth(2).locator(".task-workspace-list-state").inner_text() == "FUTURE"
            assert "done" in (rows.nth(0).get_attribute("class") or "").split()
            assert "current" in (rows.nth(1).get_attribute("class") or "").split()
            assert "done" not in (rows.nth(2).get_attribute("class") or "").split()
            assert "current" not in (rows.nth(2).get_attribute("class") or "").split()
            assert rows.nth(0).evaluate("node => getComputedStyle(node).opacity") == "0.68"
            current_background = rows.nth(1).evaluate("node => getComputedStyle(node).backgroundColor")
            future_background = rows.nth(2).evaluate("node => getComputedStyle(node).backgroundColor")
            assert current_background != future_background

            context_menu = page.locator("#taskWorkspaceContextMenu")
            completed = rows.nth(0)
            completed.locator(".task-workspace-row-more").click()
            assert context_menu.get_by_role("button", name="Edit", exact=True).is_disabled()
            assert context_menu.get_by_role("button", name="Remove", exact=True).is_disabled()
            page.keyboard.press("Escape")
            assert completed.get_attribute("draggable") == "false"

            current = rows.nth(1)
            current.locator(".task-workspace-row-more").click()
            assert context_menu.get_by_role("button", name="Edit", exact=True).is_enabled()
            assert context_menu.get_by_role("button", name="Remove", exact=True).is_disabled()
            page.keyboard.press("Escape")
            assert current.get_attribute("draggable") == "false"

            future = rows.nth(2)
            future.locator(".task-workspace-row-more").click()
            assert context_menu.get_by_role("button", name="Edit", exact=True).is_enabled()
            assert context_menu.get_by_role("button", name="Remove", exact=True).is_enabled()
            page.keyboard.press("Escape")
            assert future.get_attribute("draggable") == "true"
            assert page.locator("#taskWorkspaceAddTask").is_enabled()
            assert page.locator("#taskWorkspaceHeaderYaml").is_disabled()
            assert "Completed Task items are locked" in (
                page.locator("#taskWorkspaceHeaderYaml").get_attribute("title") or ""
            )

            current.locator(".task-workspace-row-more").click()
            context_menu.get_by_role("button", name="Edit", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspacePrompt", "Edited current prompt")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert "restart required" in page.locator(".task-workspace-action-note").inner_text().lower()

            saved = state.tasks.get(root, created["task_id"])
            assert saved["status"] == "paused"
            assert saved["restart_required"] is True
            assert saved["items"][0]["prompt"] == "Frozen completed prompt"
            assert saved["items"][1]["prompt"] == "Edited current prompt"
            assert saved["edit_policy"]["items"][0]["editable"] is False
            assert saved["edit_policy"]["items"][1]["editable"] is True
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_browser_workflow_settings_manager_and_prompt_crud() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        (state.repo_root / "runner" / "assets" / "workflows" / "workflow.yaml").write_text(
            "stages: {}\nflow: []\n",
            encoding="utf-8",
        )
        state.studio_workflow_create("e2e_crud", "global", None)

        # Real Prompt impact fixture: a second Workflow references a Prompt so
        # the browser verifies the same backend usage evidence shown by rename/delete safety.
        prompt = state.studio_prompt_create("used_prompt", "global", None)
        used_workflow = state.studio_workflow_create("uses_prompt", "global", None)
        used_file = state.studio_read(used_workflow["item"]["id"], None)
        state.studio_save(
            used_workflow["item"]["id"],
            (
                "stages:\n"
                "  review:\n"
                "    type: base\n"
                "    profile: review\n"
                "    prompt: common/used_prompt.md\n"
                "flow: [review]\n"
            ),
            used_file["hash"],
            None,
        )

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            page.route(
                "http://local.test/workflow-studio-app/**",
                lambda route: route.fulfill(status=200, content_type="text/html", body="<html><body>Workflow Editor</body></html>"),
            )
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            # Tasks opens the durable Board; the legacy Runner console remains a Tasks subview.
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            assert page.locator("#chatView").is_hidden()
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.wait_for_function("document.querySelector('#chatNav')?.classList.contains('active')")

            # Environment diagnostics stay readable but the completed checklist can collapse.
            page.locator("#optionsButton").click()
            page.locator("#environmentCheckButton").click()
            page.wait_for_function("document.querySelector('.environment-check-toggle')?.getAttribute('aria-expanded') === 'true'")
            assert page.locator("#environmentCheckDetails").is_visible()
            page.locator(".environment-check-toggle").click()
            assert page.locator(".environment-check-toggle").get_attribute("aria-expanded") == "false"
            assert page.locator("#environmentCheckDetails").is_hidden()
            page.locator(".environment-check-toggle").click()
            assert page.locator(".environment-check-toggle").get_attribute("aria-expanded") == "true"
            assert page.locator("#environmentCheckDetails").is_visible()
            page.locator("#optionsCloseButton").click()

            # Shared dialogs must restore keyboard focus to the control that opened them.
            page.locator("#openProject").focus()
            page.evaluate("void window.UiDialogs.confirm({title:'Confirm focus', message:'Regression', confirmLabel:'OK'})")
            page.locator("[data-dialog-cancel]").click()
            page.wait_for_function("document.activeElement?.id === 'openProject'")

            page.click("#workflowNav")
            page.wait_for_function("document.querySelector('#workflowNav')?.classList.contains('active')")
            page.wait_for_function("document.querySelector('.studio-designer-body')?.classList.contains('workflow-manager-mode')")
            assert page.locator(".studio-designer-body").evaluate(
                "node => node.classList.contains('workflow-manager-mode')"
            )
            assert not page.locator(".studio-workflow-main").is_visible()
            sidebar = page.locator(".studio-workflow-sidebar").bounding_box()
            body = page.locator(".studio-designer-body").bounding_box()
            assert sidebar and body
            assert abs(sidebar["width"] - body["width"]) <= 2
            workflow_row = page.locator("#studioFileList .studio-file-item").filter(
                has_text="e2e_crud.workflow.yaml"
            )
            assert workflow_row.count() == 1
            assert workflow_row.locator(".studio-file-item-action").count() == 1

            # Search no-result is actionable and restores the list without navigation.
            page.fill("#studioSearchInput", "definitely-no-match")
            page.wait_for_timeout(80)
            assert page.locator(".studio-list-empty", has_text="No matching workflows").count() == 1
            page.locator(".studio-empty-action", has_text="Clear search").click()
            page.wait_for_timeout(80)
            assert page.locator("#studioSearchInput").input_value() == ""
            assert workflow_row.count() == 1

            # Right-click visibility is owned by the Workflow Library and updates Chat immediately.
            workflow_row.click(button="right")
            assert page.locator("#workflowContextMenu").is_visible()
            for control in (
                "#workflowContextOpen", "#workflowContextVisibility", "#workflowContextRename",
                "#workflowContextDuplicate", "#workflowContextExport", "#workflowContextDelete",
            ):
                assert page.locator(control).is_visible()
            page.click("#workflowContextVisibility")
            page.wait_for_timeout(80)
            assert workflow_row.locator("small.hidden-state").count() == 1
            assert page.locator("#workflowSelect option", has_text="e2e_crud.workflow.yaml").count() == 0

            workflow_row.click(button="right")
            assert page.locator("#workflowContextVisibility").is_visible()
            page.click("#workflowContextVisibility")
            page.wait_for_timeout(80)
            assert workflow_row.locator("small.hidden-state").count() == 0
            assert page.locator("#workflowSelect option", has_text="e2e_crud.workflow.yaml").count() == 1

            # Prompt assets keep the inline master-detail editor.
            page.click("#promptNav")
            page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
            page.wait_for_function("document.querySelector('.studio-designer-body')?.classList.contains('prompt-manager-mode')")
            assert page.locator(".studio-designer-body").evaluate(
                "node => node.classList.contains('prompt-manager-mode')"
            )

            used_prompt_row = page.locator("#studioFileList .studio-file-item").filter(
                has_text="used_prompt.md"
            )
            assert used_prompt_row.count() == 1
            used_prompt_row.click()
            page.wait_for_function("document.querySelector('#studioFileName')?.textContent === 'used_prompt.md'")
            assert page.locator("#studioPromptUsedBy .prompt-used-by-chip", has_text="uses_prompt.workflow.yaml · review").count() == 1

            # Project rows are a Tasks/Chat navigation affordance from both asset pages.
            # Regression: Prompts used to leave the UI on the Prompt manager because
            # Project selection always returns to the Project Chat, not the Tasks/Runner surface.
            page.locator("#projectList .project-root").first.click()
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
            assert not page.locator("#chatNav").evaluate("(node) => node.classList.contains('active')")
            assert page.locator("#projectChatView").is_visible()
            assert page.locator("#chatView").is_hidden()
            assert page.locator("#workflowView").is_hidden()
            assert page.locator("#openProject.new-project-button").count() == 1
            assert page.locator(".project-add-button").count() == 0
            sidebar_project_geometry = page.evaluate(
                """() => {
                    const create = document.querySelector('#openProject').getBoundingClientRect();
                    const scroll = document.querySelector('.sidebar-scroll').getBoundingClientRect();
                    const label = document.querySelector('.project-section-label').getBoundingClientRect();
                    const list = document.querySelector('#projectList').getBoundingClientRect();
                    const currentPath = document.querySelector('#projectSwitcherPath').getBoundingClientRect();
                    const overflow = getComputedStyle(document.querySelector('.sidebar-scroll')).overflowY;
                    const listOverflow = getComputedStyle(document.querySelector('#projectList')).overflowY;
                    const sidebar = document.querySelector('.projects').getBoundingClientRect();
                    const settings = document.querySelector('.sidebar-global-settings').getBoundingClientRect();
                    const settingsNode = document.querySelector('.sidebar-global-settings');
                    return {
                        createBottom: create.bottom,
                        scrollTop: scroll.top,
                        scrollBottom: scroll.bottom,
                        labelTop: label.top,
                        labelBottom: label.bottom,
                        listTop: list.top,
                        currentPathBottom: currentPath.bottom,
                        overflow,
                        listOverflow,
                        settingsTop: settings.top,
                        settingsGap: sidebar.bottom - settings.bottom,
                        settingsIsLast: settingsNode === settingsNode.parentElement.lastElementChild
                    };
                }"""
            )
            assert sidebar_project_geometry["createBottom"] <= sidebar_project_geometry["scrollTop"] + 1
            assert sidebar_project_geometry["labelBottom"] <= sidebar_project_geometry["listTop"] + 1
            assert sidebar_project_geometry["overflow"] in {"auto", "scroll"}
            assert sidebar_project_geometry["listOverflow"] == "visible"
            assert sidebar_project_geometry["currentPathBottom"] <= sidebar_project_geometry["scrollBottom"] + 1
            assert sidebar_project_geometry["scrollBottom"] <= sidebar_project_geometry["settingsTop"] + 1
            assert sidebar_project_geometry["settingsIsLast"] is True
            assert page.locator("#projectSwitcherPath").inner_text() == str(root)
            assert 0 <= sidebar_project_geometry["settingsGap"] <= 12
            assert page.locator(".sidebar-foot").count() == 0
            assert page.locator("#themeButton .global-settings-copy small").inner_text() == "Global runner preferences"
            settings_visual = page.evaluate(
                """() => {
                    const button = document.querySelector('#themeButton');
                    const icon = button.querySelector('.nav-icon');
                    const copy = button.querySelector('.global-settings-copy');
                    const ib = icon.getBoundingClientRect();
                    const bb = button.getBoundingClientRect();
                    const cs = getComputedStyle(copy);
                    return {
                        iconCount: button.querySelectorAll('.nav-icon').length,
                        iconWidth: ib.width,
                        iconHeight: ib.height,
                        buttonHeight: bb.height,
                        gap: getComputedStyle(button).gap,
                        copyBackground: cs.backgroundColor,
                        copyDisplay: cs.display,
                        copyWidth: copy.getBoundingClientRect().width,
                    };
                }"""
            )
            assert settings_visual["iconCount"] == 1
            assert abs(settings_visual["iconWidth"] - 24) <= 1
            assert abs(settings_visual["iconHeight"] - 24) <= 1
            assert abs(settings_visual["buttonHeight"] - 40) <= 1
            assert settings_visual["gap"] == "9px"
            assert settings_visual["copyBackground"] == "rgba(0, 0, 0, 0)"
            assert settings_visual["copyDisplay"] == "grid"
            assert settings_visual["copyWidth"] > 40

            # Project Chat session lifecycle is real Backend state, not a browser-only mock.
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 1")
            assert page.locator(".project-chat-preference-bar").count() == 0
            assert page.locator("#projectChatPreferences").count() == 0
            assert page.locator(".composer-left > #projectChatSettingsButton").count() == 1
            assert page.locator(".project-chat-sessions").count() == 0
            assert page.locator("#projectChatSessionSelect").is_visible()
            assert page.locator("#renameProjectChatButton").is_visible()
            assert page.locator("#deleteProjectChatButton").is_visible()
            chat_geometry = page.evaluate(
                """() => {
                    const body = document.querySelector('.project-chat-body').getBoundingClientRect();
                    const conversation = document.querySelector('.project-chat-conversation').getBoundingClientRect();
                    return {bodyWidth: body.width, conversationWidth: conversation.width, bodyHeight: body.height, conversationHeight: conversation.height};
                }"""
            )
            assert abs(chat_geometry["bodyWidth"] - chat_geometry["conversationWidth"]) <= 1
            assert abs(chat_geometry["bodyHeight"] - chat_geometry["conversationHeight"]) <= 1
            page.fill("#projectChatInput", "/bt")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            page.click("#projectChatSettingsButton")
            page.wait_for_function("!document.querySelector('#projectChatSettingsPopover')?.hidden")
            assert page.locator("#projectChatSettingsPopover").is_visible()
            assert page.locator("#projectChatSuggest").is_hidden()
            assert page.locator("#projectChatModeSelect").count() == 0
            assert page.locator("#projectChatAskCapability").count() == 0
            page.select_option("#projectChatAgentSelect", "opencode")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'opencode'")
            page.select_option("#projectChatModelSelect", "openai/gpt-5.2")
            page.wait_for_function("document.querySelector('#projectChatReasoningSelect')?.querySelector('option[value=\"deep\"]') !== null")
            page.select_option("#projectChatReasoningSelect", "deep")
            page.select_option("#projectChatModeQuick", "yolo")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'yolo'")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.title.includes('Automatically approves tools')")
            assert "Automatically approves tools" in (page.locator("#projectChatModeQuick").get_attribute("title") or "")
            page.select_option("#projectChatModeQuick", "read")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'read'")

            # Agent switch clears the previous Agent's model ID and loads only legal native options.
            page.select_option("#projectChatAgentSelect", "qwen")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'qwen'")
            page.wait_for_function("document.querySelector('#projectChatModelSelect')?.value === ''")
            assert page.locator("#projectChatModelSelect option[value='openai/gpt-5.2']").count() == 0
            assert page.locator("#projectChatModelSelect option[value='qwen/model-a']").count() == 1
            page.click("#projectChatInput")
            assert page.locator("#projectChatSettingsPopover").is_hidden()
            page.fill("#projectChatInput", "")
            page.fill("#projectChatInput", "/bt")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            assert page.locator("#projectChatSuggestList .project-chat-suggest-token").get_by_text("/btw").is_visible()
            page.keyboard.press("Escape")

            # Restore OpenCode for the remaining Project/session-scoping flow.
            page.click("#projectChatSettingsButton")
            page.wait_for_function("!document.querySelector('#projectChatSettingsPopover')?.hidden")
            page.select_option("#projectChatAgentSelect", "opencode")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'opencode'")
            page.select_option("#projectChatModelSelect", "openai/gpt-5.2")
            page.wait_for_function("document.querySelector('#projectChatReasoningSelect')?.querySelector('option[value=\\\"deep\\\"]') !== null")
            page.select_option("#projectChatReasoningSelect", "deep")
            page.select_option("#projectChatModeQuick", "read")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'read'")
            assert page.locator("#projectChatSettingsPopover").is_visible()
            page.keyboard.press("Escape")
            assert page.locator("#projectChatSettingsPopover").is_hidden()
            page.click("#projectChatSettingsButton")
            assert page.locator("#projectChatSettingsPopover").is_visible()
            page.evaluate("window.dispatchEvent(new Event('scroll'))")
            assert page.locator("#projectChatSettingsPopover").is_hidden()
            page.click("#projectChatSettingsButton")
            page.click("#projectChatSettingsClose")
            assert page.locator("#projectChatSettingsPopover").is_hidden()

            page.fill("#projectChatInput", "@task-l")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            assert page.locator("#projectChatSuggestTitle").inner_text() == "Runner Commands / Prompts"
            assert page.locator("#projectChatSuggestList .project-chat-suggest-item").count() == 1
            page.keyboard.press("Tab")
            assert page.locator("#projectChatInput").input_value() == "@task-list "
            page.fill("#projectChatInput", "@task-list browser plan")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 1")
            assert page.locator(".project-chat-task-draft").get_by_text("Browser generated draft").is_visible()
            assert page.locator(".project-chat-task-draft-item").count() == 2
            assert state.tasks.list(state.repo_root)["tasks"] == []

            chat_before = page.locator("#projectChatView").bounding_box()
            scroll_before = page.evaluate(
                "() => [window.scrollX, window.scrollY, document.querySelector('#projectChatMessages')?.scrollTop || 0]"
            )
            page.get_by_role("button", name="Edit Draft").click()
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator(".task-workspace-list-row").count() == 2
            assert page.evaluate(
                "() => getComputedStyle(document.querySelector('#taskWorkspaceOverlay')).position === 'fixed'"
                " && Number.parseInt(getComputedStyle(document.querySelector('#taskWorkspaceOverlay')).zIndex, 10) >= 520"
            )
            assert page.evaluate(
                "() => [window.scrollX, window.scrollY, document.querySelector('#projectChatMessages')?.scrollTop || 0]"
            ) == scroll_before
            page.evaluate("window.__sharedTaskWorkspaceShell = document.querySelector('#taskWorkspaceShell')")
            chat_during = page.locator("#projectChatView").bounding_box()
            assert chat_before and chat_during
            for key in ("x", "y", "width", "height"):
                assert abs(chat_before[key] - chat_during[key]) <= 1

            page.locator(".task-workspace-row-edit").first.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.evaluate(
                "window.__sharedTaskWorkspaceShell === document.querySelector('#taskWorkspaceShell')"
            )
            chat_editor = page.locator("#projectChatView").bounding_box()
            assert chat_editor
            for key in ("x", "y", "width", "height"):
                assert abs(chat_before[key] - chat_editor[key]) <= 1
            chat_editor_fields = page.evaluate(
                """() => Array.from(
                    document.querySelectorAll('#taskWorkspaceShell input[id], #taskWorkspaceShell select[id], #taskWorkspaceShell textarea[id]')
                ).map((node) => node.id).sort()"""
            )
            page.fill("#taskWorkspacePrompt", "Edited browser item one")
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelectorAll('.task-workspace-list-row').length === 2")
            assert page.locator(".task-workspace-list-row").first.locator(".task-workspace-list-copy strong").is_visible()
            page.locator(".task-workspace-row-edit").first.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.locator("#taskWorkspacePrompt").input_value() == "Edited browser item one"
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            chat_after = page.locator("#projectChatView").bounding_box()
            assert chat_after
            for key in ("x", "y", "width", "height"):
                assert abs(chat_before[key] - chat_after[key]) <= 1
            assert page.evaluate(
                "() => [window.scrollX, window.scrollY, document.querySelector('#projectChatMessages')?.scrollTop || 0]"
            ) == scroll_before
            draft_card = page.locator(".project-chat-task-draft").first
            assert draft_card.get_by_text("Edited browser item one").is_visible()
            assert draft_card.get_attribute("data-draft-id")
            assert draft_card.get_attribute("data-session-id")
            assert state.tasks.list(state.repo_root)["tasks"] == []
            # The real E2E ownership proof is create-from-draft below: the
            # browser sends only draft_id/session_id, then we assert the backend
            # canonical edit is what reaches the durable Task.
            page.get_by_role("button", name="Create Task", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")
            durable = state.tasks.list(state.repo_root)["tasks"]
            assert len(durable) == 1
            assert durable[0]["status"] == "new"
            assert state._browser_last_create_from_draft["items"][0]["prompt"] == "Edited browser item one"
            assert durable[0]["items"][0]["prompt"] == "Edited browser item one"
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO"
            assert page.locator(".task-workspace-tabs .task-workspace-tab").all_inner_texts() == [
                "Overview", "Runtime", "Output", "History",
            ]
            assert page.locator(".task-workspace-status-pill").inner_text() == "NEW"
            assert page.locator(".task-workspace-info-row").count() == 2
            page.click("#taskWorkspaceOpenList")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 2
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Info"
            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-more").click()
            page.locator("#taskWorkspaceContextMenu").get_by_role("button", name="Edit", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.evaluate(
                "window.__sharedTaskWorkspaceShell === document.querySelector('#taskWorkspaceShell')"
            )
            durable_editor_fields = page.evaluate(
                """() => Array.from(
                    document.querySelectorAll('#taskWorkspaceShell input[id], #taskWorkspaceShell select[id], #taskWorkspaceShell textarea[id]')
                ).map((node) => node.id).sort()"""
            )
            assert durable_editor_fields == chat_editor_fields
            page.fill("#taskWorkspacePrompt", "Durably edited browser item one")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.wait_for_function(
                "document.querySelector('#taskWorkspaceSave')?.getAttribute('aria-busy') !== 'true'"
            )
            assert page.locator(".task-workspace-list-row").count() == 2
            assert (
                state.tasks.list(state.repo_root)["tasks"][0]["items"][0]["prompt"]
                == "Durably edited browser item one"
            )

            # Prototype create-item ownership: a provisional child belongs to
            # the child editor until Save. Back guards dirty input and Discard
            # removes that provisional child instead of silently keeping it.
            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "Discarded browser child")
            page.fill("#taskWorkspacePrompt", "Discard this child prompt")
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('.ui-dialog-card') !== null")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 2

            page.click("#taskWorkspaceAddTask")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            page.fill("#taskWorkspaceItemTitle", "Added browser child")
            page.fill("#taskWorkspacePrompt", "Added child prompt")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator(".task-workspace-list-row").count() == 3
            page.locator(".task-workspace-list-row").nth(2).focus()
            page.keyboard.press("Alt+ArrowUp")
            assert page.locator(".task-workspace-list-row.selected").count() == 1
            assert "Added browser child" in page.locator(".task-workspace-list-row.selected").inner_text()
            assert page.locator(".task-workspace-list-row").nth(1).get_attribute("aria-selected") == "true"
            page.locator(".task-workspace-list-row").nth(2).locator(".task-workspace-row-more").click()
            page.locator("#taskWorkspaceContextMenu").get_by_role("button", name="Remove", exact=True).click()
            assert page.locator(".task-workspace-list-row").count() == 2
            page.click("#taskWorkspaceSave")
            page.wait_for_function(
                "document.querySelector('#taskWorkspaceSave')?.getAttribute('aria-busy') !== 'true'"
            )
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            durable_items = state.tasks.list(state.repo_root)["tasks"][0]["items"]
            assert durable_items[0]["prompt"] == "Durably edited browser item one"
            assert [item["title"] for item in durable_items] == ["Draft item 1", "Added browser child"]
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Info"

            page.click("#taskWorkspaceHeaderYaml")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK YAML'")
            yaml_text = page.locator("#taskWorkspaceYamlText").input_value()
            dirty_yaml = yaml_text.replace("title: Browser generated draft", "title: YAML renamed list", 1)
            page.fill("#taskWorkspaceYamlText", dirty_yaml)

            for close_kind in ("header", "footer", "x", "backdrop", "escape"):
                if close_kind == "header":
                    page.click("#taskWorkspaceHeaderBack")
                elif close_kind == "footer":
                    page.click("#taskWorkspaceFooterBack")
                elif close_kind == "x":
                    page.click("#taskWorkspaceClose")
                elif close_kind == "backdrop":
                    page.locator("#taskWorkspaceOverlay").click(position={"x": 8, "y": 8})
                else:
                    page.locator("#taskWorkspaceYamlText").focus()
                    page.keyboard.press("Escape")
                page.locator(".ui-dialog-card").wait_for(state="visible")
                page.locator("[data-dialog-cancel]").click()
                assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK YAML"
                assert page.locator("#taskWorkspaceYamlText").input_value() == dirty_yaml

            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert state.tasks.list(state.repo_root)["tasks"][0]["title"] == "YAML renamed list"
            assert [item["item_id"] for item in state.tasks.list(state.repo_root)["tasks"][0]["items"]] == [
                item["item_id"] for item in durable_items
            ]

            page.click("#taskWorkspaceFooterBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            assert page.locator(".task-workspace-tabs .task-workspace-tab").count() == 4
            page.get_by_role("button", name="Runtime", exact=True).click()
            assert page.locator(".task-workspace-empty-panel").get_by_text("No Runner runtime yet").is_visible()
            page.locator("#taskWorkspaceClose").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            # Tasks nav now projects canonical durable Tasks into Board/List views.
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function("document.querySelectorAll('#tasksBoardNew .tasks-board-card').length === 1")
            assert page.locator("#tasksBoardNewCount").inner_text() == "1"
            assert page.locator("#tasksProjectFilterSummary").inner_text() == "Fixture Project"

            # Prototype parity: opening a Task context menu owns the top menu
            # layer and dismisses the + New create menu first.
            board_card = page.locator("#tasksBoardNew .tasks-board-card").first
            page.click("#tasksNewButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            board_card.click(button="right")
            assert page.locator("#taskCreateMenu").is_hidden()
            board_menu = page.locator("#tasksBoardContextMenu")
            assert board_menu.is_visible()
            assert board_menu.locator("[data-tasks-context-action]").count() == 4
            assert board_menu.get_by_role("button").all_inner_texts() == [
                "Open list\n↵", "Rename\nF2", "Info\ni", "Delete\nDel",
            ]
            page.keyboard.press("Escape")
            assert board_menu.is_hidden()

            page.locator("[data-tasks-view-mode='list']").click()
            assert page.locator("#tasksListRows .tasks-list-data").count() == 1
            task_list_row = page.locator("#tasksListRows .tasks-list-data").first
            task_list_row.click(button="right")
            assert board_menu.is_visible()
            assert board_menu.get_by_role("button", name="Rename", exact=True).is_enabled()
            assert board_menu.get_by_role("button", name="Delete", exact=True).is_enabled()
            board_menu.get_by_role("button", name="Info", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            task_list_row.click(button="right")
            board_menu.get_by_role("button", name="Rename", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceTitle").get_attribute("contenteditable") == "true"
            page.keyboard.press("Escape")
            assert page.locator("#taskWorkspaceTitle").get_attribute("contenteditable") == "false"
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            task_list_row.click(button="right")
            board_menu.get_by_role("button", name="Open list", exact=True).click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceHeaderBack").is_hidden()
            assert page.locator("#taskWorkspaceFooterInfo").is_visible()
            assert page.locator("#taskWorkspaceFooterBack").inner_text() == "Back"
            page.click("#taskWorkspaceFooterInfo")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            # Escape belongs to the focused top layer. The Task Workspace stays
            # open while a Project menu, rename dialog or discard dialog closes.
            active_project = page.locator("#projectList .project-row.active")
            active_project.locator(".project-menu-button").click()
            page.wait_for_function("document.querySelector('.project-action-menu:not([hidden])') !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('.project-action-menu:not([hidden])') === null")
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO"

            active_project.locator(".project-menu-button").click()
            page.locator(".project-action-menu:not([hidden])").get_by_role("button", name="Rename project").click()
            page.wait_for_function("document.querySelector('.ui-dialog-input') !== null")
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('.ui-dialog-card') === null")
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO"

            page.click("#taskWorkspaceOpenList")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            # Prototype final ownership: header + Add task is hidden; the
            # stable List footer is the one primary Add task entry.
            assert page.locator("#taskWorkspaceHeaderAddTask").is_hidden()
            assert page.locator("#taskWorkspaceAddTask").is_visible()
            assert page.locator("#taskWorkspaceHeaderMoveExisting").is_visible()
            assert page.locator("#taskWorkspaceHeaderYaml").is_visible()
            assert page.locator("#taskWorkspaceHeaderOpenWorkflow").is_hidden()
            assert page.locator("#taskWorkspaceRenameList").is_visible()
            assert page.locator("#taskWorkspaceDraftTitle").count() == 0
            assert page.locator(".task-workspace-list-side-card").first.locator(
                ".task-workspace-list-kv>span"
            ).all_inner_texts() == ["List", "Status", "Runtime", "Tasks", "Progress", "Current"]
            list_title_before_rename = page.locator("#taskWorkspaceTitle").inner_text()
            page.click("#taskWorkspaceRenameList")
            assert page.locator("#taskWorkspaceTitle").get_attribute("contenteditable") == "true"
            page.locator("#taskWorkspaceTitle").fill("Cancelled inline rename")
            page.keyboard.press("Escape")
            assert page.locator("#taskWorkspaceTitle").inner_text() == list_title_before_rename
            assert page.locator("#taskWorkspaceTitle").get_attribute("contenteditable") == "false"
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            page.locator(".task-workspace-list-row").first.click()
            assert page.locator(".task-workspace-list-row").first.get_attribute("aria-selected") == "true"
            assert "selected" in (page.locator(".task-workspace-list-row").first.get_attribute("class") or "")
            assert page.locator("#taskWorkspaceHeaderOpenWorkflow").is_visible()
            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-more").click()
            page.locator("#taskWorkspaceContextMenu").get_by_role("button", name="Edit", exact=True).click()
            original_child_prompt = page.locator("#taskWorkspacePrompt").input_value()
            page.fill("#taskWorkspacePrompt", "Back should guard dirty child edits")
            page.click("#taskWorkspaceFooterBack")
            page.wait_for_function("document.querySelector('.ui-dialog-card') !== null")
            assert page.locator(".ui-dialog-card").get_by_text("unsaved Task edits", exact=False).is_visible()
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('.ui-dialog-card') === null")
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK EDITOR"
            assert page.locator("#taskWorkspacePrompt").input_value() == "Back should guard dirty child edits"
            page.click("#taskWorkspaceFooterBack")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-more").click()
            page.locator("#taskWorkspaceContextMenu").get_by_role("button", name="Edit", exact=True).click()
            assert page.locator("#taskWorkspacePrompt").input_value() == original_child_prompt

            page.fill("#taskWorkspacePrompt", "Escape top-layer dirty prompt")
            page.locator("#taskWorkspacePrompt").focus()
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('.ui-dialog-card') !== null")
            assert page.locator(".ui-dialog-card").get_by_text("unsaved Task edits", exact=False).is_visible()
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('.ui-dialog-card') === null")
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK EDITOR"
            assert page.locator("#taskWorkspacePrompt").input_value() == "Escape top-layer dirty prompt"
            page.click("#taskWorkspaceClose")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            page.locator("#tasksListRows .tasks-list-data").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceFooterInfo")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")

            page.click("#taskWorkspaceDeleteTask")
            assert page.locator(".ui-dialog-body").get_by_text("Task ID:", exact=False).is_visible()
            page.locator("[data-dialog-cancel]").click()
            assert len(state.tasks.list(state.repo_root)["tasks"]) == 1
            page.click("#taskWorkspaceDeleteTask")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            page.wait_for_function("document.querySelectorAll('#tasksListRows .tasks-list-row').length === 0")
            assert state.tasks.list(state.repo_root)["tasks"] == []
            page.locator("#projectList .project-root").first.click()
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")

            page.fill("#projectChatInput", "@task-single browser one")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 1")
            assert page.locator(".project-chat-task-draft-item").count() == 1
            page.get_by_role("button", name="Edit Draft").click()
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            assert page.locator(".task-workspace-list-row").count() == 0
            page.fill("#taskWorkspacePrompt", "Edited single draft")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            assert page.locator(".project-chat-task-draft-item").get_by_text("Edited single draft").is_visible()

            # A Chat TaskDraft is transient workspace state, not a durable Task.
            # Clean Back / X / Open Prompts must unmount the workspace without
            # losing the Chat-owned draft model or leaking it into the Task store.
            for leave_kind in ("back", "x", "prompts"):
                page.get_by_role("button", name="Edit Draft").click()
                page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
                assert page.locator("#taskWorkspacePrompt").input_value() == "Edited single draft"
                if leave_kind == "back":
                    page.click("#taskWorkspaceFooterBack")
                elif leave_kind == "x":
                    page.click("#taskWorkspaceClose")
                else:
                    page.click("#taskWorkspaceOpenPrompts")
                page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
                if leave_kind == "prompts":
                    page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
                    page.locator("#projectList .project-root").first.click()
                    page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
                assert page.locator(".project-chat-task-draft-item").get_by_text("Edited single draft").is_visible()
                assert state.tasks.list(state.repo_root)["tasks"] == []

            page.get_by_role("button", name="Dismiss", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")
            assert state.tasks.list(state.repo_root)["tasks"] == []

            page.fill("#projectChatInput", "@task-list browser transient multi")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 1")
            assert page.locator(".project-chat-task-draft-item").count() == 2
            page.get_by_role("button", name="Edit Draft").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.locator(".task-workspace-list-row").first.locator(".task-workspace-row-edit").click()
            page.fill("#taskWorkspacePrompt", "Edited multi draft")
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            assert page.locator(".project-chat-task-draft-item").get_by_text("Edited multi draft").is_visible()
            assert state.tasks.list(state.repo_root)["tasks"] == []

            for leave_kind in ("back", "x", "prompts"):
                page.get_by_role("button", name="Edit Draft").click()
                page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
                first_row = page.locator(".task-workspace-list-row").first
                first_row.locator(".task-workspace-row-edit").click()
                page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
                assert page.locator("#taskWorkspacePrompt").input_value() == "Edited multi draft"
                if leave_kind == "back":
                    page.click("#taskWorkspaceHeaderBack")
                    page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
                    page.click("#taskWorkspaceFooterBack")
                elif leave_kind == "x":
                    page.click("#taskWorkspaceClose")
                else:
                    page.click("#taskWorkspaceOpenPrompts")
                page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
                if leave_kind == "prompts":
                    page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
                    page.locator("#projectList .project-root").first.click()
                    page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")
                assert page.locator(".project-chat-task-draft-item").get_by_text("Edited multi draft").is_visible()
                assert state.tasks.list(state.repo_root)["tasks"] == []

            page.get_by_role("button", name="Dismiss", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")

            page.fill("#projectChatInput", "@task browser auto")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 1")
            page.get_by_role("button", name="Dismiss", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")

            page.fill("#projectChatInput", "@task mock:error")
            page.click("#projectChatSendButton")
            page.wait_for_function("Array.from(document.querySelectorAll('.app-toast.error')).some((n) => n.textContent.includes('Browser TaskDraft backend failure'))")
            page.fill("#projectChatInput", "@task mock:invalid")
            page.click("#projectChatSendButton")
            page.wait_for_function("Array.from(document.querySelectorAll('.app-toast.error')).some((n) => n.textContent.includes('invalid structured data'))")

            page.fill("#projectChatInput", "/re")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            assert page.locator("#projectChatSuggestList .project-chat-suggest-item").count() == 1
            page.keyboard.press("Tab")
            assert page.locator("#projectChatInput").input_value() == "/review "
            assert page.locator("#projectChatSuggest").is_hidden()

            page.fill("#projectChatInput", "/")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            page.keyboard.press("ArrowDown")
            page.keyboard.press("Escape")
            assert page.locator("#projectChatSuggest").is_hidden()

            page.fill("#projectChatInput", "hello from normal chat")
            page.click("#projectChatSendButton")
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#projectChatMessages .message')).some((n) => n.textContent.includes('Browser Chat reply'))"
            )
            assert page.locator("#projectChatView").is_visible()
            assert page.locator("#chatView").is_hidden()

            page.fill("#projectChatInput", "@ask-demo")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelector('.project-chat-ask') !== null")
            assert page.locator(".project-chat-ask-head").get_by_text("1 / 3").is_visible()

            # Ask and Queue are Chat-session scoped while Agent/Model/Mode remain Project scoped.
            for queued_text in ("queued while ask 1", "queued while ask 2", "queued while ask 3"):
                page.fill("#projectChatInput", queued_text)
                page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 3")
            assert [
                node.inner_text()
                for node in page.locator("#projectChatQueueList .project-chat-queue-copy").all()
            ] == ["queued while ask 1", "queued while ask 2", "queued while ask 3"]
            assert page.locator("#projectChatQueueCount").inner_text() == "3"

            queue_rows = page.locator("#projectChatQueueList .project-chat-queue-item")
            queue_rows.nth(1).get_by_role("button", name="Edit", exact=True).click()
            page.fill("#projectChatQueueList .project-chat-queue-item.editing textarea", "queued while ask 2 edited")
            page.get_by_role("button", name="Save", exact=True).click()
            page.wait_for_function(
                "document.querySelectorAll('#projectChatQueueList .project-chat-queue-copy')[1]?.textContent === 'queued while ask 2 edited'"
            )
            assert [
                node.inner_text()
                for node in page.locator("#projectChatQueueList .project-chat-queue-copy").all()
            ] == ["queued while ask 1", "queued while ask 2 edited", "queued while ask 3"]
            assert page.locator("#projectChatQueueCount").inner_text() == "3"

            queue_rows = page.locator("#projectChatQueueList .project-chat-queue-item")
            queue_rows.first.get_by_role("button", name="Edit", exact=True).click()
            page.fill("#projectChatQueueList .project-chat-queue-item.editing textarea", "temporary edit")
            page.locator("#projectChatQueueList .project-chat-queue-item.editing").get_by_role("button", name="Cancel", exact=True).click()
            assert [
                node.inner_text()
                for node in page.locator("#projectChatQueueList .project-chat-queue-copy").all()
            ] == ["queued while ask 1", "queued while ask 2 edited", "queued while ask 3"]
            assert page.locator("#projectChatQueueCount").inner_text() == "3"

            page.click("#newProjectChatButton")
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 2")
            assert page.locator(".project-chat-ask").count() == 0
            assert page.locator("#projectChatQueue").is_hidden()
            assert page.locator("#projectChatAgentSelect").input_value() == "opencode"
            assert page.locator("#projectChatModeQuick").input_value() == "read"

            page.select_option("#projectChatSessionSelect", index=0)
            page.wait_for_function("document.querySelector('.project-chat-ask') !== null")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 3")
            assert page.locator("#projectChatAgentSelect").input_value() == "opencode"
            assert page.locator("#projectChatModeQuick").input_value() == "read"

            page.get_by_role("button", name="Other / custom answer").click()
            page.fill(".project-chat-ask-input[aria-label='Custom answer']", "Stale custom answer")
            page.locator(".project-chat-ask-option").filter(has_text="Safe").first.click()
            page.get_by_role("button", name="Other / custom answer").click()
            assert page.locator(".project-chat-ask-input[aria-label='Custom answer']").input_value() == ""
            page.fill(".project-chat-ask-input[aria-label='Custom answer']", "Custom browser approach")
            page.get_by_role("button", name="Other / custom answer").click()
            assert page.locator(".project-chat-ask-input[aria-label='Custom answer']").input_value() == "Custom browser approach"
            page.get_by_role("button", name="Next", exact=True).click()
            page.wait_for_function("document.querySelector('.project-chat-ask-head')?.textContent.includes('2 / 3')")
            page.locator(".project-chat-ask-option").filter(has_text="Queue").first.click()
            page.locator(".project-chat-ask-option").filter(has_text="Ask").first.click()
            page.get_by_role("button", name="Other / custom answer").click()
            page.fill(".project-chat-ask-input[aria-label='Custom answer']", "Docs")
            page.get_by_role("button", name="Next", exact=True).click()
            page.wait_for_function("document.querySelector('.project-chat-ask-head')?.textContent.includes('3 / 3')")
            assert page.get_by_role("button", name="Submit", exact=True).is_disabled()
            page.fill(".project-chat-ask-input[aria-label='Ask text answer']", "Browser reason")
            assert page.get_by_role("button", name="Submit", exact=True).is_enabled()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.wait_for_function("document.querySelector('.project-chat-ask') === null")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 0")
            page.wait_for_function("document.querySelector('#projectChatMessages')?.textContent.includes('Browser queued reply · queued while ask 3')")
            queued_replies = page.locator("#projectChatMessages .message.assistant > .message-body").all_inner_texts()
            queued_replies = [text for text in queued_replies if "Browser queued reply" in text]
            assert queued_replies[-3:] == [
                "Browser queued reply · queued while ask 1",
                "Browser queued reply · queued while ask 2 edited",
                "Browser queued reply · queued while ask 3",
            ]
            answered_ask = state.chat_service.ask(state.repo_root, state.chat_service.sessions(state.repo_root)["active_session_id"])["ask"]
            assert answered_ask["status"] == "answered"
            assert answered_ask["answers"]["approach"]["other"] == "Custom browser approach"
            assert answered_ask["answers"]["features"] == {
                "values": ["queue", "ask"],
                "other": "Docs",
            }
            assert answered_ask["answers"]["reason"] == "Browser reason"

            # Cancel is explicit and also releases next-turn Queue processing.
            page.fill("#projectChatInput", "@ask-demo")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelector('.project-chat-ask') !== null")
            page.fill("#projectChatInput", "queued before cancel")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 1")
            page.locator(".project-chat-ask-actions").get_by_role("button", name="Cancel", exact=True).click()
            page.wait_for_function("document.querySelector('.project-chat-ask') === null")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 0")
            page.wait_for_function("document.querySelector('#projectChatMessages')?.textContent.includes('Browser queued reply · queued before cancel')")

            page.fill("#projectChatInput", "queue browser message")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 1")
            assert page.locator("#projectChatQueue").is_visible()
            assert page.locator("#projectChatTurnStatus").is_visible()
            assert page.locator("#projectChatStopButton").is_visible()
            assert page.locator("#projectChatQueueList").get_by_text("queue browser message").is_visible()
            page.locator("#projectChatStopButton").click()
            page.wait_for_function("document.querySelector('#projectChatTurnStatus')?.hidden === true")
            assert page.locator("#projectChatQueueList").get_by_text("queue browser message").is_visible()
            page.locator("#projectChatQueueList .project-chat-queue-item button").filter(has_text="Edit").click()
            page.wait_for_function("document.querySelector('#projectChatQueueList .project-chat-queue-item.editing textarea') !== null")
            page.fill("#projectChatQueueList .project-chat-queue-item.editing textarea", "")
            page.get_by_role("button", name="Save", exact=True).click()
            assert page.locator("#projectChatQueueList .project-chat-queue-error").is_visible()
            page.fill("#projectChatQueueList .project-chat-queue-item.editing textarea", "queue browser edited")
            page.get_by_role("button", name="Save", exact=True).click()
            page.wait_for_function("document.querySelector('#projectChatQueueList')?.textContent.includes('queue browser edited')")
            page.locator("#projectChatQueueList .project-chat-queue-item button").filter(has_text="Delete").click()
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 0")
            assert page.locator("#projectChatQueue").is_hidden()

            page.click("#newProjectChatButton")
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 3")
            page.click("#renameProjectChatButton")
            page.locator(".ui-dialog-input").fill("Implementation Chat")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#projectChatSessionSelect option')).some((n) => n.textContent === 'Implementation Chat')"
            )
            page.click("#deleteProjectChatButton")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelectorAll('#projectChatSessionSelect option').length === 2")

            page.click("#promptNav")
            page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
            page.wait_for_function("document.querySelector('.studio-designer-body')?.classList.contains('prompt-manager-mode')")
            page.click("#newWorkflowButton")
            page.fill("#newPromptName", "e2e_prompt")
            page.select_option("#newPromptDestination", "global")
            page.click("#newPromptConfirm")
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_prompt.md"
            assert page.locator(".studio-workflow-main").is_visible()

            # Runtime-created Prompt parameter chips are real editor operations,
            # not decorative metadata. Clicking one must insert its token at the
            # current textarea selection and mark the Prompt dirty.
            page.wait_for_function(
                "document.querySelectorAll('#studioPromptParamList .designer-param-chip').length > 0"
            )
            param_chip = page.locator("#studioPromptParamList .designer-param-chip").first
            token = param_chip.inner_text()
            page.fill("#studioPromptTextarea", "")
            param_chip.click()
            assert page.locator("#studioPromptTextarea").input_value() == token
            page.wait_for_function("!document.querySelector('#saveStudioButton')?.disabled")

            # Prompt crash/reload recovery stays local-only and hash-gated.
            prompt_path = next(Path(td).rglob("e2e_prompt.md"))
            canonical_before_draft = prompt_path.read_text(encoding="utf-8")
            local_draft = "# Unsaved Prompt Draft\n\n{{ goal }}\n\nLOCAL_DRAFT_ONLY\n"
            page.fill("#studioPromptTextarea", local_draft)
            page.wait_for_function("!document.querySelector('#saveStudioButton')?.disabled")
            assert prompt_path.read_text(encoding="utf-8") == canonical_before_draft
            page.wait_for_function(
                "() => Array.from({length: localStorage.length}, (_, i) => localStorage.key(i)).some(key => key?.startsWith('ai-task-runner:prompt-draft:v1:'))"
            )
            page.reload(wait_until="domcontentloaded")
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)
            page.click("#promptNav")
            page.wait_for_function("document.querySelector('#workflowView') && !document.querySelector('#workflowView').hidden && document.querySelector('#promptNav')?.classList.contains('active')")
            page.get_by_text("e2e_prompt.md").click()
            page.get_by_text("Restore unsaved Prompt draft?").wait_for(state="visible")
            page.get_by_role("button", name="Restore Draft").click()
            page.wait_for_function(
                "() => document.querySelector('#studioPromptTextarea')?.value.includes('LOCAL_DRAFT_ONLY')"
            )
            assert prompt_path.read_text(encoding="utf-8") == canonical_before_draft

            page.fill("#studioPromptTextarea", "# Prompt\n\n{{ goal }}\n\nReturn concise evidence.\n")
            page.wait_for_function("!document.querySelector('#saveStudioButton')?.disabled")
            page.click("#saveStudioButton")
            page.wait_for_function("document.querySelector('#saveStudioButton')?.disabled")
            page.click("#validateStudioButton")
            page.wait_for_timeout(120)

            page.click("#workflowNav")
            workflow_row = page.locator("#studioFileList .studio-file-item").filter(
                has_text="e2e_crud.workflow.yaml"
            )
            workflow_row.click()
            page.wait_for_url(re.compile(r".*/workflow-studio-app/index\.html\?id="))
            assert "Workflow Editor" in page.locator("body").inner_text()
            assert page_errors == []
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_project_chat_goal_uses_one_backend_create_run_action() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        state.project_preferences.update(root, {"workflow": "workflow.yaml"})
        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)
            page.locator("#projectList .project-root").first.click()
            page.wait_for_function("!document.querySelector('#projectChatView')?.hidden")

            page.fill("#projectChatInput", "@go")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            goal_suggestion = page.locator("#projectChatSuggestList .project-chat-suggest-item").filter(has_text="@goal")
            assert goal_suggestion.count() == 1
            assert "unavailable" not in goal_suggestion.inner_text().lower()
            page.keyboard.press("Escape")

            page.fill("#projectChatInput", "@goal browser quick run")
            page.evaluate(
                """() => {
                    const button = document.querySelector('#projectChatSendButton');
                    button.click();
                    button.click();
                }"""
            )
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK INFO'")
            tasks = state.tasks.list(root)["tasks"]
            assert len(tasks) == 1
            assert tasks[0]["status"] == "ongoing"
            assert tasks[0]["run"]["phase"] == "running"
            assert tasks[0]["items"][0]["prompt"] == "browser quick run"
            assert page.locator("#projectChatInput").input_value() == ""
            assert page.locator(".project-chat-task-draft").count() == 0
            assert page.locator(".task-workspace-status-pill").inner_text() == "ONGOING"
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_first_paint_restores_cached_theme_before_app_mount() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    html = (static_root / "index.html").read_text(encoding="utf-8")
    html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
    html = re.sub(
        r'<script(?![^>]+src="/js/ui-bootstrap\.js")[^>]*>.*?</script>',
        "",
        html,
        flags=re.S,
    )
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright)
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            color_scheme="dark",
        )
        context.add_init_script(
            """if (location.origin === 'http://local.test') {
                localStorage.setItem(
                    'ai-task-runner.ui.bootstrap.v1',
                    JSON.stringify({theme:'violet', appearance:'dark', motion:'reduced'})
                );
            }"""
        )
        page = context.new_page()
        page.route(
            "http://local.test/js/ui-bootstrap.js",
            lambda route: route.fulfill(
                status=200,
                content_type="text/javascript",
                body=(static_root / "js" / "ui-bootstrap.js").read_text(encoding="utf-8"),
            ),
        )
        _load_main_ui_document(page, html)
        assert page.locator("html").get_attribute("data-theme") == "violet"
        assert page.locator("html").get_attribute("data-appearance-preference") == "dark"
        assert page.locator("html").get_attribute("data-appearance") == "dark"
        assert page.locator("html").get_attribute("data-motion") == "reduced"
        browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_global_settings_and_project_chat_composer_browser_contract() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        second = root / "second-project"
        second.mkdir()
        state._write_projects([
            {"name": "Fixture Project", "path": str(root)},
            {"name": "Second Project", "path": str(second)},
        ])
        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        def install(page, expected_project: str = "Fixture Project") -> None:
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page, expected_project)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.emulate_media(color_scheme="dark")
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            install(page)

            assert page.locator("html").get_attribute("data-appearance-preference") == "system"
            assert page.locator("html").get_attribute("data-appearance") == "dark"

            brand_geometry = page.evaluate(
                """() => {
                    const brand = document.querySelector('.projects .brand');
                    const mark = brand.querySelectorAll('.brandmark');
                    const pseudo = getComputedStyle(brand, '::before');
                    return {
                        markCount: mark.length,
                        markWidth: mark[0]?.getBoundingClientRect().width || 0,
                        pseudoDisplay: pseudo.display,
                        pseudoContent: pseudo.content,
                    };
                }"""
            )
            assert brand_geometry["markCount"] == 1
            assert abs(brand_geometry["markWidth"] - 30) <= 1
            assert brand_geometry["pseudoDisplay"] == "none"
            assert brand_geometry["pseudoContent"] in {"none", '""'}

            chat_geometry = page.evaluate(
                """() => {
                    const session = document.querySelector('#projectChatSessionSelect');
                    const compose = document.querySelector('#projectChatComposePanel');
                    const composer = compose.querySelector('.composer-box');
                    const input = document.querySelector('#projectChatInput');
                    const modeControl = document.querySelector('.project-chat-mode-quick');
                    const modeSelect = document.querySelector('#projectChatModeQuick');
                    return {
                        sessionHeight: session.getBoundingClientRect().height,
                        sessionRadius: getComputedStyle(session).borderRadius,
                        sessionFont: getComputedStyle(session).fontSize,
                        composeBackgroundColor: getComputedStyle(compose).backgroundColor,
                        composeBackgroundImage: getComputedStyle(compose).backgroundImage,
                        composerBackground: getComputedStyle(composer).backgroundColor,
                        inputHeight: input.getBoundingClientRect().height,
                        modeControlHeight: modeControl.getBoundingClientRect().height,
                        modeSelectHeight: modeSelect.getBoundingClientRect().height,
                    };
                }"""
            )
            assert abs(chat_geometry["sessionHeight"] - 34) <= 1
            assert chat_geometry["sessionRadius"] == "8px"
            assert chat_geometry["sessionFont"] == "10px"
            assert chat_geometry["composeBackgroundColor"] == "rgba(0, 0, 0, 0)"
            assert "linear-gradient" in chat_geometry["composeBackgroundImage"]
            assert chat_geometry["composerBackground"] != "rgba(0, 0, 0, 0)"
            assert abs(chat_geometry["inputHeight"] - 44) <= 1
            assert abs(chat_geometry["modeControlHeight"] - 30) <= 1
            assert abs(chat_geometry["modeSelectHeight"] - 26) <= 1

            # Build the dynamic Chat surfaces before cycling themes so every
            # palette exercises the real composer / TaskDraft / Ask / Queue.
            page.fill("#projectChatInput", "@task-single theme surface")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelector('.project-chat-task-draft') !== null")
            page.fill("#projectChatInput", "@ask-demo")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelector('.project-chat-ask') !== null")
            page.fill("#projectChatInput", "theme queue item")
            page.click("#projectChatSendButton")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 1")

            def chat_surface_backgrounds():
                return page.evaluate(
                    """() => {
                        const selectors = {
                            composer: '#projectChatComposePanel .composer-box',
                            ask: '.project-chat-ask',
                            queue: '#projectChatQueue',
                            settings: '#projectChatSettingsPopover',
                            draft: '.project-chat-task-draft'
                        };
                        const result = {};
                        for (const [key, selector] of Object.entries(selectors)) {
                            const node = document.querySelector(selector);
                            if (!node) throw new Error('Missing theme surface: ' + selector);
                            const style = getComputedStyle(node);
                            result[key] = {
                                background: style.backgroundColor,
                                color: style.color,
                                border: style.borderColor
                            };
                        }
                        return result;
                    }"""
                )

            page.click("#themeButton")
            assert page.locator("#themePanel").is_visible()
            assert page.locator(".global-settings-card").is_visible()
            assert page.locator("[data-settings-tab]").count() == 4
            assert page.locator("[data-settings-tab='execution']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-settings-panel='execution']").is_visible()
            assert page.locator("[data-settings-panel='defaults']").is_hidden()
            tab_colors = page.evaluate(
                """() => ({
                    active: getComputedStyle(document.querySelector("[data-settings-tab='execution']")).backgroundColor,
                    inactive: getComputedStyle(document.querySelector("[data-settings-tab='defaults']")).backgroundColor
                })"""
            )
            assert tab_colors["active"] != tab_colors["inactive"]
            settings_geometry = page.locator(".global-settings-card").evaluate(
                """node => {
                    const rect = node.getBoundingClientRect();
                    return {left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom};
                }"""
            )
            assert settings_geometry["left"] > 0
            assert settings_geometry["top"] > 0
            assert settings_geometry["right"] < 1366
            assert settings_geometry["bottom"] < 820
            settings_visual_geometry = page.evaluate(
                """() => {
                    const card = document.querySelector('.global-settings-card');
                    const nav = document.querySelector('.settings-sections');
                    const tab = document.querySelector('[data-settings-tab="execution"]');
                    const panel = document.querySelector('[data-settings-panel="execution"]');
                    const select = document.querySelector('#globalAutoWorkspacePolicy');
                    return {
                        cardWidth: parseFloat(getComputedStyle(card).width),
                        cardHeight: parseFloat(getComputedStyle(card).height),
                        navWidth: parseFloat(getComputedStyle(nav).width),
                        tabHeight: parseFloat(getComputedStyle(tab).height),
                        panelPadding: getComputedStyle(panel).paddingTop,
                        selectHeight: parseFloat(getComputedStyle(select).height),
                    };
                }"""
            )
            assert abs(settings_visual_geometry["cardWidth"] - 760) <= 2
            assert abs(settings_visual_geometry["cardHeight"] - 700) <= 2
            assert abs(settings_visual_geometry["navWidth"] - 170) <= 2
            assert abs(settings_visual_geometry["tabHeight"] - 38) <= 1
            assert settings_visual_geometry["panelPadding"] == "18px"
            assert abs(settings_visual_geometry["selectHeight"] - 34) <= 1
            page.click("[data-settings-tab='defaults']")
            assert page.locator("[data-settings-panel='defaults']").is_visible()
            page.click("[data-settings-tab='interface']")
            assert page.locator("[data-settings-panel='interface']").is_visible()
            page.click("[data-settings-tab='language']")
            assert page.locator("[data-settings-panel='language']").is_visible()
            page.click("[data-settings-tab='execution']")

            # Execution settings share the same backend-owned Global Settings store.
            # Exercise every Auto policy now; actual Main/worktree resolution stays
            # in the final Workspace phase.
            assert page.locator("#globalMergeFailureLimit").get_attribute("min") == "0"
            assert page.locator("#globalMergeFailureLimit").get_attribute("max") == "99"
            for policy in ("busy-worktree", "always-main", "always-worktree"):
                page.select_option("#globalAutoWorkspacePolicy", policy)
                page.wait_for_function(
                    "(value) => document.querySelector('#globalAutoWorkspacePolicy')?.value === value",
                    arg=policy,
                )
                page.wait_for_timeout(30)
                assert state.global_settings.get()["execution"]["auto_workspace_policy"] == policy

            page.fill("#globalMergeFailureLimit", "99")
            page.locator("#globalMergeFailureLimit").press("Tab")
            page.wait_for_timeout(30)
            assert state.global_settings.get()["execution"]["merge_failure_limit"] == 99

            page.locator("#globalAllowConcurrentMain").check()
            page.wait_for_timeout(30)
            assert state.global_settings.get()["execution"]["allow_concurrent_main_tasks"] is True

            page.click("[data-settings-tab='interface']")
            for appearance in ("light", "dark"):
                page.locator(f"[data-appearance-option='{appearance}']").click()
                page.wait_for_function(
                    "(value) => document.documentElement.dataset.appearance === value",
                    arg=appearance,
                )
                for palette in ("teal", "blue", "violet", "amber", "rose"):
                    page.locator(f"[data-theme-option='{palette}']").click()
                    page.wait_for_function(
                        "(value) => document.documentElement.dataset.theme === value",
                        arg=palette,
                    )
                    tokens = page.evaluate(
                        """() => {
                            const style = getComputedStyle(document.documentElement);
                            return [
                                style.getPropertyValue('--text').trim(),
                                style.getPropertyValue('--panel').trim(),
                                style.getPropertyValue('--accent').trim()
                            ];
                        }"""
                    )
                    assert all(tokens)
                    assert len(set(tokens)) == 3

                    # Settings is a real popover surface, so inspect it while
                    # open instead of relying only on root CSS variables.
                    page.click("#themeCloseButton")
                    page.click("#projectChatSettingsButton")
                    page.wait_for_function("document.querySelector('#projectChatSettingsPopover')?.hidden === false")
                    surfaces = chat_surface_backgrounds()
                    for values in surfaces.values():
                        assert values["background"] not in {"rgba(0, 0, 0, 0)", "transparent", ""}
                        assert values["color"]
                        assert values["border"]
                        if appearance == "dark":
                            assert values["background"] not in {"rgb(255, 255, 255)", "rgba(255, 255, 255, 1)"}
                    page.click("#projectChatSettingsClose")
                    page.click("#themeButton")
                    assert page.locator("#themePanel").is_visible()

            # Static Composer copy and dynamic Queue / Ask / command suggestions
            # / Chat TaskDraft must all rerender from the same language owner.
            page.click("[data-settings-tab='language']")
            page.locator("[data-language-option='zh-TW']").click()
            page.wait_for_function("document.documentElement.lang === 'zh-Hant'")
            assert page.locator("#themeButton .global-settings-copy strong").inner_text() == "設定"
            assert page.locator("#themeButton .global-settings-copy small").inner_text() == "全域 Runner 偏好設定"
            page.click("#themeCloseButton")
            assert page.locator("#projectChatInput").get_attribute("placeholder") == "輸入訊息給此專案…"
            assert page.locator(".project-chat-mode-quick > span").inner_text() == "模式"
            page.click("#projectChatSettingsButton")
            assert page.locator("#projectChatSettingsPopover .project-chat-settings-body > label strong").all_inner_texts() == ["Workflow", "Agent", "Model", "推理程度"]
            assert page.locator("#projectChatAskCapability").count() == 0
            page.click("#projectChatSettingsClose")
            assert page.locator("#projectChatNewTaskButton").inner_text() == "新增任務"
            assert page.locator("#projectChatSendButton").inner_text() == "加入佇列"
            assert page.locator(".project-chat-task-draft-actions").get_by_role("button", name="編輯草稿").is_visible()
            assert page.locator(".project-chat-ask-option").filter(has_text="其他／自行輸入").first.is_visible()
            assert page.locator("#projectChatQueueList .project-chat-queue-item").first.get_by_role("button", name="編輯").is_visible()
            page.fill("#projectChatInput", "/")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            assert page.locator("#projectChatSuggestTitle").inner_text() == "Agent 技能 / 指令"
            page.keyboard.press("Escape")

            page.click("#themeButton")
            page.locator("[data-language-option='en']").click()
            page.wait_for_function("document.documentElement.lang === 'en'")
            assert page.locator("#themeButton .global-settings-copy strong").inner_text() == "Settings"
            assert page.locator("#themeButton .global-settings-copy small").inner_text() == "Global runner preferences"
            page.click("#themeCloseButton")
            assert page.locator("#projectChatInput").get_attribute("placeholder") == "Message this Project…"
            assert page.locator(".project-chat-mode-quick > span").inner_text() == "MODE"
            page.click("#projectChatSettingsButton")
            assert page.locator("#projectChatSettingsPopover .project-chat-settings-body > label strong").all_inner_texts() == ["Workflow", "Agent", "Model", "Reasoning"]
            assert page.locator("#projectChatAskCapability").count() == 0
            page.click("#projectChatSettingsClose")
            assert page.locator("#projectChatNewTaskButton").inner_text() == "New Task"
            assert page.locator("#projectChatSendButton").inner_text() == "Queue"
            assert page.locator(".project-chat-task-draft-actions").get_by_role("button", name="Edit Draft").is_visible()
            assert page.locator(".project-chat-ask-option").filter(has_text="Other / custom answer").first.is_visible()
            assert page.locator("#projectChatQueueList .project-chat-queue-item").first.get_by_role("button", name="Edit").is_visible()

            # Task List Draft rerenders in place on the same language event.
            page.click("#projectChatNewTaskButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            page.locator("#taskCreateMenu [data-task-create-kind='list']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceAddTask").inner_text() == "No tasks yet\n+ Add first task"
            assert page.locator("#taskWorkspaceHeaderCreateList").inner_text() == "Create Task List"
            assert page.locator("#taskWorkspaceHeaderCreateList").is_disabled()
            page.evaluate("window.I18n.setLanguage('zh-TW')")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === '任務清單'")
            assert page.locator("#taskWorkspaceAddTask").inner_text() == "尚無任務\n+ 新增第一個任務"
            assert page.locator("#taskWorkspaceHeaderCreateList").inner_text() == "建立任務清單"
            page.evaluate("window.I18n.setLanguage('en')")
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceAddTask").inner_text() == "No tasks yet\n+ Add first task"
            page.click("#taskWorkspaceClose")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.click("#themeButton")
            page.click("[data-settings-tab='interface']")
            page.locator("[data-appearance-option='dark']").click()
            page.locator("[data-theme-option='violet']").click()
            page.click("[data-settings-tab='language']")
            page.locator("[data-language-option='en']").click()
            page.wait_for_function("document.documentElement.dataset.appearancePreference === 'dark'")
            page.wait_for_function("document.documentElement.dataset.theme === 'violet'")
            page.wait_for_function("document.documentElement.lang === 'en'")
            saved = state.global_settings.get()
            assert saved["interface"]["appearance"] == "dark"
            assert saved["interface"]["theme"] == "violet"
            assert saved["language"] == "en"
            bootstrap = page.evaluate(
                "() => JSON.parse(localStorage.getItem('ai-task-runner.ui.bootstrap.v1'))"
            )
            assert bootstrap == {"theme": "violet", "appearance": "dark", "motion": "full"}
            page.click("#themeCloseButton")
            assert page.locator("#themePanel").is_hidden()

            page.locator("#projectList .project-root").filter(has_text="Second Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Second Project'")
            assert page.locator("html").get_attribute("data-theme") == "violet"
            assert page.locator("html").get_attribute("data-appearance-preference") == "dark"

            input_box = page.locator("#projectChatInput")
            input_box.fill("short")
            compact_height = input_box.evaluate("(node) => node.getBoundingClientRect().height")
            assert 43 <= compact_height <= 45
            input_box.fill("\n".join(f"line {index}" for index in range(40)))
            long_metrics = input_box.evaluate(
                """node => ({
                    height: node.getBoundingClientRect().height,
                    scrollHeight: node.scrollHeight,
                    overflowY: getComputedStyle(node).overflowY
                })"""
            )
            assert long_metrics["height"] <= 181
            assert long_metrics["scrollHeight"] > long_metrics["height"]
            assert long_metrics["overflowY"] == "auto"

            input_box.fill("composer overlap check")
            page.click("#projectChatSendButton")
            page.wait_for_function(
                "document.querySelector('#projectChatMessages')?.textContent.includes('Browser Chat reply')"
            )
            messages_box = page.locator("#projectChatMessages").bounding_box()
            compose_box = page.locator("#projectChatComposePanel").bounding_box()
            last_message = page.locator("#projectChatMessages .project-chat-message").last.bounding_box()
            assert messages_box and compose_box and last_message
            assert messages_box["y"] + messages_box["height"] <= compose_box["y"] + 1
            assert last_message["y"] + last_message["height"] <= messages_box["y"] + messages_box["height"] + 1
            message_visual = page.locator("#projectChatMessages .project-chat-message.user").first.evaluate(
                """node => ({
                    maxWidth: getComputedStyle(node).maxWidth,
                    radius: getComputedStyle(node).borderRadius,
                    fontSize: getComputedStyle(node).fontSize,
                    metaCount: node.querySelectorAll('.project-chat-message-meta').length
                })"""
            )
            assert message_visual["maxWidth"] == "82%"
            assert message_visual["radius"] == "14px"
            assert message_visual["fontSize"] == "13px"
            assert message_visual["metaCount"] == 1

            # Qwen-style queued-next-turn UX reuses the canonical Chat Queue.
            input_box.fill("queue browser message")
            page.click("#projectChatSendButton")
            page.wait_for_function(
                "document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 1"
            )
            assert page.locator("#projectChatSendButton").inner_text() == "Queue"
            assert "Ctrl+Q" in (page.locator("#projectChatSendButton").get_attribute("title") or "")

            input_box.fill("queued by ctrl q")
            input_box.press("Control+q")
            page.wait_for_function(
                "document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 2"
            )

            first_queue = page.locator("#projectChatQueueList .project-chat-queue-item").first
            first_queue.get_by_role("button", name="Edit").click()
            queue_editor = first_queue.locator("textarea")
            queue_editor.fill("changed but cancelled")
            first_queue.get_by_role("button", name="Cancel").click()
            assert "queue browser message" in first_queue.inner_text()

            first_queue.get_by_role("button", name="Edit").click()
            queue_editor = first_queue.locator("textarea")
            queue_editor.fill("   ")
            first_queue.get_by_role("button", name="Save").click()
            assert "Queued message cannot be empty." in first_queue.inner_text()

            long_queue_message = "long queued message " + ("x" * 4096)
            queue_editor = first_queue.locator("textarea")
            queue_editor.fill(long_queue_message)
            first_queue.get_by_role("button", name="Save").click()
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatQueueList .project-chat-queue-item .project-chat-queue-copy')?.textContent === value",
                arg=long_queue_message,
            )

            old_session_id = state.chat_service.sessions(second)["active_session_id"]
            assert len(getattr(state, "_browser_chat_queue", {})[old_session_id]) == 2
            page.click("#newProjectChatButton")
            page.wait_for_function("document.querySelector('#projectChatQueue')?.hidden === true")
            assert len(getattr(state, "_browser_chat_queue", {})[old_session_id]) == 2

            page.reload(wait_until="domcontentloaded")
            install(page, "Second Project")
            assert page.locator("html").get_attribute("data-theme") == "violet"
            assert page.locator("html").get_attribute("data-appearance-preference") == "dark"
            assert page.locator("html").get_attribute("data-appearance") == "dark"
            assert page.locator("html").get_attribute("lang") == "en"
            execution = state.global_settings.get()["execution"]
            assert execution == {
                "auto_workspace_policy": "always-worktree",
                "merge_failure_limit": 99,
                "allow_concurrent_main_tasks": True,
            }
            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_global_defaults_copy_once_new_chat_reload_and_project_rename_identity() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        workflow_path = root / "runner" / "assets" / "workflows" / "ralphy_ai_validate.yaml"
        workflow_path.parent.mkdir(parents=True, exist_ok=True)
        workflow_path.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        workflow = str(workflow_path)
        project_only_workflow = root / ".ai-task-runner" / "assets" / "workflows" / "project-only.yaml"
        project_only_workflow.parent.mkdir(parents=True, exist_ok=True)
        project_only_workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        old_project_preferences = {
            "agent": "qwen",
            "model": "qwen/model-a",
            "mode": "auto",
            "reasoning": "medium",
            "workflow": workflow,
        }
        state.project_preferences.update(root, old_project_preferences)
        added_project = root / "new-default-project"
        added_project.mkdir()

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        def install(page, expected_project: str = "Fixture Project") -> None:
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page, expected_project)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            install(page)

            page.click("#themeButton")
            page.click("[data-settings-tab='defaults']")
            page.wait_for_function(
                "(value) => Array.from(document.querySelectorAll('#globalDefaultWorkflow option')).some((node) => node.value === value)",
                arg=workflow,
            )
            workflow_options = page.locator("#globalDefaultWorkflow option").evaluate_all(
                "(nodes) => nodes.map((node) => node.value)"
            )
            assert workflow in workflow_options
            assert str(project_only_workflow) not in workflow_options
            page.select_option("#globalDefaultAgent", "opencode")
            page.wait_for_function(
                "() => document.querySelector('#globalDefaultModel')?.querySelector('option[value=\"openai/gpt-5.2\"]') !== null"
            )
            page.select_option("#globalDefaultModel", "openai/gpt-5.2")
            page.wait_for_function(
                "() => document.querySelector('#globalDefaultReasoning')?.querySelector('option[value=\"deep\"]') !== null"
            )
            page.select_option("#globalDefaultMode", "read")
            page.select_option("#globalDefaultReasoning", "deep")
            page.select_option("#globalDefaultWorkflow", workflow)
            page.wait_for_function(
                """() => document.querySelector('#globalDefaultAgent')?.value === 'opencode'
                    && document.querySelector('#globalDefaultModel')?.value === 'openai/gpt-5.2'
                    && document.querySelector('#globalDefaultMode')?.value === 'read'
                    && document.querySelector('#globalDefaultReasoning')?.value === 'deep'"""
            )
            defaults = state.global_settings.get()["defaults"]
            assert defaults == {
                "agent": "opencode",
                "model": "openai/gpt-5.2",
                "mode": "read",
                "reasoning": "deep",
                "workflow": workflow,
            }
            # Existing Project remains independently owned.
            current_old = state.project_preferences.get(root)
            for key, value in old_project_preferences.items():
                assert current_old[key] == value

            page.click("#themeCloseButton")
            page.click("#openProject")
            page.fill("#projectPathInput", str(added_project))
            page.click("#projectModalConfirm")
            page.wait_for_function(
                "(name) => document.querySelector('#projectChatName')?.textContent === name",
                arg=added_project.name,
            )
            new_preferences = state.project_preferences.get(added_project)
            for key, value in defaults.items():
                assert new_preferences[key] == value
            assert state.project_preferences.get(root)["agent"] == "qwen"

            # New Chat has no independent defaults; it projects the Project settings.
            first_session = state.chat_service.sessions(added_project)["active_session_id"]
            page.click("#newProjectChatButton")
            page.wait_for_function(
                "document.querySelectorAll('#projectChatSessionSelect option').length === 2"
            )
            second_session = state.chat_service.sessions(added_project)["active_session_id"]
            assert second_session != first_session

            def assert_chat_preferences(expected: dict[str, str]) -> None:
                assert page.locator("#projectChatAgentSelect").input_value() == expected["agent"]
                assert page.locator("#projectChatModelSelect").input_value() == expected["model"]
                assert page.locator("#projectChatModeQuick").input_value() == expected["mode"]
                assert page.locator("#projectChatReasoningSelect").input_value() == expected["reasoning"]
                assert page.locator("#projectChatWorkflowSelect").input_value() == expected["workflow"]

            assert_chat_preferences(defaults)

            # Switching Chat sessions within one Project must not fork Project-level
            # Agent/Model/Mode/Reasoning/Workflow preferences.
            page.select_option("#projectChatSessionSelect", first_session)
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatSessionSelect')?.value === value",
                arg=first_session,
            )
            assert state.chat_service.sessions(added_project)["active_session_id"] == first_session
            assert_chat_preferences(defaults)

            # Switching Projects restores each Project's independently persisted
            # five-value Chat preference set.
            page.locator("#projectList .project-root").filter(has_text="Fixture Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Fixture Project'")
            assert_chat_preferences(old_project_preferences)

            # Workflow is a visible Project Chat preference inside Run settings.
            page.click("#projectChatSettingsButton")
            page.locator("#projectChatSettingsPopover").wait_for(state="visible")
            page.wait_for_function(
                "(value) => Array.from(document.querySelectorAll('#projectChatWorkflowSelect option')).some((node) => node.value === value)",
                arg=str(project_only_workflow),
            )
            page.select_option("#projectChatWorkflowSelect", str(project_only_workflow))
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatWorkflowSelect')?.value === value",
                arg=str(project_only_workflow),
            )
            assert state.project_preferences.get(root)["workflow"] == str(project_only_workflow)
            page.select_option("#projectChatWorkflowSelect", workflow)
            page.wait_for_function(
                "(value) => document.querySelector('#projectChatWorkflowSelect')?.value === value",
                arg=workflow,
            )
            assert state.project_preferences.get(root)["workflow"] == workflow
            page.click("#projectChatSettingsClose")
            page.locator("#projectChatSettingsPopover").wait_for(state="hidden")

            page.locator("#projectList .project-root").filter(has_text=added_project.name).click()
            page.wait_for_function(
                "(name) => document.querySelector('#projectChatName')?.textContent === name",
                arg=added_project.name,
            )
            assert_chat_preferences(defaults)

            # Display-name rename must not retarget Project path or Chat identity.
            row = page.locator("#projectList .project-tree").filter(has_text=added_project.name)
            row.locator(".project-menu-button").click()
            project_menu = page.locator(".project-action-menu:not([hidden])")
            project_menu.locator("button").first.click()
            page.locator(".ui-dialog-input").fill("Renamed Default Project")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "() => Array.from(document.querySelectorAll('#projectList .project-root strong')).some((n) => n.textContent === 'Renamed Default Project')"
            )
            project_rows = state.projects()
            renamed = next(item for item in project_rows if item["name"] == "Renamed Default Project")
            assert Path(renamed["path"]).resolve() == added_project.resolve()
            assert state.chat_service.sessions(added_project)["active_session_id"] == first_session

            page.reload(wait_until="domcontentloaded")
            install(page, "Renamed Default Project")
            page.wait_for_function(
                "() => document.querySelector('#projectChatName')?.textContent === 'Renamed Default Project'"
            )
            assert_chat_preferences(defaults)
            assert state.project_preferences.get(root)["agent"] == "qwen"
            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
@pytest.mark.parametrize("viewport", [
    {"width": 1024, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
])
def test_workflow_settings_common_desktop_viewports_do_not_overflow(viewport) -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        state.studio_workflow_create("layout_check", "global", None)
        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport=viewport)
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)
            page.click("#workflowNav")
            page.wait_for_function("document.querySelector('#workflowNav')?.classList.contains('active')")
            page.wait_for_function("document.querySelector('.studio-designer-body')?.classList.contains('workflow-manager-mode')")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            assert page.locator("#settingsNav").count() == 0
            body = page.locator(".studio-designer-body").bounding_box()
            sidebar = page.locator(".studio-workflow-sidebar").bounding_box()
            assert body and sidebar
            assert body["x"] >= 0 and body["x"] + body["width"] <= viewport["width"] + 1
            assert sidebar["x"] >= 0 and sidebar["x"] + sidebar["width"] <= viewport["width"] + 1

            workflow_row = page.locator("#studioFileList .studio-file-item").filter(has_text="layout_check.workflow.yaml")
            workflow_row.dispatch_event(
                "contextmenu",
                {"clientX": viewport["width"] - 2, "clientY": viewport["height"] - 2, "button": 2},
            )
            menu = page.locator("#workflowContextMenu").bounding_box()
            assert menu
            assert menu["x"] >= 0 and menu["y"] >= 0
            assert menu["x"] + menu["width"] <= viewport["width"] + 1
            assert menu["y"] + menu["height"] <= viewport["height"] + 1
            page.keyboard.press("Escape")

            page.click("#promptNav")
            page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
            page.wait_for_function("document.querySelector('.studio-designer-body')?.classList.contains('prompt-manager-mode')")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            prompt_body = page.locator(".studio-designer-body").bounding_box()
            assert prompt_body and prompt_body["x"] + prompt_body["width"] <= viewport["width"] + 1
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_chat_defaults_to_ralphy_ai_validate_when_no_saved_choice() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        root = Path(td) / "runner" / "assets" / "workflows"
        base = "stages:\n  execute:\n    type: command\n    command: [python, -c, \"print('ok')\"]\nflow: [execute]\n"
        (root / "aaa.yaml").write_text(base, encoding="utf-8")
        (root / "ralphy_ai_validate.yaml").write_text(base, encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)
            page.wait_for_function("document.querySelector('#workflowSelectedLabel')?.textContent === 'ralphy_ai_validate.yaml'")
            assert page.locator("#workflowSelectedLabel").inner_text() == "ralphy_ai_validate.yaml"
            assert page.locator("#workflowSelect").input_value().replace("\\", "/").endswith("/ralphy_ai_validate.yaml")
            browser.close()

@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_board_opens_each_task_with_its_own_project_catalog() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        second = root / "second-project"
        second.mkdir()
        state._write_projects([
            {"name": "Fixture Project", "path": str(root)},
            {"name": "Second Project", "path": str(second)},
        ])
        project_workflows = second / ".ai-task-runner" / "assets" / "workflows"
        project_workflows.mkdir(parents=True)
        second_workflow = project_workflows / "second-only.yaml"
        second_workflow.write_text(
            "stages:\n"
            "  validate_file:\n    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "flow: [validate_file]\n",
            encoding="utf-8",
        )
        state.tasks._workflow_requirements = state._task_workflow_requirements
        second_row = next(row for row in state.projects() if row["name"] == "Second Project")
        state.tasks.create(
            second,
            {
                "title": "Second catalog task",
                "items": [{
                    "title": "Second child",
                    "prompt": "Use the second Project catalog only",
                    "workflow": str(second_workflow),
                    "project": str(second),
                    "workspace": "auto",
                    "validator": str(second / "validate.py"),
                }],
            },
            request_id="second-catalog-task",
            project_id=second_row["project_id"],
        )

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page, "Fixture Project")

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksProjectFilterButton")
            page.click("#tasksProjectFilterAll")
            page.wait_for_function("document.querySelector('#tasksProjectFilterSummary')?.textContent.startsWith('All Projects · ')")
            page.keyboard.press("Escape")
            page.wait_for_function("document.querySelector('#tasksProjectFilterMenu')?.hidden === true")
            task_card = page.locator("#tasksBoardNew .tasks-board-card").filter(has_text="Second catalog task")
            assert task_card.count() == 1
            task_card.click()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert page.locator("#taskWorkspaceHeaderBack").is_hidden()
            page.locator(".task-workspace-list-row").first.dblclick()
            page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert page.locator("#taskWorkspaceProject").input_value() == str(second.resolve())
            assert page.locator("#taskWorkspaceWorkflow").input_value() == str(second_workflow.resolve())
            assert page.locator("#taskWorkspaceWorkflow option").filter(has_text="second-only.yaml").count() == 1
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-editor-tab='ai']").count() == 0
            assert page.locator("[data-task-editor-tab='validator']").count() == 1
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("#taskWorkspaceValidator").is_visible()
            assert page.locator("#taskWorkspaceValidator").input_value() == str(second / "validate.py")
            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
@pytest.mark.parametrize(
    ("viewport", "color_scheme"),
    [
        ({"width": 1366, "height": 900}, "light"),
        ({"width": 820, "height": 900}, "light"),
        ({"width": 820, "height": 900}, "dark"),
        ({"width": 620, "height": 900}, "light"),
        ({"width": 620, "height": 900}, "dark"),
        ({"width": 520, "height": 900}, "light"),
    ],
)
def test_task_editor_source_modes_keep_shared_drawer_geometry(viewport, color_scheme) -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        workflows = root / "runner" / "assets" / "workflows"
        mixed = workflows / "mixed.yaml"
        mixed.write_text(
            "stages:\n"
            "  planning:\n    type: plan\n"
            "  validate_file:\n    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
            "flow: [planning, validate_file, validate_ai]\n",
            encoding="utf-8",
        )
        file_only = workflows / "file-only.yaml"
        file_only.write_text(
            "stages:\n"
            "  planning:\n    type: plan\n"
            "  validate_file:\n    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "flow: [planning, validate_file]\n",
            encoding="utf-8",
        )
        ai_only = workflows / "ai-only.yaml"
        ai_only.write_text(
            "stages:\n"
            "  planning:\n    type: plan\n"
            "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
            "flow: [planning, validate_ai]\n",
            encoding="utf-8",
        )
        plain = workflows / "plain.yaml"
        plain.write_text(
            "stages:\n"
            "  planning:\n    type: plan\n"
            "flow: [planning]\n",
            encoding="utf-8",
        )
        prompt_asset = root / "runner" / "assets" / "prompts" / "common" / "task_source_asset.md"
        prompt_asset.write_text("Task source asset\n", encoding="utf-8")
        state.project_preferences.update(root, {"workflow": str(mixed)})
        state.tasks._workflow_requirements = state._task_workflow_requirements

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            context = browser.new_context(viewport=viewport, color_scheme=color_scheme)
            page = context.new_page()
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            assert page.locator("html").get_attribute("data-appearance") == color_scheme
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksNewButton")
            page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
            page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
            page.wait_for_function(
                "document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'"
            )
            page.select_option("#taskWorkspaceWorkflow", str(mixed))
            page.fill("#taskWorkspaceItemTitle", "Tabbed source editor")

            tabs = page.locator("#taskWorkspaceEditorInputTabs [data-task-editor-tab]")
            assert tabs.count() == 3
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-editor-tab='ai']").is_visible()
            assert page.locator("[data-task-editor-tab='validator']").is_visible()
            assert page.locator("[data-task-source-card='prompt']").is_visible()
            assert page.locator("[data-task-source-card='ai']").count() == 0
            assert page.locator("[data-task-source-card='validator']").count() == 0

            # The new hierarchy is deliberately lighter than the former nested
            # card + pill + card layout.
            light_geometry = page.locator("#taskWorkspaceEditorInputTabs").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {
                        display: style.display,
                        gridAutoFlow: style.gridAutoFlow,
                        borderTopWidth: style.borderTopWidth,
                        borderRadius: style.borderRadius,
                        paddingTop: style.paddingTop,
                        gap: style.gap,
                        background: style.backgroundColor,
                    };
                }"""
            )
            assert light_geometry["display"] == "grid"
            assert light_geometry["gridAutoFlow"] == "column"
            assert light_geometry["borderTopWidth"] == "1px"
            assert light_geometry["borderRadius"] == "10px"
            assert light_geometry["paddingTop"] == "3px"
            assert light_geometry["gap"] == "3px"
            active_outer_tab = page.locator("[data-task-editor-tab='prompt']").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {
                        borderRadius: style.borderRadius,
                        borderTopWidth: style.borderTopWidth,
                        background: style.backgroundColor,
                        boxShadow: style.boxShadow,
                        color: style.color,
                        fontWeight: style.fontWeight,
                    };
                }"""
            )
            inactive_outer_tab = page.locator("[data-task-editor-tab='ai']").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {
                        background: style.backgroundColor,
                        color: style.color,
                        fontWeight: style.fontWeight,
                        boxShadow: style.boxShadow,
                    };
                }"""
            )
            assert active_outer_tab["borderRadius"] == "7px"
            assert active_outer_tab["borderTopWidth"] == "1px"
            assert active_outer_tab["background"] != light_geometry["background"]
            assert active_outer_tab["background"] != inactive_outer_tab["background"]
            assert active_outer_tab["color"] != inactive_outer_tab["color"]
            assert int(active_outer_tab["fontWeight"]) > int(inactive_outer_tab["fontWeight"])
            assert active_outer_tab["boxShadow"] != inactive_outer_tab["boxShadow"]

            # Selected-state contract matches the segmented-control reference:
            # exactly one tab is visually raised; clicking AI transfers that
            # selected treatment and clears it from Prompt.
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function(
                "() => document.querySelector('[data-task-editor-tab="ai"]')?.getAttribute('aria-selected') === 'true'"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "false"
            assert "active" not in (page.locator("[data-task-editor-tab='prompt']").get_attribute("class") or "").split()
            assert "active" in (page.locator("[data-task-editor-tab='ai']").get_attribute("class") or "").split()
            ai_selected_style = page.locator("[data-task-editor-tab='ai']").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {background: style.backgroundColor, boxShadow: style.boxShadow};
                }"""
            )
            prompt_unselected_style = page.locator("[data-task-editor-tab='prompt']").evaluate(
                """node => {
                    const style = getComputedStyle(node);
                    return {background: style.backgroundColor, boxShadow: style.boxShadow};
                }"""
            )
            assert ai_selected_style["background"] != prompt_unselected_style["background"]
            assert ai_selected_style["boxShadow"] != prompt_unselected_style["boxShadow"]
            page.locator("[data-task-editor-tab='prompt']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")

            prompt_card_style = page.locator("[data-task-source-card='prompt']").evaluate(
                """node => ({
                    borderTopWidth: getComputedStyle(node).borderTopWidth,
                    borderRadius: getComputedStyle(node).borderRadius,
                    boxShadow: getComputedStyle(node).boxShadow,
                })"""
            )
            assert prompt_card_style == {
                "borderTopWidth": "0px",
                "borderRadius": "0px",
                "boxShadow": "none",
            }
            inner_tabs_style = page.locator("[data-task-source-group='prompt']").evaluate(
                """node => ({
                    borderTopWidth: getComputedStyle(node).borderTopWidth,
                    background: getComputedStyle(node).backgroundColor,
                    display: getComputedStyle(node).display,
                })"""
            )
            assert inner_tabs_style["borderTopWidth"] == "0px"
            assert inner_tabs_style["display"] == "flex"

            page.fill("#taskWorkspacePrompt", "Prompt text retained across outer tabs")
            page.locator("[data-task-source-group='prompt'] [data-task-source-mode='file']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceGoalFile') !== null")
            page.fill("#taskWorkspaceGoalFile", str(root / "goal.md"))
            page.locator("[data-task-source-group='prompt'] [data-task-source-mode='asset']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceGoalAsset') !== null")
            page.select_option("#taskWorkspaceGoalAsset", str(prompt_asset))
            page.locator("[data-task-source-group='prompt'] [data-task-source-mode='write']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")
            assert page.locator("#taskWorkspacePrompt").input_value() == "Prompt text retained across outer tabs"

            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function(
                "() => document.querySelector('[data-task-source-card=\"ai\"]') "
                "&& !document.querySelector('[data-task-source-card=\"prompt\"]')"
            )
            assert page.locator("[data-task-source-card='validator']").count() == 0
            assert page.locator("[data-task-source-group='ai'] button").count() == 4
            page.locator("[data-task-source-group='ai'] [data-task-source-mode='file']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            page.fill("#taskWorkspaceAiValidatorPrompt", str(root / "workflow-ai.md"))

            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("[data-task-source-card='validator']").is_visible()
            assert page.locator("[data-task-source-card='prompt']").count() == 0
            assert page.locator("[data-task-source-card='ai']").count() == 0
            page.fill("#taskWorkspaceValidator", str(root / "validate.py"))

            # Switching outer tabs never destroys another tab's draft values.
            page.locator("[data-task-editor-tab='prompt']").click()
            page.wait_for_function("document.querySelector('#taskWorkspacePrompt') !== null")
            assert page.locator("#taskWorkspacePrompt").input_value() == "Prompt text retained across outer tabs"
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == str(root / "workflow-ai.md")
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("#taskWorkspaceValidator").input_value() == str(root / "validate.py")

            # Workflow capability changes control which outer tabs exist. An
            # invalid active tab falls back to Task Prompt without losing draft data.
            page.select_option("#taskWorkspaceWorkflow", str(ai_only))
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 2"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-editor-tab='ai']").count() == 1
            assert page.locator("[data-task-editor-tab='validator']").count() == 0

            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == str(root / "workflow-ai.md")

            page.select_option("#taskWorkspaceWorkflow", str(file_only))
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 2"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-editor-tab='ai']").count() == 0
            assert page.locator("[data-task-editor-tab='validator']").count() == 1
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("#taskWorkspaceValidator").input_value() == str(root / "validate.py")

            page.select_option("#taskWorkspaceWorkflow", str(plain))
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 1"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            assert page.locator("[data-task-editor-tab='ai']").count() == 0
            assert page.locator("[data-task-editor-tab='validator']").count() == 0

            page.select_option("#taskWorkspaceWorkflow", str(mixed))
            page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 3"
            )
            assert page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"
            page.locator("[data-task-editor-tab='validator']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            assert page.locator("#taskWorkspaceValidator").input_value() == str(root / "validate.py")
            page.locator("[data-task-editor-tab='ai']").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == str(root / "workflow-ai.md")

            panel_box = page.locator("#taskWorkspaceEditorInputPanel").bounding_box()
            shell_box = page.locator("#taskWorkspaceShell").bounding_box()
            assert panel_box and shell_box
            assert panel_box["x"] >= shell_box["x"] - 1
            assert panel_box["x"] + panel_box["width"] <= shell_box["x"] + shell_box["width"] + 1
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

            if viewport["width"] == 820 and color_scheme == "light":
                page.evaluate("window.I18n.setLanguage('zh-TW')")
                page.wait_for_function(
                    "() => document.querySelector('[data-task-editor-tab=\"ai\"]')?.textContent === 'AI 驗證'"
                )
                assert page.locator("[data-task-editor-tab='validator']").inner_text() == "程式驗證"
                assert page.locator("[data-task-source-card='ai']").get_by_text("AI 驗證", exact=True).is_visible()
                page.evaluate("window.I18n.setLanguage('en')")
                page.wait_for_function(
                    "() => document.querySelector('[data-task-editor-tab=\"validator\"]')?.textContent === 'Program Validation'"
                )

            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_validation_options_follow_builtin_workflow_capabilities() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        state.workflow_catalog = lambda: {
            "stage_types": {
                "base": {"profiles": {}, "options": []},
                "plan": {"options": []},
                "command": {"options": []},
                "ai_validator": {"options": []},
            },
            "node_options": {},
        }

        workflows = state.repo_root / "runner" / "assets" / "workflows"
        fixtures = {
            "ralphy_ai_validate.yaml": (
                "stages:\n"
                "  ralphy:\n    type: base\n    profile: execute\n"
                "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
                "flow: [ralphy, validate_ai]\n"
            ),
            "ai.yaml": (
                "stages:\n"
                "  planning:\n    type: plan\n"
                "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
                "flow: [planning, validate_ai]\n"
            ),
            "file.yaml": (
                "stages:\n"
                "  planning:\n    type: plan\n"
                "  validate_file:\n    type: command\n"
                "    command: \"{python} {validator} --project-root {project_root}\"\n"
                "flow: [planning, validate_file]\n"
            ),
            "mixed.yaml": (
                "stages:\n"
                "  planning:\n    type: plan\n"
                "  validate_file:\n    type: command\n"
                "    command: \"{python} {validator} --project-root {project_root}\"\n"
                "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
                "flow: [planning, validate_file, validate_ai]\n"
            ),
            "plain.yaml": (
                "stages:\n"
                "  planning:\n    type: plan\n"
                "flow: [planning]\n"
            ),
        }
        for name, content in fixtures.items():
            (workflows / name).write_text(content, encoding="utf-8")

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.wait_for_function("document.querySelector('#chatNav')?.classList.contains('active')")
            page.locator("#optionsButton").click()
            assert page.locator("#activeRunDetails").count() == 0

            # Default Chat workflow is ralphy_ai_validate: AI validator prompt must be visible.
            page.wait_for_function("document.querySelector('#workflowSelectedLabel')?.textContent === 'ralphy_ai_validate.yaml'")
            assert page.locator("#validationPickers").is_visible()
            assert not page.locator("#validatorPicker").is_visible()
            assert page.locator("#aiValidatorPromptPicker").is_visible()

            def choose_workflow(name: str) -> None:
                if page.locator("#optionsPanel").is_visible():
                    page.locator("#optionsCloseButton").click()
                    page.wait_for_function("document.querySelector('#optionsPanel')?.hidden === true")
                page.locator("#workflowDropdownButton").click()
                page.locator("#workflowDropdownMenu .workflow-dropdown-option").filter(has_text=name).click()
                page.wait_for_function(
                    "(name) => document.querySelector('#workflowSelectedLabel')?.textContent === name",
                    arg=name,
                )
                page.locator("#optionsButton").click()
                page.wait_for_function("document.querySelector('#optionsPanel')?.hidden === false")
                page.wait_for_timeout(50)

            choose_workflow("file.yaml")
            assert page.locator("#validationPickers").is_visible()
            assert page.locator("#validatorPicker").is_visible()
            assert not page.locator("#aiValidatorPromptPicker").is_visible()

            choose_workflow("ai.yaml")
            assert page.locator("#validationPickers").is_visible()
            assert not page.locator("#validatorPicker").is_visible()
            assert page.locator("#aiValidatorPromptPicker").is_visible()

            # Mixed validation is the densest Chat options case. Verify it at
            # a smaller desktop viewport so both resource cards remain usable
            # without horizontal or viewport overflow.
            page.set_viewport_size({"width": 720, "height": 720})
            choose_workflow("mixed.yaml")
            assert page.locator("#validationPickers").is_visible()
            assert page.locator("#validatorPicker").is_visible()
            assert page.locator("#aiValidatorPromptPicker").is_visible()
            panel = page.locator("#optionsPanel")
            panel_box = panel.bounding_box()
            file_box = page.locator("#validatorPicker").bounding_box()
            ai_box = page.locator("#aiValidatorPromptPicker").bounding_box()
            assert panel_box and file_box and ai_box
            panel_scroll = panel.evaluate(
                "(node) => ({left: node.scrollLeft, width: node.clientWidth, scrollWidth: node.scrollWidth})"
            )
            assert panel_scroll["left"] == 0
            assert panel_scroll["scrollWidth"] <= panel_scroll["width"] + 1
            assert file_box["height"] >= 72
            assert ai_box["height"] >= 72
            assert file_box["y"] + file_box["height"] + 6 <= ai_box["y"]
            assert file_box["x"] >= panel_box["x"] - 1
            assert ai_box["x"] >= panel_box["x"] - 1
            assert file_box["x"] + file_box["width"] <= panel_box["x"] + panel_box["width"] + 1
            assert ai_box["x"] + ai_box["width"] <= panel_box["x"] + panel_box["width"] + 1
            assert panel_box["x"] >= -1
            assert panel_box["x"] + panel_box["width"] <= 721
            assert panel_box["y"] >= -1
            assert panel_box["y"] + min(panel_box["height"], 720) <= 721

            for picker_id in ("validatorPicker", "aiValidatorPromptPicker"):
                kind_box = page.locator(f"#{picker_id} .resource-kind").bounding_box()
                name_box = page.locator(f"#{picker_id} .resource-name").bounding_box()
                choose_box = page.locator(f"#{picker_id} .resource-action").bounding_box()
                assert kind_box and name_box and choose_box
                assert kind_box["y"] + kind_box["height"] <= name_box["y"] + 1
                assert name_box["x"] + name_box["width"] <= choose_box["x"] + 1
                assert choose_box["height"] >= 32

            choose_workflow("plain.yaml")
            assert not page.locator("#validationPickers").is_visible()
            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_workspace_options_follow_backend_resolver_and_merge_failure_count_is_task_local() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        workflow = str(root / "runner" / "assets" / "workflows" / "workflow.yaml")

        active = state.tasks.create(
            root,
            {
                "title": "Active Main Task",
                "items": [{
                    "title": "Active",
                    "prompt": "Keep Main busy",
                    "workflow": workflow,
                    "project": str(root),
                    "workspace": "main",
                }],
            },
            request_id="browser-active-main-create",
            project_id=state.project_identity(root)["project_id"],
        )
        state.tasks.begin_run(
            root,
            active["task_id"],
            request_id="browser-active-main-run",
            workspace={
                "task_id": active["task_id"],
                "run_number": 1,
                "project_root": str(root),
                "effective_mode": "main",
            },
        )

        completed = state.tasks.create(
            root,
            {
                "title": "Failure count task",
                "items": [{
                    "title": "Completed",
                    "prompt": "Keep Task merge failures separate",
                    "workflow": workflow,
                    "project": str(root),
                    "workspace": "worktree",
                }],
            },
            request_id="browser-failure-count-create",
            project_id=state.project_identity(root)["project_id"],
        )
        completed_workspace = {
            "task_id": completed["task_id"],
            "run_number": 1,
            "project_root": str(root),
            "effective_mode": "worktree",
            "task_branch": f"local/task/{completed['task_id']}-r1",
            "worktree_path": str(root / ".browser-worktrees" / completed["task_id"]),
            "target_branch": "main",
        }
        state.tasks.begin_run(
            root,
            completed["task_id"],
            request_id="browser-failure-count-run",
            workspace=completed_workspace,
        )
        state.tasks.transition_run(
            root,
            completed["task_id"],
            1,
            phase="conflict",
            status="ongoing",
            increment_merge_failure=True,
        )
        state.tasks.transition_run(
            root,
            completed["task_id"],
            1,
            phase="source_fail",
            status="ongoing",
            increment_merge_failure=True,
        )
        state.tasks.transition_run(
            root,
            completed["task_id"],
            1,
            phase="worktree_ready",
            status="closed",
            completed_item_count=1,
            workspace_result={
                "snapshot": {
                    "task_snapshot_sha": "browser-snapshot",
                    "no_changes": False,
                    "created_commit": True,
                },
                "effective_mode": "worktree",
                "branch": completed_workspace["task_branch"],
                "path": completed_workspace["worktree_path"],
                "merge": {"status": "worktree_ready"},
            },
        )

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        def install(page) -> None:
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(page, html)
            install(page)

            page.click("#themeButton")
            page.fill("#globalMergeFailureLimit", "7")
            page.locator("#globalMergeFailureLimit").press("Tab")
            page.wait_for_timeout(50)
            assert state.global_settings.get()["execution"]["merge_failure_limit"] == 7
            page.click("#themeCloseButton")
            page.click("#chatNav")

            cases = [
                ("busy-worktree", False, True, "worktree", False),
                ("always-main", False, False, "", False),
                ("always-worktree", False, True, "worktree", False),
                ("busy-worktree", True, True, "worktree", True),
                ("always-main", True, True, "main", True),
                ("always-worktree", True, True, "worktree", True),
            ]
            for policy, allow_concurrent, auto_enabled, auto_effective, main_enabled in cases:
                page.click("#themeButton")
                page.select_option("#globalAutoWorkspacePolicy", policy)
                concurrent = page.locator("#globalAllowConcurrentMain")
                if allow_concurrent:
                    concurrent.check()
                else:
                    concurrent.uncheck()
                page.wait_for_timeout(50)
                execution = state.global_settings.get()["execution"]
                assert execution["auto_workspace_policy"] == policy
                assert execution["allow_concurrent_main_tasks"] is allow_concurrent
                page.click("#themeCloseButton")

                page.click("#tasksNewButton")
                page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")
                page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
                page.wait_for_function(
                    "() => document.querySelector('#taskWorkspaceWorkspaceAvailability')"
                    " && !document.querySelector('#taskWorkspaceWorkspaceAvailability').textContent.includes('Checking')"
                )
                auto_option = page.locator("#taskWorkspaceWorkspace option[value='auto']")
                main_option = page.locator("#taskWorkspaceWorkspace option[value='main']")
                worktree_option = page.locator("#taskWorkspaceWorkspace option[value='worktree']")
                assert auto_option.evaluate("(node) => node.disabled") is (not auto_enabled)
                assert auto_option.get_attribute("data-effective-mode") == auto_effective
                assert main_option.evaluate("(node) => node.disabled") is (not main_enabled)
                assert main_option.get_attribute("data-effective-mode") == ("main" if main_enabled else "")
                assert worktree_option.evaluate("(node) => node.disabled") is False
                assert worktree_option.get_attribute("data-effective-mode") == "worktree"
                page.click("#taskWorkspaceFooterBack")
                page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

            page.wait_for_function(
                "() => document.querySelectorAll('#tasksBoardClosed .tasks-board-card').length >= 1"
            )
            page.locator("#tasksBoardClosed .tasks-board-card", has_text="Failure count task").click()
            page.wait_for_function(
                "() => document.querySelector('#taskWorkspaceMergeFailures')?.textContent === '2'"
            )
            assert page.locator("#taskWorkspaceMergeFailures").inner_text() == "2"
            page.click("#taskWorkspaceClose")

            page.click("#themeButton")
            assert page.locator("#globalMergeFailureLimit").input_value() == "7"
            page.fill("#globalMergeFailureLimit", "9")
            page.locator("#globalMergeFailureLimit").press("Tab")
            page.wait_for_timeout(50)
            assert state.global_settings.get()["execution"]["merge_failure_limit"] == 9
            assert state.tasks.get(root, completed["task_id"])["merge_failure_count"] == 2
            page.click("#themeCloseButton")

            page.locator("#tasksBoardClosed .tasks-board-card", has_text="Failure count task").click()
            page.wait_for_function(
                "() => document.querySelector('#taskWorkspaceMergeFailures')?.textContent === '2'"
            )
            assert page.locator("#taskWorkspaceMergeFailures").inner_text() == "2"
            assert not errors
            browser.close()


def _load_feature_prototype(page, feature_root: Path) -> None:
    def serve_feature(route) -> None:
        parsed = urlparse(route.request.url)
        prefix = "/feature/"
        if not parsed.path.startswith(prefix):
            route.abort()
            return
        relative = parsed.path[len(prefix):]
        source = (feature_root / relative).resolve()
        try:
            source.relative_to(feature_root.resolve())
        except ValueError:
            route.abort()
            return
        if not source.is_file():
            route.fulfill(status=404, body="not found")
            return
        content_type = "text/plain"
        if source.suffix == ".html":
            content_type = "text/html"
        elif source.suffix == ".css":
            content_type = "text/css"
        elif source.suffix == ".js":
            content_type = "text/javascript"
        route.fulfill(
            status=200,
            content_type=content_type,
            body=source.read_text(encoding="utf-8"),
        )

    page.route("http://prototype.test/feature/**", serve_feature)
    page.goto(
        "http://prototype.test/feature/ai-task-runner-ui-prototype.html",
        wait_until="domcontentloaded",
    )
    page.wait_for_function("window.TaskUi && document.querySelector('#newTask')")


def _computed_style(page, selector: str, properties: list[str]) -> dict[str, str]:
    return page.locator(selector).evaluate(
        """(node, properties) => {
            const style = getComputedStyle(node);
            return Object.fromEntries(properties.map((property) => [property, style[property]]));
        }""",
        properties,
    )


def _box(page, selector: str) -> dict[str, float]:
    box = page.locator(selector).bounding_box()
    assert box is not None, f"Expected visible geometry for {selector}"
    return box


def _assert_feature_computed_style_parity(
    feature_page,
    feature_selector: str,
    production_page,
    production_selector: str,
    properties: list[str],
) -> None:
    feature = _computed_style(feature_page, feature_selector, properties)
    production = _computed_style(production_page, production_selector, properties)
    assert production == feature, (
        f"Computed style drift for {production_selector} vs {feature_selector}: "
        f"production={production!r}, feature={feature!r}"
    )


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_editor_and_list_computed_geometry_match_feature_prototype() -> None:
    """Compare the rendered production Task surfaces against the real feature prototype.

    Static selector mapping catches obvious CSS drift but cannot model cascade,
    specificity, inherited values, or browser layout. This regression loads both
    implementations in Chromium and compares their final computed geometry.
    """
    static_root = Path(__file__).resolve().parents[1] / "static"
    feature_root = Path(__file__).resolve().parents[2] / "feature"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        mixed = root / "runner" / "assets" / "workflows" / "mixed.yaml"
        mixed.write_text(
            "stages:\n"
            "  planning:\n"
            "    type: plan\n"
            "  validate_file:\n"
            "    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "  validate_ai:\n"
            "    type: ai_validator\n"
            "    validator: ai\n"
            "flow:\n"
            "  - planning\n"
            "  - validate_file\n"
            "  - validate_ai\n",
            encoding="utf-8",
        )
        feature_file_only = root / "runner" / "assets" / "workflows" / "file.yaml"
        feature_file_only.write_text(
            "stages:\n"
            "  planning:\n"
            "    type: plan\n"
            "  validate_file:\n"
            "    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "flow:\n"
            "  - planning\n"
            "  - validate_file\n",
            encoding="utf-8",
        )
        state.tasks._workflow_requirements = state._task_workflow_requirements
        state.task_drafts._workflow_requirements = state._task_workflow_requirements
        # Keep + New deterministic: this parity test adds validator-heavy
        # Workflows only to compare controls. Task List creation must still
        # inherit the Project's canonical saved Workflow rather than whichever
        # catalog row happens to sort first.
        default_workflow = root / "runner" / "assets" / "workflows" / "workflow.yaml"
        state.project_preferences.update(root, {"workflow": str(default_workflow)})

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            context = browser.new_context(
                viewport={"width": 1440, "height": 900},
                color_scheme="light",
            )
            feature_page = context.new_page()
            production_page = context.new_page()
            feature_page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            production_page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)

            _load_feature_prototype(feature_page, feature_root)

            production_page.expose_function("__apiBridge", _bridge_for(state))
            _load_main_ui_document(production_page, html)
            production_page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {ok: response.status >= 200 && response.status < 300, status: response.status, json: async () => response.data};
                };"""
            )
            _install_main_ui_styles(production_page, static_root)
            _install_main_ui_scripts(production_page, static_root)
            _boot_main_ui(production_page)

            # Open the actual prototype and production Task editors through
            # their user-facing + New entry points.
            feature_page.click("#newTask")
            feature_page.wait_for_function("!document.querySelector('#createTypeMenu')?.hidden")

            production_page.click("#chatNav")
            production_page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            production_page.click("#tasksNewButton")
            production_page.wait_for_function("!document.querySelector('#taskCreateMenu')?.hidden")

            # Compare the actual create popover before entering the Editor.
            # This catches cascade/layout drift that static selector mapping
            # cannot see (including the pointer affordance on clickable rows).
            create_menu_pairs = [
                (
                    "#createTypeMenu",
                    "#taskCreateMenu",
                    [
                        "position", "zIndex", "width",
                        "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius",
                        "backgroundColor", "boxShadow",
                    ],
                ),
                (
                    "#createTypeMenu [data-create-type='task']",
                    "#taskCreateMenu [data-task-create-kind='task']",
                    [
                        "display", "gridTemplateColumns", "gap", "alignItems", "width",
                        "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderRadius", "cursor",
                    ],
                ),
                (
                    "#createTypeMenu [data-create-type='task'] .create-type-icon",
                    "#taskCreateMenu [data-task-create-kind='task'] .task-create-menu-icon",
                    ["display", "width", "height", "borderRadius", "backgroundColor", "color", "fontSize", "fontWeight"],
                ),
                (
                    "#createTypeMenu [data-create-type='task'] strong",
                    "#taskCreateMenu [data-task-create-kind='task'] strong",
                    ["display", "fontSize"],
                ),
                (
                    "#createTypeMenu [data-create-type='task'] small",
                    "#taskCreateMenu [data-task-create-kind='task'] small",
                    ["display", "marginTop", "fontSize", "lineHeight"],
                ),
            ]
            for feature_selector, production_selector, properties in create_menu_pairs:
                _assert_feature_computed_style_parity(
                    feature_page,
                    feature_selector,
                    production_page,
                    production_selector,
                    properties,
                )
            feature_create_menu = _box(feature_page, "#createTypeMenu")
            production_create_menu = _box(production_page, "#taskCreateMenu")
            assert abs(feature_create_menu["width"] - production_create_menu["width"]) <= 1

            feature_page.locator("#createTypeMenu [data-create-type='task']").click()
            feature_page.wait_for_function(
                "document.querySelector('#newTaskModal')?.classList.contains('open')"
            )
            feature_page.select_option("#newTaskWorkflow", "mixed.yaml")
            feature_page.wait_for_function(
                "document.querySelector('#newTaskValidationSource .task-ai-source') !== null"
            )

            production_page.locator("#taskCreateMenu [data-task-create-kind='task']").click()
            production_page.wait_for_function(
                "document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'"
            )
            production_page.select_option("#taskWorkspaceWorkflow", str(mixed))
            production_page.wait_for_function(
                "() => document.querySelectorAll('#taskWorkspaceEditorInputTabs [data-task-editor-tab]').length === 3"
            )
            assert production_page.locator("[data-task-editor-tab='prompt']").get_attribute("aria-selected") == "true"

            # Interactive state parity was previously missing from the geometry gate.
            # Compare actual browser-computed selected Workspace and Project-menu
            # states against the accepted prototype.
            _assert_feature_computed_style_parity(
                feature_page,
                "#newTaskModal .task-editor-secondary .workspace-option.selected",
                production_page,
                ".task-workspace-editor-secondary [data-workspace-option='auto'].selected",
                ["borderColor", "backgroundColor", "boxShadow", "opacity", "cursor"],
            )

            if feature_page.locator("#projectDropdown").is_hidden():
                feature_page.locator("#projectDropdownToggle").click()
            feature_page.wait_for_function("!document.querySelector('#projectDropdown')?.hidden")
            if production_page.locator(".task-workspace-project-dropdown").is_hidden():
                production_page.locator(".task-workspace-project-toggle").click()
            production_page.wait_for_function(
                "!document.querySelector('.task-workspace-project-dropdown')?.hidden"
            )
            feature_project_choice = feature_page.locator("#projectDropdown .project-dropdown-option").first
            production_project_choice = production_page.locator(
                ".task-workspace-project-dropdown .task-workspace-project-dropdown-option"
            ).first
            feature_project_choice.hover()
            production_project_choice.hover()
            _assert_feature_computed_style_parity(
                feature_page,
                "#projectDropdown .project-dropdown-option:first-child",
                production_page,
                ".task-workspace-project-dropdown .task-workspace-project-dropdown-option:first-child",
                ["backgroundColor", "borderRadius", "color"],
            )
            # Close through the same outside-click behavior on both surfaces.
            # The prototype's global Escape handlers are order-sensitive inside the
            # full fixture, so Escape is covered separately by production behavior
            # tests instead of being used as parity-test cleanup here.
            feature_page.locator("#newTaskTitle").click()
            production_page.locator(".task-workspace-title-field input").click()
            feature_page.wait_for_function("document.querySelector('#projectDropdown')?.hidden")
            production_page.wait_for_function(
                "document.querySelector('.task-workspace-project-dropdown')?.hidden"
            )
            assert feature_page.locator("#projectDropdown").is_hidden()
            assert production_page.locator(".task-workspace-project-dropdown").is_hidden()

            style_pairs = [
                (
                    "#newTaskModal>.modal-body",
                    "#taskWorkspaceBody",
                    ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
                (
                    "#newTaskModal .task-basics",
                    ".task-workspace-basics",
                    ["display", "gridTemplateColumns", "gap", "alignItems"],
                ),
                # Task input/source geometry intentionally diverges here:
                # production uses capability-aware outer tabs and a lighter
                # single-panel source editor. The dedicated tabbed-editor browser
                # test owns that hierarchy; this parity gate keeps comparing the
                # shared drawer basics, workspace selector, footer and motion.
                (
                    "#newTaskModal .task-editor-secondary",
                    ".task-workspace-editor-secondary",
                    ["marginTop", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
                (
                    "#newTaskModal .task-editor-secondary .workspace-options",
                    ".task-workspace-editor-secondary .task-workspace-workspace-options",
                    ["display", "gridTemplateColumns", "gap"],
                ),
                (
                    "#newTaskModal .task-editor-secondary .workspace-option:first-child",
                    ".task-workspace-editor-secondary [data-workspace-option='auto']",
                    ["minHeight", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
                (
                    "#newTaskModal .task-editor-secondary .workspace-option:first-child small",
                    ".task-workspace-editor-secondary [data-workspace-option='auto'] small",
                    ["marginTop", "fontSize", "lineHeight"],
                ),
                (
                    "#newTaskModal .task-editor-secondary .workspace-option:first-child .workspace-status",
                    ".task-workspace-editor-secondary [data-workspace-option='auto'] .task-workspace-workspace-status",
                    ["marginTop", "fontSize"],
                ),
                (
                    "#newTaskModal>.modal-foot",
                    ".task-workspace-shell.task-editor-route .task-workspace-foot",
                    ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
            ]
            for feature_selector, production_selector, properties in style_pairs:
                _assert_feature_computed_style_parity(
                    feature_page,
                    feature_selector,
                    production_page,
                    production_selector,
                    properties,
                )

            feature_basics = _box(feature_page, "#newTaskModal .task-basics")
            production_basics = _box(production_page, ".task-workspace-basics")
            feature_project_field = _box(feature_page, "#newTaskModal .task-project-field")
            production_project_field = _box(production_page, ".task-workspace-project-field")
            feature_field_offset = feature_project_field["y"] - feature_basics["y"]
            production_field_offset = production_project_field["y"] - production_basics["y"]
            assert abs(feature_field_offset - production_field_offset) <= 1, (
                "Task basics top spacing drift: "
                f"production={production_field_offset}, feature={feature_field_offset}"
            )

            feature_label = _box(feature_page, "#newTaskModal .task-project-field>label")
            feature_control = _box(feature_page, "#newTaskModal .task-project-field .project-combobox")
            production_label = _box(production_page, ".task-workspace-project-field>span:first-child")
            production_control = _box(production_page, ".task-workspace-project-combobox")
            feature_label_gap = feature_control["y"] - (feature_label["y"] + feature_label["height"])
            production_label_gap = production_control["y"] - (
                production_label["y"] + production_label["height"]
            )
            assert abs(feature_label_gap - production_label_gap) <= 1, (
                "Task label/control spacing drift: "
                f"production={production_label_gap}, feature={feature_label_gap}"
            )

            # File-mode AI validator input is especially sensitive to the
            # generic input cascade. Compare the actual browser-computed style
            # against the prototype instead of relying on selector mapping.
            feature_page.locator("[data-task-ai-mode][data-source-value='file']").click()
            feature_page.wait_for_function("document.querySelector('#taskAiFile') !== null")
            production_page.locator("[data-task-editor-tab='ai']").click()
            production_page.wait_for_function("""document.querySelector('[data-task-source-card="ai"]') !== null""")
            production_page.locator("[data-task-source-group='ai'] [data-task-source-mode='file']").click()
            production_page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            _assert_feature_computed_style_parity(
                feature_page,
                "#taskAiFile",
                production_page,
                "#taskWorkspaceAiValidatorPrompt",
                [
                    "height", "minWidth", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                    "borderTopWidth", "borderTopStyle", "borderRadius",
                    "backgroundColor", "color", "fontSize",
                ],
            )
            _assert_feature_computed_style_parity(
                feature_page,
                "#newTaskModal .task-ai-source .pathrow",
                production_page,
                "[data-task-source-card='ai'] .task-workspace-path-row",
                ["display", "gap", "alignItems"],
            )
            _assert_feature_computed_style_parity(
                feature_page,
                "#taskPickAi",
                production_page,
                "[data-task-source-card='ai'] .task-workspace-upload",
                [
                    "height", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                    "borderTopWidth", "borderTopStyle", "borderTopColor", "borderRadius",
                    "backgroundColor", "color", "fontSize", "fontWeight",
                ],
            )

            # Behavior parity: source-mode, Workflow and Workspace changes must
            # produce the same retained/reset state as the final feature
            # prototype and must never redirect focus into the Title field.
            feature_page.fill("#taskValidatorFile", "feature-validator.py")
            feature_page.fill("#taskAiFile", "feature-ai-override.md")
            production_page.fill("#taskWorkspaceAiValidatorPrompt", "feature-ai-override.md")
            production_page.locator("[data-task-editor-tab='validator']").click()
            production_page.wait_for_function("document.querySelector('#taskWorkspaceValidator') !== null")
            production_page.fill("#taskWorkspaceValidator", "feature-validator.py")

            feature_page.select_option("#newTaskWorkflow", "file.yaml")
            production_page.select_option("#taskWorkspaceWorkflow", str(feature_file_only))
            feature_page.wait_for_function(
                "() => document.querySelector('#newTaskValidationSource .task-file-source') && !document.querySelector('#newTaskValidationSource .task-ai-source')"
            )
            production_page.wait_for_function(
                "() => document.querySelector('[data-task-source-card=\"validator\"]') && !document.querySelector('[data-task-source-card=\"ai\"]')"
            )
            assert feature_page.locator("#taskValidatorFile").input_value() == "feature-validator.py"
            assert production_page.locator("#taskWorkspaceValidator").input_value() == "feature-validator.py"

            feature_page.select_option("#newTaskWorkflow", "mixed.yaml")
            production_page.select_option("#taskWorkspaceWorkflow", str(mixed))
            feature_page.wait_for_function("document.querySelector('#taskAiFile') !== null")
            production_page.locator("[data-task-editor-tab='ai']").click()
            production_page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert feature_page.locator("#taskAiFile").input_value() == "feature-ai-override.md"
            assert production_page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == "feature-ai-override.md"

            feature_page.locator("[data-task-ai-mode][data-source-value='default']").click()
            production_page.locator("[data-task-source-group='ai'] [data-task-source-mode='default']").click()
            feature_page.wait_for_function("document.querySelector('#newTaskModal .task-ai-source [data-source-mode=\"default\"]') !== null")
            production_page.wait_for_function("document.querySelector('[data-task-source-card=\"ai\"] .task-workspace-compact-default-value') !== null")
            assert feature_page.evaluate("document.activeElement?.id !== 'newTaskTitle'")
            assert production_page.evaluate("document.activeElement?.id !== 'taskWorkspaceItemTitle'")

            feature_page.locator("[data-task-ai-mode][data-source-value='file']").click()
            production_page.locator("[data-task-source-group='ai'] [data-task-source-mode='file']").click()
            feature_page.wait_for_function("document.querySelector('#taskAiFile') !== null")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceAiValidatorPrompt') !== null")
            assert feature_page.locator("#taskAiFile").input_value() == ""
            assert production_page.locator("#taskWorkspaceAiValidatorPrompt").input_value() == ""

            # Prompt source tabs preserve each alternate source independently.
            feature_page.locator("[data-task-goal-mode][data-source-value='inline']").click()
            production_page.locator("[data-task-editor-tab='prompt']").click()
            production_page.wait_for_function("""document.querySelector('[data-task-source-card="prompt"]') !== null""")
            production_page.locator("[data-task-source-group='prompt'] [data-task-source-mode='write']").click()
            feature_page.fill("#taskPromptInline", "Prompt text retained across modes")
            production_page.fill("#taskWorkspacePrompt", "Prompt text retained across modes")
            feature_page.locator("[data-task-goal-mode][data-source-value='file']").click()
            production_page.locator("[data-task-source-group='prompt'] [data-task-source-mode='file']").click()
            feature_page.wait_for_function("document.querySelector('#taskGoalFile') !== null")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceGoalFile') !== null")
            feature_page.fill("#taskGoalFile", "prompts/manual-review.md")
            production_page.fill("#taskWorkspaceGoalFile", "prompts/manual-review.md")
            feature_page.locator("[data-task-goal-mode][data-source-value='inline']").click()
            production_page.locator("[data-task-source-group='prompt'] [data-task-source-mode='write']").click()
            assert feature_page.locator("#taskPromptInline").input_value() == "Prompt text retained across modes"
            assert production_page.locator("#taskWorkspacePrompt").input_value() == "Prompt text retained across modes"
            feature_page.locator("[data-task-goal-mode][data-source-value='file']").click()
            production_page.locator("[data-task-source-group='prompt'] [data-task-source-mode='file']").click()
            assert feature_page.locator("#taskGoalFile").input_value() == "prompts/manual-review.md"
            assert production_page.locator("#taskWorkspaceGoalFile").input_value() == "prompts/manual-review.md"
            assert feature_page.evaluate("document.activeElement?.id !== 'newTaskTitle'")
            assert production_page.evaluate("document.activeElement?.id !== 'taskWorkspaceItemTitle'")

            # Click the visible option cards, matching actual user interaction.
            # The prototype radio is intentionally covered by its label content,
            # so direct input.check() bypasses the surface we are comparing.
            feature_page.locator("#newTaskWorkspace .workspace-option.worktree-option").click()
            production_page.locator("[data-workspace-option='worktree']").click()
            feature_page.wait_for_function("document.querySelector('#newTaskWorkspace input[name=\"workspaceMode\"][value=\"worktree\"]')?.checked === true")
            production_page.wait_for_function("document.querySelector('[data-workspace-option=\"worktree\"] input')?.checked === true")
            assert "selected" in (feature_page.locator("#newTaskWorkspace .workspace-option.worktree-option").get_attribute("class") or "")
            assert "selected" in (production_page.locator("[data-workspace-option='worktree']").get_attribute("class") or "")
            _assert_feature_computed_style_parity(
                feature_page,
                "#newTaskWorkspace .workspace-option.worktree-option.selected",
                production_page,
                "[data-workspace-option='worktree'].selected",
                ["borderTopColor", "backgroundColor", "boxShadow"],
            )
            _assert_feature_computed_style_parity(
                feature_page,
                "#newTaskWorkspace .workspace-preview.worktree-active",
                production_page,
                ".task-workspace-workspace-preview.worktree-active",
                ["borderTopColor", "backgroundColor", "color", "boxShadow"],
            )
            assert feature_page.evaluate("document.activeElement?.id !== 'newTaskTitle'")
            assert production_page.evaluate("document.activeElement?.id !== 'taskWorkspaceItemTitle'")

            feature_shell = feature_page.locator("#taskOverlay .drawer").bounding_box()
            production_shell = production_page.locator("#taskWorkspaceShell").bounding_box()
            assert feature_shell and production_shell
            assert abs(feature_shell["width"] - production_shell["width"]) <= 1

            # Close editor and compare the empty Task List workspace rendered
            # through the same public create menu on both implementations.
            feature_page.click("#taskEditorBack")
            feature_page.wait_for_function(
                "document.querySelector('#taskEditorDiscardModal')?.classList.contains('open')"
            )
            feature_page.click("#confirmDiscardTaskEditor")
            feature_page.wait_for_function(
                "!document.querySelector('#newTaskModal')?.classList.contains('open')"
            )
            feature_page.click("#newTask")
            feature_page.locator("#createTypeMenu [data-create-type='list']").click()
            feature_page.wait_for_function(
                "document.querySelector('#planModal')?.classList.contains('open')"
            )

            production_page.click("#taskWorkspaceFooterBack")
            production_page.wait_for_function(
                "() => !document.querySelector('.ui-dialog-card')?.hidden"
            )
            production_page.locator("[data-dialog-ok]").click()
            production_page.wait_for_function(
                "document.querySelector('#taskWorkspaceOverlay')?.hidden === true"
            )
            production_page.click("#tasksNewButton")
            production_page.locator("#taskCreateMenu [data-task-create-kind='list']").click()
            production_page.wait_for_function(
                "document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'"
            )
            feature_page.wait_for_function("document.activeElement?.id === 'taskListDraftTitle'")
            production_page.wait_for_function("document.activeElement?.id === 'taskWorkspaceDraftTitle'")
            assert feature_page.evaluate("""() => {
                const input = document.querySelector('#taskListDraftTitle');
                return input.selectionStart === 0 && input.selectionEnd === input.value.length;
            }""")
            assert production_page.evaluate("""() => {
                const input = document.querySelector('#taskWorkspaceDraftTitle');
                return input.selectionStart === 0 && input.selectionEnd === input.value.length;
            }""")

            list_pairs = [
                (
                    "#planModal .plan-page-body",
                    ".task-workspace-list-page",
                    ["display", "gridTemplateColumns", "gap", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
                (
                    "#planModal .plan-main",
                    ".task-workspace-list-main",
                    ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderRadius"],
                ),
                (
                    "#planModal .plan-side",
                    ".task-workspace-list-side",
                    ["display", "gridTemplateColumns", "gap", "alignContent"],
                ),
                (
                    "#planModal .plan-side>.plan-side-card:first-child",
                    ".task-workspace-list-side>.task-workspace-list-side-card:first-child",
                    ["paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "borderRadius"],
                ),
                (
                    "#taskListDraftTitle",
                    "#taskWorkspaceDraftTitle",
                    [
                        "width", "minWidth", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius", "backgroundColor", "color", "fontSize",
                    ],
                ),
                (
                    "#taskListDraftProject",
                    "#taskWorkspaceListProject",
                    [
                        "width", "minWidth", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius", "backgroundColor", "color", "fontSize",
                    ],
                ),
                (
                    "#planModal .empty-plan-cta.large",
                    ".task-workspace-empty-list-cta",
                    ["display", "minHeight", "gap", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft", "flexDirection"],
                ),
                (
                    "#planModal .empty-plan-cta strong",
                    ".task-workspace-empty-list-cta strong",
                    ["fontSize"],
                ),
                (
                    "#planModal .empty-plan-cta span",
                    ".task-workspace-empty-list-cta span",
                    ["fontSize", "fontWeight"],
                ),
                (
                    "#planModal .plan-page-foot",
                    ".task-workspace-shell.task-list-route .task-workspace-foot",
                    ["display", "justifyContent", "gap", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft"],
                ),
                (
                    "#cancelTaskListDraft",
                    "#taskWorkspaceHeaderCancel",
                    [
                        "height", "minHeight", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius",
                        "backgroundColor", "color", "fontSize", "fontWeight",
                    ],
                ),
                (
                    "#confirmTaskListDraft",
                    "#taskWorkspaceHeaderCreateList",
                    [
                        "height", "minHeight", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius",
                        "backgroundColor", "color", "fontSize", "fontWeight",
                    ],
                ),
            ]
            for feature_selector, production_selector, properties in list_pairs:
                _assert_feature_computed_style_parity(
                    feature_page,
                    feature_selector,
                    production_page,
                    production_selector,
                    properties,
                )

            feature_page.locator("#planModal .empty-plan-cta.large").hover()
            production_page.locator(".task-workspace-empty-list-cta").hover()
            _assert_feature_computed_style_parity(
                feature_page,
                "#planModal .empty-plan-cta.large",
                production_page,
                ".task-workspace-empty-list-cta",
                ["borderTopColor", "backgroundColor"],
            )
            feature_page.locator("#planModal .empty-plan-cta.large").click()
            production_page.locator(".task-workspace-empty-list-cta").click()
            feature_page.wait_for_function("document.querySelector('#taskFormTitle')?.textContent === 'New task'")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert feature_page.locator("#createTaskConfirm").inner_text() == "Create task"
            assert production_page.locator("#taskWorkspaceSave").inner_text() == "Create task"
            assert production_page.locator("#taskWorkspaceFooterBack").inner_text() == "Back to Task List Draft"
            feature_page.click("#taskEditorBack")
            production_page.click("#taskWorkspaceHeaderBack")
            feature_page.wait_for_function("document.querySelector('#planModal')?.classList.contains('open') && !document.querySelector('#planModal')?.classList.contains('subview-open')")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert feature_page.locator("#planFormList [data-draft-row]").count() == 0
            assert production_page.locator(".task-workspace-list-row").count() == 0

            feature_page.locator("#planModal .empty-plan-cta.large").hover()
            production_page.locator(".task-workspace-empty-list-cta").hover()
            _assert_feature_computed_style_parity(
                feature_page,
                "#planModal .empty-plan-cta.large",
                production_page,
                ".task-workspace-empty-list-cta",
                ["borderTopColor", "backgroundColor"],
            )
            feature_page.locator("#planModal .empty-plan-cta.large").click()
            production_page.locator(".task-workspace-empty-list-cta").click()
            feature_page.wait_for_function("document.querySelector('#taskFormTitle')?.textContent === 'New task'")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            assert production_page.locator("#taskWorkspaceWorkflow").input_value() == str(default_workflow)

            # Earlier in this test the prototype Editor is intentionally switched
            # to mixed.yaml to compare Validator + AI controls. The prototype
            # remembers that selection for the next child editor, while production
            # correctly restores the Project's saved default Workflow. Select the
            # prototype's no-file-validator default explicitly so this fixture is
            # testing List-row parity instead of failing child validation.
            feature_page.select_option("#newTaskWorkflow", "ralphy_ai_validate.yaml")
            feature_page.wait_for_function(
                "!document.querySelector('#newTaskValidationSource .task-file-source')"
            )
            feature_page.fill("#newTaskTitle", "Parity child")
            feature_page.fill("#newTaskModal .task-primary-source .task-source-mode-panel>textarea", "Parity child prompt")
            production_page.fill("#taskWorkspaceItemTitle", "Parity child")
            production_page.fill("#taskWorkspacePrompt", "Parity child prompt")
            feature_page.click("#createTaskConfirm")
            production_page.click("#taskWorkspaceSave")
            feature_page.wait_for_function("document.querySelectorAll('#planFormList [data-draft-row]').length === 1")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST' && document.querySelectorAll('.task-workspace-list-row').length === 1")

            # Compare the final rendered row after both implementations have
            # actually created a child. This catches cascade/specificity drift
            # that selector-level tests cannot see.
            row_pairs = [
                (
                    "#planFormList [data-draft-row='0']",
                    ".task-workspace-list-row",
                    ["borderTopWidth", "borderTopStyle", "borderRadius", "backgroundColor"],
                ),
                (
                    "#planFormList [data-draft-row='0'] .plan-row-head",
                    ".task-workspace-list-row",
                    [
                        # Do not compare resolved grid track pixels here. The
                        # prototype Draft markup still nests its drag grip inside
                        # the number and then hides that nested grip, even though
                        # its final CSS declares the intended four-column layout.
                        # compare_feature_ui.py locks that declaration exactly;
                        # browser parity owns only equivalent rendered geometry.
                        "display", "columnGap", "alignItems",
                        "minHeight", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                    ],
                ),
                (
                    "#planFormList [data-draft-row='0'] .plan-row-num",
                    ".task-workspace-list-number",
                    ["display", "width", "height", "marginLeft", "marginRight", "lineHeight", "alignSelf"],
                ),
                (
                    "#planFormList [data-draft-row='0'] .plan-row-copy strong",
                    ".task-workspace-list-copy strong",
                    ["display", "fontSize"],
                ),
                (
                    "#planFormList [data-draft-row='0'] .plan-row-copy small",
                    ".task-workspace-list-copy small",
                    ["display", "marginTop", "color", "fontSize", "whiteSpace", "overflow", "textOverflow"],
                ),
                (
                    "#planFormList [data-draft-row='0'] .plan-row-actions",
                    ".task-workspace-list-actions",
                    ["display", "alignItems", "gap"],
                ),
                (
                    "#planFormList [data-draft-row='0'] [data-draft-edit='0']",
                    ".task-workspace-list-row .task-workspace-row-edit",
                    [
                        "height", "minWidth", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
                        "borderTopWidth", "borderTopStyle", "borderRadius",
                        "backgroundColor", "color", "fontSize",
                    ],
                ),
            ]
            for feature_selector, production_selector, properties in row_pairs:
                _assert_feature_computed_style_parity(
                    feature_page,
                    feature_selector,
                    production_page,
                    production_selector,
                    properties,
                )

            # Behavior parity for the same row: a plain click leaves a New List
            # Draft in the List route; double-click opens the child Editor; Back
            # returns to that same Draft without adding/removing a row.
            feature_row = feature_page.locator("#planFormList [data-draft-row='0']")
            production_row = production_page.locator(".task-workspace-list-row").first
            _assert_feature_computed_style_parity(
                feature_page,
                "#planFormList [data-draft-up='0']",
                production_page,
                ".task-workspace-list-row .task-workspace-row-up",
                ["display"],
            )
            _assert_feature_computed_style_parity(
                feature_page,
                "#planFormList [data-draft-down='0']",
                production_page,
                ".task-workspace-list-row .task-workspace-row-down",
                ["display"],
            )
            assert production_row.locator(".task-workspace-row-up").is_hidden()
            assert production_row.locator(".task-workspace-row-down").is_hidden()
            feature_row.click()
            production_row.click()
            assert feature_page.locator("#planModal").get_attribute("class").find("subview-open") == -1
            assert production_page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK LIST"
            feature_row.dblclick()
            production_row.dblclick()
            feature_page.wait_for_function("document.querySelector('#taskFormTitle')?.textContent === 'Edit task'")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK EDITOR'")
            feature_page.click("#taskEditorBack")
            production_page.click("#taskWorkspaceHeaderBack")
            feature_page.wait_for_function("document.querySelector('#planModal')?.classList.contains('open') && !document.querySelector('#planModal')?.classList.contains('subview-open')")
            production_page.wait_for_function("document.querySelector('#taskWorkspaceEyebrow')?.textContent === 'TASK LIST'")
            assert feature_page.locator("#planFormList [data-draft-row]").count() == 1
            assert production_page.locator(".task-workspace-list-row").count() == 1

            feature_list_shell = feature_page.locator("#taskOverlay .drawer").bounding_box()
            production_list_shell = production_page.locator("#taskWorkspaceShell").bounding_box()
            assert feature_list_shell and production_list_shell
            assert abs(feature_list_shell["width"] - production_list_shell["width"]) <= 1

            # Final prototype responsive contract: at <=900px the shared Task
            # workspace is full width and Task List hides the secondary side rail.
            feature_page.set_viewport_size({"width": 880, "height": 900})
            production_page.set_viewport_size({"width": 880, "height": 900})
            feature_page.wait_for_timeout(50)
            production_page.wait_for_timeout(50)
            _assert_feature_computed_style_parity(
                feature_page,
                "#planModal .plan-page-body",
                production_page,
                ".task-workspace-list-page",
                ["gridTemplateColumns"],
            )
            _assert_feature_computed_style_parity(
                feature_page,
                "#planModal .plan-side",
                production_page,
                ".task-workspace-list-side",
                ["display"],
            )
            assert feature_page.locator("#planModal .plan-side").is_hidden()
            assert production_page.locator(".task-workspace-list-side").is_hidden()
            feature_narrow_shell = feature_page.locator("#taskOverlay .drawer").bounding_box()
            production_narrow_shell = production_page.locator("#taskWorkspaceShell").bounding_box()
            assert feature_narrow_shell and production_narrow_shell
            assert abs(feature_narrow_shell["width"] - production_narrow_shell["width"]) <= 1
            assert abs(production_narrow_shell["width"] - 880) <= 1

            # The accepted prototype keeps Task List rows/actions structurally
            # identical below the side-rail breakpoint. Legacy production CSS
            # used to move actions into explicit grid columns and shrink header
            # buttons at 760/620px, shifting click targets away from prototype.
            for narrow_width in (740, 620, 520):
                feature_page.set_viewport_size({"width": narrow_width, "height": 900})
                production_page.set_viewport_size({"width": narrow_width, "height": 900})
                feature_page.wait_for_timeout(50)
                production_page.wait_for_timeout(50)
                _assert_feature_computed_style_parity(
                    feature_page,
                    ".app",
                    production_page,
                    "body",
                    ["gridTemplateColumns"],
                )
                feature_transition = _computed_style(
                    feature_page,
                    ".app",
                    ["transitionProperty"],
                )["transitionProperty"]
                production_transition = _computed_style(
                    production_page,
                    "body",
                    ["transitionProperty"],
                )["transitionProperty"]
                assert "grid-template-columns" not in feature_transition
                assert "grid-template-columns" not in production_transition
                _assert_feature_computed_style_parity(
                    feature_page,
                    "#planFormList [data-draft-row='0'] .plan-row-actions",
                    production_page,
                    ".task-workspace-list-actions",
                    ["gridColumnStart", "gridColumnEnd", "justifyContent", "flexWrap"],
                )
                _assert_feature_computed_style_parity(
                    feature_page,
                    "#cancelTaskListDraft",
                    production_page,
                    "#taskWorkspaceHeaderCancel",
                    ["height", "minHeight", "paddingLeft", "paddingRight", "fontSize"],
                )
                feature_shell = feature_page.locator("#taskOverlay .drawer").bounding_box()
                production_shell = production_page.locator("#taskWorkspaceShell").bounding_box()
                assert feature_shell and production_shell
                assert abs(feature_shell["width"] - production_shell["width"]) <= 1
                assert abs(production_shell["width"] - narrow_width) <= 1
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_task_board_search_runtime_back_and_validator_picker_actions() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        project_id = state.project_identity(root)["project_id"]
        workflow = root / "runner" / "assets" / "workflows" / "mixed.yaml"
        workflow.write_text(
            "stages:\n"
            "  planning:\n    type: plan\n"
            "  validate_file:\n    type: command\n"
            "    command: \"{python} {validator} --project-root {project_root}\"\n"
            "  validate_ai:\n    type: ai_validator\n    validator: ai\n"
            "flow: [planning, validate_file, validate_ai]\n",
            encoding="utf-8",
        )
        validator_path = root / "selected_validator.py"
        ai_prompt_path = root / "selected_ai_validator.md"
        validator_path.write_text("print('validator')\n", encoding="utf-8")
        ai_prompt_path.write_text("Validate {{ goal }}\n", encoding="utf-8")

        for title, request_id in (
            ("Coverage Alpha", "coverage-alpha-create"),
            ("Coverage Beta", "coverage-beta-create"),
        ):
            state.tasks.create(
                root,
                {
                    "title": title,
                    "items": [{
                        "title": title,
                        "prompt": f"Do {title}",
                        "workflow": str(workflow),
                        "project": str(root),
                        "workspace": "auto",
                        "validator": str(validator_path),
                    }],
                },
                request_id=request_id,
                project_id=project_id,
            )
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            parsed = urlparse(url)
            body = json.loads(body_json or "{}")
            if method == "POST" and parsed.path == "/api/files/pick":
                selected = validator_path if body.get("kind") == "python" else ai_prompt_path
                return {"status": 200, "data": {"cancelled": False, "path": str(selected)}}
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", bridge)
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.wait_for_function(
                "() => document.querySelectorAll('#tasksBoardNew .tasks-board-card').length >= 2"
            )

            page.fill("#tasksBoardSearch", "Coverage Alpha")
            page.wait_for_timeout(80)
            assert page.locator(".tasks-board-card", has_text="Coverage Alpha").count() == 1
            assert page.locator(".tasks-board-card", has_text="Coverage Beta").count() == 0
            page.fill("#tasksBoardSearch", "")
            page.wait_for_timeout(80)
            assert page.locator(".tasks-board-card", has_text="Coverage Alpha").count() == 1
            assert page.locator(".tasks-board-card", has_text="Coverage Beta").count() == 1

            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            assert page.locator("#messageInput").is_enabled()
            page.fill("#messageInput", "Coverage runtime message")
            assert page.locator("#messageInput").input_value() == "Coverage runtime message"
            page.fill("#messageInput", "")
            page.click("#tasksRuntimeBackButton")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            assert page.locator("#chatView").is_hidden()

            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.locator("#workflowDropdownButton").click()
            page.locator("#workflowDropdownMenu .workflow-dropdown-option").filter(
                has_text="mixed.yaml"
            ).click()
            page.wait_for_function(
                "document.querySelector('#workflowSelectedLabel')?.textContent === 'mixed.yaml'"
            )
            page.locator("#optionsButton").click()
            page.wait_for_function("document.querySelector('#optionsPanel')?.hidden === false")
            assert page.locator("#validatorPicker").is_visible()
            assert page.locator("#aiValidatorPromptPicker").is_visible()

            page.click("#backendDropdownButton")
            assert page.locator("#backendDropdownMenu").is_visible()
            page.locator("#backendDropdownMenu .backend-dropdown-option").filter(
                has_text="opencode"
            ).click()
            page.wait_for_function(
                "() => document.querySelector('#backend')?.value === 'opencode' "
                "&& document.querySelector('#backendSelectedLabel')?.textContent === 'opencode'"
            )
            assert page.locator("#backendDropdownMenu").is_hidden()

            # The picker button still owns explicit open/close toggling.
            page.click("#backendDropdownButton")
            assert page.locator("#backendDropdownMenu").is_visible()
            page.click("#backendDropdownButton")
            assert page.locator("#backendDropdownMenu").is_hidden()

            page.click("#browseValidatorButton")
            page.wait_for_function(
                "(value) => document.querySelector('#validator')?.value === value",
                arg=str(validator_path),
            )
            assert page.locator("#clearValidatorButton").is_visible()
            page.click("#clearValidatorButton")
            assert page.locator("#validator").input_value() == ""
            assert page.locator("#clearValidatorButton").is_hidden()

            page.click("#browseAiValidatorPromptButton")
            page.wait_for_function(
                "(value) => document.querySelector('#aiValidatorPrompt')?.value === value",
                arg=str(ai_prompt_path),
            )
            assert page.locator("#clearAiValidatorPromptButton").is_visible()
            page.click("#clearAiValidatorPromptButton")
            assert page.locator("#aiValidatorPrompt").input_value() == ""
            assert page.locator("#clearAiValidatorPromptButton").is_hidden()

            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_prompt_asset_manager_actions_import_export_and_detail_dialogs() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        created = state.studio_prompt_create("coverage_prompt", "global", None)
        opened = state.studio_read(created["item"]["id"], None)
        state.studio_save(
            created["item"]["id"],
            "Original coverage prompt {{ goal }}\n",
            opened["hash"],
            None,
        )
        import_source = root / "coverage-import.md"
        import_source.write_text("Imported coverage prompt {{ goal }}\n", encoding="utf-8")
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            parsed = urlparse(url)
            body = json.loads(body_json or "{}")
            query = parse_qs(parsed.query)
            if method == "GET" and parsed.path == "/api/studio/export":
                project_value = query.get("project", [""])[0]
                project = Path(project_value) if project_value else None
                return {
                    "status": 200,
                    "data": state.studio_export(query.get("id", [""])[0], project),
                }
            if method == "POST" and parsed.path == "/api/studio/import":
                if str(body.get("name", "")).strip() == "explode.md":
                    return {
                        "status": 400,
                        "data": {
                            "code": "invalid_request",
                            "message": "Import exploded on line one\nDetailed diagnostic on line two",
                            "retryable": False,
                            "request_id": "",
                        },
                    }
                project = Path(body["project"]) if body.get("project") else None
                try:
                    data = state.studio_import(
                        body.get("kind", ""),
                        body.get("name", ""),
                        body.get("content", ""),
                        body.get("destination", "global"),
                        project,
                    )
                    return {"status": 200, "data": data}
                except Exception as exc:
                    return {
                        "status": 400,
                        "data": {
                            "code": "invalid_request",
                            "message": str(exc),
                            "retryable": False,
                            "request_id": "",
                        },
                    }
            if method == "POST" and parsed.path == "/api/studio/validate":
                return {
                    "status": 200,
                    "data": {
                        "ok": False,
                        "summary": "Validation failed",
                        "output": "First validation line\nSecond validation line",
                        "diagnostics": [],
                    },
                }
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 860})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", bridge)
            page.route(
                "http://local.test/workflow-studio-app/**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="<html><body>Workflow Editor</body></html>",
                ),
            )
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };
                Object.defineProperty(navigator, 'clipboard', {
                    configurable: true,
                    value: { writeText: async (text) => { window.__copiedText = String(text); } }
                });"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#promptNav")
            page.wait_for_function("document.querySelector('#promptNav')?.classList.contains('active')")
            row = page.locator("#studioFileList .studio-file-item").filter(
                has_text="coverage_prompt.md"
            )
            assert row.count() == 1
            row.click()
            page.wait_for_function(
                "document.querySelector('#studioFileName')?.textContent === 'coverage_prompt.md'"
            )

            page.fill("#studioPromptTextarea", "Unsaved local draft")
            page.click("#reloadStudioButton")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard')")
            page.click("[data-dialog-ok]")
            page.wait_for_function(
                "() => document.querySelector('#studioPromptTextarea')?.value.includes('Original coverage prompt')"
            )

            page.click("#validateStudioButton")
            page.wait_for_function("document.querySelector('#validationOutput')?.hidden === false")
            page.click("#validationDetailsButton")
            assert page.locator("#validationDetailsBackdrop").is_visible()
            assert "Second validation line" in page.locator("#validationDetailsContent").inner_text()
            page.click("#validationDetailsCopy")
            page.wait_for_function(
                "() => window.__copiedText?.includes('Second validation line')"
            )
            page.click("#validationDetailsOk")
            assert page.locator("#validationDetailsBackdrop").is_hidden()
            page.click("#validationDetailsButton")
            page.click("#validationDetailsClose")
            assert page.locator("#validationDetailsBackdrop").is_hidden()

            page.click("#studioAssetMenuButton")
            assert page.locator("#studioAssetMenu").is_visible()
            page.click("#renameStudioButton")
            page.fill(".ui-dialog-input", "coverage_renamed.md")
            page.click("[data-dialog-ok]")
            page.wait_for_function(
                "document.querySelector('#studioFileName')?.textContent === 'coverage_renamed.md'"
            )

            page.click("#studioAssetMenuButton")
            page.click("#duplicateStudioButton")
            assert page.locator("#duplicateAssetBackdrop").is_visible()
            page.click("#duplicateAssetClose")
            assert page.locator("#duplicateAssetBackdrop").is_hidden()
            page.click("#studioAssetMenuButton")
            page.click("#duplicateStudioButton")
            page.click("#duplicateAssetCancel")
            assert page.locator("#duplicateAssetBackdrop").is_hidden()
            page.click("#studioAssetMenuButton")
            page.click("#duplicateStudioButton")
            page.fill("#duplicateAssetName", "coverage_copy.md")
            page.click("#duplicateAssetConfirm")
            page.wait_for_function(
                "document.querySelector('#studioFileName')?.textContent === 'coverage_copy.md'"
            )

            page.click("#studioAssetMenuButton")
            with page.expect_download() as download_info:
                page.click("#exportStudioButton")
            download = download_info.value
            assert download.suggested_filename == "coverage_copy.md"

            page.click("#importAssetButton")
            assert page.locator("#importAssetBackdrop").is_visible()
            page.select_option("#importAssetDestination", "project")
            assert page.locator("#importAssetDestination").input_value() == "project"
            page.select_option("#importAssetDestination", "global")
            with page.expect_file_chooser() as chooser_info:
                page.click("#importAssetChooseButton")
            chooser_info.value.set_files(str(import_source))
            page.wait_for_function(
                "() => document.querySelector('#importAssetFile')?.files?.[0]?.name === 'coverage-import.md'"
            )
            page.wait_for_function(
                "() => document.querySelector('#importAssetContent')?.value.includes('Imported coverage prompt')"
            )
            page.fill("#importAssetName", "coverage_imported.md")
            page.click("#importAssetConfirm")
            page.wait_for_function(
                "document.querySelector('#studioFileName')?.textContent === 'coverage_imported.md'"
            )

            page.click("#importAssetButton")
            page.fill("#importAssetName", "explode.md")
            page.fill("#importAssetContent", "Bad import content")
            page.click("#importAssetConfirm")
            page.wait_for_function(
                "() => document.querySelector('#importAssetHint')?.textContent.includes('Detailed diagnostic')"
            )
            assert "Import exploded on line one" in page.locator("#importAssetHint").inner_text()
            assert "Detailed diagnostic on line two" in page.locator("#importAssetHint").inner_text()
            assert page.locator("#importAssetHint").evaluate(
                "(node) => node.classList.contains('error')"
            )
            page.click("#importAssetCancel")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard import')")
            page.click("[data-dialog-ok]")
            assert page.locator("#importAssetBackdrop").is_hidden()
            page.click("#importAssetButton")
            assert page.locator("#importAssetBackdrop").is_visible()
            page.click("#importAssetClose")
            assert page.locator("#importAssetBackdrop").is_hidden()
            assert page.locator("#importAssetBackdrop").is_hidden()

            page.fill("#studioSearchInput", "definitely-no-coverage-match")
            assert page.locator("#studioSearchClear").is_visible()
            page.click("#studioSearchClear")
            assert page.locator("#studioSearchInput").input_value() == ""

            page.click("#newWorkflowButton")
            assert page.locator("#newPromptBackdrop").is_visible()
            page.click("#newPromptClose")
            assert page.locator("#newPromptBackdrop").is_hidden()
            page.click("#newWorkflowButton")
            page.fill("#newPromptName", "discard_me")
            page.click("#newPromptCancel")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard new Prompt')")
            page.click("[data-dialog-ok]")
            assert page.locator("#newPromptBackdrop").is_hidden()
            page.click("#newWorkflowButton")
            page.fill("#newPromptName", "coverage_created")
            page.click("#newPromptConfirm")
            page.wait_for_function(
                "document.querySelector('#studioFileName')?.textContent === 'coverage_created.md'"
            )

            page.click("#studioAssetMenuButton")
            page.click("#deleteStudioButton")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Delete Prompt')")
            page.click("[data-dialog-ok]")
            page.wait_for_function(
                "() => ![...document.querySelectorAll('#studioFileList .studio-file-item')].some(node => node.textContent.includes('coverage_created.md'))"
            )

            page.click("#workflowNav")
            page.wait_for_function("document.querySelector('#workflowNav')?.classList.contains('active')")
            page.click("#newWorkflowButton")
            assert page.locator("#newWorkflowBackdrop").is_visible()
            page.click("#newWorkflowClose")
            assert page.locator("#newWorkflowBackdrop").is_hidden()
            page.click("#newWorkflowButton")
            page.fill("#newWorkflowName", "discard_workflow")
            page.click("#newWorkflowCancel")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard new Workflow')")
            page.click("[data-dialog-ok]")
            assert page.locator("#newWorkflowBackdrop").is_hidden()
            page.click("#newWorkflowButton")
            page.fill("#newWorkflowName", "coverage_created_workflow")
            page.select_option("#newWorkflowDestination", "project")
            assert page.locator("#newWorkflowDestination").input_value() == "project"
            page.select_option("#newWorkflowDestination", "global")
            page.click("#newWorkflowConfirm")
            # Create Workflow navigates immediately into the Workflow Editor.
            # Waiting on the Studio list is racy because that list leaves the
            # active document as soon as the new asset opens.
            page.wait_for_url("**/workflow-studio-app/index.html?*")
            created_item = next(
                item
                for item in state.studio_files(root)["workflows"]
                if "coverage_created_workflow" in item["name"]
            )
            navigation = parse_qs(urlparse(page.url).query)
            assert navigation["id"] == [created_item["id"]]
            assert navigation["project"] == [str(root)]
            assert page.get_by_text("Workflow Editor", exact=True).is_visible()

            assert not errors
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_workflow_generator_full_browser_lifecycle() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        base_bridge = _bridge_for(state)
        generator = {
            "state": "idle",
            "job_id": "",
            "attempt": 0,
            "request": "",
            "filename": "",
            "backend": "",
        }

        def draft_payload() -> dict:
            return {
                "workflow": (
                    "stages:\n"
                    "  execute:\n"
                    "    type: base\n"
                    "    profile: execute\n"
                    "    prompt: common/execution.md\n"
                    "flow:\n"
                    "  - execute\n"
                ),
                "prompts": [
                    {"name": "generated.md", "content": "Generated prompt {{ goal }}\n"},
                    {"name": "generated-review.md", "content": "Generated review {{ goal }}\n"},
                ],
                "visual": {
                    "stages": [
                        {
                            "name": "execute",
                            "type": "base",
                            "profile": "execute",
                            "status": "execute",
                        }
                    ],
                    "flow": ["execute"],
                },
                "validation": "PASS",
            }

        def bridge(method: str, url: str, body_json: str):
            parsed = urlparse(url)
            body = json.loads(body_json or "{}")
            query = parse_qs(parsed.query)
            path = parsed.path

            if method == "GET" and path == "/api/studio/draft":
                return {
                    "status": 200,
                    "data": {
                        "available": True,
                        "workspace_root": str(root / ".builder"),
                        "workspace_pattern": str(root / ".builder" / "<new-job-id>"),
                        "message": "AI Workflow Builder is ready.",
                    },
                }
            if method == "GET" and path == "/api/studio/generate/active":
                return {"status": 200, "data": {"active": False}}
            if method == "GET" and path == "/api/studio/generate/status":
                job_id = query.get("job_id", [""])[0]
                if job_id != generator["job_id"]:
                    return {
                        "status": 400,
                        "data": {
                            "code": "invalid_request",
                            "message": "Unknown generator job",
                            "retryable": False,
                        },
                    }
                if generator["state"] == "running":
                    if generator["attempt"] == 1:
                        return {
                            "status": 200,
                            "data": {
                                "ok": True,
                                "job_id": job_id,
                                "state": "running",
                                "message": "Still generating",
                                "workspace": str(root / ".builder" / job_id),
                            },
                        }
                    if "fail" in generator["request"].lower():
                        generator["state"] = "failed"
                    else:
                        generator["state"] = "ready"
                if generator["state"] == "ready":
                    return {
                        "status": 200,
                        "data": {
                            "ok": True,
                            "job_id": job_id,
                            "state": "ready",
                            "message": "Draft ready",
                            "workspace": str(root / ".builder" / job_id),
                            "draft": draft_payload(),
                        },
                    }
                if generator["state"] == "failed":
                    return {
                        "status": 200,
                        "data": {
                            "ok": False,
                            "job_id": job_id,
                            "state": "failed",
                            "message": "Synthetic Workflow Builder failure",
                            "workspace": str(root / ".builder" / job_id),
                        },
                    }
                if generator["state"] == "cancelled":
                    return {
                        "status": 200,
                        "data": {
                            "ok": True,
                            "job_id": job_id,
                            "state": "cancelled",
                            "message": "Workflow generation cancelled",
                            "workspace": str(root / ".builder" / job_id),
                        },
                    }

            if method == "POST" and path == "/api/studio/generate":
                generator["attempt"] += 1
                generator["job_id"] = f"coverage-job-{generator['attempt']}"
                generator["state"] = "running"
                generator["request"] = str(body.get("request", ""))
                generator["filename"] = str(body.get("filename", ""))
                generator["backend"] = str(body.get("backend", ""))
                return {
                    "status": 200,
                    "data": {
                        "ok": True,
                        "job_id": generator["job_id"],
                        "state": "running",
                        "workspace": str(root / ".builder" / generator["job_id"]),
                        "message": "Synthetic generation started",
                    },
                }
            if method == "POST" and path == "/api/studio/generate/cancel":
                generator["state"] = "cancelled"
                return {
                    "status": 200,
                    "data": {
                        "ok": True,
                        "state": "cancelling",
                        "message": "Cancelling Workflow generation…",
                    },
                }
            if method == "POST" and path == "/api/studio/generate/discard":
                generator["state"] = "idle"
                return {"status": 200, "data": {"ok": True, "message": "Draft discarded"}}
            if method == "POST" and path == "/api/studio/generate/validate":
                current = draft_payload()
                current["workflow"] = str(body.get("workflow", current["workflow"]))
                current["prompts"] = body.get("prompts", current["prompts"])
                return {
                    "status": 200,
                    "data": {
                        "ok": True,
                        "summary": "Validation passed",
                        "draft": current,
                    },
                }
            if method == "POST" and path == "/api/studio/generate/save":
                project = Path(body["project"]) if body.get("project") else None
                try:
                    imported = state.studio_import(
                        "workflow",
                        body.get("filename", ""),
                        body.get("workflow", ""),
                        body.get("destination", "global"),
                        project,
                    )
                    generator["state"] = "idle"
                    return {
                        "status": 200,
                        "data": {
                            "ok": True,
                            "workflow": imported["item"]["path"],
                            "item": imported["item"],
                            "file": imported["file"],
                            "message": f"Workflow {imported['item']['name']} saved",
                        },
                    }
                except Exception as exc:
                    return {
                        "status": 400,
                        "data": {
                            "code": "invalid_request",
                            "message": str(exc),
                            "retryable": False,
                        },
                    }
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", bridge)
            page.route(
                "http://local.test/workflow-studio-app/**",
                lambda route: route.fulfill(
                    status=200,
                    content_type="text/html",
                    body="<html><body>Workflow Editor</body></html>",
                ),
            )
            _load_main_ui_document(page, html)
            page.evaluate(
                """window.fetch = async (url, options = {}) => {
                    const method = (options.method || 'GET').toUpperCase();
                    const response = await window.__apiBridge(method, String(url), options.body || '{}');
                    return {
                        ok: response.status >= 200 && response.status < 300,
                        status: response.status,
                        json: async () => response.data
                    };
                };"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#workflowNav")
            page.wait_for_function("document.querySelector('#workflowNav')?.classList.contains('active')")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#workflowGeneratorPage')?.hidden")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.click("#generateWorkflowBack")
            page.wait_for_function("document.querySelector('#workflowGeneratorPage')?.hidden === true")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            assert page.locator("#generateWorkflowBackend").count() == 1
            assert page.locator("#generateWorkflowBackend option").count() >= 1
            page.select_option("#generateWorkflowBackend", "opencode")
            assert page.locator("#generateWorkflowBackend").input_value() == "opencode"
            page.click("#generateWorkflowConfirm")
            assert "Describe the Workflow" in page.locator("#generateWorkflowHint").inner_text()

            page.fill("#generateWorkflowRequest", "Cancel this coverage generation")
            page.fill("#generateWorkflowFilename", "cancel-coverage.workflow.yaml")
            page.select_option("#generateWorkflowBackend", "opencode")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowRunning')?.hidden")
            assert generator["backend"] == "opencode"
            page.click("#generateWorkflowStop")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Cancel Workflow generation')")
            page.click("[data-dialog-ok]")
            page.wait_for_function("document.querySelector('#workflowGeneratorPage')?.hidden === true")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.fill("#generateWorkflowRequest", "Build a coverage workflow")
            page.fill("#generateWorkflowFilename", "regenerate-coverage.workflow.yaml")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowReady')?.hidden")
            page.click("#generateWorkflowRegenerate")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Generate a new Draft')")
            page.click("[data-dialog-ok]")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowReady')?.hidden")

            page.click("#generateWorkflowDiscard")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard generated Workflow')")
            page.click("[data-dialog-ok]")
            page.wait_for_function("document.querySelector('#workflowGeneratorPage')?.hidden === true")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.fill("#generateWorkflowRequest", "Please fail this coverage generation")
            page.fill("#generateWorkflowFilename", "failed-coverage.workflow.yaml")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowFailed')?.hidden")
            assert "Synthetic Workflow Builder failure" in page.locator("#generateWorkflowFailure").inner_text()
            page.click("#generateWorkflowRetry")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            assert "Please fail" in page.locator("#generateWorkflowRequest").input_value()
            page.click("#generateWorkflowCancel")
            page.wait_for_function("document.querySelector('.ui-dialog-title')?.textContent.includes('Discard Workflow request')")
            page.click("[data-dialog-ok]")
            page.wait_for_function("document.querySelector('#workflowGeneratorPage')?.hidden === true")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.fill("#generateWorkflowRequest", "Fail once more for failed cancel coverage")
            page.fill("#generateWorkflowFilename", "failed-cancel.workflow.yaml")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowFailed')?.hidden")
            page.click("#generateWorkflowFailedCancel")
            page.wait_for_function("document.querySelector('#workflowGeneratorPage')?.hidden === true")

            page.click("#generateWorkflowButton")
            page.wait_for_function("!document.querySelector('#generateWorkflowForm')?.hidden")
            page.fill("#generateWorkflowRequest", "Build and save final coverage workflow")
            page.fill("#generateWorkflowFilename", "coverage-generated.workflow.yaml")
            page.click("#generateWorkflowConfirm")
            page.wait_for_function("!document.querySelector('#generateWorkflowReady')?.hidden")

            page.click("#generateWorkflowEditYaml")
            assert page.locator("#generateDraftYamlPanel").is_visible()
            page.wait_for_function("document.activeElement === document.querySelector('#generateWorkflowPreview')")
            page.click("#generateDraftVisualTab")
            assert page.locator("#generateDraftVisualPanel").is_visible()
            page.click("#generateDraftYamlTab")
            assert page.locator("#generateDraftYamlPanel").is_visible()
            page.wait_for_function("document.activeElement === document.querySelector('#generateWorkflowPreview')")
            page.fill(
                "#generateWorkflowPreview",
                (
                    "stages:\n"
                    "  execute:\n"
                    "    type: base\n"
                    "    profile: execute\n"
                    "    prompt: common/execution.md\n"
                    "flow: [execute]\n"
                ),
            )
            assert page.locator("#generateDraftDirtyHint").is_visible()

            page.click("#generateDraftPromptTab")
            assert page.locator("#generateDraftPromptPanel").is_visible()
            prompt_pills = page.locator(
                "#generateWorkflowPromptList .designer-workflow-pill"
            )
            assert prompt_pills.count() == 2
            prompt_pills.nth(1).click()
            page.wait_for_function(
                "() => document.querySelector('#generateDraftPromptTextarea')?.value"
                " === 'Generated review {{ goal }}\\n'"
            )
            page.click("#generateWorkflowEditPrompt")
            page.wait_for_function("document.activeElement === document.querySelector('#generateDraftPromptTextarea')")
            page.fill("#generateDraftPromptTextarea", "Edited generated review {{ goal }}\n")

            page.click("#generateDraftVisualTab")
            assert page.locator("#generateDraftVisualPanel").is_visible()
            page.click("#generateWorkflowValidate")
            page.wait_for_function(
                "() => document.querySelector('#generateWorkflowValidation')?.textContent.includes('PASS')"
            )
            assert page.locator("#generateDraftDirtyHint").is_hidden()

            page.click("#generateWorkflowSave")
            assert page.locator("#generateWorkflowSaveBackdrop").is_visible()
            page.click("#generateWorkflowSaveCancel")
            assert page.locator("#generateWorkflowSaveBackdrop").is_hidden()
            page.click("#generateWorkflowSave")
            page.click("#generateWorkflowSaveClose")
            assert page.locator("#generateWorkflowSaveBackdrop").is_hidden()
            page.click("#generateWorkflowSave")
            assert page.locator("#generateWorkflowSaveFilename").input_value() == "coverage-generated.workflow.yaml"
            page.fill("#generateWorkflowSaveFilename", "coverage-final.workflow.yaml")
            assert page.locator("#generateWorkflowSaveFilename").input_value() == "coverage-final.workflow.yaml"
            page.select_option("#generateWorkflowDestination", "project")
            assert page.locator("#generateWorkflowDestination").input_value() == "project"
            page.select_option("#generateWorkflowDestination", "global")
            page.click("#generateWorkflowSaveConfirm")
            page.wait_for_url("**/workflow-studio-app/index.html?*")
            saved_item = next(
                item
                for item in state.studio_files(root)["workflows"]
                if item["name"] == "coverage-final.workflow.yaml"
            )
            navigation = parse_qs(urlparse(page.url).query)
            assert navigation["id"] == [saved_item["id"]]
            assert navigation["project"] == [str(root)]
            assert page.get_by_text("Workflow Editor", exact=True).is_visible()
            saved = root / "runner" / "assets" / "workflows" / "coverage-final.workflow.yaml"
            assert saved.is_file()
            assert "flow: [execute]" in saved.read_text(encoding="utf-8")

            assert not errors
            browser.close()
