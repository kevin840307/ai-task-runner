"""Browser regression for formerly unreferenced UI modal actions."""
from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

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

            for close_button in ("#projectModalCancel", "#projectModalClose"):
                page.click("#openProject")
                page.locator("#projectModalBackdrop").wait_for(state="visible")
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
