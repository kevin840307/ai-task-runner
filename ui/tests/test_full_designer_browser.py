"""Browser smoke check for the built Full Designer against the real local UI."""
from __future__ import annotations

import os
import socket
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import pytest
import yaml

from ui.server import UIServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


ROOT = Path(__file__).resolve().parents[2]
BROWSER_REQUIRED = os.environ.get("AI_TASK_RUNNER_BROWSER_REQUIRED") == "1"
BROWSER_DEFAULT_TIMEOUT_MS = 8_000



def _system_browser() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and Path(configured).is_file():
        return configured
    default_windows = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    if default_windows.is_file():
        return str(default_windows)
    return None


def _browser_unavailable() -> bool:
    return sync_playwright is None or not BROWSER_REQUIRED


def _launch_browser(playwright):
    executable = _system_browser()
    if executable:
        return playwright.chromium.launch(headless=True, executable_path=executable)
    return playwright.chromium.launch(headless=True)


def _connect_nodes(page, source_selector: str, target_selector: str) -> None:
    source = page.locator(source_selector)
    target = page.locator(target_selector)
    source.scroll_into_view_if_needed()
    target.scroll_into_view_if_needed()
    start = source.bounding_box()
    end = target.bounding_box()
    assert start and end
    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=12)
    page.mouse.up()
    page.wait_for_timeout(120)


def _save_editor(page) -> None:
    button = page.locator(".studio-header button.primary")
    assert button.is_enabled()
    assert page.locator(".unsaved-badge").count() == 1
    button.click()
    try:
        page.locator(".unsaved-badge").wait_for(state="detached", timeout=8000)
    except Exception as error:
        message = page.locator(".studio-header .message").inner_text()
        raise AssertionError(f"Workflow save did not clear dirty state: {message}") from error
    assert button.is_disabled()


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_full_designer_ai_profiles_routes_and_draft_do_not_write_yaml() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-editor-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "editor-e2e.yaml"
        workflow.write_text(
            """stages:
  execute:
    type: base
    profile: execute
  review:
    type: base
    profile: review
    error_policy:
      retries: 2
    max_failures: 3
    routes:
      fail: execute
flow:
  - execute
  - review
""",
            encoding="utf-8",
        )
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
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(f"http://127.0.0.1:{port}/api/studio/files?project={project_q}").json()
                file_id = next(item["id"] for item in files["workflows"] if item["name"] == "editor-e2e.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(file_id)}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                assert page.locator(".react-flow__node-scope").count() == 0

                page.locator('.react-flow__node[data-id="review"]').dblclick()
                assert page.get_by_text("AI profile").is_visible()
                assert page.get_by_text("執行範圍").count() == 0
                page.get_by_role("tab", name="連線").click()
                assert page.get_by_text("Semantic FAIL 上限").is_visible()
                page.locator(".modal-close-button").click()

                ai_palette = page.locator(".palette-item").filter(has_text="AI Stage").first
                ai_palette.locator(".palette-quick-add").click()
                create = page.locator(".create-stage-card")
                create.wait_for(state="attached")
                create.get_by_text("AI profile").locator("..").locator("select").select_option("review")
                create.get_by_role("button", name="Create Stage").click()
                page.locator('.react-flow__node[data-id="ai_stage"]').wait_for(state="attached")
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
    with tempfile.TemporaryDirectory(prefix="ai-runner-viewport-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "viewport-e2e.yaml"
        workflow.write_text(
            """stages:
  execute:
    type: base
    profile: execute
  review:
    type: base
    profile: review
    error_policy:
      retries: 2
    max_failures: 3
    routes:
      fail: execute
flow:
  - execute
  - review
""",
            encoding="utf-8",
        )
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
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(f"http://127.0.0.1:{port}/api/studio/files?project={project_q}").json()
                file_id = next(item["id"] for item in files["workflows"] if item["name"] == "viewport-e2e.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(file_id)}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")

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
                page.locator(".stage-yaml-panel textarea").wait_for(state="attached")
                stage_yaml_box = page.locator(".stage-yaml-panel textarea").bounding_box()
                yaml_content_box = page.locator(".stage-editor-content.yaml-mode").bounding_box()
                assert stage_yaml_box and yaml_content_box
                assert stage_yaml_box["x"] >= modal["x"]
                assert stage_yaml_box["x"] + stage_yaml_box["width"] <= modal["x"] + modal["width"] + 1
                assert stage_yaml_box["y"] + stage_yaml_box["height"] <= modal["y"] + modal["height"] + 1
                assert stage_yaml_box["height"] >= yaml_content_box["height"] * 0.72
                page.locator(".modal-close-button").click()

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
                page.locator(".workflow-yaml-editor").wait_for(state="attached")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                yaml_box = page.locator(".workflow-yaml-editor").bounding_box()
                assert yaml_box and yaml_box["x"] >= 0 and yaml_box["x"] + yaml_box["width"] <= viewport["width"] + 1
                assert not errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_full_designer_graph_crud_roundtrip() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-graph-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "graph-e2e.yaml"
        workflow.write_text(
            """stages:
  execute:
    type: base
    profile: execute
  review:
    type: base
    profile: review
    routes:
      fail: execute
  router:
    type: handoff
    targets: [worker]
  worker:
    type: command
    command:\n      - "{python}"\n      - "-c"\n      - "print(\'worker\')"
  after:
    type: command
    command:\n      - "{python}"\n      - "-c"\n      - "print(\'after\')"\nflow:
  - execute
  - review
  - router
  - worker
  - after
""",
            encoding="utf-8",
        )

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
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/files?project={project_q}"
                ).json()
                item = next(row for row in files["workflows"] if row["name"] == "graph-e2e.yaml")
                file_id = item["id"]
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(file_id)}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")

                # Existing explicit FAIL edge can be selected and removed with Delete.
                fail_edge = page.locator('.react-flow__edge[data-id="review:fail:execute"]')
                fail_edge.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert fail_edge.count() == 0
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert "routes" not in saved["stages"]["review"]

                page.reload()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")

                # Connect FAIL to END: FAIL terminal semantics must persist as stop.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="review"] .react-flow__handle.fail',
                    '.react-flow__node[data-id="__end__"] .react-flow__handle',
                )
                page.locator('.react-flow__edge[data-id="review:fail:__end__"]').wait_for(state="attached")
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["review"]["routes"]["fail"] == "stop"

                # Ctrl+Z restores the most recent graph draft mutation before save.
                edge = page.locator('.react-flow__edge[data-id="review:fail:__end__"]')
                edge.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert edge.count() == 0
                page.keyboard.press("Control+z")
                page.locator('.react-flow__edge[data-id="review:fail:__end__"]').wait_for(state="attached")
                assert page.get_by_text("已復原上一個 Workflow 草稿修改。").is_visible()
                _save_editor(page)

                page.reload()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")

                # Reconnecting FAIL retargets the semantic edge.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="review"] .react-flow__handle.fail',
                    '.react-flow__node[data-id="worker"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="review:fail:worker"]').wait_for(state="attached")
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["review"]["routes"]["fail"] == "worker"
                assert saved["stages"]["execute"]["profile"] == "execute"

                # Explicit PASS edge is also persisted and can later be removed.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="review"] .react-flow__handle.pass',
                    '.react-flow__node[data-id="worker"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="review:pass:worker"]').wait_for(state="attached")
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["review"]["routes"]["pass"] == "worker"

                # Handoff edges are Stage-owned targets. Add a second forward target and persist it.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="router"] .react-flow__handle.handoff',
                    '.react-flow__node[data-id="after"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="router:handoff:after"]').wait_for(state="attached")
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["router"]["targets"] == ["worker", "after"]

                page.reload()
                page.locator('.react-flow__edge[data-id="router:handoff:worker"]').wait_for(state="attached")

                # Selected explicit HANDOFF edge follows the same Delete keyboard contract.
                handoff_edge = page.locator('.react-flow__edge[data-id="router:handoff:worker"]')
                handoff_edge.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert handoff_edge.count() == 0
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["router"]["targets"] == ["after"]

                # Remove PASS/FAIL references before deleting the target Stage.
                pass_edge = page.locator('.react-flow__edge[data-id="review:pass:worker"]')
                pass_edge.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert pass_edge.count() == 0

                fail_edge = page.locator('.react-flow__edge[data-id="review:fail:worker"]')
                fail_edge.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert fail_edge.count() == 0
                _save_editor(page)

                # Once no edge targets worker, node deletion uses the guarded confirmation flow.
                page.locator('.react-flow__node[data-id="worker"]').click()
                page.keyboard.press("Delete")
                dialog = page.locator(".designer-confirm-dialog")
                dialog.wait_for(state="attached")
                dialog.locator("button.danger-confirm").click()
                page.locator('.react-flow__node[data-id="worker"]').wait_for(state="detached")
                _save_editor(page)

                page.reload()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert "worker" not in saved["stages"]
                assert "worker" not in saved["flow"]
                assert "routes" not in saved["stages"]["review"]
                assert saved["stages"]["router"]["targets"] == ["after"]
                assert page.locator('.react-flow__node[data-id="worker"]').count() == 0

                # START handle reorders the canonical flow; save/reload must preserve it.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="__start__"] .react-flow__handle',
                    '.react-flow__node[data-id="review"] .react-flow__handle.stage-input',
                )
                _save_editor(page)
                page.reload()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["flow"][0] == "review"
                assert saved["stages"]["execute"]["profile"] == "execute"
                assert not errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)



@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_edit_prompt_deep_link_opens_prompt_workspace() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-prompt-link-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "prompt-link-e2e.yaml"
        workflow.write_text(
            """stages:
  review:
    type: base
    profile: review
    prompt: common/review.md
flow:
  - review
""",
            encoding="utf-8",
        )

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = UIServer(ROOT, "127.0.0.1", port)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = _launch_browser(playwright)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                project_q = quote(str(project))
                files = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/files?project={project_q}"
                ).json()
                workflow_id = next(
                    item["id"] for item in files["workflows"]
                    if item["name"] == "prompt-link-e2e.yaml"
                )
                prompt = next(
                    item for item in files["prompts"]
                    if (item.get("reference") or item.get("display_name") or item.get("name"))
                    == "common/review.md"
                )

                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(workflow_id)}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                page.locator('.react-flow__node[data-id="review"]').dblclick()
                edit_prompt = page.get_by_role("button", name="Edit Prompt")
                edit_prompt.wait_for(state="attached")
                edit_prompt.click()

                page.wait_for_url(
                    f"**/index.html?view=workflow&source=prompt&studio={quote(prompt['id'])}*"
                )
                page.locator("#studioPromptTextarea").wait_for(state="visible")
                assert page.locator("#studioPromptTextarea").input_value().strip()
                assert page.locator("#studioFileName").inner_text() == prompt["name"]
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
