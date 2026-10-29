"""Browser regression for formerly unreferenced UI modal actions."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from urllib.parse import urlparse

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
