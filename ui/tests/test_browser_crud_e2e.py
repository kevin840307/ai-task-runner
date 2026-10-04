from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

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
    for relative in ("app.js", "js/ui-lifecycle.js", "js/workflow-generator.js"):
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


def _boot_main_ui(page) -> None:
    # app.js performs its production bootstrap immediately as an ES module.
    page.wait_for_function(
        "document.querySelector('#projectName')?.textContent === 'Fixture Project'",
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
                if path == "/api/projects":
                    data = {"projects": state.projects()}
                elif path == "/api/project/messages":
                    data = {"messages": []}
                elif path == "/api/project/runs":
                    data = {"runs": state.run_history(project) if project is not None else []}
                elif path == "/api/project/runtime":
                    data = {
                        "running": False, "completed": False, "resumable": False,
                        "stage": "", "cli_status": "", "completed_count": 0, "total": 0,
                        "recent_transitions": [
                            {
                                "stage": "execute", "status": "pass", "target": "review",
                                "cycle": 1, "kind": "task", "timestamp": 1.0,
                            },
                            {
                                "stage": "review", "status": "fail", "target": "execute",
                                "cycle": 1, "kind": "review", "timestamp": 2.0,
                            },
                        ],
                    }
                elif path == "/api/workflow/catalog":
                    data = {"stage_types": {}, "node_options": {}}
                elif path == "/api/backends":
                    data = state.backend_catalog()
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
                if path == "/api/studio/prompt/create":
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
            # selectProject() only switched away from the Workflow view.
            page.locator("#projectList .project-root").first.click()
            page.wait_for_function("document.querySelector('#chatNav')?.classList.contains('active')")
            assert page.locator("#chatView").is_visible()
            assert page.locator("#workflowView").is_hidden()

            # Runtime Trace reuses bounded runtime evidence and remains mutually
            # exclusive with Recent Runs.
            assert page.locator("#runtimeTraceButton").is_visible()
            page.click("#runtimeTraceButton")
            assert page.locator("#runtimeTracePanel").is_visible()
            assert page.locator("#runtimeTraceList", has_text="review FAIL → execute").count() == 1
            assert page.locator("#runtimeTraceList", has_text="Cycle 1").count() >= 1
            assert page.locator("#runtimeTraceButton").get_attribute("aria-expanded") == "true"

            # Recent Runs is a lightweight derived view and must not require another
            # navigation surface or history store.
            page.click("#runHistoryButton")
            assert page.locator("#runtimeTracePanel").is_hidden()
            assert page.locator("#runtimeTraceButton").get_attribute("aria-expanded") == "false"
            assert page.locator("#runHistoryPanel").is_visible()
            assert page.locator("#runHistoryList", has_text="No runs yet.").count() == 1
            assert page.locator("#runHistoryButton").get_attribute("aria-expanded") == "true"
            page.click("#runHistoryClose")
            assert page.locator("#runHistoryPanel").is_hidden()
            assert page.locator("#runHistoryButton").get_attribute("aria-expanded") == "false"

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
            page.wait_for_function("document.querySelector('#promptView') && !document.querySelector('#promptView').hidden")
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
