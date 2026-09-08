from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from ui.server import Handler, UIState


class _DisconnectingWriter:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def write(self, payload: bytes) -> None:
        raise self.exc


class _JsonHandlerStub:
    _json = Handler._json

    def __init__(self, exc: BaseException) -> None:
        self.wfile = _DisconnectingWriter(exc)

    def send_response(self, status) -> None:
        return

    def send_header(self, name: str, value: str) -> None:
        return

    def end_headers(self) -> None:
        return


class HandlerDisconnectTests(unittest.TestCase):
    def test_json_response_ignores_expected_client_disconnects(self) -> None:
        for exc in (
            BrokenPipeError("closed"),
            ConnectionAbortedError("aborted"),
            ConnectionResetError("reset"),
        ):
            with self.subTest(exc=type(exc).__name__):
                _JsonHandlerStub(exc)._json({"ok": True})

    def test_json_response_does_not_hide_unrelated_write_errors(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "unexpected write failure"):
            _JsonHandlerStub(RuntimeError("unexpected write failure"))._json({"ok": True})


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
        backends = self.root / "runner" / "backends"; backends.mkdir(parents=True)
        (backends / "qwen.py").write_text("class QwenBackend:\n    name = 'qwen'\n", encoding="utf-8")
        (backends / "opencode.py").write_text("class OpenCodeBackend:\n    name = 'opencode'\n", encoding="utf-8")
        defaults = self.root / "runner" / "config"; defaults.mkdir(parents=True)
        (defaults / "defaults.py").write_text("DEFAULT_BACKEND = 'qwen'\n", encoding="utf-8")
        self.state = UIState(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_json(self, path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")


    def test_workflow_visibility_is_persisted_and_reported(self) -> None:
        listing = self.state.studio_files(self.project)
        item = next(row for row in listing["workflows"] if row["path"] == str(self.workflow.resolve()))
        self.assertFalse(item["hidden"])
        updated = self.state.studio_set_workflow_hidden(item["id"], True, self.project)
        self.assertTrue(updated["hidden"])
        listing = self.state.studio_files(self.project)
        item = next(row for row in listing["workflows"] if row["path"] == str(self.workflow.resolve()))
        self.assertTrue(item["hidden"])
        self.state.studio_set_workflow_hidden(item["id"], False, self.project)
        self.assertFalse(self.state.studio_files(self.project)["workflows"][0]["hidden"])

    def test_backend_catalog_is_read_without_importing_runner_core(self) -> None:
        catalog = self.state.backend_catalog()
        self.assertEqual(catalog["default"], "qwen")
        self.assertEqual(catalog["backends"], ["opencode", "qwen"])

    def test_environment_check_invokes_standalone_tool(self) -> None:
        tool = self.root / "tool" / "environment_check.py"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text("# test tool\n", encoding="utf-8")
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=json.dumps({"ok": True, "status": "pass", "checks": []}), stderr=""
        )
        with patch("ui.server.subprocess.run", return_value=completed) as run:
            result = self.state.environment_check()
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertIn("environment_check.py", " ".join(map(str, command)))
        self.assertIn("--json", command)


    def test_process_snapshot_windows_parses_tasklist_once(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='"python.exe","123","Console","1","10,000 K"\n"qwen.exe","456","Console","1","20,000 K"\n',
            stderr="",
        )
        with patch("ui.server.os.name", "nt"), patch("ui.server.subprocess.run", return_value=completed) as run:
            pids = self.state._process_snapshot()
        self.assertEqual(pids, {123, 456})
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0][:3], ["tasklist", "/FO", "CSV"])

    def test_second_project_can_launch_while_first_project_is_running(self) -> None:
        second = self.root / "project-two"; second.mkdir()
        first_runtime = self.project / ".ai-task-runner"; first_runtime.mkdir()
        self.write_json(first_runtime / "state.json", {"run_id": "run-1", "completed": False})
        self.write_json(first_runtime / "runner-process.json", {"supervisor_pid": 12345})
        original_read = self.state.read_runtime
        def read_runtime(project):
            path = Path(project)
            if path.resolve() == self.project.resolve():
                return {"running": True}
            return original_read(path)
        with patch.object(self.state, "read_runtime", side_effect=read_runtime), patch("ui.server.subprocess.Popen") as popen:
            self.state.launch_message(second, "run second", workflow=str(self.workflow))
        command = popen.call_args.args[0]
        self.assertEqual(Path(command[command.index("--project-root") + 1]).resolve(), second.resolve())

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

    def test_clear_chat_history_removes_conversation_and_does_not_resync_completed_result(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-clear", "completed": True})
        (runtime / "debug").mkdir(parents=True)
        (runtime / "debug" / "last-result.txt").write_text("old assistant", encoding="utf-8")
        self.state.append_message(self.project, "user", "old user")
        self.assertTrue(self.state.sync_completion(self.project))
        self.assertEqual(len(self.state.messages(self.project)), 2)

        self.assertEqual(self.state.clear_chat_history(self.project), {"ok": True})
        self.assertEqual(self.state.messages(self.project), [])
        marker = json.loads((runtime / "ui" / "chat-state.json").read_text(encoding="utf-8"))
        self.assertEqual(marker["last_assistant_run_id"], "run-clear")

    def test_clear_chat_history_is_blocked_only_for_running_project(self) -> None:
        self.state.append_message(self.project, "user", "keep while running")
        with patch.object(self.state, "read_runtime", return_value={"running": True}):
            with self.assertRaisesRegex(ValueError, "Cannot clear chat history while this Project is running"):
                self.state.clear_chat_history(self.project)
        self.assertTrue(self.state.messages(self.project))

    def test_clear_chat_history_remains_available_for_other_idle_project(self) -> None:
        other = self.root / "other-project"; other.mkdir()
        self.state.append_message(other, "user", "clear me")
        def runtime(project):
            return {"running": Path(project).resolve() == self.project.resolve()}
        with patch.object(self.state, "read_runtime", side_effect=runtime):
            self.assertEqual(self.state.clear_chat_history(other), {"ok": True})
        self.assertEqual(self.state.messages(other), [])

    def test_clear_chat_history_does_not_touch_runner_or_request_snapshots(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-active", "completed": False})
        request = runtime / "ui" / "requests" / "r1"
        request.mkdir(parents=True)
        (request / "prompt.md").write_text("keep request", encoding="utf-8")
        self.state.append_message(self.project, "user", "remove me")

        self.state.clear_chat_history(self.project)

        self.assertEqual(self.state.messages(self.project), [])
        self.assertTrue((runtime / "state.json").is_file())
        self.assertTrue((request / "prompt.md").is_file())

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

    def test_runtime_fallback_exposes_plan_todos_in_cli_format(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {
            "run_id": "run-plan",
            "cycle": 2,
            "current": 1,
            "completed": False,
            "stage": "execute",
            "tasks": [
                {"id": "t1", "title": "First TODO", "status": "completed", "attempts": 1},
                {"id": "t2", "title": "Second TODO", "status": "pending", "attempts": 2},
            ],
        })
        info = self.state.read_runtime(self.project)
        self.assertFalse(info["console_snapshot_exists"])
        self.assertEqual(info["completed_count"], 1)
        self.assertEqual(info["cli_tasks"][0]["mark"], "x")
        self.assertEqual(info["cli_tasks"][1]["mark"], ">")
        self.assertEqual(info["cli_lines"][:4], [
            "AI Task Runner  Cycle 2  Progress 1/2",
            "",
            "  [x] 1. First TODO",
            "  [>] 2. Second TODO",
        ])

    def test_runtime_prefers_current_console_snapshot_status(self) -> None:
        runtime = self.project / ".ai-task-runner"
        tasks = [{"id": "t1", "title": "Plan TODO", "status": "pending", "attempts": 0}]
        self.write_json(runtime / "state.json", {"run_id": "run-cli", "cycle": 1, "current": 0, "completed": False, "stage": "execute", "tasks": tasks})
        self.write_json(runtime / "console-view.json", {
            "run_id": "run-cli", "cycle": 1, "current": 0, "completed": False,
            "completed_count": 0, "total": 1, "status": "AI running skill", "detail": "Plan TODO",
            "tasks": [{"index": 1, **tasks[0], "mark": ">", "line": "  [>] 1. Plan TODO"}],
            "lines": ["AI Task Runner  Cycle 1  Progress 0/1", "", "  [>] 1. Plan TODO", "", "  {spinner} AI running skill", "    Plan TODO"],
        })
        info = self.state.read_runtime(self.project)
        self.assertTrue(info["console_snapshot_exists"])
        self.assertEqual(info["cli_status"], "AI running skill")
        self.assertEqual(info["cli_detail"], "Plan TODO")

    def test_project_list_reports_runtime_status(self) -> None:
        self.state.add_project(str(self.project))
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-status", "completed": False})
        self.assertEqual(self.state.projects()[0]["runtime_status"], "stopped")
        self.write_json(runtime / "runner-process.json", {"supervisor_pid": 12345})
        with patch.object(UIState, "_pid_alive", return_value=True):
            self.assertEqual(self.state.projects()[0]["runtime_status"], "running")

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
            self.state._clear_launch_reservation(self.project)
            self.state.launch(self.project, "again", mode="rerun")
            rerun = popen.call_args.args[0]
            self.assertIn("--force-new", rerun)
            self.assertIn("again", rerun)

    def test_launch_reservation_blocks_duplicate_before_runner_marker_exists(self) -> None:
        process = type("Process", (), {"pid": 24680})()
        with patch("ui.server.subprocess.Popen", return_value=process) as popen, patch.object(
            UIState, "_pid_alive", side_effect=lambda pid, alive_pids=None: pid in {24680, os.getpid()}
        ):
            self.state.launch(self.project, "first", mode="run")
            info = self.state.read_runtime(self.project)
            self.assertTrue(info["running"])
            self.assertTrue(info["launching"])
            with self.assertRaisesRegex(ValueError, "already has an active runtime"):
                self.state.launch(self.project, "second", mode="run")
        self.assertEqual(popen.call_count, 1)

    def test_launch_reservation_survives_ui_state_reopen_until_runner_takes_over(self) -> None:
        process = type("Process", (), {"pid": 24681})()
        with patch("ui.server.subprocess.Popen", return_value=process), patch.object(
            UIState, "_pid_alive", side_effect=lambda pid, alive_pids=None: pid in {24681, 24682, os.getpid()}
        ):
            self.state.launch(self.project, "first", mode="run")
            reopened = UIState(self.root)
            self.assertTrue(reopened.read_runtime(self.project)["launching"])
            self.write_json(
                self.project / ".ai-task-runner" / "runner-process.json",
                {"supervisor_pid": 24682, "worker_pid": 77},
            )
            info = reopened.read_runtime(self.project)
            self.assertTrue(info["running"])
            self.assertFalse(info["launching"])
            self.assertFalse((self.project / ".ai-task-runner" / "ui" / "launching.json").exists())

    def test_dead_launch_reservation_is_cleaned_and_does_not_block_relaunch(self) -> None:
        launch = self.project / ".ai-task-runner" / "ui" / "launching.json"
        self.write_json(launch, {"token": "old", "owner_pid": 1, "child_pid": 99999, "created_at": time.time(), "mode": "run"})
        process = type("Process", (), {"pid": 24683})()
        with patch.object(UIState, "_pid_alive", side_effect=lambda pid, alive_pids=None: pid in {24683, os.getpid()}), patch(
            "ui.server.subprocess.Popen", return_value=process
        ) as popen:
            self.assertFalse(self.state.read_runtime(self.project)["running"])
            self.state.launch(self.project, "again", mode="run")
        self.assertEqual(popen.call_count, 1)

    def test_launch_marker_update_failure_keeps_prelaunch_reservation_active(self) -> None:
        process = type("Process", (), {"pid": 24684})()
        with patch("ui.server.subprocess.Popen", return_value=process), patch.object(
            self.state, "_update_launch_reservation", side_effect=OSError("disk busy")
        ), patch.object(UIState, "_pid_alive", side_effect=lambda pid, alive_pids=None: pid == os.getpid()):
            self.state.launch(self.project, "first", mode="run")
            info = self.state.read_runtime(self.project)
            self.assertTrue(info["running"])
            self.assertTrue(info["launching"])
            with self.assertRaisesRegex(ValueError, "already has an active runtime"):
                self.state.launch(self.project, "second", mode="run")

    def test_stop_writes_only_stop_request(self) -> None:
        self.state.stop(self.project)
        path = self.project / ".ai-task-runner" / "stop.request"
        self.assertEqual(path.read_text(encoding="utf-8"), "stop\n")


    def test_workflow_builder_system_workflow_is_hidden_from_studio_files(self) -> None:
        system_dir = self.root / "runner" / "workflow" / "system"
        system_dir.mkdir(parents=True, exist_ok=True)
        (system_dir / "workflow_builder.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")
        (system_dir / "file.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")
        names = [item["name"] for item in self.state.studio_files()["workflows"]]
        assert "workflow_builder.yaml" not in names
        assert "file.yaml" in names

    def test_custom_workflow_and_prompt_can_be_created_in_nested_folders(self):
        workflow_folder = self.state.studio_custom_folder_create("workflow", "e2e/regression")
        self.assertIn("e2e/regression", workflow_folder["folders"])
        original_validate = self.state._validate_workflow_before_write
        self.state._validate_workflow_before_write = lambda path, content: {"ok": True}
        try:
            created_workflow = self.state.studio_workflow_create("nested", "custom", self.project, "e2e/regression")
        finally:
            self.state._validate_workflow_before_write = original_validate
        self.assertTrue(Path(created_workflow["file"]["path"]).is_file())
        self.assertEqual(created_workflow["item"]["display_name"], "e2e/regression/nested.workflow.yaml")

        prompt_folder = self.state.studio_custom_folder_create("prompt", "e2e")
        self.assertIn("e2e", prompt_folder["folders"])
        created_prompt = self.state.studio_prompt_create("review", "custom", self.project, "e2e")
        self.assertTrue(Path(created_prompt["file"]["path"]).is_file())
        self.assertEqual(created_prompt["item"]["display_name"], "e2e/review.md")

    def test_custom_folder_rejects_path_escape(self):
        for bad in ("../escape", "e2e/../escape", "/absolute", "C:/absolute"):
            with self.assertRaises(ValueError):
                self.state.studio_custom_folder_create("workflow", bad)

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
        (self.root / "runner" / "prompts" / "system").mkdir(parents=True)
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
        (self.root / "runner" / "prompts" / "loader.py").write_text(
            "def render_prompt(name, values=None): return ''\n"
            "def ai_rules(root): return render_prompt('system/rules.md', {'project': {'root': str(root)}, 'plugin_rules': ''})\n",
            encoding="utf-8",
        )
        (self.root / "runner" / "prompts" / "system" / "rules.md").write_text("{{ project.root }}\n{{ plugin_rules }}\n", encoding="utf-8")
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

    def test_custom_workflow_and_prompt_are_classified_custom(self) -> None:
        skill = self.root / "runner" / "workflow" / "custom" / "fixture_custom_workflow.yaml"
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

    def test_system_loader_prompts_use_their_real_variable_contracts(self) -> None:
        files = self.state.studio_files(self.project)
        rules = next(row for row in files["prompts"] if row["name"] == "rules.md")
        self.assertFalse(any(row["name"] == "structured_output_retry.md" for row in files["prompts"]))
        rules_check = self.state.studio_prompt_check(rules["id"], "{{ project.root }} / {{ plugin_rules }}", self.project)
        self.assertTrue(rules_check["ok"]); self.assertEqual(rules_check["contract"], "loader")
        rules_tags = {row["key"] for row in self.state.studio_prompt_tags(rules["id"], self.project)["tags"]}
        self.assertEqual(rules_tags, {"project", "project.root", "plugin_rules"})

    def test_all_bundled_prompt_contracts_have_no_false_warning(self) -> None:
        for item in self.state.studio_files(self.project)["prompts"]:
            path = Path(item["path"])
            check = self.state.studio_prompt_check(item["id"], path.read_text(encoding="utf-8"), self.project)
            self.assertTrue(check["ok"], f"{path}: {check}")

    def test_prompt_validate_api_contract_uses_current_unsaved_content(self) -> None:
        custom_prompt = self.root / "runner" / "prompts" / "custom" / "validate.md"
        custom_prompt.write_text("{{ goal }}\n", encoding="utf-8")
        item = next(x for x in self.state.studio_files(self.project)["prompts"] if x["path"] == str(custom_prompt.resolve()))
        ok = self.state.studio_validate(item["id"], self.project, content="{{ project.root }}\n")
        bad = self.state.studio_validate(item["id"], self.project, content="{{ unknown_prompt_var }}\n")
        self.assertTrue(ok["ok"]); self.assertEqual(ok["summary"], "Prompt validation passed")
        self.assertFalse(bad["ok"]); self.assertIn("unknown_prompt_var", bad["output"])

    def test_prompt_import_must_pass_validation_before_file_is_created(self) -> None:
        target = self.root / "runner" / "prompts" / "custom" / "bad_import.md"
        with self.assertRaisesRegex(ValueError, "Invalid Prompt template"):
            self.state.studio_import("prompt", "bad_import.md", "{{ missing_tag }}\n", "custom", self.project)
        self.assertFalse(target.exists())
        result = self.state.studio_import("prompt", "good_import.md", "{{ goal }}\n", "custom", self.project)
        self.assertTrue(Path(result["item"]["path"]).is_file())

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
        path = self.project / ".ai-task-runner" / "workflows" / "regression" / "workflow" / "regression.workflow.yaml"
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

    def test_visual_save_reorder_keeps_flow_mapping_entries_indented_and_parseable(self) -> None:
        self.workflow.write_text(
            "stages:\n  preflight:\n    type: command\n  planning:\n    type: plan\nflow:\n  - stage: planning\n    scope: workflow\n  - preflight\n",
            encoding="utf-8",
        )
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        self.state.studio_visual_save(
            item["id"],
            [{"stage": "preflight", "scope": "workflow"}, {"stage": "planning", "scope": "workflow"}],
            opened["hash"],
            self.project,
        )
        updated = self.workflow.read_text(encoding="utf-8")
        parsed = __import__("yaml").safe_load(updated)
        self.assertIn("flow:\n  - stage: preflight", updated)
        self.assertEqual(parsed["flow"][0]["stage"], "preflight")
        self.assertEqual(parsed["flow"][1]["stage"], "planning")

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

    def test_stage_save_supports_bounded_recovery_flow_fields(self) -> None:
        self.workflow.write_text(
            "stages:\n  review:\n    type: review\n    recover: [review]\nflow:\n  - review\n", encoding="utf-8"
        )
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(
            item["id"], "review", {}, opened["hash"], self.project, flow_index=0,
            flow_fields={"max_attempts": 3, "on_exhausted": "continue"},
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertEqual(data["flow"][0]["max_attempts"], 3)
        self.assertEqual(data["flow"][0]["on_exhausted"], "continue")
        self.assertNotIn("max_attempts", data["stages"]["review"])

    def test_stage_save_rejects_bounded_recovery_without_recover(self) -> None:
        self.workflow.write_text("stages:\n  review:\n    type: review\nflow:\n  - review\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "max_attempts requires recover"):
            self.state.studio_stage_save(
                item["id"], "review", {}, opened["hash"], self.project, flow_index=0,
                flow_fields={"max_attempts": 3, "on_exhausted": "continue"},
            )

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

    def test_workflow_rename_and_duplicate_preserve_validated_content(self) -> None:
        item = self._workflow_item()
        renamed = self.state.studio_rename(item["id"], "renamed.workflow.yaml", self.project)
        renamed_path = self.root / "runner" / "workflow" / "custom" / "renamed.workflow.yaml"
        self.assertTrue(renamed_path.is_file()); self.assertFalse(self.workflow.exists())
        copied = self.state.studio_duplicate(renamed["item"]["id"], "renamed copy.workflow.yaml", self.project)
        copy_path = self.root / "runner" / "workflow" / "custom" / "renamed copy.workflow.yaml"
        self.assertTrue(copy_path.is_file())
        self.assertEqual(copy_path.read_text(encoding="utf-8"), renamed_path.read_text(encoding="utf-8"))
        self.assertEqual(copied["item"]["group"], "Custom")

    def test_prompt_rename_is_blocked_when_referenced_but_duplicate_is_allowed(self) -> None:
        prompt = self.root / "runner" / "prompts" / "custom" / "used.md"; prompt.write_text("{{goal}}\n", encoding="utf-8")
        self.workflow.write_text("stages:\n  work:\n    type: task\n    prompt: custom/used.md\nflow: [work]\n", encoding="utf-8")
        item = next(x for x in self.state.studio_files(self.project)["prompts"] if x["path"] == str(prompt.resolve()))
        with self.assertRaisesRegex(ValueError, "still referenced"):
            self.state.studio_rename(item["id"], "renamed.md", self.project)
        copied = self.state.studio_duplicate(item["id"], "used copy.md", self.project)
        self.assertTrue(Path(copied["item"]["path"]).is_file())
        self.assertEqual(copied["item"]["group"], "Custom")

    def test_system_workflow_duplicate_goes_to_custom_without_mutating_system(self) -> None:
        system = next(x for x in self.state.studio_files(self.project)["workflows"] if x["path"] == str(self.system_workflow.resolve()))
        copied = self.state.studio_duplicate(system["id"], "system copy.workflow.yaml", self.project)
        self.assertEqual(copied["item"]["group"], "Custom")
        self.assertTrue(self.system_workflow.is_file())
        self.assertTrue((self.root / "runner" / "workflow" / "custom" / "system copy.workflow.yaml").is_file())

    def test_stage_definition_delete_removes_selected_flow_and_definition_preserving_other_text(self) -> None:
        self.workflow.write_text("# keep header\nstages:\n  work:\n    type: task\n    status: Working\n  review:\n    type: review\n\nflow:\n  - work\n  - review\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_delete(item["id"], "work", opened["hash"], self.project, flow_index=0)
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertNotIn("work", data["stages"]); self.assertEqual(data["flow"], ["review"])
        self.assertIn("# keep header", result["file"]["content"]); self.assertIn("review:", result["file"]["content"])

    def test_stage_definition_delete_is_blocked_by_other_flow_or_recovery_reference(self) -> None:
        self.workflow.write_text("stages:\n  work:\n    type: task\n  review:\n    type: review\n    recover: [work]\nflow:\n  - work\n  - review\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "still referenced"):
            self.state.studio_stage_delete(item["id"], "work", opened["hash"], self.project, flow_index=0)
        self.assertIn("work", __import__("yaml").safe_load(self.workflow.read_text(encoding="utf-8"))["stages"])
        self.workflow.write_text("stages:\n  work:\n    type: task\nflow:\n  - work\n  - work\n", encoding="utf-8")
        item = self._workflow_item(); opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "still referenced"):
            self.state.studio_stage_delete(item["id"], "work", opened["hash"], self.project, flow_index=0)

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
        self.assertEqual(exported["kind"], "prompt")
        self.assertEqual(exported["name"], "my_prompt.md")
        self.assertEqual(exported["content"], (self.root / "runner" / "prompts" / "custom" / "my_prompt.md").read_text(encoding="utf-8"))

    def _write_builder_fixture(self) -> Path:
        builder_dir = self.root / "workflow_builder"
        builder_dir.mkdir(exist_ok=True)
        for name in ("run.py", "validation.py", "publish.py"):
            (builder_dir / name).write_text("print('ok')\n", encoding="utf-8")
        (builder_dir / "workflow_builder.yaml").write_text("stages: {}\nflow: []\n", encoding="utf-8")
        (builder_dir / "prompt.md").write_text("{{ goal }}\n", encoding="utf-8")
        return builder_dir

    def test_ai_workflow_builder_launches_hidden_draft_job_without_project(self) -> None:
        builder_dir = self._write_builder_fixture()
        with patch("ui.server.subprocess.Popen") as popen:
            result = self.state.studio_generate_workflow(
                "Create a review + validation workflow", backend="qwen",
                folder="generated", filename="generated.workflow.yaml"
            )
        self.assertEqual(result["folder"], "generated")
        self.assertEqual(result["filename"], "generated.workflow.yaml")
        command = popen.call_args.args[0]
        self.assertIn(str(builder_dir / "run.py"), command)
        self.assertIn("--project-root", command)
        workspace = Path(command[command.index("--project-root") + 1]).resolve()
        expected = (self.root / "ui" / "data" / "workflow-builder" / result["job_id"]).resolve()
        self.assertEqual(workspace, expected)
        self.assertNotEqual(workspace, self.project.resolve())
        self.assertIn("--request", command); self.assertIn("Create a review + validation workflow", command)
        self.assertIn("--draft-only", command); self.assertIn("--job-dir", command)
        self.assertEqual(Path(command[command.index("--job-dir") + 1]).resolve(), expected)
        self.assertNotIn("--output-workflow", command)
        self.assertIn("--backend", command); self.assertIn("qwen", command)
        self.assertRegex(result["job_id"], r"^[a-f0-9]{12}$")
        self.assertEqual(Path(result["workspace"]).resolve(), expected)
        active = json.loads((self.root / "ui" / "data" / "workflow-builder" / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["job_id"], result["job_id"])
        self.assertFalse(any((self.root / "runner" / "workflow" / "custom").glob("generated*.yaml")))
        status = json.loads((expected / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status["state"], "queued")
        self.assertEqual(popen.call_args.kwargs["stdout"], subprocess.DEVNULL)
        if os.name == "nt": self.assertTrue(popen.call_args.kwargs.get("creationflags", 0))
        else: self.assertTrue(popen.call_args.kwargs.get("start_new_session"))

    def test_ai_workflow_builder_active_registry_survives_browser_reopen_and_blocks_second_job(self) -> None:
        self._write_builder_fixture()
        with patch("ui.server.subprocess.Popen") as popen:
            first = self.state.studio_generate_workflow("first request", backend="qwen", folder="generated", filename="first.workflow.yaml")
            active_path = self.root / "ui" / "data" / "workflow-builder" / "active.json"
            self.assertTrue(active_path.is_file())
            self.assertEqual(json.loads(active_path.read_text(encoding="utf-8"))["job_id"], first["job_id"])
            active = self.state.studio_generate_active()
            self.assertTrue(active["active"]); self.assertEqual(active["job_id"], first["job_id"])
            self.assertEqual(active["request"], "first request"); self.assertEqual(active["backend"], "qwen")
            self.assertEqual(Path(active["workspace"]).resolve(), (self.root / "ui" / "data" / "workflow-builder" / first["job_id"]).resolve())
            second = self.state.studio_generate_workflow("second request", backend="opencode", folder="generated", filename="second.workflow.yaml")
        self.assertTrue(second["existing"]); self.assertEqual(second["job_id"], first["job_id"]); self.assertEqual(popen.call_count, 1)

    def test_ai_workflow_builder_ready_active_job_restores_until_discard(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef333333"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        result = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "status.json").write_text(json.dumps({"state": "ready", "message": "Draft ready", "request": "make it", "backend": "qwen", "folder": "e2e", "filename": "review.workflow.yaml", "result": result, "runtime_cleared": True}), encoding="utf-8")
        self.state._builder_set_active(job_id)
        restored = self.state.studio_generate_active()
        self.assertTrue(restored["active"]); self.assertEqual(restored["state"], "ready"); self.assertIn("draft", restored)
        self.assertEqual(restored["folder"], "e2e"); self.assertEqual(restored["filename"], "review.workflow.yaml")
        self.state.studio_generate_discard(job_id)
        self.assertFalse((self.root / "ui" / "data" / "workflow-builder" / "active.json").exists())
        self.assertFalse(self.state.studio_generate_active()["active"])

    def test_ai_workflow_builder_ready_status_returns_preview_and_discard_removes_draft(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef123456"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        (prompts / "review.md").write_text("{{ goal }}\n", encoding="utf-8")
        result = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (root / "status.json").write_text(json.dumps({"state": "ready", "message": "Draft ready", "result": result, "runtime_cleared": True}), encoding="utf-8")
        status = self.state.studio_generate_status(job_id)
        self.assertEqual(status["state"], "ready"); self.assertIn("stages", status["draft"]["workflow"])
        self.assertEqual(status["draft"]["prompts"][0]["name"], "review.md")
        self.state.studio_generate_discard(job_id)
        self.assertFalse(root.exists())

    def test_ai_workflow_builder_save_custom_without_project(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef654321"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        result = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (root / "status.json").write_text(json.dumps({"state": "ready", "result": result, "runtime_cleared": True}), encoding="utf-8")
        self.state._builder_set_active(job_id)
        target = self.root / "runner" / "workflow" / "custom" / "generated" / "generated.workflow.yaml"
        def fake_publish(*args, **kwargs):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(workflow.read_text(encoding="utf-8"), encoding="utf-8")
            return subprocess.CompletedProcess(args=[], returncode=0, stdout='{"ok":true}', stderr="")
        with patch.object(self.state, "_builder_validate_draft", return_value={"ok": True, "output": "PASS"}), patch("ui.server.subprocess.run", side_effect=fake_publish):
            saved = self.state.studio_generate_save(None, job_id, "generated", "generated", "custom")
        self.assertTrue(target.is_file()); self.assertEqual(saved["item"]["group"], "Custom"); self.assertFalse(root.exists())
        self.assertFalse((self.root / "ui" / "data" / "workflow-builder" / "active.json").exists())


    def test_ai_workflow_builder_save_is_blocked_when_dryrun_validation_fails(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef654323"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        result = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "result.json").write_text(json.dumps(result), encoding="utf-8")
        (root / "status.json").write_text(json.dumps({"state": "ready", "result": result, "runtime_cleared": True}), encoding="utf-8")
        self.state._builder_set_active(job_id)
        target = self.root / "runner" / "workflow" / "custom" / "generated-fail" / "generated-fail.workflow.yaml"
        with patch.object(self.state, "_builder_validate_draft", side_effect=ValueError("Workflow draft validation failed: workflow dry-run failed")), patch("ui.server.subprocess.run") as publish:
            with self.assertRaisesRegex(ValueError, "dry-run failed"):
                self.state.studio_generate_save(None, job_id, "generated-fail", "generated-fail", "custom")
        self.assertFalse(target.exists())
        publish.assert_not_called()

    def test_ai_workflow_builder_project_destination_requires_project_only_at_save(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef654322"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        manifest = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "status.json").write_text(json.dumps({"state": "ready", "result": manifest}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Open a Project before saving"):
            self.state.studio_generate_save(None, job_id, "generated", "generated", "project")

    def test_ai_workflow_builder_each_generate_starts_fresh_and_cleans_old_ready_draft(self) -> None:
        self._write_builder_fixture()
        old = self.root / "ui" / "data" / "workflow-builder" / "abcdef000001"
        old.mkdir(parents=True); (old / "status.json").write_text(json.dumps({"state": "ready", "updated_at": 1}), encoding="utf-8")
        with patch("ui.server.subprocess.Popen"):
            result = self.state.studio_generate_workflow("new draft", backend="qwen", folder="generated", filename="new.workflow.yaml")
        self.assertFalse(old.exists())
        self.assertNotEqual(result["job_id"], "abcdef000001")

    def test_ai_workflow_builder_cancel_stops_only_isolated_builder_runtime(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef111111"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        root.mkdir(parents=True); (root / "status.json").write_text(json.dumps({"state": "running", "pid": 123}), encoding="utf-8")
        result = self.state.studio_generate_cancel(job_id)
        self.assertEqual(result["state"], "cancelling")
        self.assertTrue((root / "cancel.request").is_file())
        self.assertTrue((root / ".ai-task-runner" / "stop.request").is_file())
        self.assertFalse((self.project / ".ai-task-runner" / "stop.request").exists())

    def test_ai_workflow_builder_validate_accepts_current_draft_edits(self) -> None:
        self._write_builder_fixture(); job_id = "abcdef222222"
        root = self.root / "ui" / "data" / "workflow-builder" / job_id
        prompts = root / "draft" / "prompts"; prompts.mkdir(parents=True)
        workflow = root / "draft" / "workflow.yaml"; workflow.write_text("stages: {}\nflow: []\n", encoding="utf-8")
        prompt = prompts / "review.md"; prompt.write_text("{{ goal }}\n", encoding="utf-8")
        manifest = {"draft_workflow": str(workflow), "draft_prompt_dir": str(prompts), "validation": "PASS"}
        (root / "result.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "status.json").write_text(json.dumps({"state": "ready", "result": manifest}), encoding="utf-8")
        with patch.object(self.state, "_builder_validate_draft", return_value={"ok": True, "output": "PASS"}):
            result = self.state.studio_generate_validate(job_id, "stages: {}\nflow: []\n", [{"name": "review.md", "content": "{{ project.root }}\n"}])
        self.assertTrue(result["ok"]); self.assertIn("project.root", prompt.read_text(encoding="utf-8"))
        self.assertIn("visual", result["draft"])

    def test_ai_workflow_builder_rejects_incomplete_external_builder_without_project(self) -> None:
        builder_dir = self.root / "workflow_builder"; builder_dir.mkdir()
        (builder_dir / "run.py").write_text("print('builder')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            self.state.studio_generate_workflow("Create workflow", folder="generated", filename="generated.workflow.yaml")

    def test_studio_check_reports_yaml_location(self) -> None:
        item = self._workflow_item()
        result = self.state.studio_check(item["id"], "stages:\n  review: [\n", self.project)
        self.assertFalse(result["ok"]); self.assertGreaterEqual(result["line"], 1); self.assertGreaterEqual(result["column"], 1)


class ProjectPollingEfficiencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "ui" / "data").mkdir(parents=True)
        self.projects = []
        for index, pid in enumerate((111, 222, 333), 1):
            project = self.root / f"project-{index}"
            runtime = project / ".ai-task-runner"
            runtime.mkdir(parents=True)
            (runtime / "runner-process.json").write_text(
                json.dumps({"supervisor_pid": pid}), encoding="utf-8"
            )
            self.projects.append(project)
        self.state = UIState(self.root)
        self.state._write_projects([
            {"name": project.name, "path": str(project)} for project in self.projects
        ])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_project_list_uses_one_process_snapshot_for_all_projects(self) -> None:
        with patch.object(self.state, "_process_snapshot", return_value={111, 222}) as snapshot, \
             patch("ui.server.subprocess.run") as process_run:
            rows = self.state.projects()
        snapshot.assert_called_once_with()
        process_run.assert_not_called()
        self.assertEqual([row["runtime_status"] for row in rows], ["running", "running", "idle"])


def test_process_snapshot_windows_branch_has_csv_import():
    """Regression: Windows process snapshot must not fail with NameError for csv."""
    import ast
    from pathlib import Path

    server_path = Path(__file__).resolve().parents[1] / "server.py"
    source = server_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "csv" in imported, "ui/server.py uses csv in Windows process snapshot but does not import csv"


class WorkflowRequirementCacheContractTests(unittest.TestCase):
    def test_workflow_requirements_cache_tracks_file_version(self):
        source = Path(__file__).resolve().parents[1] / "server.py"
        text = source.read_text(encoding="utf-8")
        self.assertIn("_workflow_requirement_cache", text)
        self.assertIn("stat.st_mtime_ns", text)
        self.assertIn('item["version"]', text)


class ModelSelectionContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = UIState(self.root)
        self.project = self.root / "project"
        self.project.mkdir()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_model_is_passed_as_backend_agent_argument(self) -> None:
        with patch.object(self.state, "read_runtime", return_value={"running": False}), patch("ui.server.subprocess.Popen") as popen:
            self.state.launch(self.project, "fix it", mode="run", backend="qwen", model="qwen3-coder")
        command = popen.call_args.args[0]
        self.assertIn("--agent-arg=--model", command)
        self.assertIn("--agent-arg=qwen3-coder", command)

    def test_runtime_reports_latest_ui_request_model(self) -> None:
        request_dir = self.project / ".ai-task-runner" / "ui" / "requests" / "req-1"
        request_dir.mkdir(parents=True)
        (request_dir / "request.json").write_text(json.dumps({"backend": "qwen", "model": "qwen3-coder", "workflow": "w.yaml", "validator": ""}), encoding="utf-8")
        runtime = self.state.read_runtime(self.project)
        self.assertEqual(runtime["backend"], "qwen")
        self.assertEqual(runtime["model"], "qwen3-coder")

    def test_model_validation_rejects_control_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "Model name is invalid"):
            self.state._normalize_model("bad\nmodel")
