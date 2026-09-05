from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ui.server import UIState


class UIStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "ui" / "data").mkdir(parents=True)
        self.project = self.root / "project"
        self.project.mkdir()
        custom = self.root / "runner" / "workflow" / "custom"
        custom.mkdir(parents=True)
        self.workflow = custom / "task.workflow.yaml"
        self.workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        self.state = UIState(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")


    def test_running_project_cannot_be_removed(self) -> None:
        self.state.add_project(str(self.project))
        with patch.object(self.state, "read_runtime", return_value={"running": True}):
            with self.assertRaisesRegex(ValueError, "Stop the active runtime"):
                self.state.remove_project(str(self.project))
        self.assertEqual(len(self.state.projects()), 1)

    def test_project_list_marks_missing_without_dropping_it(self) -> None:
        added = self.state.add_project(str(self.project))
        self.assertTrue(added["path"])
        self.project.rmdir()
        rows = self.state.projects()
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["exists"])

    def test_completed_run_appends_assistant_once(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-1", "completed": True})
        (runtime / "debug").mkdir(parents=True)
        (runtime / "debug" / "last-result.txt").write_text("Done successfully", encoding="utf-8")

        self.assertTrue(self.state.sync_completion(self.project))
        self.assertFalse(self.state.sync_completion(self.project))
        messages = self.state.messages(self.project)
        self.assertEqual([m["role"] for m in messages], ["assistant"])
        self.assertEqual(messages[0]["content"], "Done successfully")
        self.assertEqual(messages[0]["run_id"], "run-1")

    def test_completion_without_result_uses_small_fallback(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-2", "completed": True})
        self.assertTrue(self.state.sync_completion(self.project))
        self.assertEqual(self.state.messages(self.project)[0]["content"], "Run completed.")

    def test_runtime_reports_interrupted_when_marker_is_stale(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-3", "completed": False, "stage": "review"})
        self.write_json(runtime / "runner-process.json", {"supervisor_pid": 999999, "worker_pid": 88})
        with patch.object(UIState, "_pid_alive", return_value=False):
            info = self.state.read_runtime(self.project)
        self.assertFalse(info["running"])
        self.assertTrue(info["stale"])
        self.assertTrue(info["resumable"])
        self.assertEqual(info["stage"], "review")

    def test_malformed_pid_marker_does_not_break_runtime(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "runner-process.json", {"supervisor_pid": "oops"})
        info = self.state.read_runtime(self.project)
        self.assertFalse(info["running"])
        self.assertTrue(info["stale"])

    def test_stream_hides_reasoning_fields_but_keeps_normal_analysis_text(self) -> None:
        raw = "\n".join([
            json.dumps({"type": "reasoning", "content": "private"}),
            json.dumps({"type": "tool", "content": "Running static analysis"}),
            "Thinking: private scratchpad",
            "Running pytest",
        ])
        visible = UIState._display_stream(raw)
        self.assertNotIn("private", visible)
        self.assertIn("Running static analysis", visible)
        self.assertIn("Running pytest", visible)


    def test_launch_message_appends_user_only_after_successful_launch(self) -> None:
        with patch.object(self.state, "launch", side_effect=ValueError("boom")):
            with self.assertRaisesRegex(ValueError, "boom"):
                self.state.launch_message(self.project, "hello", workflow=str(self.workflow))
        self.assertEqual(self.state.messages(self.project), [])

        with patch.object(self.state, "launch", return_value=None):
            self.state.launch_message(self.project, "hello", workflow=str(self.workflow))
        self.assertEqual([m["content"] for m in self.state.messages(self.project)], ["hello"])

    def test_launch_message_requires_selected_workflow_and_creates_request_snapshot(self) -> None:
        with self.assertRaisesRegex(ValueError, "Select a Workflow"):
            self.state.launch_message(self.project, "what does this project do?")
        with patch.object(self.state, "launch", return_value=None) as launch:
            self.state.launch_message(self.project, "run the task", workflow=str(self.workflow))
        kwargs = launch.call_args.kwargs
        self.assertEqual(Path(kwargs["workflow"]).resolve(), self.workflow.resolve())
        self.assertEqual(kwargs["validator"], "")
        request_files = list((self.project / ".ai-task-runner" / "ui" / "requests").glob("*/request.json"))
        self.assertEqual(len(request_files), 1)
        manifest = json.loads(request_files[0].read_text(encoding="utf-8"))
        self.assertEqual(manifest["mode"], "workflow")
        self.assertEqual(Path(manifest["workflow"]).resolve(), self.workflow.resolve())
        self.assertTrue(Path(manifest["prompt_file"]).is_file())
        self.assertEqual(self.state.messages(self.project)[0]["content"], "run the task")

    def test_reset_runtime_preserves_ui_history_and_removes_runner_state(self) -> None:
        runtime = self.project / ".ai-task-runner"
        (runtime / "debug").mkdir(parents=True)
        (runtime / "state.json").write_text("{}", encoding="utf-8")
        (runtime / "debug" / "last-result.txt").write_text("old", encoding="utf-8")
        self.append = self.state.append_message(self.project, "user", "keep me")
        request = runtime / "ui" / "requests" / "r1"
        request.mkdir(parents=True)
        (request / "prompt.md").write_text("keep request", encoding="utf-8")
        result = self.state.reset_runtime(self.project)
        self.assertIn("state.json", result["removed"])
        self.assertFalse((runtime / "state.json").exists())
        self.assertFalse((runtime / "debug").exists())
        self.assertEqual(self.state.messages(self.project)[0]["content"], "keep me")
        self.assertTrue((request / "prompt.md").is_file())

    def test_reset_runtime_rejects_active_runtime(self) -> None:
        with patch.object(self.state, "read_runtime", return_value={"running": True}):
            with self.assertRaisesRegex(ValueError, "Stop the active runtime"):
                self.state.reset_runtime(self.project)

    def test_new_task_after_completed_run_auto_resets_old_runtime(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir(parents=True)
        (runtime / "state.json").write_text(json.dumps({"run_id": "old", "completed": True}), encoding="utf-8")
        (runtime / "old.log").write_text("old", encoding="utf-8")
        with patch.object(self.state, "launch", return_value=None):
            self.state.launch_message(self.project, "next task", workflow=str(self.workflow))
        self.assertFalse((runtime / "old.log").exists())
        self.assertTrue(any((runtime / "ui" / "requests").glob("*/prompt.md")))

    def test_new_task_does_not_discard_resumable_state(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir(parents=True)
        (runtime / "state.json").write_text(json.dumps({"run_id": "old", "completed": False}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Continue it or Reset"):
            self.state.launch_message(self.project, "new task", workflow=str(self.workflow))
        self.assertTrue((runtime / "state.json").exists())

    def test_launch_uses_detached_cli_contract(self) -> None:
        with patch.object(self.state, "read_runtime", return_value={"running": False}), patch("ui.server.subprocess.Popen") as popen:
            self.state.launch(self.project, "fix it", mode="run", backend="qwen", validator="v.py", workflow="w.yaml")
        command = popen.call_args.args[0]
        self.assertIn("--project-root", command)
        self.assertIn(str(self.project), command)
        self.assertIn("--goal", command)
        self.assertIn("fix it", command)
        self.assertIn("--backend", command)
        self.assertIn("qwen", command)
        self.assertEqual(popen.call_args.kwargs["stdout"], __import__("subprocess").DEVNULL)
        if os.name == "nt":
            self.assertTrue(popen.call_args.kwargs.get("creationflags", 0))
        else:
            self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_resume_and_rerun_use_existing_cli_modes(self) -> None:
        with patch.object(self.state, "read_runtime", return_value={"running": False}), patch("ui.server.subprocess.Popen") as popen:
            self.state.launch(self.project, None, mode="resume")
            resume = popen.call_args.args[0]
            self.assertIn("--resume", resume)
            self.state.launch(self.project, "again", mode="rerun")
            rerun = popen.call_args.args[0]
            self.assertIn("--force-new", rerun)
            self.assertIn("again", rerun)

    def test_stop_writes_only_stop_request(self) -> None:
        self.state.stop(self.project)
        path = self.project / ".ai-task-runner" / "stop.request"
        self.assertEqual(path.read_text(encoding="utf-8"), "stop\n")


if __name__ == "__main__":
    unittest.main()

class HTTPServerSmokeTests(unittest.TestCase):
    def test_server_serves_projects_api_and_static_index(self) -> None:
        import threading
        import urllib.request
        from ui.server import UIServer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ui" / "data").mkdir(parents=True)
            (root / "ui" / "static").mkdir(parents=True)
            (root / "ui" / "static" / "index.html").write_text("UI OK", encoding="utf-8")
            server = UIServer(root, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/projects", timeout=2) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    self.assertEqual(payload, {"projects": []})
                with urllib.request.urlopen(f"http://127.0.0.1:{server.port}/", timeout=2) as response:
                    self.assertIn("UI OK", response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


    def test_static_path_cannot_escape_ui_root(self) -> None:
        import threading
        import urllib.error
        import urllib.request
        from ui.server import UIServer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ui" / "data").mkdir(parents=True)
            (root / "ui" / "static").mkdir(parents=True)
            (root / "secret.txt").write_text("SECRET", encoding="utf-8")
            server = UIServer(root, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{server.port}/../secret.txt", timeout=2)
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 404)
                else:
                    self.fail("static traversal unexpectedly succeeded")
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

    def test_invalid_studio_get_returns_json_400(self) -> None:
        import threading
        import urllib.error
        import urllib.request
        from ui.server import UIServer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "ui" / "data").mkdir(parents=True)
            (root / "ui" / "static").mkdir(parents=True)
            server = UIServer(root, "127.0.0.1", 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                try:
                    urllib.request.urlopen(f"http://127.0.0.1:{server.port}/api/studio/file?id=bad", timeout=2)
                except urllib.error.HTTPError as exc:
                    self.assertEqual(exc.code, 400)
                    payload = json.loads(exc.read().decode("utf-8"))
                    self.assertIn("error", payload)
                else:
                    self.fail("invalid studio request unexpectedly succeeded")
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=2)

class WorkflowStudioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "ui" / "data").mkdir(parents=True)
        (self.root / "runner" / "workflow" / "system").mkdir(parents=True)
        (self.root / "runner" / "prompts" / "stages").mkdir(parents=True)
        (self.root / "runner" / "workflow" / "custom").mkdir(parents=True)
        (self.root / "runner" / "prompts" / "custom").mkdir(parents=True)
        (self.root / "tool").mkdir(exist_ok=True)
        (self.root / "tool" / "workflow_dryrun.py").write_text("print('{\"closed\": true, \"valid\": true, \"paths_passed\": 1, \"paths_total\": 1}')\n", encoding="utf-8")
        self.system_workflow = self.root / "runner" / "workflow" / "system" / "file.yaml"
        self.system_workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        self.workflow = self.root / "runner" / "workflow" / "custom" / "custom.workflow.yaml"
        self.workflow.parent.mkdir(parents=True, exist_ok=True)
        self.workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        self.prompt = self.root / "runner" / "prompts" / "stages" / "execution.md"
        self.prompt.write_text("Do the task.\n", encoding="utf-8")
        (self.root / "runner" / "prompts" / "stages" / "continue.md").write_text("Continue.\n", encoding="utf-8")
        (self.root / "runner" / "prompts" / "context.py").write_text(
            "def _task_data(task):\n    return {'id': '', 'title': '', 'description': ''}\n\n"
            "def build_stage_prompt_context(ctx, stage, previous=None):\n"
            "    return {'goal': '', 'stage': stage, 'task': _task_data(None), 'project': {'root': ''}, 'previous': {'output': ''}, 'validation': {'feedback': ''}}\n",
            encoding="utf-8",
        )
        self.project = self.root / "project"
        self.project.mkdir()
        self.state = UIState(self.root)
        self.state.add_project(str(self.project))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _workflow_item(self) -> dict:
        files = self.state.studio_files(self.project)
        return next(item for item in files["workflows"] if item["path"] == str(self.workflow.resolve()))


    def test_launch_and_studio_save_share_lifecycle_lock(self) -> None:
        self.assertIs(self.state._launch_lock, self.state._edit_lock)

    def test_studio_lists_workflow_and_prompt_files(self) -> None:
        files = self.state.studio_files(self.project)
        self.assertTrue(any(item["name"] == "file.yaml" for item in files["workflows"]))
        self.assertTrue(any(item["name"] == "execution.md" for item in files["prompts"]))
        self.assertTrue(files["guard"]["editable"])

    def test_system_assets_are_readonly_and_custom_assets_are_editable(self) -> None:
        files = self.state.studio_files(self.project)
        system = next(item for item in files["workflows"] if item["path"] == str(self.system_workflow.resolve()))
        custom = next(item for item in files["workflows"] if item["path"] == str(self.workflow.resolve()))
        prompt = next(item for item in files["prompts"] if item["path"] == str(self.prompt.resolve()))
        self.assertTrue(system["readonly"]); self.assertEqual(system["group"], "System")
        self.assertFalse(custom["readonly"]); self.assertEqual(custom["group"], "Custom")
        self.assertTrue(prompt["readonly"]); self.assertEqual(prompt["group"], "System")
        opened = self.state.studio_read(system["id"], self.project)
        with self.assertRaisesRegex(ValueError, "read only"):
            self.state.studio_save(system["id"], opened["content"] + "# x\n", opened["hash"], self.project)
        with self.assertRaisesRegex(ValueError, "read only"):
            self.state.studio_delete(prompt["id"], self.project)

    def test_custom_skill_workflow_and_prompt_are_classified_custom(self) -> None:
        skill = self.root / "runner" / "workflow" / "custom" / "skill_prompt_review_chain.yaml"
        skill.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        custom_prompt = self.root / "runner" / "prompts" / "custom" / "review.md"
        custom_prompt.write_text("{{goal}}\n", encoding="utf-8")
        files = self.state.studio_files(self.project)
        self.assertEqual(next(x for x in files["workflows"] if x["path"] == str(skill.resolve()))["group"], "Custom")
        self.assertEqual(next(x for x in files["prompts"] if x["path"] == str(custom_prompt.resolve()))["group"], "Custom")

    def test_prompt_tags_are_read_from_core_context_contract_without_importing_runner(self) -> None:
        tags = {item["key"] for item in self.state.studio_prompt_tags()["tags"]}
        self.assertIn("goal", tags)
        self.assertIn("project.root", tags)
        self.assertIn("task.title", tags)

    def test_prompt_check_accepts_known_context_and_rejects_unknown_variable(self) -> None:
        files = self.state.studio_files(self.project)
        item = next(row for row in files["prompts"] if row["name"] == "execution.md")
        ok = self.state.studio_prompt_check(item["id"], "Goal: {{ goal }} / {{ project.root }} / {{ task.title }}", self.project)
        self.assertTrue(ok["ok"])
        bad = self.state.studio_prompt_check(item["id"], "{{ made_up_variable }}", self.project)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["unknown"], ["made_up_variable"])

    def test_prompt_save_is_server_side_validated(self) -> None:
        custom_prompt = self.root / "runner" / "prompts" / "custom" / "editable.md"
        custom_prompt.write_text("{{ goal }}\n", encoding="utf-8")
        item = next(x for x in self.state.studio_files(self.project)["prompts"] if x["path"] == str(custom_prompt.resolve()))
        opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "Prompt validation failed"):
            self.state.studio_save(item["id"], "{{ unknown_ui_variable }}\n", opened["hash"], self.project)
        saved = self.state.studio_save(item["id"], "{{ goal }} / {{ project.root }}\n", opened["hash"], self.project)
        self.assertIn("project.root", saved["content"])

    def test_manual_workflow_create_is_exclusive_and_immediately_listed(self) -> None:
        created = self.state.studio_workflow_create("regression", "project", self.project)
        path = self.project / "regression.workflow.yaml"
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_text(encoding="utf-8"), "stages:\n  planning:\n    type: plan\n\nflow:\n  - planning\n")
        self.assertEqual(created["file"]["name"], "regression.workflow.yaml")
        self.assertTrue(any(row["name"] == "regression.workflow.yaml" for row in self.state.studio_files(self.project)["workflows"]))
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.state.studio_workflow_create("regression", "project", self.project)

    def test_manual_workflow_create_honors_runtime_lock(self) -> None:
        with patch.object(self.state, "edit_guard", return_value={"editable": False, "active_projects": [{"name": "project"}]}):
            with self.assertRaisesRegex(ValueError, "runtime is active"):
                self.state.studio_workflow_create("locked", "project", self.project)

    def test_running_project_locks_workflow_and_prompt_edits(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir()
        (runtime / "runner-process.json").write_text(json.dumps({"supervisor_pid": 1234}), encoding="utf-8")
        with patch.object(UIState, "_pid_alive", return_value=True):
            guard = self.state.edit_guard()
            item = self._workflow_item()
            opened = self.state.studio_read(item["id"], self.project)
            with self.assertRaisesRegex(ValueError, "runtime is active"):
                self.state.studio_save(item["id"], opened["content"] + "# change\n", opened["hash"], self.project)
        self.assertFalse(guard["editable"])
        self.assertEqual(guard["active_projects"][0]["name"], "project")

    def test_stale_runtime_marker_does_not_lock_studio(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir()
        (runtime / "runner-process.json").write_text(json.dumps({"supervisor_pid": 999999}), encoding="utf-8")
        with patch.object(UIState, "_pid_alive", return_value=False):
            self.assertTrue(self.state.edit_guard()["editable"])

    def test_save_uses_hash_guard_to_prevent_overwrite(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        self.workflow.write_text("changed elsewhere\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "changed on disk"):
            self.state.studio_save(item["id"], "my edit\n", opened["hash"], self.project)
        self.assertEqual(self.workflow.read_text(encoding="utf-8"), "changed elsewhere\n")

    def test_save_replaces_file_and_returns_new_hash(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        saved = self.state.studio_save(item["id"], "flow:\n  - planning\n# saved\n", opened["hash"], self.project)
        self.assertIn("# saved", self.workflow.read_text(encoding="utf-8"))
        self.assertNotEqual(saved["hash"], opened["hash"])
        self.assertFalse(self.workflow.with_name(self.workflow.name + ".tmp").exists())

    def test_file_id_cannot_escape_allowed_roots(self) -> None:
        outside = self.root / "secret.md"
        outside.write_text("secret", encoding="utf-8")
        file_id = self.state._encode_file_id(outside, "prompt", "system")
        with self.assertRaisesRegex(ValueError, "outside allowed"):
            self.state.studio_read(file_id, self.project)

    def test_visual_designer_reads_stages_and_flow(self) -> None:
        self.workflow.write_text(
            "stages:\n  planning:\n    type: plan\n    prompt: stages/planning.md\n  review:\n    type: review\nflow:\n  - planning\n  - stage: review\n    scope: task\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        visual = self.state.studio_visual(item["id"], self.project)
        self.assertEqual([stage["name"] for stage in visual["stages"]], ["planning", "review"])
        self.assertEqual([row["stage"] for row in visual["flow"]], ["planning", "review"])
        self.assertEqual(visual["flow"][1]["scope"], "task")

    def test_visual_flow_status_and_prompt_override_round_trip(self) -> None:
        self.workflow.write_text(
            "stages:\n  run_prompt:\n    type: task\n    status: Default status\n    prompt: stages/execution.md\nflow:\n  - stage: run_prompt\n    status: Flow status\n    prompt: stages/continue.md\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        visual = self.state.studio_visual(item["id"], self.project)
        stage = visual["stages"][0]
        flow = visual["flow"][0]
        self.assertEqual(stage["status"], "Default status")
        self.assertEqual(stage["prompt"], "stages/execution.md")
        self.assertEqual(flow["status"], "Flow status")
        self.assertEqual(flow["prompt"], "stages/continue.md")

        opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(
            item["id"], "run_prompt", {}, opened["hash"], self.project,
            flow_index=0, scope="",
            flow_fields={"status": "Changed flow status", "prompt": "stages/execution.md"},
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertEqual(data["stages"]["run_prompt"]["status"], "Default status")
        self.assertEqual(data["stages"]["run_prompt"]["prompt"], "stages/execution.md")
        self.assertEqual(data["flow"][0]["status"], "Changed flow status")
        self.assertEqual(data["flow"][0]["prompt"], "stages/execution.md")

    def test_stage_draft_validation_does_not_write_workflow(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    status: Before\nflow:\n  - review\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        original = self.workflow.read_text(encoding="utf-8")
        result = self.state.studio_stage_save(
            item["id"], "review", {"status": "Draft only"}, opened["hash"], self.project,
            flow_index=0, scope="", validate_only=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(self.workflow.read_text(encoding="utf-8"), original)

    def test_yaml_draft_validation_does_not_write_workflow(self) -> None:
        item = self._workflow_item()
        original = self.workflow.read_text(encoding="utf-8")
        result = self.state.studio_validate(item["id"], self.project, content=original + "# draft validation only\n")
        self.assertTrue(result["ok"])
        self.assertEqual(self.workflow.read_text(encoding="utf-8"), original)

    def test_visual_save_reorders_only_through_ui_guard(self) -> None:
        self.workflow.write_text(
            "stages:\n  planning:\n    type: plan\n  review:\n    type: review\nflow:\n  - planning\n  - review\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        saved = self.state.studio_visual_save(item["id"], [{"stage": "review"}, {"stage": "planning"}], opened["hash"], self.project)
        visual = self.state.studio_visual(item["id"], self.project)
        self.assertEqual([row["stage"] for row in visual["flow"]], ["review", "planning"])
        self.assertNotEqual(saved["hash"], opened["hash"])

    def test_visual_save_preserves_stage_yaml_and_anchors(self) -> None:
        original = "stages:\n  planning: &planning\n    type: plan\n  execute:\n    <<: *planning\n    status: Run\n# keep this comment\nflow:\n  - planning\n  - execute\n"
        self.workflow.write_text(original, encoding="utf-8")
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        self.state.studio_visual_save(item["id"], [{"stage": "execute"}, {"stage": "planning"}], opened["hash"], self.project)
        updated = self.workflow.read_text(encoding="utf-8")
        self.assertIn("planning: &planning", updated)
        self.assertIn("<<: *planning", updated)
        self.assertIn("# keep this comment", updated)
        self.assertLess(updated.index("- execute"), updated.index("- planning", updated.index("flow:")))

    def test_workflow_save_is_blocked_when_dryrun_matrix_fails(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        original = self.workflow.read_text(encoding="utf-8")
        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout='{"closed":false,"valid":true}', stderr="")
        with patch("ui.server.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(ValueError, "Workflow validation failed"):
                self.state.studio_save(item["id"], original + "# invalid closure\n", opened["hash"], self.project)
        self.assertEqual(self.workflow.read_text(encoding="utf-8"), original)

    def test_validate_runs_existing_dryrun_tool_without_importing_core(self) -> None:
        item = self._workflow_item()
        fake = subprocess.CompletedProcess(args=[], returncode=0, stdout='{"closed":true,"valid":true,"paths_passed":1,"paths_total":1}', stderr="")
        with patch("ui.server.subprocess.run", return_value=fake) as run:
            result = self.state.studio_validate(item["id"], self.project)
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertIn("workflow_dryrun.py", " ".join(map(str, command)))
        self.assertIn("--json", command)
        self.assertIn("--matrix", command)
        self.assertIn("--max-steps", command)
    def test_stage_save_updates_supported_fields_and_flow_scope(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    status: Old\n# keep workflow comment\nflow:\n  - stage: review\n    scope: task\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(
            item["id"], "review",
            {
                "status": "Reviewing", "run_state": "reviewing", "actor": "ai", "mode": "readonly",
                "timeout": 45, "prompt": "stages/execution.md", "continuation_prompt": "stages/continue.md",
                "instructions": "Be strict", "detail": "Review result", "session_key": "review_client",
                "recover": ["repair"], "retry": 2, "structured_retries": 1, "structured_fresh_retries": 1,
                "skip_on_error": False, "fresh_session_on_start": True, "fresh_session_each_run": True,
                "track_changes": True, "tolerate_restored_changes": True, "allow_project_read": True,
                "clean_work": ["validator-reports"],
            },
            opened["hash"], self.project, flow_index=0, scope="",
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        stage = data["stages"]["review"]
        self.assertEqual(stage["status"], "Reviewing")
        self.assertEqual(stage["prompt"], "stages/execution.md")
        self.assertEqual(stage["recover"], ["repair"])
        self.assertTrue(stage["fresh_session_each_run"])
        self.assertEqual(stage["structured_fresh_retries"], 1)
        self.assertEqual(data["flow"], ["review"])
        self.assertIn("# keep workflow comment", result["file"]["content"])

    def test_stage_save_preserves_comment_immediately_after_changed_field(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    status: Old\n    # keep field comment\n    retry: -1\nflow:\n  - review\n",
            encoding="utf-8",
        )
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(item["id"], "review", {"status": "New"}, opened["hash"], self.project)
        self.assertIn("    # keep field comment\n", result["file"]["content"])
        self.assertIn("    retry: -1\n", result["file"]["content"])

    def test_stage_save_accepts_retry_minus_one_and_parser(self) -> None:
        self.workflow.write_text("stages:\n  review:\n    type: review\nflow:\n  - review\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(item["id"], "review", {"retry": -1, "parser": "review"}, opened["hash"], self.project)
        stage = __import__("yaml").safe_load(result["file"]["content"])["stages"]["review"]
        self.assertEqual(stage["retry"], -1); self.assertEqual(stage["parser"], "review")

    def test_stage_save_updates_flow_routing_fields_without_polluting_stage_definition(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    recover: [review]\nflow:\n  - review\n  - review\n", encoding="utf-8"
        )
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(
            item["id"], "review", {}, opened["hash"], self.project, flow_index=1, scope="task",
            flow_fields={"label": "retry review", "restart_at": "review", "repeat": 2, "fresh_after_same_failures": 1},
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertNotIn("label", data["stages"]["review"]); self.assertNotIn("repeat", data["stages"]["review"])
        self.assertEqual(data["flow"][1]["scope"], "task")
        self.assertEqual(data["flow"][1]["label"], "retry review")
        self.assertEqual(data["flow"][1]["restart_at"], "review")
        self.assertEqual(data["flow"][1]["repeat"], 2)
        self.assertEqual(data["flow"][1]["fresh_after_same_failures"], 1)

    def test_flow_routing_validation_rejects_future_restart_and_repeat_without_recover(self) -> None:
        self.workflow.write_text("stages:\n  a:\n    type: task\n  b:\n    type: review\nflow:\n  - a\n  - b\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "restart_at"):
            self.state.studio_stage_save(item["id"], "a", {}, opened["hash"], self.project, flow_index=0, flow_fields={"restart_at": "b"})
        with self.assertRaisesRegex(ValueError, "requires recover"):
            self.state.studio_stage_save(item["id"], "a", {}, opened["hash"], self.project, flow_index=0, flow_fields={"repeat": 2})

    def test_stage_save_null_removes_direct_field(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    status: Reviewing\n    retry: 2\nflow:\n  - review\n", encoding="utf-8"
        )
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(item["id"], "review", {"status": None, "retry": None}, opened["hash"], self.project)
        stage = __import__("yaml").safe_load(result["file"]["content"])["stages"]["review"]
        self.assertNotIn("status", stage); self.assertNotIn("retry", stage)

    def test_stage_add_creates_minimal_stage_and_flow_entry(self) -> None:
        self.workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_add(
            item["id"], "review_result", "review", opened["hash"], self.project,
            status="Reviewing", prompt="stages/execution.md", add_to_flow=True,
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertEqual(data["stages"]["review_result"], {"type": "review", "status": "Reviewing", "prompt": "stages/execution.md"})
        self.assertEqual(data["flow"], ["planning", "review_result"])

    def test_stage_add_rejects_invalid_key_and_command_without_command(self) -> None:
        self.workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "Stage key"):
            self.state.studio_stage_add(item["id"], "bad stage", "task", opened["hash"], self.project)
        with self.assertRaisesRegex(ValueError, "requires a command"):
            self.state.studio_stage_add(item["id"], "check", "command", opened["hash"], self.project)

    def test_stage_save_and_add_honor_runtime_edit_lock(self) -> None:
        self.workflow.write_text("stages:\n  review:\n    type: review\nflow:\n  - review\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with patch.object(self.state, "edit_guard", return_value={"editable": False, "active_projects": [{"name": "project"}]}):
            with self.assertRaisesRegex(ValueError, "runtime is active"):
                self.state.studio_stage_save(item["id"], "review", {"status": "x"}, opened["hash"], self.project)
            with self.assertRaisesRegex(ValueError, "runtime is active"):
                self.state.studio_stage_add(item["id"], "new_stage", "task", opened["hash"], self.project)

    def test_launch_message_snapshots_prompt_and_uses_goal_file(self) -> None:
        self.workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        with patch.object(self.state, "read_runtime", return_value={"running": False}), patch("ui.server.subprocess.Popen") as popen:
            self.state.launch_message(self.project, "fix this", workflow=str(self.workflow))
        command = popen.call_args.args[0]
        self.assertIn("--goal-file", command); self.assertNotIn("--goal", command)
        goal_file = Path(command[command.index("--goal-file") + 1])
        self.assertEqual(goal_file.read_text(encoding="utf-8"), "fix this\n")
        manifest = json.loads((goal_file.parent / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["workflow"], str(self.workflow.resolve()))
        self.assertEqual(manifest["validator"], "")
        self.assertFalse(manifest["requires_python_validator"]); self.assertFalse(manifest["has_ai_validator"])

    def test_run_request_requires_python_validator_only_when_workflow_uses_it(self) -> None:
        self.workflow.write_text("""stages:
  validate:
    type: command
    result_kind: validation
    command: "{python} {validator}"
flow: [validate]
""", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Python validation"):
            self.state._create_run_request(self.project, "x", workflow=str(self.workflow))
        validator = self.project / "validation.py"; validator.write_text("print('PASS')\n", encoding="utf-8")
        request = self.state._create_run_request(self.project, "x", validator=str(validator), workflow=str(self.workflow))
        self.assertEqual(request["validator"], str(validator.resolve())); self.assertTrue(request["requires_python_validator"])

    def test_ai_validator_is_detected_without_creating_separate_ai_request_file(self) -> None:
        prompt = self.root / "runner" / "prompts" / "custom" / "validate.md"; prompt.write_text("{{goal}}\n", encoding="utf-8")
        self.workflow.write_text("stages:\n  ai:\n    type: ai_validator\n    prompt: custom/validate.md\nflow: [ai]\n", encoding="utf-8")
        request = self.state._create_run_request(self.project, "x", workflow=str(self.workflow))
        self.assertTrue(request["has_ai_validator"]); self.assertEqual(request["validator"], "")
        names = {p.name for p in Path(request["request_dir"]).iterdir()}
        self.assertEqual(names, {"prompt.md", "request.json"})

    def test_run_request_rejects_workflow_outside_allowed_roots(self) -> None:
        outside = self.root / "outside.yaml"; outside.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside the allowed"):
            self.state._create_run_request(self.project, "x", workflow=str(outside))

    def test_prompt_delete_is_blocked_while_custom_workflow_uses_it(self) -> None:
        prompt = self.root / "runner" / "prompts" / "custom" / "used.md"; prompt.write_text("{{goal}}\n", encoding="utf-8")
        self.workflow.write_text("stages:\n  work:\n    type: task\n    prompt: custom/used.md\nflow: [work]\n", encoding="utf-8")
        item = next(x for x in self.state.studio_files(self.project)["prompts"] if x["path"] == str(prompt.resolve()))
        with self.assertRaisesRegex(ValueError, "still used"):
            self.state.studio_delete(item["id"], self.project)

    def test_import_workflow_rejects_missing_prompt_and_accepts_existing_prompt(self) -> None:
        bad = "stages:\n  work:\n    type: task\n    prompt: prompts/missing.md\nflow: [work]\n"
        with self.assertRaisesRegex(ValueError, "missing Prompt"):
            self.state.studio_import("workflow", "bad.yaml", bad, "custom", self.project)
        prompt = self.root / "runner" / "prompts" / "custom" / "exists.md"; prompt.write_text("{{goal}}\n", encoding="utf-8")
        good = bad.replace("prompts/missing.md", "custom/exists.md")
        result = self.state.studio_import("workflow", "good.yaml", good, "custom", self.project)
        self.assertEqual(result["item"]["group"], "Custom")

    def test_stage_add_rejects_missing_prompt_reference(self) -> None:
        self.workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "Prompt not found"):
            self.state.studio_stage_add(item["id"], "work", "task", opened["hash"], self.project, prompt="prompts/nope.md")

    def test_custom_prompt_create_and_export(self) -> None:
        result = self.state.studio_prompt_create("my_prompt", "custom", self.project)
        self.assertEqual(result["item"]["group"], "Custom")
        exported = self.state.studio_export(result["item"]["id"], self.project)
        self.assertEqual(exported["kind"], "prompt"); self.assertIn("{{goal}}", exported["content"])

    def test_ai_workflow_builder_launches_external_wrapper_hidden_and_targets_custom(self) -> None:
        builder_dir = self.root / "workflow_builder"
        builder_dir.mkdir()
        (builder_dir / "run.py").write_text("print('builder')\n", encoding="utf-8")
        (builder_dir / "validation.py").write_text("print('validator')\n", encoding="utf-8")
        (self.root / "runner" / "workflow" / "system" / "workflow_builder.yaml").write_text(
            "stages: {}\nflow: []\n", encoding="utf-8"
        )
        with patch.object(self.state, "read_runtime", return_value={"running": False}), patch("ui.server.subprocess.Popen") as popen:
            result = self.state.studio_generate_workflow(
                self.project, "generated", "custom", "Create a review + validation workflow", backend="qwen"
            )
        command = popen.call_args.args[0]
        self.assertIn(str(builder_dir / "run.py"), command)
        self.assertIn("--project-root", command); self.assertIn(str(self.project), command)
        self.assertIn("--request", command); self.assertIn("Create a review + validation workflow", command)
        self.assertIn("--output-workflow", command)
        output = Path(command[command.index("--output-workflow") + 1])
        self.assertEqual(output, (self.root / "runner" / "workflow" / "custom" / "generated.workflow.yaml").resolve())
        self.assertIn("--backend", command); self.assertIn("qwen", command)
        self.assertEqual(result["workflow"], str(output))
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        if os.name == "nt":
            self.assertTrue(popen.call_args.kwargs.get("creationflags", 0))
        else:
            self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_ai_workflow_builder_rejects_incomplete_system_builder(self) -> None:
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.state.studio_generate_workflow(self.project, "generated", "custom", "Create workflow")

    def test_studio_check_reports_yaml_location(self) -> None:
        item = self._workflow_item()
        result = self.state.studio_check(item["id"], "stages:\n  review: [\n", self.project)
        self.assertFalse(result["ok"]); self.assertGreaterEqual(result["line"], 1); self.assertGreaterEqual(result["column"], 1)

