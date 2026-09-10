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
except ImportError:  # pragma: no cover - optional browser dependency
    sync_playwright = None


def _chromium_executable() -> str | None:
    configured = os.environ.get("CHROMIUM_PATH")
    if configured and Path(configured).exists():
        return configured
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _write_fixture_repo(root: Path) -> UIState:
    (root / "ui" / "data").mkdir(parents=True)
    (root / "ui" / "data" / "projects.json").write_text("[]", encoding="utf-8")
    for relative in (
        "runner/workflow/system",
        "runner/workflow/custom",
        "runner/prompts/stages",
        "runner/prompts/system",
        "runner/prompts/custom",
        "runner/backends",
        "runner/config",
        "tool",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)
    (root / "runner" / "backends" / "qwen.py").write_text("class QwenBackend:\n    name='qwen'\n", encoding="utf-8")
    (root / "runner" / "config" / "defaults.py").write_text("DEFAULT_BACKEND='qwen'\n", encoding="utf-8")
    (root / "runner" / "prompts" / "context.py").write_text(
        "def build_stage_prompt_context(ctx, stage, previous=None):\n"
        "    return {'goal':'','project':{'root':''},'task':{'title':''},'stage':stage}\n",
        encoding="utf-8",
    )
    (root / "runner" / "prompts" / "loader.py").write_text("def render_prompt(name, values=None): return ''\n", encoding="utf-8")
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
            if method == "GET":
                if path == "/api/projects":
                    data = {"projects": state.projects()}
                elif path == "/api/backends":
                    data = state.backend_catalog()
                elif path == "/api/studio/files":
                    data = state.studio_files(None)
                elif path == "/api/studio/file":
                    data = state.studio_read(query.get("id", [""])[0], None)
                elif path == "/api/studio/visual":
                    data = state.studio_visual(query.get("id", [""])[0], None)
                elif path == "/api/studio/guard":
                    data = state.edit_guard()
                elif path == "/api/studio/prompt-tags":
                    data = state.studio_prompt_tags(query.get("id", [""])[0], None)
                elif path == "/api/studio/generate/active":
                    data = {"active": False}
                else:
                    raise ValueError(f"Unhandled browser E2E GET {path}")
            else:
                if path == "/api/studio/custom-folder/create":
                    data = state.studio_custom_folder_create(body.get("kind", ""), body.get("folder", ""))
                elif path == "/api/studio/prompt/create":
                    data = state.studio_prompt_create(body.get("name", ""), body.get("destination", "custom"), None, body.get("folder", ""))
                elif path == "/api/studio/workflow/create":
                    data = state.studio_workflow_create(body.get("name", ""), body.get("destination", "custom"), None, body.get("folder", ""))
                elif path == "/api/studio/prompt/check":
                    data = state.studio_prompt_check(body.get("id", ""), body.get("content", ""), None)
                elif path == "/api/studio/check":
                    data = state.studio_check(body.get("id", ""), body.get("content", ""), None)
                elif path == "/api/studio/save":
                    data = state.studio_save(body.get("id", ""), body.get("content", ""), body.get("hash", ""), None)
                elif path == "/api/studio/validate":
                    data = state.studio_validate(body.get("id", ""), None, content=body.get("content"), flow=body.get("flow"))
                elif path == "/api/studio/stage/add":
                    data = state.studio_stage_add(
                        body.get("id", ""), body.get("stage", ""), body.get("type", "base"), body.get("hash", ""), None,
                        status=body.get("status", ""), prompt=body.get("prompt", ""), command=body.get("command", ""),
                        add_to_flow=body.get("add_to_flow", True),
                    )
                elif path == "/api/studio/stage/save":
                    data = state.studio_stage_save(
                        body.get("id", ""), body.get("stage", ""), body.get("fields", {}), body.get("hash", ""), None,
                        flow_index=body.get("flow_index"), scope=body.get("scope", ""), flow_fields=body.get("flow_fields", {}),
                    )
                elif path == "/api/studio/stage/delete":
                    data = state.studio_stage_delete(
                        body.get("id", ""), body.get("stage", ""), body.get("hash", ""), None,
                        flow_index=body.get("flow_index"),
                    )
                elif path == "/api/studio/duplicate":
                    data = state.studio_duplicate(body.get("id", ""), body.get("name", ""), None, body.get("folder", ""))
                elif path == "/api/studio/rename":
                    data = state.studio_rename(body.get("id", ""), body.get("name", ""), None)
                elif path == "/api/studio/delete":
                    data = state.studio_delete(body.get("id", ""), None)
                else:
                    raise ValueError(f"Unhandled browser E2E POST {path}")
            return {"status": 200, "data": data}
        except Exception as exc:  # browser must receive the same API-style error shape
            return {"status": 400, "data": {"error": str(exc)}}

    return bridge


@pytest.mark.skipif(sync_playwright is None or _chromium_executable() is None, reason="Playwright/Chromium not available")
def test_browser_crud_journey_covers_prompt_workflow_stage_search_rename_duplicate() -> None:
    """Real browser journey over the production UI with real UIState CRUD methods.

    Local HTTP navigation is intentionally avoided: some CI/browser sandboxes block loopback
    navigation. The page is loaded with set_content and fetch is bridged to UIState, so the
    production DOM/event code and production CRUD implementation are still exercised together.
    """

    static_root = Path(__file__).resolve().parents[1] / "static"
    with tempfile.TemporaryDirectory() as td:
        state = _write_fixture_repo(Path(td))
        html = (static_root / "index.html").read_text(encoding="utf-8")
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S)
        html = re.sub(r'<link[^>]+rel="stylesheet"[^>]*>', "", html)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=_chromium_executable(), args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page_errors: list[str] = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.expose_function("__apiBridge", _bridge_for(state))
            page.set_content(html, wait_until="domcontentloaded")
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
            page.add_script_tag(path=str(static_root / "js" / "ui-dialogs.js"))
            page.add_script_tag(path=str(static_root / "js" / "studio-support.js"))
            page.add_script_tag(path=str(static_root / "app.js"))
            page.wait_for_timeout(200)

            # Create + edit + validate + save Prompt.
            page.click("#workflowNav")
            page.click("#yamlPromptSource")
            page.click("#newWorkflowButton")
            page.fill("#newPromptName", "e2e_prompt")
            page.click("#newPromptFolderToggle")
            page.fill("#newPromptFolderName", "e2e")
            page.click("#newPromptFolderCreate")
            page.wait_for_timeout(80)
            assert page.locator("#newPromptFolder").input_value() == "e2e"
            page.click("#newPromptConfirm")
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_prompt.md"
            page.fill("#studioPromptTextarea", "# Prompt\n\n{{ goal }}\n")
            page.click("#validateStudioButton")
            page.click("#saveStudioButton")
            page.wait_for_timeout(120)

            # Create Workflow and add a Stage that references the new Prompt.
            page.click("#yamlWorkflowSource")
            page.click("#newWorkflowButton")
            page.fill("#newWorkflowName", "e2e_crud")
            page.click("#newWorkflowFolderToggle")
            page.fill("#newWorkflowFolderName", "e2e")
            page.click("#newWorkflowFolderCreate")
            page.wait_for_timeout(80)
            assert page.locator("#newWorkflowFolder").input_value() == "e2e"
            page.click("#newWorkflowConfirm")
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_crud.workflow.yaml"
            folder_header = page.locator("#studioFileList .studio-folder-header").filter(has_text="e2e").first
            assert folder_header.count() == 1
            folder_header.click()
            assert not page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_crud.workflow.yaml").is_visible()
            page.fill("#studioSearchInput", "e2e_crud")
            page.wait_for_timeout(80)
            assert page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_crud.workflow.yaml").is_visible()
            page.fill("#studioSearchInput", "")
            page.wait_for_timeout(80)
            folder_header = page.locator("#studioFileList .studio-folder-header").filter(has_text="e2e").first
            folder_header.click()
            page.click("#addFlowStepButton")
            page.fill("#addStageName", "work")
            page.select_option("#addStageType", "task")
            page.select_option("#addStagePrompt", "custom/e2e/e2e_prompt.md")
            page.click("#addStageConfirm")
            page.wait_for_timeout(180)
            assert page.locator("#stagePromptSelect").input_value() == "custom/e2e/e2e_prompt.md"

            # Visual UI can opt into bounded FAIL -> recover -> retry behavior.
            page.click('[data-stage-tab="control"]')
            page.fill("#stageRecover", "work")
            assert page.locator("#stageMaxAttemptsRow").is_visible()
            page.fill("#stageMaxAttempts", "3")
            assert page.locator("#stageOnExhaustedRow").is_visible()
            page.select_option("#stageOnExhausted", "continue")
            assert "up to 3 attempts" in page.locator("#stageRecoveryBehavior").inner_text()
            page.click("#saveStageButton")
            page.wait_for_timeout(220)
            assert page.locator("#stageMaxAttempts").input_value() == "3"
            assert page.locator("#stageOnExhausted").input_value() == "continue"
            page.locator(".designer-step-modal-box [data-stage-close]").first.click()

            # Prompt deletion must be protected while referenced.
            page.click("#yamlPromptSource")
            page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_prompt.md").click()
            page.click("#deleteStudioButton")
            page.get_by_role("button", name="Delete Prompt").click()
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_prompt.md"
            assert "still used by Workflow Stage" in page.locator("#studioStatus").inner_text()

            # Delete the selected flow invocation and its Stage definition together.
            page.click("#yamlWorkflowSource")
            page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_crud.workflow.yaml").click()
            page.wait_for_timeout(80)
            cards = page.locator("#visualFlowList .visual-flow-card")
            assert cards.count() == 2  # start + work
            cards.nth(1).click()
            page.locator('[data-flow-action="toggle"]').click()
            page.locator('[data-flow-action="remove"]').click()
            page.get_by_role("button", name="Delete Definition Too").click()
            page.wait_for_timeout(150)
            assert page.locator("#visualFlowList .visual-flow-card").count() == 1

            # Once the reference is gone, Prompt delete succeeds.
            page.click("#yamlPromptSource")
            page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_prompt.md").click()
            page.click("#deleteStudioButton")
            page.get_by_role("button", name="Delete Prompt").click()
            page.wait_for_timeout(120)
            assert not page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_prompt.md").count()

            # Duplicate + rename Workflow through the production menus/dialogs.
            page.click("#yamlWorkflowSource")
            page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_crud.workflow.yaml").click()
            page.click("#studioAssetMenuButton")
            page.click("#duplicateStudioButton")
            page.fill("#duplicateAssetName", "e2e_crud copy.workflow.yaml")
            page.select_option("#duplicateAssetFolder", "")
            page.click("#duplicateAssetConfirm")
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_crud copy.workflow.yaml"
            page.click("#studioAssetMenuButton")
            page.click("#renameStudioButton")
            page.fill(".ui-dialog-input", "e2e_crud renamed.workflow.yaml")
            page.click("[data-dialog-ok]")
            page.wait_for_timeout(120)
            assert page.locator("#studioFileName").inner_text() == "e2e_crud renamed.workflow.yaml"

            # Client-side catalog search should immediately reduce the visible list.
            page.fill("#studioSearchInput", "renamed")
            assert page.locator("#studioFileList .studio-file-item").count() == 1
            assert "renamed" in page.locator("#studioFileList .studio-file-item").inner_text().lower()
            page.click("#studioSearchClear")

            # Cleanup both Workflows and confirm the browser stayed healthy end-to-end.
            page.click("#deleteStudioButton")
            page.get_by_role("button", name="Delete Workflow").click()
            page.wait_for_timeout(100)
            page.locator("#studioFileList .studio-file-item").filter(has_text="e2e_crud.workflow.yaml").click()
            page.click("#deleteStudioButton")
            page.get_by_role("button", name="Delete Workflow").click()
            page.wait_for_timeout(100)
            assert page.locator("#studioFileList .studio-file-item").count() == 0
            assert page_errors == []
            browser.close()
