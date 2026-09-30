from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from project_registry import path_key
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
        assets = self.root / "runner" / "assets" / "workflows"
        assets.mkdir(parents=True)
        self.workflow = assets / "task.workflow.yaml"
        self.workflow.write_text("stages:\n  planning:\n    type: plan\nflow:\n  - planning\n", encoding="utf-8")
        backends = self.root / "runner" / "agent"; backends.mkdir(parents=True)
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
        with patch("ui.project_runtime_state.subprocess.run", return_value=completed) as run:
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
        with patch("ui.project_runtime_state.os.name", "nt"), patch("ui.project_runtime_state.subprocess.run", return_value=completed) as run:
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

    def test_add_project_deduplicates_equivalent_path_spellings(self) -> None:
        self.state.add_project(str(self.project) + os.sep)
        self.state.add_project(str(self.project))

        rows = self.state.projects()

        self.assertEqual(len(rows), 1)
        self.assertEqual(Path(rows[0]["path"]).resolve(), self.project.resolve())

    def test_write_projects_deduplicates_equivalent_path_spellings(self) -> None:
        self.state._write_projects([
            {"name": "First", "path": str(self.project) + os.sep},
            {"name": "Second", "path": str(self.project)},
        ])

        rows = self.state.projects()

        self.assertEqual(rows, [{
            "name": "First",
            "path": str(self.project.resolve()),
            "exists": True,
            "runtime_status": "idle",
            "runtime_stage": "",
            "runtime_completed_count": 0,
            "runtime_total": 0,
        }])

    def test_project_display_name_can_be_renamed_without_changing_path(self) -> None:
        self.state.add_project(str(self.project))

        renamed = self.state.rename_project(str(self.project), "  Login Worktree  ")
        rows = self.state.projects()

        self.assertEqual(renamed, {"name": "Login Worktree", "path": str(self.project.resolve())})
        self.assertEqual(rows[0]["name"], "Login Worktree")
        self.assertEqual(Path(rows[0]["path"]).resolve(), self.project.resolve())

    def test_project_rename_requires_existing_sidebar_project(self) -> None:
        with self.assertRaisesRegex(ValueError, "not in the sidebar"):
            self.state.rename_project(str(self.project), "New Name")

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

        self.assertEqual(self.state.clear_chat_history(self.project), {"ok": True, "runtime_reset": False})
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
            self.assertEqual(self.state.clear_chat_history(other), {"ok": True, "runtime_reset": False})
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

    def test_clear_chat_history_can_atomically_discard_stopped_runtime(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir(parents=True, exist_ok=True)
        self.write_json(runtime / "state.json", {
            "run_id": "stopped-1",
            "completed": False,
            "stage": "execute",
            "tasks": [{"id": "t1", "status": "pending"}],
        })
        self.state.append_message(self.project, "user", "old task")

        result = self.state.clear_chat_history(self.project, reset_stopped=True)

        self.assertEqual(result, {"ok": True, "runtime_reset": True})
        self.assertEqual(self.state.messages(self.project), [])
        self.assertFalse((runtime / "state.json").exists())
        self.assertFalse(self.state.read_runtime(self.project)["resumable"])

    def test_projects_payload_does_not_replay_cached_runtime_status(self) -> None:
        self.state.add_project(str(self.project))
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir(parents=True, exist_ok=True)
        self.write_json(runtime / "state.json", {
            "run_id": "status-1",
            "completed": False,
            "stage": "execute",
        })

        first = self.state.projects_payload()
        self.assertEqual(first["projects"][0]["runtime_status"], "stopped")

        self.write_json(runtime / "state.json", {
            "run_id": "status-1",
            "completed": True,
            "stage": "completed",
        })
        second = self.state.projects_payload()

        self.assertEqual(second["projects"][0]["runtime_status"], "completed")

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


    def test_yaml_script_runtime_follows_current_child_and_exposes_input_prompt(self) -> None:
        self.state.add_project(str(self.project))
        runtime = self.project / ".ai-task-runner"
        child_root = self.project / "child"
        child_runtime = child_root / ".ai-task-runner" / "script" / "002"
        child_runtime.mkdir(parents=True)
        self.write_json(runtime / "console-view.json", {
            "schema_version": 1,
            "mode": "script",
            "script_index": 2,
            "script_total": 3,
            "script_status": "running",
            "child_project_root": str(child_root.resolve()),
            "child_work_dir": ".ai-task-runner/script/002",
            "prompt_preview": "short preview",
            "updated_at": 123.0,
        })
        self.write_json(runtime / "runner-process.json", {"supervisor_pid": 12345, "worker_pid": 12346, "started_at": 100.0})
        tasks = [{"id": "t1", "title": "Child TODO", "status": "pending", "attempts": 1}]
        self.write_json(child_runtime / "state.json", {
            "run_id": "child-run-2",
            "goal": "full YAML item prompt",
            "cycle": 1,
            "current": 0,
            "completed": False,
            "stage": "review",
            "last_activity_at": 124.0,
            "tasks": tasks,
        })
        self.write_json(child_runtime / "console-view.json", {
            "run_id": "child-run-2",
            "cycle": 1,
            "current": 0,
            "completed": False,
            "completed_count": 0,
            "total": 1,
            "status": "AI reviewing",
            "detail": "Child TODO",
            "tasks": [{"index": 1, **tasks[0], "mark": ">", "line": "  [>] 1. Child TODO"}],
            "lines": ["AI Task Runner  Cycle 1  Progress 0/1", "", "  [>] 1. Child TODO", "", "  {spinner} AI reviewing"],
        })
        (child_runtime / "stream.log").write_text("child output", encoding="utf-8")

        with patch.object(UIState, "_pid_alive", return_value=True):
            info = self.state.read_runtime(self.project)
            project_row = self.state.projects()[0]

        self.assertTrue(info["running"])
        self.assertTrue(info["script_mode"])
        self.assertEqual((info["script_index"], info["script_total"]), (2, 3))
        self.assertEqual(info["run_id"], "child-run-2")
        self.assertEqual(info["stage"], "review")
        self.assertEqual(info["input_prompt"], "full YAML item prompt")
        self.assertEqual(info["stream"], "child output")
        self.assertEqual(info["cli_status"], "AI reviewing")
        self.assertEqual(info["cli_lines"][0], "AI Task Runner  Script 2/3")
        self.assertIn("Script 2/3", project_row["runtime_stage"])
        self.assertIn("review", project_row["runtime_stage"])

    def test_direct_cli_runtime_exposes_goal_as_input_prompt(self) -> None:
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {
            "run_id": "cli-run",
            "goal": "CLI supplied requirement",
            "completed": False,
            "stage": "execute",
            "tasks": [],
        })

        info = self.state.read_runtime(self.project)

        self.assertFalse(info["script_mode"])
        self.assertEqual(info["input_prompt"], "CLI supplied requirement")

    def test_finished_yaml_script_uses_outer_item_completion_not_child_only(self) -> None:
        runtime = self.project / ".ai-task-runner"
        child_runtime = self.project / ".ai-task-runner" / "script" / "002"
        self.write_json(runtime / "console-view.json", {
            "mode": "script",
            "script_index": 2,
            "script_total": 2,
            "script_status": "completed",
            "child_project_root": str(self.project.resolve()),
            "child_work_dir": ".ai-task-runner/script/002",
        })
        self.write_json(child_runtime / "state.json", {
            "run_id": "child-done",
            "goal": "second",
            "completed": True,
            "tasks": [],
        })

        info = self.state.read_runtime(self.project)

        self.assertTrue(info["completed"])
        self.assertFalse(info["resumable"])

    def test_project_list_reports_runtime_status(self) -> None:
        self.state.add_project(str(self.project))
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {"run_id": "run-status", "completed": False})
        self.assertEqual(self.state.projects()[0]["runtime_status"], "stopped")
        self.write_json(runtime / "runner-process.json", {"supervisor_pid": 12345})
        with patch.object(UIState, "_pid_alive", return_value=True):
            self.assertEqual(self.state.projects()[0]["runtime_status"], "running")

    def test_project_payload_suggests_slower_polling_under_load(self) -> None:
        for index in range(20):
            project = self.root / f"load-{index:02d}"
            project.mkdir()
            self.state.add_project(str(project))

        payload = self.state.projects_payload()

        self.assertEqual(payload["meta"]["total"], 20)
        self.assertEqual(payload["meta"]["suggested_poll_ms"], 12000)

    def test_project_list_reads_runtime_display_once_per_project(self) -> None:
        self.state.add_project(str(self.project))
        runtime = self.project / ".ai-task-runner"
        self.write_json(runtime / "state.json", {
            "run_id": "run-status",
            "completed": False,
            "stage": "execute",
            "tasks": [{"id": "t1", "status": "completed"}, {"id": "t2", "status": "pending"}],
        })

        original = self.state._runtime_display
        with patch.object(self.state, "_runtime_display", wraps=original) as runtime_display:
            row = self.state.projects()[0]

        runtime_display.assert_called_once()
        self.assertEqual(path_key(runtime_display.call_args.args[0]), path_key(self.project))
        self.assertEqual(row["runtime_stage"], "execute")
        self.assertEqual(row["runtime_completed_count"], 1)
        self.assertEqual(row["runtime_total"], 2)

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

    def test_failed_launch_removes_nested_request_snapshot_resources(self) -> None:
        self.workflow.write_text(
            "stages:\n  ai:\n    type: ai_validator\n    prompt: custom/validate.md\nflow: [ai]\n",
            encoding="utf-8",
        )
        custom = self.project / "my_ai_validation.md"
        custom.write_text("Check business rules.\n", encoding="utf-8")

        with patch.object(self.state, "launch", side_effect=ValueError("boom")):
            with self.assertRaisesRegex(ValueError, "boom"):
                self.state.launch_message(
                    self.project,
                    "hello",
                    workflow=str(self.workflow),
                    ai_validator_prompt_file=str(custom),
                )

        requests = self.project / ".ai-task-runner" / "ui" / "requests"
        self.assertEqual(list(requests.glob("*")) if requests.exists() else [], [])
        self.assertEqual(self.state.messages(self.project), [])

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

    def test_old_launch_reservation_expires_even_if_child_pid_is_reused(self) -> None:
        launch = self.project / ".ai-task-runner" / "ui" / "launching.json"
        self.write_json(launch, {
            "token": "old-reused",
            "owner_pid": 1,
            "child_pid": 24680,
            "created_at": time.time() - 30 - 5,
            "mode": "run",
        })
        with patch.object(UIState, "_pid_alive", return_value=True):
            info = self.state.read_runtime(self.project)

        self.assertFalse(info["running"])
        self.assertFalse(info["launching"])
        self.assertFalse(launch.exists())

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


    def test_global_workflows_are_visible_and_editable(self) -> None:
        assets = self.root / "runner" / "assets" / "workflows"
        (assets / "workflow_builder.yaml").write_text(
            "stages:\n  planning:\n    type: plan\nflow:\n  - planning\n",
            encoding="utf-8",
        )
        rows = self.state.studio_files(self.project)["workflows"]
        item = next(row for row in rows if row["name"] == "workflow_builder.yaml")
        self.assertEqual(item["scope"], "global")
        self.assertFalse(item["readonly"])

    def test_global_workflow_and_prompt_share_one_asset_package_but_separate_roots(self):
        original_validate = self.state._validate_workflow_before_write
        self.state._validate_workflow_before_write = lambda path, content: {"ok": True}
        try:
            workflow = self.state.studio_workflow_create("nested", "global", self.project)
        finally:
            self.state._validate_workflow_before_write = original_validate
        prompt = self.state.studio_prompt_create("common/review_copy", "global", self.project)

        self.assertEqual(
            Path(workflow["item"]["path"]).parent,
            (self.root / "runner" / "assets" / "workflows").resolve(),
        )
        self.assertEqual(
            Path(prompt["item"]["path"]).parent,
            (self.root / "runner" / "assets" / "prompts" / "common").resolve(),
        )
        self.assertEqual(prompt["item"]["reference"], "common/review_copy.md")
        self.assertEqual(workflow["item"]["group"], "Global")
        self.assertEqual(prompt["item"]["group"], "Global")

    def test_project_assets_mirror_global_workflow_and_prompt_roots(self):
        original_validate = self.state._validate_workflow_before_write
        self.state._validate_workflow_before_write = lambda path, content: {"ok": True}
        try:
            workflow = self.state.studio_workflow_create("project_job", "project", self.project)
        finally:
            self.state._validate_workflow_before_write = original_validate
        prompt = self.state.studio_prompt_create("common/project_review", "project", self.project)
        asset_root = (self.project / ".ai-task-runner" / "assets").resolve()
        self.assertEqual(Path(workflow["item"]["path"]).parent, asset_root / "workflows")
        self.assertEqual(Path(prompt["item"]["path"]).parent, asset_root / "prompts" / "common")
        self.assertEqual(prompt["item"]["reference"], "common/project_review.md")
        self.assertEqual(workflow["item"]["group"], "Project")
        self.assertEqual(prompt["item"]["group"], "Project")

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
                    self.assertEqual(payload["projects"], [])
                    self.assertEqual(payload["meta"]["suggested_poll_ms"], 8000)
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
        assets = self.root / "runner" / "assets" / "workflows"
        assets.mkdir(parents=True)
        (self.root / "runner" / "assets" / "prompts" / "common").mkdir(parents=True)
        (self.root / "runner" / "config").mkdir(parents=True)
        (self.root / "runner" / "agent").mkdir(parents=True)
        (self.root / "tool").mkdir(parents=True)

        (self.root / "tool" / "workflow_dryrun.py").write_text(
            "import json; print(json.dumps({'closed': True, 'valid': True, 'paths_passed': 1, 'paths_total': 1}))\n",
            encoding="utf-8",
        )
        (self.root / "runner" / "config" / "defaults.py").write_text(
            "DEFAULT_BACKEND='qwen'\n",
            encoding="utf-8",
        )
        (self.root / "runner" / "agent" / "qwen.py").write_text(
            "class QwenBackend: name='qwen'\n",
            encoding="utf-8",
        )
        (self.root / "runner" / "agent" / "opencode.py").write_text(
            "class OpenCodeBackend: name='opencode'\n",
            encoding="utf-8",
        )
        (self.root / "runner" / "prompting.py").write_text(
            "def _task_data(task): return {'id':'','title':'','description':'','acceptance_criteria':[]}\n"
            "def build_stage_prompt_context(ctx, stage, previous=None): "
            "return {'goal':'','stage':stage,'task':_task_data(None),'project':{'root':''},"
            "'previous':{'output':'','status':'','data':{}},"
            "'validation':{'feedback':''},'workflow':{'validator_feedback':''}}\n"
            "def render_prompt(name, values=None): return ''\n"
            "def ai_rules(root): return render_prompt('common/rules.md', {'project': {'root': str(root)}, 'plugin_rules': ''})\n",
            encoding="utf-8",
        )

        self.workflow = assets / "main.workflow.yaml"
        self.workflow.write_text(
            "stages:\n"
            "  work:\n"
            "    type: task\n"
            "    scope: task\n"
            "  review:\n"
            "    type: review\n"
            "    scope: task\n"
            "    routes:\n"
            "      fail: work\n"
            "flow:\n"
            "  - work\n"
            "  - review\n",
            encoding="utf-8",
        )
        ((self.root / "runner" / "assets" / "prompts" / "common") / "execution.md").write_text("Do {{ goal }}\n", encoding="utf-8")
        ((self.root / "runner" / "assets" / "prompts" / "common") / "review.md").write_text("Review {{ goal }}\n", encoding="utf-8")
        ((self.root / "runner" / "assets" / "prompts" / "common") / "rules.md").write_text(
            "{{ project.root }}\n{{ plugin_rules }}\n",
            encoding="utf-8",
        )

        self.project = self.root / "project"
        self.project.mkdir()
        self.state = UIState(self.root)
        self.state.add_project(str(self.project))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _workflow_item(self) -> dict:
        return next(
            item
            for item in self.state.studio_files(self.project)["workflows"]
            if item["path"] == str(self.workflow.resolve())
        )

    def test_studio_and_runtime_locks_remain_independent(self) -> None:
        locks = [
            self.state._launch_lock,
            self.state._edit_lock,
            self.state._builder_lock,
            self.state._runtime_lock,
        ]
        self.assertEqual(len({id(lock) for lock in locks}), len(locks))

    def test_global_workflow_and_prompt_are_editable_peer_assets(self) -> None:
        files = self.state.studio_files(self.project)
        workflow = next(row for row in files["workflows"] if row["name"] == "main.workflow.yaml")
        prompt = next(row for row in files["prompts"] if row["name"] == "execution.md")
        self.assertEqual(workflow["group"], "Global")
        self.assertEqual(prompt["group"], "Global")
        self.assertFalse(workflow["readonly"])
        self.assertFalse(prompt["readonly"])
        self.assertEqual(Path(workflow["path"]).parent.name, "workflows")
        self.assertEqual(Path(prompt["path"]).parent.name, "common")
        self.assertEqual(prompt["reference"], "common/execution.md")

    def test_workflow_builder_internal_prompt_is_not_a_studio_asset(self) -> None:
        internal = self.root / "workflow_builder" / "prompt.md"
        internal.parent.mkdir(parents=True)
        internal.write_text("internal builder prompt\n", encoding="utf-8")

        files = self.state.studio_files(self.project)
        listed = {Path(row["path"]).resolve() for row in files["prompts"]}
        self.assertNotIn(internal.resolve(), listed)
        self.assertTrue(all("workflow_builder" not in Path(row["path"]).parts for row in files["prompts"]))

    def test_stage_can_be_created_disconnected_until_edges_join_it_to_flow(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_add(
            item["id"],
            "detached_execute",
            "task",
            opened["hash"],
            self.project,
            add_to_flow=False,
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        self.assertIn("detached_execute", data["stages"])
        self.assertEqual(data["flow"], ["work", "review"])
        self.assertIn(
            "detached_execute",
            [stage["name"] for stage in result["visual"]["stages"]],
        )

    def test_graph_save_round_trips_session_policy_and_rejects_conflicting_session_key(self) -> None:
        item = self._workflow_item()
        visual = self.state.studio_visual(item["id"], self.project)
        work = {**visual["stages"][0], "session_policy": "role"}
        review = {**visual["stages"][1], "session_policy": "fresh"}
        draft = {
            "stages": [work, review],
            "flow": ["work", "review"],
            "routes": {"review": {"fail": "work"}},
        }

        saved = self.state.studio_graph_save(
            item["id"], draft, visual["hash"], self.project
        )
        data = __import__("yaml").safe_load(saved["file"]["content"])
        self.assertEqual(data["stages"]["work"]["session_policy"], "role")
        self.assertEqual(data["stages"]["review"]["session_policy"], "fresh")

        bad = self.state.studio_visual(item["id"], self.project)
        bad_work = {
            **bad["stages"][0],
            "session_policy": "role",
            "session_key": "conflict",
        }
        bad_draft = {
            "stages": [bad_work, bad["stages"][1]],
            "flow": ["work", "review"],
            "routes": {"review": {"fail": "work"}},
        }
        with self.assertRaisesRegex(ValueError, "session_key is only valid"):
            self.state.studio_graph_save(
                item["id"], bad_draft, bad["hash"], self.project
            )

    def test_graph_draft_validates_before_one_atomic_yaml_write(self) -> None:
        item = self._workflow_item()
        visual = self.state.studio_visual(item["id"], self.project)
        before = self.workflow.read_text(encoding="utf-8")
        work = {**visual["stages"][0], "label": "Do work"}
        command = {"name": "check", "type": "command", "command": "{python} -c 'print(1)'"}
        draft = {"stages": [work, command], "flow": ["work", "check"], "routes": {"work": {"fail": "check"}}}

        self.assertEqual(self.workflow.read_text(encoding="utf-8"), before)
        with self.assertRaisesRegex(ValueError, "unknown target"):
            self.state.studio_graph_save(item["id"], {**draft, "routes": {"work": {"fail": "missing"}}}, visual["hash"], self.project)
        self.assertEqual(self.workflow.read_text(encoding="utf-8"), before)

        saved = self.state.studio_graph_save(item["id"], draft, visual["hash"], self.project)
        content = self.workflow.read_text(encoding="utf-8")
        data = __import__("yaml").safe_load(content)
        self.assertEqual(data["flow"], ["work", "check"])
        self.assertEqual(data["stages"]["work"]["label"], "Do work")
        self.assertEqual(data["stages"]["work"]["routes"], {"fail": "check"})
        self.assertEqual(data["stages"]["check"]["type"], "command")
        self.assertNotIn("review", data["stages"])
        self.assertEqual(saved["visual"]["hash"], self.state.studio_visual(item["id"], self.project)["hash"])

    def test_graph_save_round_trips_session_policy_and_rejects_conflicting_session_key(self) -> None:
        item = self._workflow_item()
        visual = self.state.studio_visual(item["id"], self.project)
        work = {**visual["stages"][0], "session_policy": "role"}
        review = visual["stages"][1]
        draft = {
            "stages": [work, review],
            "flow": list(visual["flow"]),
            "routes": {"review": {"fail": "work"}},
        }

        saved = self.state.studio_graph_save(
            item["id"], draft, visual["hash"], self.project
        )
        data = __import__("yaml").safe_load(self.workflow.read_text(encoding="utf-8"))
        self.assertEqual(data["stages"]["work"]["session_policy"], "role")
        self.assertNotIn("session_key", data["stages"]["work"])

        conflict_visual = saved["visual"]
        conflict_work = {
            **conflict_visual["stages"][0],
            "session_policy": "role",
            "session_key": "stale-key",
        }
        conflict = {
            "stages": [conflict_work, conflict_visual["stages"][1]],
            "flow": list(conflict_visual["flow"]),
            "routes": {"review": {"fail": "work"}},
        }
        with self.assertRaisesRegex(ValueError, "session_key is only valid"):
            self.state.studio_graph_save(
                item["id"], conflict, conflict_visual["hash"], self.project
            )


    def test_global_and_project_assets_use_identical_split_shape(self) -> None:
        global_workflow = self.state.studio_workflow_create("global_job", "global", self.project)
        global_prompt = self.state.studio_prompt_create("common/global_review", "global", self.project)
        project_workflow = self.state.studio_workflow_create("project_job", "project", self.project)
        project_prompt = self.state.studio_prompt_create("common/project_review", "project", self.project)

        global_assets = (self.root / "runner" / "assets").resolve()
        project_assets = (self.project / ".ai-task-runner" / "assets").resolve()
        self.assertEqual(Path(global_workflow["item"]["path"]).parent, global_assets / "workflows")
        self.assertEqual(Path(global_prompt["item"]["path"]).parent, global_assets / "prompts" / "common")
        self.assertEqual(Path(project_workflow["item"]["path"]).parent, project_assets / "workflows")
        self.assertEqual(Path(project_prompt["item"]["path"]).parent, project_assets / "prompts" / "common")

    def test_prompt_contract_accepts_known_tags_and_rejects_unknown(self) -> None:
        prompt = next(
            row for row in self.state.studio_files(self.project)["prompts"]
            if row["name"] == "execution.md"
        )
        ok = self.state.studio_prompt_check(
            prompt["id"],
            "{{ goal }} / {{ project.root }} / {{ task.title }}",
            self.project,
        )
        bad = self.state.studio_prompt_check(
            prompt["id"],
            "{{ missing_tag }}",
            self.project,
        )
        self.assertTrue(ok["ok"])
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["unknown"], ["missing_tag"])

    def test_prompt_save_is_hash_guarded_and_server_validated(self) -> None:
        prompt = next(
            row for row in self.state.studio_files(self.project)["prompts"]
            if row["name"] == "execution.md"
        )
        opened = self.state.studio_read(prompt["id"], self.project)
        with self.assertRaisesRegex(ValueError, "Prompt validation failed"):
            self.state.studio_save(
                prompt["id"],
                "{{ unknown_ui_variable }}\n",
                opened["hash"],
                self.project,
            )
        saved = self.state.studio_save(
            prompt["id"],
            "{{ goal }} / {{ project.root }}\n",
            opened["hash"],
            self.project,
        )
        self.assertIn("project.root", saved["content"])

    def test_stage_node_owns_scope_label_and_result_edges_not_retry(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        result = self.state.studio_stage_save(
            item["id"],
            "review",
            {
                "label": "Review result",
                "scope": "task",
                "routes": {"fail": "work"},
            },
            opened["hash"],
            self.project,
        )
        data = __import__("yaml").safe_load(result["file"]["content"])
        stage = data["stages"]["review"]
        self.assertEqual(stage["scope"], "task")
        self.assertEqual(stage["label"], "Review result")
        self.assertEqual(stage["routes"], {"fail": "work"})

        opened = self.state.studio_read(item["id"], self.project)
        with self.assertRaisesRegex(ValueError, "Unsupported Stage field"):
            self.state.studio_stage_save(
                item["id"],
                "review",
                {"retry": -1},
                opened["hash"],
                self.project,
            )

    def test_visual_designer_is_one_stage_per_node_with_string_flow(self) -> None:
        visual = self.state.studio_visual(self._workflow_item()["id"], self.project)
        self.assertEqual(visual["flow"], ["work", "review"])
        self.assertEqual(
            [stage["name"] for stage in visual["stages"]],
            ["work", "review"],
        )
        review = next(stage for stage in visual["stages"] if stage["name"] == "review")
        self.assertEqual(review["scope"], "task")

    def test_visual_save_reorders_only_string_stage_names(self) -> None:
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        self.state.studio_visual_save(
            item["id"],
            ["review", "work"],
            opened["hash"],
            self.project,
        )
        data = __import__("yaml").safe_load(self.workflow.read_text(encoding="utf-8"))
        self.assertEqual(data["flow"], ["review", "work"])

    def test_duplicate_and_import_stay_in_the_selected_flat_scope(self) -> None:
        item = self._workflow_item()
        copied = self.state.studio_duplicate(
            item["id"],
            "copy.workflow.yaml",
            self.project,
        )
        self.assertEqual(
            Path(copied["item"]["path"]).parent,
            (self.root / "runner" / "assets" / "workflows").resolve(),
        )

        imported = self.state.studio_import(
            "prompt",
            "common/imported.md",
            "{{ goal }}\n",
            "project",
            self.project,
        )
        self.assertEqual(
            Path(imported["item"]["path"]).parent,
            (self.project / ".ai-task-runner" / "assets" / "prompts" / "common").resolve(),
        )

    def test_prompt_rename_is_blocked_while_referenced(self) -> None:
        prompt = self.root / "runner" / "assets" / "prompts" / "common" / "used.md"
        prompt.write_text("{{ goal }}\n", encoding="utf-8")
        self.workflow.write_text(
            "stages:\n"
            "  work:\n"
            "    type: base\n"
            "    prompt: common/used.md\n"
            "flow:\n"
            "  - work\n",
            encoding="utf-8",
        )
        item = next(
            row for row in self.state.studio_files(self.project)["prompts"]
            if row["path"] == str(prompt.resolve())
        )
        with self.assertRaisesRegex(ValueError, "still referenced"):
            self.state.studio_rename(item["id"], "renamed.md", self.project)

    def test_workflow_validation_uses_real_dryrun_boundary(self) -> None:
        item = self._workflow_item()
        fake = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"closed":true,"valid":true,"paths_passed":1,"paths_total":1}',
            stderr="",
        )
        with patch("ui.workflow_studio_state.subprocess.run", return_value=fake) as run:
            result = self.state.studio_validate(item["id"], self.project)
        self.assertTrue(result["ok"])
        command = run.call_args.args[0]
        self.assertIn("workflow_dryrun.py", " ".join(map(str, command)))
        self.assertIn("--matrix", command)
        self.assertIn("--json", command)

    def test_runtime_lock_blocks_global_and_project_asset_writes(self) -> None:
        runtime = self.project / ".ai-task-runner"
        runtime.mkdir()
        (runtime / "runner-process.json").write_text(
            json.dumps({"supervisor_pid": 1234}),
            encoding="utf-8",
        )
        item = self._workflow_item()
        opened = self.state.studio_read(item["id"], self.project)
        with patch.object(UIState, "_pid_alive", return_value=True):
            with self.assertRaisesRegex(ValueError, "runtime is active"):
                self.state.studio_save(
                    item["id"],
                    opened["content"] + "# change\n",
                    opened["hash"],
                    self.project,
                )


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
             patch("ui.project_runtime_state.subprocess.run") as process_run:
            rows = self.state.projects()
        snapshot.assert_called_once_with()
        process_run.assert_not_called()
        self.assertEqual([row["runtime_status"] for row in rows], ["running", "running", "idle"])

    def test_idle_project_list_skips_process_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "idle-project"
            project.mkdir(parents=True)
            state = UIState(root)
            state._write_projects([{"name": project.name, "path": str(project)}])

            with patch.object(state, "_process_snapshot") as snapshot:
                rows = state.projects()

        snapshot.assert_not_called()
        self.assertEqual(rows[0]["runtime_status"], "idle")

    def test_projects_payload_does_not_cache_live_runtime_status(self) -> None:
        with patch.object(self.state, "_process_snapshot", return_value={111, 222}) as snapshot:
            first = self.state.projects_payload()
            second = self.state.projects_payload()

        self.assertEqual(snapshot.call_count, 2)
        self.assertIsNot(first, second)


def test_windows_pid_probe_failure_does_not_report_process_dead(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0] if args else "tasklist", 2)

    monkeypatch.setattr("ui.project_runtime_state.os.name", "nt", raising=False)
    monkeypatch.setattr("ui.project_runtime_state.subprocess.run", fail)

    assert UIState._pid_alive(12345) is True


def test_process_snapshot_windows_branch_has_csv_import():
    """Regression: Windows process snapshot owner must import csv."""
    import ast
    from pathlib import Path

    runtime_path = Path(__file__).resolve().parents[1] / "project_runtime_state.py"
    source = runtime_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "csv" in imported, "ui/project_runtime_state.py uses csv in Windows process snapshot but does not import csv"


class WorkflowRequirementCacheContractTests(unittest.TestCase):
    def test_workflow_requirements_cache_tracks_file_version(self):
        ui_root = Path(__file__).resolve().parents[1]
        server = (ui_root / "server.py").read_text(encoding="utf-8")
        studio = (ui_root / "workflow_studio_state.py").read_text(encoding="utf-8")

        self.assertIn("_workflow_requirement_cache", server)
        self.assertIn("stat.st_mtime_ns", studio)
        self.assertIn('item["version"]', studio)


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


def test_remote_ui_requires_explicit_opt_in_helper():
    from ui.server import is_loopback_host
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("::1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")


def test_workflow_catalog_is_loaded_through_standalone_tool(tmp_path):
    state = UIState(tmp_path)
    payload = {
        "stage_types": {
            "dynamic_agent": {
                "type": "dynamic_agent",
                "options": [{"name": "prompt", "type": "str", "required": False}],
            }
        },
        "flow_options": {"restart_at": {"type": "stage"}},
    }
    completed = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(payload), stderr=""
    )
    with patch("ui.project_runtime_state.subprocess.run", return_value=completed) as run:
        result = state.workflow_catalog()
    assert "dynamic_agent" in result["stage_types"]
    command = run.call_args.args[0]
    assert "workflow_catalog.py" in " ".join(map(str, command))


