"""Browser regression for formerly unreferenced UI modal actions."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from ui.tests.test_browser_crud_e2e import (
    _browser_unavailable,
    _bridge_for,
    _boot_main_ui,
    _install_main_ui_scripts,
    _install_main_ui_styles,
    _launch_browser,
    _load_main_ui_document,
    _write_fixture_repo,
    BROWSER_DEFAULT_TIMEOUT_MS,
    sync_playwright,
)


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_project_modal_cancel_close_and_settings_done_use_real_click_handlers() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        base_bridge = _bridge_for(state)
        picked = str(Path(td) / "selected-only-not-added")

        def bridge(method: str, url: str, body_json: str):
            if method == "POST" and urlparse(url).path == "/api/projects/pick":
                return {"status": 200, "data": {"cancelled": False, "path": picked}}
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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

            for close_button in ("#projectModalCancel", "#projectModalClose"):
                page.click("#openProject")
                page.locator("#projectModalBackdrop").wait_for(state="visible")
                page.click("#browseProjectButton")
                page.wait_for_function(
                    "(path) => document.querySelector('#projectPathInput')?.value === path",
                    arg=picked,
                )
                page.click(close_button)
                page.locator("#projectModalBackdrop").wait_for(state="hidden")
                assert page.locator("#projectPathInput").count() == 1
                assert len(state.projects()) == 1

            page.click("#themeButton")
            page.locator("#themePanel").wait_for(state="visible")
            page.click("#themeDoneButton")
            page.locator("#themePanel").wait_for(state="hidden")
            assert page.locator("#themeButton").get_attribute("aria-expanded") == "false"
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_chat_suggestion_error_retry_recovers_real_command_options() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        control = {"fail": True, "calls": 0}
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            if method == "GET" and urlparse(url).path == "/api/chat/capabilities":
                control["calls"] += 1
                if control["fail"]:
                    return {
                        "status": 503,
                        "data": {
                            "code": "backend_unavailable",
                            "message": "Injected capability discovery failure",
                            "retryable": True,
                        },
                    }
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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
            page.fill("#projectChatInput", "/bt")
            page.wait_for_function(
                "!document.querySelector('#projectChatSuggestRetry')?.hidden"
            )
            assert "Injected capability discovery failure" in page.locator(
                "#projectChatSuggestList"
            ).inner_text()
            calls_before = control["calls"]
            control["fail"] = False
            page.click("#projectChatSuggestRetry")
            page.wait_for_function(
                "() => document.querySelector('#projectChatSuggestRetry')?.hidden "
                "&& [...document.querySelectorAll('#projectChatSuggestList .project-chat-suggest-token')]"
                ".some(node => node.textContent.includes('/btw'))"
            )
            assert control["calls"] > calls_before
            assert page.locator("#projectChatSuggestRetry").is_hidden()
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_runtime_error_details_copy_ok_and_close_are_clickable() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            if method == "GET" and urlparse(url).path == "/api/environment/check":
                return {
                    "status": 503,
                    "data": {
                        "code": "environment_unavailable",
                        "message": "Environment failed on line one\nDetailed runtime diagnostic on line two",
                        "retryable": True,
                    },
                }
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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
                };
                Object.defineProperty(navigator, 'clipboard', {
                    configurable: true,
                    value: {
                        writeText: async (text) => { window.__copiedRuntimeError = String(text); }
                    }
                });"""
            )
            _install_main_ui_styles(page, static_root)
            _install_main_ui_scripts(page, static_root)
            _boot_main_ui(page)

            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.click("#optionsButton")
            page.wait_for_function("document.querySelector('#optionsPanel')?.hidden === false")
            page.click("#environmentCheckButton")
            page.wait_for_function(
                "() => !document.querySelector('#errorDetailsButton')?.hidden"
            )
            assert page.locator("#errorDetailsButton").is_visible()
            assert "Environment failed on line one" in page.locator(
                "#environmentCheckResult"
            ).inner_text()

            page.click("#errorDetailsButton")
            assert page.locator("#errorDetailsBackdrop").is_visible()
            assert "Detailed runtime diagnostic on line two" in page.locator(
                "#errorDetailsContent"
            ).inner_text()
            page.click("#errorDetailsCopy")
            page.wait_for_function(
                "() => window.__copiedRuntimeError?.includes('Detailed runtime diagnostic')"
            )
            page.click("#errorDetailsOk")
            assert page.locator("#errorDetailsBackdrop").is_hidden()

            page.click("#errorDetailsButton")
            assert page.locator("#errorDetailsBackdrop").is_visible()
            page.click("#errorDetailsClose")
            assert page.locator("#errorDetailsBackdrop").is_hidden()
            assert errors == []
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_primary_runtime_controls_history_and_guidance_use_real_click_handlers() -> None:
    """Exercise the legacy/current-runtime surface instead of only Task-card controls."""
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        actions: list[tuple[str, dict]] = []
        state._browser_runtime_override = {
            "status": "idle",
            "view": {"label": "Ready"},
            "actions": {
                "run": True, "stop": False, "resume": False,
                "reset": False, "rerun": False,
            },
            "running": False,
            "completed": False,
            "resumable": False,
            "stale": False,
            "has_state": False,
            "task": "",
            "stage": "",
            "cli_status": "",
            "completed_count": 0,
            "total": 0,
            "run_id": "",
        }
        base_bridge = _bridge_for(state)

        def runtime(status: str) -> dict:
            if status == "running":
                return {
                    "status": "running",
                    "view": {"label": "Running"},
                    "actions": {
                        "run": False, "stop": True, "resume": False,
                        "reset": False, "rerun": False,
                    },
                    "running": True,
                    "completed": False,
                    "resumable": False,
                    "stale": False,
                    "has_state": True,
                    "task": "Browser runtime controls",
                    "stage": "execute",
                    "cli_status": "execute",
                    "completed_count": 0,
                    "total": 1,
                    "run_id": "browser-runtime-controls",
                    "started_at": 1,
                }
            if status == "stopped":
                return {
                    "status": "stopped",
                    "view": {"label": "Stopped", "reason": "Browser stop requested"},
                    "attention_reason": "Browser stop requested",
                    "recommended_actions": ["resume", "reset", "open_workflow"],
                    "actions": {
                        "run": False, "stop": False, "resume": True,
                        "reset": True, "rerun": False,
                    },
                    "running": False,
                    "completed": False,
                    "resumable": True,
                    "stale": False,
                    "has_state": True,
                    "task": "Browser runtime controls",
                    "stage": "execute",
                    "cli_status": "stopped",
                    "completed_count": 0,
                    "total": 1,
                    "run_id": "browser-runtime-controls",
                    "started_at": 1,
                }
            return {
                "status": "idle",
                "view": {"label": "Ready"},
                "actions": {
                    "run": True, "stop": False, "resume": False,
                    "reset": False, "rerun": False,
                },
                "running": False,
                "completed": False,
                "resumable": False,
                "stale": False,
                "has_state": False,
                "task": "",
                "stage": "",
                "cli_status": "",
                "completed_count": 0,
                "total": 0,
                "run_id": "",
            }

        def bridge(method: str, url: str, body_json: str):
            path = urlparse(url).path
            body = json.loads(body_json or "{}")
            if method == "POST" and path in {
                "/api/project/message",
                "/api/project/stop",
                "/api/project/resume",
                "/api/project/reset",
                "/api/project/history/clear",
            }:
                actions.append((path, body))
                if path == "/api/project/message":
                    state._browser_runtime_override = runtime("running")
                elif path == "/api/project/stop":
                    state._browser_runtime_override = runtime("stopped")
                elif path == "/api/project/resume":
                    state._browser_runtime_override = runtime("running")
                elif path == "/api/project/reset":
                    state._browser_runtime_override = runtime("idle")
                return {"status": 200, "data": {"ok": True}}
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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

            # The main navigation lands on Tasks. Open the explicit current-runtime
            # surface before interacting with the legacy/current Runner controls.
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.wait_for_function(
                "() => !document.querySelector('#sendButton')?.disabled "
                "&& !document.querySelector('#sendButton')?.hidden"
            )
            page.fill("#messageInput", "Run the browser runtime-control check")
            page.click("#sendButton")
            page.wait_for_function("!document.querySelector('#stopButton')?.hidden")
            assert actions[-1][0] == "/api/project/message"
            assert actions[-1][1]["message"] == "Run the browser runtime-control check"

            page.click("#stopButton")
            page.wait_for_function("!document.querySelector('#resumeButton')?.hidden")
            page.wait_for_function("!document.querySelector('#resetButton')?.hidden")
            page.wait_for_function("!document.querySelector('#runtimeGuidanceWorkflow')?.hidden")
            assert actions[-1][0] == "/api/project/stop"

            # Guidance is an actual navigation action, not only rendered text.
            page.click("#runtimeGuidanceWorkflow")
            page.wait_for_function("!document.querySelector('#workflowView')?.hidden")
            assert page.locator("#workflowView").is_visible()

            # Return to the current Runtime and prove Resume -> Stop -> Reset.
            page.click("#chatNav")
            page.wait_for_function("!document.querySelector('#tasksBoardView')?.hidden")
            page.click("#tasksCurrentRuntimeButton")
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.click("#resumeButton")
            page.wait_for_function("!document.querySelector('#stopButton')?.hidden")
            assert actions[-1][0] == "/api/project/resume"

            page.click("#stopButton")
            page.wait_for_function("!document.querySelector('#resetButton')?.hidden")
            stop_count = sum(1 for path, _ in actions if path == "/api/project/stop")
            assert stop_count == 2

            page.click("#resetButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-cancel]").click()
            assert not any(path == "/api/project/reset" for path, _ in actions)

            page.click("#resetButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "() => !document.querySelector('#sendButton')?.hidden "
                "&& !document.querySelector('#sendButton')?.disabled"
            )
            assert actions[-1][0] == "/api/project/reset"

            # Clear History also owns a destructive confirmation and backend action.
            page.click("#clearHistoryButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-cancel]").click()
            assert not any(path == "/api/project/history/clear" for path, _ in actions)

            page.click("#clearHistoryButton")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "() => document.querySelector('.ui-dialog-card') === null "
                "|| document.querySelector('.ui-dialog-card')?.parentElement?.hidden"
            )
            assert actions[-1][0] == "/api/project/history/clear"
            assert actions[-1][1]["reset_stopped"] is False
            assert errors == []
            browser.close()


@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_empty_state_open_project_button_opens_the_real_project_modal() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        state._write_projects([])
        base_bridge = _bridge_for(state)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.expose_function("__apiBridge", base_bridge)
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
            page.wait_for_function("!document.querySelector('#chatView')?.hidden")
            page.wait_for_function("!document.querySelector('#emptyState')?.hidden")
            page.click("#emptyOpenProjectButton")
            page.locator("#projectModalBackdrop").wait_for(state="visible")
            assert page.locator("#projectModalBackdrop").is_visible()
            page.click("#projectModalCancel")
            page.locator("#projectModalBackdrop").wait_for(state="hidden")
            assert errors == []
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_workflow_library_context_open_rename_duplicate_export_delete_actions() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        state = _write_fixture_repo(root)
        created = state.studio_workflow_create("context_actions", "global", None)
        workflow_id = created["item"]["id"]
        exports = []
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            parsed = urlparse(url)
            if method == "GET" and parsed.path == "/api/studio/export":
                query = parse_qs(parsed.query)
                item_id = query.get("id", [""])[0]
                exports.append(item_id)
                return {
                    "status": 200,
                    "data": state.studio_export(item_id, None),
                }
            return base_bridge(method, url, body_json)

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820}, accept_downloads=True)
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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
            page.wait_for_function(
                "document.querySelector('#workflowNav')?.classList.contains('active')"
            )

            def workflow_row(name: str):
                return page.locator("#studioFileList .studio-file-item").filter(
                    has_text=name
                )

            row = workflow_row("context_actions.workflow.yaml")
            row.wait_for()

            # Rename uses the right-click action and shared input dialog.
            row.click(button="right")
            page.click("#workflowContextRename")
            page.locator(".ui-dialog-input").fill("context_renamed")
            page.locator("[data-dialog-ok]").click()
            renamed = workflow_row("context_renamed.workflow.yaml")
            renamed.wait_for()
            assert workflow_row("context_actions.workflow.yaml").count() == 0

            # Duplicate creates an independent Workflow through the context action.
            renamed.click(button="right")
            page.click("#workflowContextDuplicate")
            page.locator(".ui-dialog-input").fill("context_copy")
            page.locator("[data-dialog-ok]").click()
            copied = workflow_row("context_copy.workflow.yaml")
            copied.wait_for()
            assert copied.count() == 1

            # Export must execute the real API + browser download path.
            renamed.click(button="right")
            with page.expect_download() as download_info:
                page.click("#workflowContextExport")
            download = download_info.value
            assert download.suggested_filename == "context_renamed.workflow.yaml"
            renamed_item = next(
                item
                for item in state.studio_files(root)["workflows"]
                if item["name"] == "context_renamed.workflow.yaml"
            )
            assert exports == [renamed_item["id"]]

            # Delete is destructive: cancel keeps the asset, confirm removes it.
            copied.click(button="right")
            page.click("#workflowContextDelete")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-cancel]").click()
            assert copied.count() == 1

            copied.click(button="right")
            page.click("#workflowContextDelete")
            page.locator(".ui-dialog-card").wait_for(state="visible")
            page.locator("[data-dialog-ok]").click()
            page.wait_for_function(
                "() => ![...document.querySelectorAll('#studioFileList .studio-file-item')]"
                ".some(node => node.textContent.includes('context_copy.workflow.yaml'))"
            )

            # Open is a navigation action into the real Workflow Editor route.
            renamed = workflow_row("context_renamed.workflow.yaml")
            renamed.click(button="right")
            page.click("#workflowContextOpen")
            page.wait_for_url("**/workflow-studio-app/index.html?*")
            assert page.get_by_text("Workflow Editor", exact=True).is_visible()
            assert errors == []
            browser.close()



@pytest.mark.skipif(
    _browser_unavailable(),
    reason="Playwright/Chromium unavailable outside browser CI",
)
def test_empty_workflow_and_prompt_library_create_ctas_open_real_modals() -> None:
    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        base_bridge = _bridge_for(state)

        def bridge(method: str, url: str, body_json: str):
            parsed = urlparse(url)
            response = base_bridge(method, url, body_json)
            if method == "GET" and parsed.path == "/api/studio/files":
                data = dict(response["data"])
                data["workflows"] = []
                data["prompts"] = []
                return {"status": response["status"], "data": data}
            return response

        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = html.replace("<head>", '<head><base href="http://local.test/">', 1)
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1366, "height": 820})
            page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
            errors = []
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

            page.click("#promptNav")
            page.wait_for_function(
                "document.querySelector('#promptNav')?.classList.contains('active')"
            )
            create_prompt = page.locator(
                ".studio-empty-action", has_text="Create Prompt"
            )
            create_prompt.wait_for(state="visible")
            create_prompt.click()
            page.locator("#newPromptBackdrop").wait_for(state="visible")
            assert page.locator("#newPromptName").is_visible()
            page.click("#newPromptCancel")
            page.locator("#newPromptBackdrop").wait_for(state="hidden")

            page.click("#workflowNav")
            page.wait_for_function(
                "document.querySelector('#workflowNav')?.classList.contains('active')"
            )
            create_workflow = page.locator(
                ".studio-empty-action", has_text="Create Workflow"
            )
            create_workflow.wait_for(state="visible")
            create_workflow.click()
            page.locator("#newWorkflowBackdrop").wait_for(state="visible")
            assert page.locator("#newWorkflowName").is_visible()
            page.click("#newWorkflowCancel")
            page.locator("#newWorkflowBackdrop").wait_for(state="hidden")

            assert errors == []
            browser.close()
