from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "ui" / "static"
BROWSER_REQUIRED = os.environ.get("AI_TASK_RUNNER_BROWSER_REQUIRED") == "1"


def _browser_unavailable() -> bool:
    return sync_playwright is None or not BROWSER_REQUIRED


def _chromium_executable() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and Path(configured).exists():
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


@pytest.mark.skipif(_browser_unavailable(), reason="browser E2E is optional locally")
def test_future_chat_task_and_task_list_browser_contract():
    project = str(ROOT)
    chats = [{
        "chat_id": "a" * 32,
        "root_path": project,
        "title": "Fixture Chat",
        "path_available": True,
        "archived": False,
    }]
    messages = [{"message_id": "m1", "role": "user", "text": "Refactor backend safely"}]
    tasks: list[dict] = []
    created_payloads: list[dict] = []
    actions: list[str] = []

    def runtime_for(task_type: str = "single", status: str = "running") -> dict:
        running = status == "running"
        runtime = {
            "status": status,
            "running": running,
            "completed": status == "completed",
            "stage": "execute" if running else "",
            "cycle": 1,
            "completed_count": 0,
            "total": 1,
            "actions": {
                "stop": running,
                "resume": status == "stopped",
                "rerun": status == "completed",
                "run": status in {"completed", "idle"},
            },
        }
        if task_type == "sequential":
            runtime.update({"script_index": 2, "script_total": 2})
        return runtime

    def make_task(body: dict) -> dict:
        task_type = body.get("task_type", "single")
        task_id = ("b" if task_type == "single" else "c") * 32
        items = body.get("items", [])
        execution = {
            "request_id": "req-1" if task_type == "single" else "",
            "run_id": "run-1" if task_type == "single" else "",
            "instruction": body.get("instruction") or "Task List",
            "started_at": 1_700_000_000,
        }
        if task_type == "sequential":
            execution["children"] = [
                {"index": 1, "run_id": "child-1", "completed": True, "stage": "done", "last_error": "", "result": "child one result"},
                {"index": 2, "run_id": "child-2", "completed": False, "stage": "execute", "last_error": "", "result": ""},
            ]
        return {
            "task_id": task_id,
            "chat_id": chats[0]["chat_id"],
            "root_path": project,
            "source_root_path": project,
            "workspace_kind": "main",
            "workspace_branch": "",
            "workspace_managed": False,
            "title": body.get("title") or (body.get("instruction") or (items[0]["instruction"] if items else "Task"))[:80],
            "task_type": task_type,
            "instruction": body.get("instruction") or "Task List",
            "workflow": str(ROOT / "runner/assets/workflows/ralphy_ai_validate.yaml"),
            "items": items,
            "created_at": 1_700_000_000,
            "updated_at": 1_700_000_010,
            "executions": [execution],
            "last_status": "running",
            "last_error": "",
            "path_available": True,
            "runtime": runtime_for(task_type),
            "owns_runtime": True,
            "history": [],
        }

    def handler(route):
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path in {"/chats.html", "/library.html", "/settings.html"}:
            return route.fulfill(status=200, content_type="text/html", body=(STATIC / path.lstrip("/")).read_text(encoding="utf-8"))
        if path in {"/js/chats-workspace.js", "/js/library.js", "/js/settings.js"}:
            return route.fulfill(status=200, content_type="text/javascript", body=(STATIC / path.lstrip("/")).read_text(encoding="utf-8"))
        if path == "/js/i18n.js":
            return route.fulfill(status=200, content_type="text/javascript", body=(STATIC / "js/i18n.js").read_text(encoding="utf-8"))
        if path == "/styles.css":
            return route.fulfill(status=200, content_type="text/css", body=(STATIC / "styles.css").read_text(encoding="utf-8"))
        if path.startswith("/css/"):
            css = (STATIC / path.lstrip("/")).resolve()
            css.relative_to(STATIC.resolve())
            return route.fulfill(status=200, content_type="text/css", body=css.read_text(encoding="utf-8"))

        body = json.loads(request.post_data or "{}") if request.method == "POST" else {}
        data: dict
        if request.method == "GET" and path == "/api/projects":
            data = {"projects": [{"name": "Fixture Project", "path": project, "exists": True}]}
        elif request.method == "GET" and path == "/api/chats":
            data = {"chats": chats}
        elif request.method == "GET" and path == "/api/chats/messages":
            data = {"chat": chats[0], "messages": messages}
        elif request.method == "GET" and path == "/api/tasks":
            chat_id = query.get("chat_id", [""])[0]
            data = {"tasks": [task for task in tasks if not chat_id or task["chat_id"] == chat_id]}
        elif request.method == "GET" and path == "/api/task":
            task_id = query.get("task_id", [""])[0]
            data = next(task for task in tasks if task["task_id"] == task_id)
        elif request.method == "GET" and path == "/api/workspaces":
            data = {"git_available": False, "path_available": True, "workspaces": [{
                "kind": "main", "path": project, "branch": "", "is_main": True, "busy": False,
                "owner_task_id": "", "owner_chat_id": "", "owner_title": "",
            }]}
        elif request.method == "GET" and path == "/api/studio/files":
            data = {"workflows": [{
                "id": "global:workflow:ralphy_ai_validate.yaml",
                "name": "ralphy_ai_validate.yaml",
                "path": str(ROOT / "runner/assets/workflows/ralphy_ai_validate.yaml"),
                "kind": "workflow", "scope": "global", "hidden": False,
            }], "prompts": []}
        elif request.method == "GET" and path == "/api/backends":
            data = {"backends": ["fake"], "default": "fake", "models": {"fake": ["fake-model"]}}
        elif request.method == "POST" and path == "/api/chats/turn":
            user = {"message_id": "m2", "role": "user", "text": body["message"]}
            assistant = {"message_id": "m3", "role": "assistant", "text": "Read-only answer"}
            messages.extend([user, assistant])
            data = {"chat": chats[0], "user": user, "assistant": assistant}
        elif request.method == "POST" and path == "/api/tasks/create":
            created_payloads.append(body)
            task = make_task(body)
            tasks[:] = [existing for existing in tasks if existing["task_id"] != task["task_id"]]
            tasks.append(task)
            data = task
        elif request.method == "POST" and path == "/api/tasks/action":
            actions.append(body["action"])
            task = next(task for task in tasks if task["task_id"] == body["task_id"])
            if body["action"] == "stop":
                task["runtime"] = runtime_for(task["task_type"], "stopped")
                task["last_status"] = "stopped"
            elif body["action"] == "resume":
                task["runtime"] = runtime_for(task["task_type"], "running")
                task["last_status"] = "running"
            data = task
        elif request.method == "POST" and path == "/api/tasks/list/export":
            data = {"canonical": "- prompt: preview\n", "raw": [item.get("raw") or {"prompt": item["instruction"]} for item in body["items"]]}
        elif request.method == "POST" and path == "/api/tasks/list/parse":
            data = {"canonical": body["content"], "raw": [{"prompt": "preview"}]}
        elif request.method == "POST" and path == "/api/chats/task-list/suggest":
            data = {"items": [{"instruction": "First"}, {"instruction": "Second"}]}
        else:
            raise AssertionError(f"Unhandled {request.method} {path}")

        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    with sync_playwright() as playwright:
        kwargs = {"headless": True, "args": ["--no-sandbox"]}
        executable = _chromium_executable()
        if executable:
            kwargs["executable_path"] = executable
        browser = playwright.chromium.launch(**kwargs)
        page = browser.new_page()
        page.add_init_script("localStorage.setItem('ai-task-runner.language', 'en')")
        page.route("http://future.test/**", handler)
        page.goto("http://future.test/chats.html", wait_until="domcontentloaded")
        page.get_by_role("button", name="Fixture Chat").click()

        # Normal AI Chat turn.
        page.locator("#chatText").fill("Explain the architecture")
        page.locator("#chatSend").click()
        page.get_by_text("Read-only answer").wait_for()

        # AI-assisted Task List creation is preview-only until the user explicitly runs it.
        page.locator(".chat-bubble-actions").first.get_by_role("button", name="Create Task List", exact=True).click()
        preview_rows = page.locator(".task-list-item textarea")
        page.wait_for_function(
            """() => {
                const rows = [...document.querySelectorAll('.task-list-item textarea')];
                return rows.length === 2 && rows[0].value === 'First' && rows[1].value === 'Second';
            }"""
        )
        assert [preview_rows.nth(i).input_value() for i in range(2)] == ["First", "Second"]
        assert page.locator("#taskRun").is_enabled()
        assert "Valid YAML" in page.locator("#taskListYamlStatus").inner_text()
        assert created_payloads == []
        page.locator("#taskCancel").click()

        # One shared New Task form from a Chat message.
        page.locator(".chat-bubble-actions").first.get_by_role("button", name="Create Task", exact=True).click()
        page.locator("#taskInstruction").wait_for()
        assert page.locator("#taskInstruction").input_value() == "Refactor backend safely"
        page.locator("#taskRun").click()
        page.get_by_role("button", name="Stop").wait_for()
        assert created_payloads[-1]["task_type"] == "single"
        assert "chat=" in page.url and "task=" in page.url

        # Stop and Resume map to canonical actions.
        page.get_by_role("button", name="Stop").click()
        page.get_by_role("button", name="Resume").wait_for()
        page.get_by_role("button", name="Resume").click()
        page.get_by_role("button", name="Stop").wait_for()
        assert actions[:2] == ["stop", "resume"]

        # Stable Chat/Task identities restore the same Task Detail after refresh.
        page.reload(wait_until="domcontentloaded")
        page.get_by_role("heading", name="Refactor backend safely").wait_for()
        assert page.locator("#tasksTab").get_attribute("aria-selected") == "true"
        assert "chat=" in page.url and "task=" in page.url

        # Task List uses the same form and preserves manual order.
        page.locator("#newTask").click()
        page.locator("#taskType").select_option("sequential")
        rows = page.locator(".task-list-item")
        rows.nth(0).locator("textarea").fill("One")
        page.locator("#addTaskListItem").click()
        rows = page.locator(".task-list-item")
        rows.nth(1).locator("textarea").fill("Two")
        rows.nth(1).get_by_title("Move up").click()
        page.locator("#taskRun").click()
        page.get_by_text("Ordered Task List").wait_for()
        assert [item["instruction"] for item in created_payloads[-1]["items"]] == ["Two", "One"]
        assert created_payloads[-1]["task_type"] == "sequential"

        # Sequential Stop / Resume uses the same canonical Task action surface.
        page.get_by_role("button", name="Stop").click()
        page.get_by_role("button", name="Resume").wait_for()
        page.get_by_role("button", name="Resume").click()
        page.get_by_role("button", name="Stop").wait_for()
        assert actions[-2:] == ["stop", "resume"]

        # Child evidence opens in the existing Task Detail surface.
        page.get_by_role("button", name="1. Two Completed").click()
        page.get_by_text("Item 1 evidence").wait_for()
        page.get_by_text("child one result", exact=True).wait_for()

        for viewport in ({"width": 720, "height": 720}, {"width": 480, "height": 720}):
            page.set_viewport_size(viewport)
            page.wait_for_timeout(50)
            width = page.evaluate("() => ({client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})")
            assert width["scroll"] <= width["client"] + 1

        # Global Library and Settings shells stay usable at low resolution too.
        page.set_viewport_size({"width": 480, "height": 720})
        page.goto("http://future.test/library.html", wait_until="domcontentloaded")
        page.get_by_text("ralphy_ai_validate.yaml", exact=True).wait_for()
        width = page.evaluate("() => ({client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})")
        assert width["scroll"] <= width["client"] + 1
        page.locator("#promptLibraryTab").click()
        page.get_by_role("button", name="Open Prompt editor").wait_for()

        page.goto("http://future.test/settings.html", wait_until="domcontentloaded")
        page.get_by_role("heading", name="Settings").wait_for()
        width = page.evaluate("() => ({client: document.documentElement.clientWidth, scroll: document.documentElement.scrollWidth})")
        assert width["scroll"] <= width["client"] + 1

        browser.close()
