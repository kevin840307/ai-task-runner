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
CHROME = Path(os.environ.get("CHROMIUM_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe"))


@pytest.mark.skipif(sync_playwright is None or not CHROME.is_file(), reason="Playwright/Chrome unavailable")
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
            browser = playwright.chromium.launch(headless=True, executable_path=str(CHROME))
            page = browser.new_page(viewport={"width": 1600, "height": 960})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            files = page.request.get(f"http://127.0.0.1:{port}/api/studio/files").json()
            file_id = next(item["id"] for item in files["workflows"] if item["name"] == "file.yaml")
            page.goto(f"http://127.0.0.1:{port}/workflow-studio-app/index.html?id={quote(file_id)}")
            page.locator('.react-flow__node[data-id="review"]').wait_for()
            assert page.locator(".react-flow__node-scope").count() == 1

            page.locator('.react-flow__node[data-id="review"]').click()
            page.get_by_role("tab", name="連線").click()
            assert "END（停止）" in page.locator(".route-row").nth(2).inner_text()

            page.get_by_role("tab", name="基本").click()
            page.get_by_text("執行範圍").locator("..").locator("select").select_option("")
            page.locator('.react-flow__node[data-id="execute"]').click()
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
