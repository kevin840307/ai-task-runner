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


def _install_main_ui_scripts(page, static_root: Path) -> None:
    # app.js is a real ES module. Route the module graph through the same HTTP
    # origin as the document instead of injecting app.js as a classic script.
    for relative in ("app.js", "js/ui-lifecycle.js", "js/workflow-generator.js", "js/project-chat.js", "js/task-workspace.js"):
        source = static_root / relative
        page.route(
            f"http://local.test/{relative}",
            lambda route, _request, source=source: route.fulfill(
                status=200,
                content_type="text/javascript",
                body=source.read_text(encoding="utf-8"),
            ),
        )
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
    (root / "tool" / "workflow_dryrun.py").write_text(
        "import json; print(json.dumps({'closed':True,'valid':True,'paths_passed':1,'paths_total':1}))\n",
        encoding="utf-8",
    )
    return UIState(root)


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
                elif path == "/api/chat/ask":
                    session_id = query.get("session_id", [""])[0]
                    data = state.chat_service.ask(project, session_id)
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
                                "user_invocable": True, "enabled": False,
                                "permission": "explicit", "availability": "workspace_phase_pending",
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
                        "workflows": [
                            {"id": "wf1", "name": "ralphy_ai_validate.yaml", "path": str(state.repo_root / "runner" / "assets" / "workflows" / "ralphy_ai_validate.yaml"), "scope": "global"}
                        ],
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
                    data = state.read_runtime(project)
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
                    mode = str(body.get("mode", "auto"))
                    spec = str(body.get("spec", ""))
                    if spec == "mock:error":
                        raise ValueError("Browser TaskDraft backend failure")
                    if spec == "mock:invalid":
                        raise ValueError("TaskDraft generator returned invalid structured data")
                    count = 2 if mode == "list" else 1
                    data = {
                        "draft_id": "draft-" + "a" * 32,
                        "mode": mode,
                        "spec": str(body.get("spec", "")),
                        "duplicate": False,
                        "draft": {
                            "schema_version": 1,
                            "title": "Browser generated draft",
                            "project": str(body["project"]),
                            "items": [
                                {
                                    "title": f"Draft item {index + 1}",
                                    "prompt": f"Do browser item {index + 1}",
                                    "workflow": "workflow.yaml",
                                    "project": str(body["project"]),
                                    "workspace": "auto",
                                }
                                for index in range(count)
                            ],
                        },
                    }
                elif path == "/api/tasks/validate-draft":
                    data = state.tasks.validate(
                        Path(body["project"]),
                        body.get("draft"),
                    )
                elif path == "/api/tasks/create":
                    state._browser_last_task_create_draft = json.loads(
                        json.dumps(body.get("draft"))
                    )
                    data = state.tasks.create(
                        Path(body["project"]),
                        body.get("draft"),
                        request_id=str(body.get("request_id", "")),
                    )
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
                            "queue_id": f"queue-{len(queue) + 1:032x}",
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
                    elif message == "queue browser message":
                        queue = getattr(state, "_browser_chat_queue", {})
                        queue.setdefault(session_id, []).append({
                            "queue_id": "queue-" + "1" * 32,
                            "content": message,
                            "created_at": 1,
                            "status": "queued",
                        })
                        state._browser_chat_queue = queue
                        busy_map = getattr(state, "_browser_chat_busy", {})
                        busy_map[session_id] = True
                        state._browser_chat_busy = busy_map
                        data = {
                            "session_id": session_id,
                            "items": list(queue[session_id]),
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
                        if item["queue_id"] == str(body.get("queue_id", "")):
                            item["content"] = str(body.get("message", ""))
                    busy_map = getattr(state, "_browser_chat_busy", {})
                    data = {"session_id": session_id, "items": list(queue), "busy": bool(busy_map.get(session_id, False))}
                elif path == "/api/chat/queue/delete":
                    session_id = str(body.get("session_id", ""))
                    queues = getattr(state, "_browser_chat_queue", {})
                    queues[session_id] = [
                        item for item in queues.get(session_id, [])
                        if item["queue_id"] != str(body.get("queue_id", ""))
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
                    data = state.chat_service.select_session(Path(body["project"]), str(body.get("session_id", "")))
                elif path == "/api/chat/session/rename":
                    data = state.chat_service.rename_session(
                        Path(body["project"]), str(body.get("session_id", "")), str(body.get("title", ""))
                    )
                elif path == "/api/chat/session/delete":
                    data = state.chat_service.delete_session(Path(body["project"]), str(body.get("session_id", "")))
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
            return {"status": 400, "data": {"error": str(exc)}}

    return bridge


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_runtime_poll_race_does_not_apply_stale_project_response() -> None:
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
def test_browser_workflow_settings_manager_and_prompt_crud() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            # Runner options belong to Tasks, not the default Project Chat.
            page.click("#chatNav")
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

            # Project Chat session lifecycle is real Backend state, not a browser-only mock.
            page.wait_for_function("document.querySelectorAll('#projectChatSessionList .project-chat-session-row').length === 1")
            page.click("#projectChatSettingsButton")
            page.wait_for_function("!document.querySelector('#projectChatSettingsPopover')?.hidden")
            assert page.locator("#projectChatSettingsPopover").is_visible()
            page.select_option("#projectChatAgentSelect", "opencode")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'opencode'")
            page.select_option("#projectChatModelSelect", "openai/gpt-5.2")
            page.wait_for_function("document.querySelector('#projectChatReasoningSelect')?.querySelector('option[value=\"deep\"]') !== null")
            page.select_option("#projectChatReasoningSelect", "deep")
            page.select_option("#projectChatModeQuick", "yolo")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'yolo'")
            page.wait_for_function("document.querySelector('#projectChatModeDescription')?.textContent.includes('Automatically approves tools')")
            assert "Automatically approves tools" in page.locator("#projectChatModeDescription").inner_text()
            page.select_option("#projectChatModeQuick", "read")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'read'")

            # Agent switch clears the previous Agent's model ID and loads only legal native options.
            page.select_option("#projectChatAgentSelect", "qwen")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'qwen'")
            page.wait_for_function("document.querySelector('#projectChatModelSelect')?.value === ''")
            assert page.locator("#projectChatModelSelect option[value='openai/gpt-5.2']").count() == 0
            assert page.locator("#projectChatModelSelect option[value='qwen/model-a']").count() == 1
            page.fill("#projectChatInput", "/bt")
            page.wait_for_function("!document.querySelector('#projectChatSuggest')?.hidden")
            assert page.locator("#projectChatSuggestList .project-chat-suggest-token").get_by_text("/btw").is_visible()
            page.keyboard.press("Escape")

            # Restore OpenCode for the remaining Project/session-scoping flow.
            page.select_option("#projectChatAgentSelect", "opencode")
            page.wait_for_function("document.querySelector('#projectChatAgentSelect')?.value === 'opencode'")
            page.select_option("#projectChatModelSelect", "openai/gpt-5.2")
            page.wait_for_function("document.querySelector('#projectChatReasoningSelect')?.querySelector('option[value=\\\"deep\\\"]') !== null")
            page.select_option("#projectChatReasoningSelect", "deep")
            page.select_option("#projectChatModeQuick", "read")
            page.wait_for_function("document.querySelector('#projectChatModeQuick')?.value === 'read'")
            assert page.locator("#projectChatSettingsPopover").is_visible()
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
            page.get_by_role("button", name="Edit Draft").click()
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            assert page.locator("#taskWorkspaceOverlay").is_visible()
            assert page.locator(".task-workspace-list-row").count() == 2
            chat_during = page.locator("#projectChatView").bounding_box()
            assert chat_before and chat_during
            assert abs(chat_before["x"] - chat_during["x"]) <= 1
            assert abs(chat_before["width"] - chat_during["width"]) <= 1

            page.locator(".task-workspace-row-edit").first.click()
            page.fill("#taskWorkspacePrompt", "Edited browser item one")
            page.click("#taskWorkspaceHeaderBack")
            page.wait_for_function("document.querySelectorAll('.task-workspace-list-row').length === 2")
            page.click("#taskWorkspaceSave")
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")
            assert page.locator(".project-chat-task-draft-item").first.get_by_text("Edited browser item one").is_visible()
            assert state.tasks.list(state.repo_root)["tasks"] == []

            page.get_by_role("button", name="Create Task", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")
            assert len(state.tasks.list(state.repo_root)["tasks"]) == 1
            assert state.tasks.list(state.repo_root)["tasks"][0]["status"] == "new"
            assert state._browser_last_task_create_draft["items"][0]["prompt"] == "Edited browser item one"
            assert state.tasks.list(state.repo_root)["tasks"][0]["items"][0]["prompt"] == "Edited browser item one"
            page.wait_for_function("!document.querySelector('#taskWorkspaceOverlay')?.hidden")
            assert page.locator("#taskWorkspaceEyebrow").inner_text() == "TASK INFO"
            assert page.locator(".task-workspace-tabs .task-workspace-tab").all_inner_texts() == [
                "Overview", "Runtime", "Output", "History",
            ]
            assert page.locator(".task-workspace-status-pill").inner_text() == "NEW"
            assert page.locator(".task-workspace-info-row").count() == 2
            page.get_by_role("button", name="Runtime", exact=True).click()
            assert page.locator(".task-workspace-empty-panel").get_by_text("No Runner runtime yet").is_visible()
            page.locator("#taskWorkspaceClose").click()
            page.wait_for_function("document.querySelector('#taskWorkspaceOverlay')?.hidden === true")

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
            page.get_by_role("button", name="Dismiss", exact=True).click()
            page.wait_for_function("document.querySelectorAll('.project-chat-task-draft').length === 0")
            assert len(state.tasks.list(state.repo_root)["tasks"]) == 1

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
            assert page.locator(".project-chat-ask-head").get_by_text("1 / 2").is_visible()

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
            page.wait_for_function("document.querySelectorAll('#projectChatSessionList .project-chat-session-row').length === 2")
            assert page.locator(".project-chat-ask").count() == 0
            assert page.locator("#projectChatQueue").is_hidden()
            assert page.locator("#projectChatAgentSelect").input_value() == "opencode"
            assert page.locator("#projectChatModeQuick").input_value() == "read"

            page.locator("#projectChatSessionList .project-chat-session-open").first.click()
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
            page.wait_for_function("document.querySelector('.project-chat-ask-head')?.textContent.includes('2 / 2')")
            assert page.get_by_role("button", name="Submit", exact=True).is_disabled()
            page.fill(".project-chat-ask-input[aria-label='Ask text answer']", "Browser reason")
            assert page.get_by_role("button", name="Submit", exact=True).is_enabled()
            page.get_by_role("button", name="Submit", exact=True).click()
            page.wait_for_function("document.querySelector('.project-chat-ask') === null")
            page.wait_for_function("document.querySelectorAll('#projectChatQueueList .project-chat-queue-item').length === 0")
            page.wait_for_function("document.querySelector('#projectChatMessages')?.textContent.includes('Browser queued reply · queued while ask 3')")
            queued_replies = page.locator("#projectChatMessages .message.assistant").all_inner_texts()
            queued_replies = [text for text in queued_replies if "Browser queued reply" in text]
            assert queued_replies[-3:] == [
                "Browser queued reply · queued while ask 1",
                "Browser queued reply · queued while ask 2 edited",
                "Browser queued reply · queued while ask 3",
            ]
            answered_ask = state.chat_service.ask(state.repo_root, state.chat_service.sessions(state.repo_root)["active_session_id"])["ask"]
            assert answered_ask["status"] == "answered"
            assert answered_ask["answers"]["approach"]["other"] == "Custom browser approach"
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
            page.wait_for_function("document.querySelectorAll('#projectChatSessionList .project-chat-session-row').length === 3")
            active_chat = page.locator("#projectChatSessionList .project-chat-session-row.active")
            active_chat.locator("button[title='Rename Chat']").click()
            page.locator(".ui-dialog-input").fill("Implementation Chat")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "Array.from(document.querySelectorAll('#projectChatSessionList .project-chat-session-open')).some((n) => n.textContent === 'Implementation Chat')"
            )
            active_chat = page.locator("#projectChatSessionList .project-chat-session-row.active")
            active_chat.locator("button[aria-label='Delete Chat']").click()
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function("document.querySelectorAll('#projectChatSessionList .project-chat-session-row').length === 1")

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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
            page.click("#themeButton")
            assert page.locator("#themePanel").is_visible()

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

            page.locator("[data-appearance-option='system']").click()
            page.locator("[data-theme-option='violet']").click()
            page.locator("[data-language-option='en']").click()
            page.wait_for_function("document.documentElement.dataset.appearancePreference === 'system'")
            page.wait_for_function("document.documentElement.dataset.theme === 'violet'")
            page.wait_for_function("document.documentElement.lang === 'en'")
            saved = state.global_settings.get()
            assert saved["interface"]["appearance"] == "system"
            assert saved["interface"]["theme"] == "violet"
            assert saved["language"] == "en"
            page.click("#themeCloseButton")
            assert page.locator("#themePanel").is_hidden()

            page.locator("#projectList .project-root").filter(has_text="Second Project").click()
            page.wait_for_function("document.querySelector('#projectChatName')?.textContent === 'Second Project'")
            assert page.locator("html").get_attribute("data-theme") == "violet"
            assert page.locator("html").get_attribute("data-appearance-preference") == "system"

            input_box = page.locator("#projectChatInput")
            input_box.fill("short")
            compact_height = input_box.evaluate("(node) => node.getBoundingClientRect().height")
            assert 45 <= compact_height <= 48
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

            page.reload(wait_until="domcontentloaded")
            install(page, "Second Project")
            assert page.locator("html").get_attribute("data-theme") == "violet"
            assert page.locator("html").get_attribute("data-appearance-preference") == "system"
            assert page.locator("html").get_attribute("data-appearance") == "dark"
            assert page.locator("html").get_attribute("lang") == "en"
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
        workflow = str(root / "runner" / "assets" / "workflows" / "ralphy_ai_validate.yaml")
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
            page.select_option("#globalDefaultAgent", "opencode")
            page.fill("#globalDefaultModel", "openai/gpt-5.2")
            page.locator("#globalDefaultModel").press("Tab")
            page.select_option("#globalDefaultMode", "read")
            page.select_option("#globalDefaultReasoning", "high")
            page.fill("#globalDefaultWorkflow", workflow)
            page.locator("#globalDefaultWorkflow").press("Tab")
            page.wait_for_function(
                """() => document.querySelector('#globalDefaultAgent')?.value === 'opencode'
                    && document.querySelector('#globalDefaultMode')?.value === 'read'"""
            )
            defaults = state.global_settings.get()["defaults"]
            assert defaults == {
                "agent": "opencode",
                "model": "openai/gpt-5.2",
                "mode": "read",
                "reasoning": "high",
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
                "document.querySelectorAll('#projectChatSessionList .project-chat-session-row').length === 2"
            )
            second_session = state.chat_service.sessions(added_project)["active_session_id"]
            assert second_session != first_session
            assert page.locator("#projectChatAgentSelect").input_value() == "opencode"
            assert page.locator("#projectChatModeQuick").input_value() == "read"

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
            assert state.chat_service.sessions(added_project)["active_session_id"] == second_session

            page.reload(wait_until="domcontentloaded")
            install(page, "Renamed Default Project")
            page.wait_for_function(
                "() => document.querySelector('#projectChatName')?.textContent === 'Renamed Default Project'"
            )
            assert page.locator("#projectChatAgentSelect").input_value() == "opencode"
            assert page.locator("#projectChatModeQuick").input_value() == "read"
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
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
            for css in sorted((static_root / "css").glob("*.css")):
                page.add_style_tag(path=str(css))
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
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
