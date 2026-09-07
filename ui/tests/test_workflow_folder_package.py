from __future__ import annotations

import base64
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from ui.workflow_folder_package import export_folder_package, import_folder_package, inspect_folder_package


class WorkflowFolderPackageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "runner/workflow/custom/demo/nested").mkdir(parents=True)
        (self.root / "runner/prompts/custom/demo/schema").mkdir(parents=True)
        (self.root / "runner/prompts/custom/common").mkdir(parents=True)
        (self.root / "runner/prompts/system").mkdir(parents=True)

        wf = self.root / "runner/workflow/custom/demo/main.workflow.yaml"
        wf.write_text(
            "stages:\n"
            "  review:\n"
            "    type: review\n"
            "    prompt: custom/demo/review.md\n"
            "  final:\n"
            "    prompt: custom/common/shared.md\n"
            "flow: [review, final]\n",
            encoding="utf-8",
        )
        (self.root / "runner/workflow/custom/demo/validator.py").write_text("print('ok')\n", encoding="utf-8")
        (self.root / "runner/workflow/custom/demo/nested/config.json").write_text('{"x":1}\n', encoding="utf-8")
        (self.root / "runner/workflow/custom/demo/blob.bin").write_bytes(b"\x00\x01\xffowned")
        (self.root / "runner/workflow/custom/demo/__pycache__").mkdir()
        (self.root / "runner/workflow/custom/demo/__pycache__/skip.pyc").write_bytes(b"cache")
        (self.root / "runner/prompts/custom/demo/review.md").write_text("Review {{ goal }}\n", encoding="utf-8")
        (self.root / "runner/prompts/custom/demo/schema/input.schema.json").write_text('{"type":"object"}\n', encoding="utf-8")
        (self.root / "runner/prompts/custom/demo/helper.j2").write_text("{{ value }}\n", encoding="utf-8")
        (self.root / "runner/prompts/custom/common/shared.md").write_text("shared\n", encoding="utf-8")
        self.workflow = wf

    def tearDown(self):
        self.tmp.cleanup()

    def test_export_contains_all_owned_files_not_only_yaml_and_md(self):
        package = export_folder_package(self.workflow, self.root)
        raw = base64.b64decode(package["content"])
        with zipfile.ZipFile(BytesIO(raw), "r") as zf:
            names = set(zf.namelist())
        self.assertIn("workflow/main.workflow.yaml", names)
        self.assertIn("workflow/validator.py", names)
        self.assertIn("workflow/nested/config.json", names)
        self.assertIn("workflow/blob.bin", names)
        self.assertIn("prompts/review.md", names)
        self.assertIn("prompts/schema/input.schema.json", names)
        self.assertIn("prompts/helper.j2", names)
        self.assertNotIn("workflow/__pycache__/skip.pyc", names)
        self.assertNotIn("prompts/custom/common/shared.md", names)
        info = inspect_folder_package(package["content"])
        self.assertEqual(info["workflow_count"], 1)
        self.assertEqual(info["total_file_count"], 7)

    def test_import_restores_arbitrary_owned_files_byte_for_byte(self):
        package = export_folder_package(self.workflow, self.root)
        target = Path(tempfile.mkdtemp())
        try:
            (target / "runner/prompts/custom/common").mkdir(parents=True)
            (target / "runner/prompts/custom/common/shared.md").write_text("shared\n", encoding="utf-8")
            seen_workflows = []
            seen_prompts = []
            folder, workflows = import_folder_package(
                package["content"],
                target,
                lambda path, text: seen_workflows.append((path, text)),
                lambda path, text: seen_prompts.append((path, text)),
            )
            self.assertEqual(folder, "demo")
            self.assertEqual(len(workflows), 1)
            self.assertEqual((target / "runner/workflow/custom/demo/blob.bin").read_bytes(), b"\x00\x01\xffowned")
            self.assertEqual((target / "runner/workflow/custom/demo/nested/config.json").read_text(encoding="utf-8"), '{"x":1}\n')
            self.assertEqual((target / "runner/prompts/custom/demo/schema/input.schema.json").read_text(encoding="utf-8"), '{"type":"object"}\n')
            self.assertEqual(len(seen_workflows), 1)
            self.assertEqual(len(seen_prompts), 1)  # only Markdown Prompt templates are template-validated
        finally:
            import shutil
            shutil.rmtree(target, ignore_errors=True)

    def test_import_failure_rolls_back_entire_owned_folder(self):
        package = export_folder_package(self.workflow, self.root)
        target = Path(tempfile.mkdtemp())
        try:
            wf_root = target / "runner/workflow/custom/demo"
            pr_root = target / "runner/prompts/custom/demo"
            (target / "runner/prompts/custom/common").mkdir(parents=True)
            (target / "runner/prompts/custom/common/shared.md").write_text("shared\n", encoding="utf-8")
            wf_root.mkdir(parents=True)
            pr_root.mkdir(parents=True)
            (wf_root / "old.bin").write_bytes(b"old-workflow")
            (pr_root / "old.json").write_text('{"old":true}\n', encoding="utf-8")

            def fail_validate(_path, _text):
                raise ValueError("boom")

            with self.assertRaisesRegex(ValueError, "boom"):
                import_folder_package(package["content"], target, fail_validate, lambda _p, _t: None)
            self.assertEqual((wf_root / "old.bin").read_bytes(), b"old-workflow")
            self.assertEqual((pr_root / "old.json").read_text(encoding="utf-8"), '{"old":true}\n')
            self.assertFalse((wf_root / "validator.py").exists())
        finally:
            import shutil
            shutil.rmtree(target, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
