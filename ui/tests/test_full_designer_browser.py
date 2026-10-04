"""Browser smoke check for the built Full Designer against the real local UI."""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
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
    fit = page.locator(".react-flow__controls-fitview")
    if fit.count():
        fit.click()
        page.wait_for_timeout(80)
    source = page.locator(source_selector)
    target = page.locator(target_selector)
    source.scroll_into_view_if_needed()
    target.scroll_into_view_if_needed()
    assert source.is_visible() and target.is_visible()
    start = source.bounding_box()
    end = target.bounding_box()
    assert start and end
    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(end["x"] + end["width"] / 2, end["y"] + end["height"] / 2, steps=12)
    page.mouse.up()
    page.wait_for_timeout(120)


def _drop_connection_on_empty_canvas(page, source_selector: str) -> None:
    fit = page.locator(".react-flow__controls-fitview")
    if fit.count():
        fit.click()
        page.wait_for_timeout(80)
    source = page.locator(source_selector)
    assert source.is_visible()
    start = source.bounding_box()
    pane = page.locator(".react-flow__pane").bounding_box()
    assert start and pane

    candidates = [
        (pane["x"] + pane["width"] - 90, pane["y"] + 110),
        (pane["x"] + pane["width"] - 90, pane["y"] + pane["height"] / 2),
        (pane["x"] + 90, pane["y"] + pane["height"] - 90),
    ]
    target = None
    for x, y in candidates:
        occupied = page.evaluate(
            """([x, y]) => {
                const el = document.elementFromPoint(x, y);
                return Boolean(el?.closest('.react-flow__node,.react-flow__handle,.react-flow__controls,.react-flow__minimap'));
            }""",
            [x, y],
        )
        if not occupied:
            target = (x, y)
            break
    assert target is not None

    page.mouse.move(start["x"] + start["width"] / 2, start["y"] + start["height"] / 2)
    page.mouse.down()
    page.mouse.move(target[0], target[1], steps=12)
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

                snap = page.get_by_role("button", name="Snap")
                assert snap.get_attribute("aria-pressed") == "false"
                snap.click()
                assert snap.get_attribute("aria-pressed") == "true"
                assert page.evaluate("localStorage.getItem('workflow-designer.snap:v1')") == "1"
                snap.click()
                assert snap.get_attribute("aria-pressed") == "false"

                add_stage = page.locator(".palette-command-add")
                add_stage.focus()
                add_stage.click()
                page.locator(".add-stage-command").wait_for(state="attached")
                page.keyboard.press("Escape")
                page.locator(".add-stage-command").wait_for(state="detached")
                page.wait_for_function("document.activeElement?.classList.contains('palette-command-add')")

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

                # A newly created Stage exists only in the Designer draft until Save.
                # Stage YAML must use that draft instead of failing with
                # "Stage not found: ai_stage" against the older saved YAML.
                page.get_by_role("tab", name="YAML").last.click()
                page.locator(".stage-yaml-panel textarea").wait_for(state="attached")
                page.wait_for_function("document.querySelector('.stage-yaml-panel textarea')?.value.includes('type: base')")
                assert "profile: review" in page.locator(".stage-yaml-panel textarea").input_value()
                assert page.locator(".stage-yaml-error").count() == 0

                assert workflow.read_bytes() == original

                # Save-boundary Problems panel: the disconnected draft Stage is a warning,
                # not a blocking schema error. Save still persists through the canonical backend.
                page.locator(".modal-close-button").click()
                page.locator(".studio-header button.primary").click()
                page.locator(".workflow-problems").wait_for(state="attached")
                assert page.locator(".workflow-problem.warning", has_text="ai_stage").count() == 1
                assert page.locator(".workflow-problem.error").count() == 0
                page.wait_for_function("document.querySelector('.studio-header .saved-badge') !== null")
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["ai_stage"]["profile"] == "review"

                # A structurally invalid Handoff must block Save before canonical YAML changes.
                before_invalid_save = workflow.read_bytes()
                handoff_palette = page.locator(".palette-item").filter(has_text="Handoff").first
                handoff_palette.locator(".palette-quick-add").click()
                create = page.locator(".create-stage-card")
                create.wait_for(state="attached")
                create.get_by_role("button", name="Create Stage").click()
                page.locator('.react-flow__node[data-id="handoff"]').wait_for(state="attached")
                page.locator(".modal-close-button").click()
                page.locator(".studio-header button.primary").click()
                page.locator(".workflow-problem.error", has_text="Handoff has no target").wait_for(state="attached")
                assert workflow.read_bytes() == before_invalid_save
                assert page.locator(".studio-header .unsaved-badge").count() == 1

                assert not errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_stage_backend_model_roundtrip_between_designer_and_yaml() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-backend-model-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "backend-model.yaml"
        workflow.write_text(
            """stages:
  worker:
    type: base
    profile: generic
flow:
  - worker
""",
            encoding="utf-8",
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = UIServer(ROOT, "127.0.0.1", port)
        state = server.RequestHandlerClass.state
        state.backend_catalog = lambda project=None: {
            "default": "qwen",
            "backends": ["qwen", "opencode"],
            "models": {
                "qwen": ["local-model-y"],
                "opencode": ["provider/model-x"],
            },
        }
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as playwright:
                browser = _launch_browser(playwright)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/files?project={project_q}"
                ).json()
                item = next(row for row in files["workflows"] if row["name"] == "backend-model.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(item['id'])}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="worker"]').dblclick()
                modal = page.locator(".stage-editor-modal")
                modal.wait_for(state="visible")

                # Execution target is a first-class Stage section. It must be visible
                # immediately and remain catalog-driven, without provider-specific UI branches.
                page.locator(".stage-execution-target").wait_for(state="visible")
                backend_field = modal.locator("label").filter(has=page.locator("span", has_text="backend")).first
                model_field = modal.locator("label").filter(has=page.locator("span", has_text="model")).first
                backend_select = backend_field.locator("select")
                model_select = model_field.locator("select")
                session_field = modal.locator("label").filter(has=page.locator("span", has_text="session_policy")).first
                session_select = session_field.locator("select")
                assert "opencode" in backend_select.locator("option").all_text_contents()

                # A Stage-local backend/model cannot share the global main session.
                # Selecting an override from main drops the explicit session override
                # and inherits the default auto policy rather than writing redundant YAML.
                session_select.select_option("main")
                backend_select.select_option("opencode")
                assert session_select.input_value() == ""
                assert model_select.is_enabled()
                model_select.select_option("provider/model-x")
                page.locator(".modal-close-button").click()
                _save_editor(page)

                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["worker"]["backend"] == "opencode"
                assert saved["stages"]["worker"]["model"] == "provider/model-x"
                assert "session_policy" not in saved["stages"]["worker"]

                # Manual YAML edits must immediately flow back into Designer Form.
                page.get_by_role("tab", name="YAML").click()
                yaml_editor = page.locator(".workflow-yaml-editor")
                yaml_editor.fill(
                    """stages:
  worker:
    type: base
    profile: generic
    backend: qwen
    model: local-model-y
flow:
  - worker
"""
                )
                designer_tab = page.get_by_role("tab", name="Designer")
                designer_tab.click()
                page.wait_for_function(
                    "() => document.querySelector('[role=tab][aria-selected=true]')?.textContent?.includes('Designer')"
                )
                page.locator('.react-flow__node[data-id="worker"]').dblclick()
                modal = page.locator(".stage-editor-modal")
                page.locator(".stage-execution-target").wait_for(state="visible")
                backend_field = modal.locator("label").filter(has=page.locator("span", has_text="backend")).first
                model_field = modal.locator("label").filter(has=page.locator("span", has_text="model")).first
                assert backend_field.locator("select").input_value() == "qwen"
                assert model_field.locator("select").input_value() == "local-model-y"
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["worker"]["backend"] == "qwen"
                assert saved["stages"]["worker"]["model"] == "local-model-y"

                # Invalid execution targets entered in YAML must fail at the same
                # canonical Save boundary and must not mutate the saved Workflow.
                page.locator(".modal-close-button").click()
                page.get_by_role("tab", name="YAML").click()
                yaml_editor = page.locator(".workflow-yaml-editor")
                before_invalid_target = workflow.read_text(encoding="utf-8")
                yaml_editor.fill(
                    """stages:
  worker:
    type: base
    profile: generic
    backend: does-not-exist
flow:
  - worker
"""
                )
                page.get_by_role("tab", name="Designer").click()
                page.locator(".workflow-yaml-error").wait_for(state="visible")
                assert page.get_by_role("tab", name="YAML").get_attribute("aria-selected") == "true"
                assert workflow.read_text(encoding="utf-8") == before_invalid_target

                assert not errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_workflow_yaml_switch_immediately_refreshes_designer_and_rejects_invalid_yaml() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-yaml-switch-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "yaml-switch.yaml"
        workflow.write_text(
            """stages:
  execute:
    type: base
    profile: execute
flow:
  - execute
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
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/files?project={project_q}"
                ).json()
                file_id = next(item["id"] for item in files["workflows"] if item["name"] == "yaml-switch.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(file_id)}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="execute"]').wait_for(state="attached")

                page.get_by_role("tab", name="YAML").click()
                editor = page.locator(".workflow-yaml-editor")
                editor.wait_for(state="visible")
                editor.fill(
                    """stages:
  execute:
    type: base
    profile: execute
  review:
    type: base
    profile: review
    routes:
      fail: execute
flow:
  - execute
  - review
"""
                )
                assert page.locator(".studio-header .unsaved-badge").count() == 1

                page.get_by_role("tab", name="Designer").click()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                assert page.locator(".designer-confirm-dialog").count() == 0
                assert page.locator(".studio-header .saved-badge").count() == 1
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["flow"] == ["execute", "review"]
                assert saved["stages"]["review"]["profile"] == "review"

                page.get_by_role("tab", name="YAML").click()
                editor.fill("stages:\n  broken: [\n")
                before_invalid = workflow.read_text(encoding="utf-8")
                page.get_by_role("tab", name="Designer").click()
                page.locator(".workflow-yaml-error").wait_for(state="visible")
                assert page.get_by_role("tab", name="YAML").get_attribute("aria-selected") == "true"
                assert workflow.read_text(encoding="utf-8") == before_invalid
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

                # Implicit PASS->next is a real Designer connection: deleting it must
                # persist an explicit stop instead of silently continuing to the next Stage.
                implicit_pass = page.locator('.react-flow__edge[data-id="execute:pass:review"]')
                implicit_pass.dispatch_event("click")
                page.keyboard.press("Delete")
                page.wait_for_timeout(100)
                assert implicit_pass.count() == 0
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["execute"]["routes"]["pass"] == "stop"

                stopped = subprocess.run(
                    [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(workflow), "--json"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                assert stopped.returncode == 1
                stopped_payload = json.loads(stopped.stdout)
                assert stopped_payload["completed"] is False
                assert [item["stage"] for item in stopped_payload["transitions"]] == ["execute"]

                # Reconnect PASS to the original next Stage. The stop marker disappears
                # and canonical implicit PASS->next behavior is restored.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="execute"] .react-flow__handle.pass',
                    '.react-flow__node[data-id="review"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="execute:pass:review"]').wait_for(state="attached")
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert "routes" not in saved["stages"]["execute"]

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
                page.keyboard.press("Control+y")
                page.wait_for_timeout(100)
                assert page.locator('.react-flow__edge[data-id="review:fail:__end__"]').count() == 0
                assert page.get_by_text("已重做上一個 Workflow 草稿修改。").is_visible()
                page.keyboard.press("Control+z")
                page.locator('.react-flow__edge[data-id="review:fail:__end__"]').wait_for(state="attached")
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

                # End-to-end contract: a connection drawn in the browser must not only
                # persist to YAML; the production loader + FlowEngine path used by the
                # dry-run tool must actually follow that saved edge.
                scenario = project / "ui-edge-runtime-scenario.yaml"
                scenario.write_text("stages:\n  review: fail\n", encoding="utf-8")
                runtime = subprocess.run(
                    [
                        sys.executable,
                        str(ROOT / "tool" / "workflow_dryrun.py"),
                        str(workflow),
                        "--scenario",
                        str(scenario),
                        "--json",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                assert runtime.returncode == 0, runtime.stdout + runtime.stderr
                payload = json.loads(runtime.stdout)
                assert payload["completed"] is True
                assert [item["stage"] for item in payload["transitions"]] == [
                    "execute",
                    "review",
                    "worker",
                    "after",
                ]
                assert [item["status"] for item in payload["transitions"]] == [
                    "pass",
                    "fail",
                    "pass",
                    "pass",
                ]

                # Drawing the same semantic output to another target is the primary
                # retarget UX. The existing explicit route is replaced atomically.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="review"] .react-flow__handle.fail',
                    '.react-flow__node[data-id="after"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="review:fail:after"]').wait_for(state="attached")
                assert page.locator('.react-flow__edge[data-id="review:fail:worker"]').count() == 0
                _save_editor(page)
                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["stages"]["review"]["routes"]["fail"] == "after"

                # The same operation can retarget it back to worker.
                _connect_nodes(
                    page,
                    '.react-flow__node[data-id="review"] .react-flow__handle.fail',
                    '.react-flow__node[data-id="worker"] .react-flow__handle.stage-input',
                )
                page.locator('.react-flow__edge[data-id="review:fail:worker"]').wait_for(state="attached")
                _save_editor(page)

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
                assert saved["stages"]["review"]["routes"] == {"pass": "stop"}
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

                # Workflow draft recovery is local-only and hash-gated.
                visual = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/visual?id={quote(file_id)}&project={project_q}"
                ).json()
                draft_key = f"workflow-studio-draft:v1:{visual['id']}"
                stale = {
                    "hash": "stale-hash",
                    "visual": visual,
                    "yamlContent": workflow.read_text(encoding="utf-8"),
                    "editorView": "designer",
                    "savedAt": 1,
                }
                page.evaluate(
                    "([key, value]) => localStorage.setItem(key, JSON.stringify(value))",
                    [draft_key, stale],
                )
                page.reload()
                page.locator('.react-flow__node[data-id="review"]').wait_for(state="attached")
                assert page.locator(".workflow-draft-recovery").count() == 0
                assert page.evaluate("(key) => localStorage.getItem(key)", draft_key) is None

                visual = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/visual?id={quote(file_id)}&project={project_q}"
                ).json()
                recovered_visual = json.loads(json.dumps(visual))
                execute = next(stage for stage in recovered_visual["stages"] if stage["name"] == "execute")
                execute["label"] = "Recovered Local Draft"
                canonical_before_recovery = workflow.read_text(encoding="utf-8")
                local_draft = {
                    "hash": visual["hash"],
                    "visual": recovered_visual,
                    "yamlContent": canonical_before_recovery,
                    "editorView": "designer",
                    "savedAt": 2,
                }
                page.evaluate(
                    "([key, value]) => localStorage.setItem(key, JSON.stringify(value))",
                    [draft_key, local_draft],
                )
                page.reload()
                page.get_by_text("本機草稿").wait_for(state="visible")
                recovery_box = page.locator(".workflow-draft-recovery").bounding_box()
                assert recovery_box and recovery_box["height"] <= 48
                page.get_by_role("button", name="還原").click()
                page.locator('.react-flow__node[data-id="execute"]').get_by_text("Recovered Local Draft").wait_for(state="visible")
                assert page.locator(".unsaved-badge").is_visible()
                assert workflow.read_text(encoding="utf-8") == canonical_before_recovery

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
                page.wait_for_function(
                    "() => document.querySelector('#studioPromptTextarea')?.value?.trim().length > 0"
                )
                assert page.locator("#studioPromptTextarea").input_value().strip()
                assert page.locator("#studioFileName").inner_text() == prompt["name"]
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)



@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_edge_drop_on_empty_canvas_creates_and_connects_stage() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-edge-drop-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "edge-drop.yaml"
        workflow.write_text(
            """stages:
  after:
    type: command
    command:
      - "{python}"
      - "-c"
      - "print('after')"
flow:
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
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.set_default_timeout(BROWSER_DEFAULT_TIMEOUT_MS)
                errors: list[str] = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                project_q = quote(str(project))
                files = page.request.get(
                    f"http://127.0.0.1:{port}/api/studio/files?project={project_q}"
                ).json()
                item = next(row for row in files["workflows"] if row["name"] == "edge-drop.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(item['id'])}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="after"]').wait_for(state="attached")

                _drop_connection_on_empty_canvas(
                    page,
                    '.react-flow__node[data-id="after"] .react-flow__handle.pass',
                )
                page.locator(".add-stage-command").wait_for(state="visible")
                page.locator('.add-stage-command-list button[data-stage-type="base"]').click()
                page.locator(".create-stage-card").wait_for(state="visible")
                page.get_by_role("button", name="Create Stage").click()

                page.locator('.react-flow__node[data-id="ai_stage"]').wait_for(state="attached")
                page.locator('.react-flow__edge[data-id="after:pass:ai_stage"]').wait_for(state="attached")
                page.locator(".modal-close-button").click()
                _save_editor(page)

                saved = yaml.safe_load(workflow.read_text(encoding="utf-8"))
                assert saved["flow"] == ["after", "ai_stage"]
                assert saved["stages"]["ai_stage"]["type"] == "base"
                assert "routes" not in saved["stages"]["after"]

                dryrun = subprocess.run(
                    [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(workflow), "--json"],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                assert dryrun.returncode == 0, dryrun.stdout + dryrun.stderr
                payload = json.loads(dryrun.stdout)
                assert [item["stage"] for item in payload["transitions"]] == ["after", "ai_stage"]
                assert payload["completed"] is True

                # Run-from-here / path test reuses saved canonical Workflow +
                # workflow_dryrun/FlowEngine and must not execute the prior Stage.
                page.locator('.react-flow__node[data-id="ai_stage"]').dblclick()
                page.locator(".stage-editor-modal").wait_for(state="visible")
                page.locator('[data-inspector-tab="test"]').click()
                path_button = page.get_by_role("button", name="Test path to END")
                assert path_button.is_enabled()
                path_button.click()
                page.locator(".path-test-result").wait_for(state="visible")
                assert page.locator(".path-test-result", has_text="CLOSED").count() == 1
                path_text = page.locator(".path-test-result pre").inner_text()
                assert "ai_stage" in path_text
                assert "after" not in path_text

                assert not errors
                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)



@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_stage_test_displays_effective_backend_model_not_fallback() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-stage-effective-backend-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "effective-backend.yaml"
        workflow.write_text(
            """stages:
  worker:
    type: base
    profile: generic
    backend: opencode
    model: provider/model-x
flow:
  - worker
""",
            encoding="utf-8",
        )

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = UIServer(ROOT, "127.0.0.1", port)
        state = server.RequestHandlerClass.state

        def fake_stage_test(*args, **kwargs):
            return {
                "ok": True,
                "stage": "worker",
                "status": "pass",
                "output": "ok",
                "data": {},
                "next": "done",
                "route": "next",
                "kind": "generic",
                "changed_files": [],
                "effective_backend": "opencode",
                "effective_model": "provider/model-x",
            }

        state.studio_stage_test = fake_stage_test
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
                item = next(row for row in files["workflows"] if row["name"] == "effective-backend.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(item['id'])}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="worker"]').dblclick()
                modal = page.locator(".stage-editor-modal")
                modal.wait_for(state="visible")
                page.locator('[data-inspector-tab="test"]').click()

                fallback = modal.locator("label").filter(has=page.get_by_text("Fallback Backend", exact=True)).locator("select")
                fallback.select_option("qwen")
                page.get_by_role("button", name="執行 Real Stage").click()
                result = page.locator(".test-result")
                result.wait_for(state="visible")
                assert "Backend：opencode" in result.inner_text()
                assert "Model：provider/model-x" in result.inner_text()
                assert "Backend：qwen" not in result.inner_text()

                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


@pytest.mark.skipif(_browser_unavailable(), reason="Playwright/Chromium unavailable outside browser CI")
def test_full_designer_stage_test_stop_and_action_spacing() -> None:
    with tempfile.TemporaryDirectory(prefix="ai-runner-stage-stop-e2e-") as td:
        project = Path(td)
        workflow_dir = project / ".ai-task-runner" / "assets" / "workflows"
        workflow_dir.mkdir(parents=True)
        workflow = workflow_dir / "stage-stop.yaml"
        workflow.write_text(
            """stages:
  worker:
    type: base
    profile: generic
flow:
  - worker
""",
            encoding="utf-8",
        )

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        server = UIServer(ROOT, "127.0.0.1", port)
        state = server.RequestHandlerClass.state
        started = threading.Event()
        cancelled = threading.Event()
        cancel_ids: list[str] = []

        def fake_stage_test(*args, test_id="", **kwargs):
            started.set()
            cancelled.wait(timeout=10)
            return {"ok": False, "cancelled": True, "test_id": test_id}

        def fake_cancel(test_id: str):
            cancel_ids.append(test_id)
            cancelled.set()
            return {"ok": True, "cancelled": True, "pending": False}

        state.studio_stage_test = fake_stage_test
        state.studio_stage_test_cancel = fake_cancel

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
                item = next(row for row in files["workflows"] if row["name"] == "stage-stop.yaml")
                page.goto(
                    f"http://127.0.0.1:{port}/workflow-studio-app/index.html"
                    f"?id={quote(item['id'])}&project={project_q}"
                )
                page.locator('.react-flow__node[data-id="worker"]').dblclick()
                page.locator(".stage-editor-modal").wait_for(state="visible")
                page.locator('[data-inspector-tab="test"]').click()

                run_button = page.locator(".test-action-row > button.primary")
                path_button = page.locator(".test-action-row > button").last
                run_box = run_button.bounding_box()
                path_box = path_button.bounding_box()
                assert run_box and path_box
                assert path_box["x"] - (run_box["x"] + run_box["width"]) >= 8

                run_button.click()
                assert started.wait(timeout=3)
                stop_button = page.locator(".test-action-row > button.danger")
                stop_button.wait_for(state="visible")
                stop_button.click()
                page.get_by_role("alert").wait_for(state="visible")
                assert page.get_by_role("alert").inner_text().strip()
                assert len(cancel_ids) == 1
                assert cancel_ids[0]

                browser.close()
        finally:
            cancelled.set()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
