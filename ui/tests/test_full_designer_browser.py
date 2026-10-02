"""Browser smoke check for the built Full Designer against the real local UI."""
from __future__ import annotations

import os
import socket
import threading
from pathlib import Path
from urllib.parse import quote

import pytest

from ui.server import UIServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[2]
BROWSER_REQUIRED = os.environ.get("AI_TASK_RUNNER_BROWSER_REQUIRED") == "1"


def _system_browser() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and Path(configured).is_file():
        return configured
    default_windows = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if default_windows.is_file():
        return str(default_windows)
    return None


def _browser_unavailable() -> bool:
    return sync_playwright is None or (not BROWSER_REQUIRED and _system_browser() is None)


def _launch_browser(playwright):
    executable = _system_browser()
    if executable:
        return playwright.chromium.launch(headless=True, executable_path=executable)
    return playwright.chromium.launch(headless=True)


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_full_designer_scope_routes_and_draft_do_not_write_yaml() -> None:
    workflow = ROOT / "runner" / "assets" / "workflows" / "file.yaml"
    original = workflow.read_bytes()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = UIServer(ROOT, "127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport={"width": 1600, "height": 960})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            files = page.request.get(f"http://127.0.0.1:{port}/api/studio/files").json()
            file_id = next(item["id"] for item in files["workflows"] if item["name"] == "file.yaml")
            page.goto(f"http://127.0.0.1:{port}/workflow-studio-app/index.html?id={quote(file_id)}")
            page.locator('.react-flow__node[data-id="review"]').wait_for()
            assert page.locator(".react-flow__node-scope").count() == 1

            page.locator('.react-flow__node[data-id="review"]').dblclick()
            page.get_by_role("tab", name="連線").click()
            assert "END（停止）" in page.locator(".route-row").nth(2).inner_text()

            page.get_by_role("tab", name="基本").click()
            page.get_by_text("執行範圍").locator("..").locator("select").select_option("")
            page.get_by_role("button", name="Close").click()
            page.locator('.react-flow__node[data-id="execute"]').dblclick()
            page.get_by_text("執行範圍").locator("..").locator("select").select_option("")
            assert page.locator(".react-flow__node-scope").count() == 0
            review_palette = page.locator(".palette-item").filter(has_text="Review")
            review_palette.click()
            assert page.locator('.react-flow__node[data-id="review_2"]').count() == 0
            review_palette.drag_to(page.locator(".canvas"), target_position={"x": 450, "y": 300})
            page.locator('.react-flow__node[data-id="review_2"]').wait_for()
            page.get_by_text("積木標題（雙擊積木可重新命名）").locator("..").locator("input").fill("Second review")
            assert page.locator('.react-flow__node[data-id="review_2"]').get_by_text("Second review").is_visible()
            assert page.get_by_text("未儲存草稿").is_visible()
            assert workflow.read_bytes() == original
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)



@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
@pytest.mark.parametrize("viewport", [
    {"width": 1024, "height": 768},
    {"width": 1280, "height": 800},
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1920, "height": 1080},
])
def test_full_designer_common_desktop_viewports_do_not_overflow(viewport) -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = UIServer(ROOT, "127.0.0.1", port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            page = browser.new_page(viewport=viewport)
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            files = page.request.get(f"http://127.0.0.1:{port}/api/studio/files").json()
            file_id = next(item["id"] for item in files["workflows"] if item["name"] == "file.yaml")
            page.goto(f"http://127.0.0.1:{port}/workflow-studio-app/index.html?id={quote(file_id)}")
            page.locator('.react-flow__node[data-id="review"]').wait_for()

            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            palette = page.locator(".palette").bounding_box()
            canvas = page.locator(".canvas").bounding_box()
            assert palette and palette["x"] >= 0 and palette["x"] + palette["width"] <= viewport["width"]
            assert canvas and canvas["x"] >= 0 and canvas["x"] + canvas["width"] <= viewport["width"] + 1

            page.locator('.react-flow__node[data-id="review"]').dblclick()
            modal = page.locator(".stage-editor-modal").bounding_box()
            assert modal
            assert modal["x"] >= 0 and modal["y"] >= 0
            assert modal["x"] + modal["width"] <= viewport["width"] + 1
            assert modal["y"] + modal["height"] <= viewport["height"] + 1

            stage_yaml_tab = page.get_by_role("tab", name="YAML").last
            stage_yaml_tab.click()
            page.locator(".stage-yaml-panel textarea").wait_for()
            stage_yaml_box = page.locator(".stage-yaml-panel textarea").bounding_box()
            assert stage_yaml_box
            assert stage_yaml_box["x"] >= modal["x"]
            assert stage_yaml_box["x"] + stage_yaml_box["width"] <= modal["x"] + modal["width"] + 1
            assert stage_yaml_box["y"] + stage_yaml_box["height"] <= modal["y"] + modal["height"] + 1
            page.get_by_role("button", name="Close").click()

            page.locator('.react-flow__node[data-id="review"]').dispatch_event(
                "contextmenu",
                {"clientX": viewport["width"] - 2, "clientY": viewport["height"] - 2, "button": 2},
            )
            menu = page.locator(".stage-context-menu").bounding_box()
            assert menu
            assert menu["x"] >= 0 and menu["y"] >= 0
            assert menu["x"] + menu["width"] <= viewport["width"] + 1
            assert menu["y"] + menu["height"] <= viewport["height"] + 1
            page.keyboard.press("Escape")

            page.get_by_role("tab", name="YAML").click()
            page.locator(".workflow-yaml-editor").wait_for()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            yaml_box = page.locator(".workflow-yaml-editor").bounding_box()
            assert yaml_box and yaml_box["x"] >= 0 and yaml_box["x"] + yaml_box["width"] <= viewport["width"] + 1
            assert not errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
