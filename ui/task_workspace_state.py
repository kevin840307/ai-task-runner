"""Task product/UI operations over the existing Runner runtime."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from project_registry import path_key

try:
    from .task_index import TaskIndex
    from .task_worktree import (
        WorktreeError,
        archive_runtime,
        attach_existing_worktree,
        create_task_worktree,
        list_worktrees,
        remove_task_worktree,
    )
except ImportError:
    from task_index import TaskIndex
    from task_worktree import (
        WorktreeError,
        archive_runtime,
        attach_existing_worktree,
        create_task_worktree,
        list_worktrees,
        remove_task_worktree,
    )

TASK_MARKER = "active-task.json"
MAX_TASK_LIST_ITEMS = 200


class TaskWorkspaceMixin:
    tasks: TaskIndex

    def _chat_for_task(self, chat_id: str) -> dict:
        chat = next((row for row in self.chats.list() if row.get("chat_id") == chat_id), None)
        if chat is None:
            raise ValueError("Chat not found")
        return chat

    def _task_marker_path(self, project: Path) -> Path:
        return project / ".ai-task-runner" / "ui" / TASK_MARKER

    def _read_task_marker(self, project: Path) -> dict:
        return self._read_json(self._task_marker_path(project)) or {}

    def _write_task_marker(self, project: Path, task_id: str, request_id: str = "") -> None:
        path = self._task_marker_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "task_id": task_id,
            "request_id": request_id,
            "updated_at": time.time(),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _clear_task_marker(self, project: Path, task_id: str) -> None:
        path = self._task_marker_path(project)
        marker = self._read_json(path) or {}
        if marker.get("task_id") != task_id:
            return
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def _resolve_task_workflow(self, project: Path, workflow: str = "") -> str:
        requested = str(workflow or "").strip()
        if requested:
            candidate = Path(requested).expanduser().resolve()
            allowed = {path_key(path) for path in self._known_workflow_paths(project)}
            if path_key(candidate) not in allowed or not candidate.is_file():
                raise ValueError("Selected Workflow is outside the allowed Global / Project Workflow asset roots")
            return str(candidate)
        default_name = str(self.product_defaults().get("default_workflow") or "").strip()
        catalog = self.studio_files(project)
        for item in catalog.get("workflows", []):
            if str(item.get("name") or "") == default_name:
                candidate = Path(str(item.get("path") or "")).expanduser().resolve()
                if candidate.is_file():
                    return str(candidate)
        raise ValueError(f"Default Workflow is unavailable: {default_name}")

    @staticmethod
    def _same_path(left: str | Path, right: str | Path) -> bool:
        return path_key(left) == path_key(right)

    def workspaces_payload(self, chat_id: str) -> dict:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            return {"workspaces": [], "path_available": False}
        source = Path(chat["root_path"])
        rows = []
        git_available = True
        try:
            for row in list_worktrees(source):
                workspace_path = str(row.get("path") or "")
                runtime = self.read_runtime(Path(workspace_path)) if Path(workspace_path).is_dir() else {}
                marker = self._read_task_marker(Path(workspace_path)) if Path(workspace_path).is_dir() else {}
                owner_task_id = str(marker.get("task_id") or "")
                owner = None
                if owner_task_id:
                    try:
                        owner = self.tasks.get(owner_task_id)
                    except ValueError:
                        owner = None
                rows.append({
                    "kind": "main" if row.get("is_main") else "worktree",
                    "path": workspace_path,
                    "branch": str(row.get("branch") or ""),
                    "is_main": bool(row.get("is_main")),
                    "busy": bool(runtime.get("running")),
                    "owner_task_id": owner_task_id,
                    "owner_chat_id": str((owner or {}).get("chat_id") or ""),
                    "owner_title": str((owner or {}).get("title") or ""),
                })
        except (OSError, WorktreeError):
            git_available = False
            runtime = self.read_runtime(source)
            marker = self._read_task_marker(source)
            owner_task_id = str(marker.get("task_id") or "")
            try:
                owner = self.tasks.get(owner_task_id) if owner_task_id else {}
            except ValueError:
                owner = {}
            rows = [{
                "kind": "main",
                "path": str(source),
                "branch": "",
                "is_main": True,
                "busy": bool(runtime.get("running")),
                "owner_task_id": owner_task_id,
                "owner_chat_id": str(owner.get("chat_id") or ""),
                "owner_title": str(owner.get("title") or ""),
            }]
        return {
            "workspaces": rows,
            "path_available": True,
            "git_available": git_available,
        }

    def _prepare_task_workspace(
        self,
        task: dict,
        chat: dict,
        workspace_mode: str,
        workspace_path: str = "",
    ) -> tuple[dict, Path]:
        source = Path(chat["root_path"]).resolve()
        mode = str(workspace_mode or "main")
        if mode == "main":
            workspace = {
                "kind": "main",
                "path": str(source),
                "branch": "",
                "source_root": str(source),
                "managed": False,
            }
        elif mode == "new":
            workspace = create_task_worktree(source, task["task_id"])
        elif mode == "existing":
            workspace = attach_existing_worktree(source, workspace_path)
        else:
            raise ValueError("Workspace must be Main, New Worktree, or Existing Worktree")
        task = self.tasks.update(
            task["task_id"],
            root_path=workspace["path"],
            source_root_path=str(source),
            workspace_kind=workspace["kind"],
            workspace_branch=workspace.get("branch", ""),
            workspace_managed=bool(workspace.get("managed")),
        )
        return task, Path(workspace["path"])

    def cleanup_task_workspace(self, task_id: str) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        if task.get("workspace_kind") != "worktree" or not task.get("workspace_managed"):
            raise ValueError("Only Task-created worktrees can be cleaned up here")
        workspace = Path(task["root_path"])
        source = Path(task.get("source_root_path") or "")
        if not source.is_dir():
            raise ValueError("Source repository is unavailable")
        if workspace.is_dir():
            marker = self._read_task_marker(workspace)
            if marker.get("task_id") == task_id and self.read_runtime(workspace).get("running"):
                raise ValueError("Stop the active Task before cleaning up its worktree")
            archive = source / ".ai-task-runner" / "ui" / "task-history" / task_id / "runtime"
            archive_path = archive_runtime(workspace, archive)
            runtime = workspace / ".ai-task-runner"
            if runtime.is_dir():
                import shutil
                shutil.rmtree(runtime)
            remove_task_worktree(source, workspace)
        else:
            archive_path = str(task.get("runtime_archive") or "")
        return self.tasks.update(
            task_id,
            runtime_archive=archive_path,
            workspace_removed=True,
            workspace_removed_at=time.time(),
        )

    def _sequential_child_evidence(self, project: Path) -> list[dict]:
        script_root = project / ".ai-task-runner" / "script"
        if not script_root.is_dir():
            return []
        evidence: list[dict] = []
        for child in sorted(script_root.iterdir()):
            if not child.is_dir() or not child.name.isdigit():
                continue
            state = self._read_json(child / "state.json") or {}
            result = self._read_text(child / "debug" / "last-result.txt", limit=6000).strip()
            evidence.append({
                "index": int(child.name),
                "run_id": str(state.get("run_id") or ""),
                "completed": bool(state.get("completed")),
                "stage": str(state.get("stage") or ""),
                "last_error": str(state.get("last_error") or ""),
                "result": result,
            })
        return evidence

    @staticmethod
    def _archived_messages(runtime_archive: str, run_ids: set[str]) -> list[dict]:
        path = Path(str(runtime_archive or "")) / "ui" / "messages.jsonl"
        if not path.is_file() or not run_ids:
            return []
        rows: list[dict] = []
        try:
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and str(item.get("run_id") or "") in run_ids:
                        rows.append(item)
        except OSError:
            return []
        return rows[-400:]

    def _terminal_execution_evidence(self, project: Path, runtime: dict) -> dict:
        return {
            "status": str(runtime.get("status") or ""),
            "stage": str(runtime.get("stage") or ""),
            "cycle": int(runtime.get("cycle") or 0),
            "completed_count": int(runtime.get("completed_count") or 0),
            "total": int(runtime.get("total") or 0),
            "last_error": str(runtime.get("last_error") or ""),
            "result": self._read_text(
                project / ".ai-task-runner" / "debug" / "last-result.txt",
                limit=12000,
            ).strip(),
            "stream_tail": str(runtime.get("stream") or "")[-6000:],
            "activity_summary": list(runtime.get("activity_summary") or [])[-20:],
            "recovery": (
                dict(runtime.get("recovery") or {})
                if isinstance(runtime.get("recovery"), dict)
                else {}
            ),
        }

    def _sync_task(self, task: dict) -> dict:
        project = Path(str(task.get("root_path") or ""))
        if not project.is_dir():
            if not task.get("workspace_removed") and task.get("last_status") != "path_unavailable":
                task = self.tasks.update(task["task_id"], last_status="path_unavailable")
            return {
                **task,
                "path_available": False,
                "workspace_removed": bool(task.get("workspace_removed")),
                "runtime": None,
            }

        marker = self._read_task_marker(project)
        owns_visible_runtime = marker.get("task_id") == task.get("task_id")
        runtime = self.read_runtime(project) if owns_visible_runtime else None
        if runtime is not None:
            request_id = str(runtime.get("request_id") or "")
            marker_request = str(marker.get("request_id") or "")
            if request_id and marker_request and request_id != marker_request:
                runtime = None
                owns_visible_runtime = False

        if runtime is not None:
            if runtime.get("completed") and task.get("task_type") != "sequential":
                self.sync_completion(project)
            status = str(runtime.get("status") or "idle")
            execution_changes = {"last_status": status}
            if task.get("task_type") == "sequential":
                children = self._sequential_child_evidence(project)
                execution_changes["children"] = children
                execution_changes["run_ids"] = [
                    child["run_id"] for child in children if child.get("run_id")
                ]
            else:
                run_id = str(runtime.get("run_id") or "")
                if run_id:
                    execution_changes["run_id"] = run_id
            if not runtime.get("running") and (
                runtime.get("completed")
                or status in {"completed", "stopped", "needs_attention"}
                or runtime.get("last_error")
            ):
                execution_changes["evidence"] = self._terminal_execution_evidence(
                    project,
                    runtime,
                )
            executions = list(task.get("executions") or [])
            latest = executions[-1] if executions else {}
            changed = (
                task.get("last_status") != status
                or any(latest.get(key) != value for key, value in execution_changes.items() if key != "last_status")
            )
            if changed:
                try:
                    task = self.tasks.update_latest_execution(task["task_id"], **execution_changes)
                except ValueError:
                    task = self.tasks.update(task["task_id"], last_status=status)
            runtime_error = str(runtime.get("last_error") or "")
            if runtime_error and runtime_error != str(task.get("last_error") or ""):
                task = self.tasks.update(task["task_id"], last_error=runtime_error)

        return {
            **task,
            "path_available": True,
            "runtime": runtime,
            "owns_runtime": owns_visible_runtime,
        }

    def tasks_payload(
        self,
        chat_id: str = "",
        *,
        limit: int = 100,
        attention_only: bool = False,
    ) -> dict:
        if chat_id:
            self._chat_for_task(chat_id)
        if not 1 <= int(limit) <= 500:
            raise ValueError("Task list limit must be 1-500")
        rows = list(self.tasks.list(chat_id=chat_id))
        rows.sort(
            key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0),
            reverse=True,
        )
        total = len(rows)
        if attention_only:
            candidate_statuses = {
                "launching", "running", "recovering", "stopping",
                "needs_attention", "error", "failed", "path_unavailable",
            }
            rows = [
                item for item in rows
                if str(item.get("last_status") or "").lower() in candidate_statuses
            ]
            synced = [self._sync_task(task) for task in rows]
            synced = [
                item for item in synced
                if str(item.get("last_status") or "").lower() in candidate_statuses
                or (
                    isinstance(item.get("runtime"), dict)
                    and (
                        item["runtime"].get("running")
                        or item["runtime"].get("attention_reason")
                    )
                )
            ][: int(limit)]
            return {
                "tasks": synced,
                "meta": {"total": total, "returned": len(synced), "has_more": False},
            }
        selected = rows[: int(limit)]
        synced = [self._sync_task(task) for task in selected]
        return {
            "tasks": synced,
            "meta": {
                "total": total,
                "returned": len(synced),
                "has_more": total > len(selected),
            },
        }

    def task_detail(self, task_id: str) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        run_ids = {
            value
            for item in task.get("executions", [])
            for value in (
                [str(item.get("run_id") or "")]
                + [str(run_id or "") for run_id in item.get("run_ids", [])]
            )
            if value
        }
        history: list[dict] = []
        project = Path(task["root_path"])
        if project.is_dir() and run_ids:
            history = [
                row for row in self.messages(project)
                if str(row.get("run_id") or "") in run_ids
            ]
        elif task.get("runtime_archive"):
            history = self._archived_messages(str(task.get("runtime_archive") or ""), run_ids)

        path_runtime = task.get("runtime")
        if path_runtime is None and project.is_dir():
            path_runtime = self.read_runtime(project)
        path_actions = (
            path_runtime.get("actions")
            if isinstance(path_runtime, dict) and isinstance(path_runtime.get("actions"), dict)
            else {}
        )
        owns_runtime = bool(task.get("owns_runtime"))
        last_status = str(task.get("last_status") or "").lower()
        terminal = (
            "completed" in last_status
            or last_status in {"needs_attention", "failed", "error"}
        )
        available_actions = {
            "stop": bool(owns_runtime and path_actions.get("stop")),
            "resume": bool(owns_runtime and path_actions.get("resume")),
            "rerun": bool(
                terminal
                and (
                    (owns_runtime and (path_actions.get("rerun") or path_actions.get("run")))
                    or (not owns_runtime and path_actions.get("run"))
                )
            ),
            "continue": bool(terminal and path_actions.get("run")),
            "delete": not bool(owns_runtime and isinstance(path_runtime, dict) and path_runtime.get("running")),
            "cleanup_workspace": bool(
                task.get("workspace_kind") == "worktree"
                and task.get("workspace_managed")
                and not task.get("workspace_removed")
                and not (owns_runtime and isinstance(path_runtime, dict) and path_runtime.get("running"))
            ),
        }
        return {**task, "history": history, "available_actions": available_actions}

    def _sync_prior_tasks(self, project: Path) -> None:
        for existing in self.tasks.list(root=str(project)):
            self._sync_task(existing)

    def create_task(
        self,
        *,
        chat_id: str,
        instruction: str,
        title: str = "",
        workflow: str = "",
        source_message_id: str = "",
        goal_file: str = "",
        workspace_mode: str = "main",
        workspace_path: str = "",
        backend: str = "",
        model: str = "",
    ) -> dict:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        source_project = Path(chat["root_path"]).resolve()
        project = source_project
        source_goal_file = str(goal_file or "").strip()
        task_instruction = str(instruction or "").strip()
        if source_goal_file:
            if task_instruction:
                raise ValueError("Task must use either Instruction or goal file, not both")
            source = Path(source_goal_file).expanduser()
            source = source.resolve() if source.is_absolute() else (source_project / source).resolve()
            if not source.is_file():
                raise ValueError("Task goal file not found")
            try:
                task_instruction = source.read_text(encoding="utf-8-sig").strip()
            except OSError as exc:
                raise ValueError(f"Cannot read Task goal file: {exc}") from exc
            if not task_instruction:
                raise ValueError("Task goal file is empty")
            source_goal_file = str(source)
        if not task_instruction:
            raise ValueError("Task instruction is required")
        resolved_workflow = self._resolve_task_workflow(source_project, workflow)

        task = self.tasks.create(
            chat_id=chat_id,
            root_path=str(project),
            instruction=task_instruction,
            title=title,
            task_type="single",
            workflow=resolved_workflow,
            source_message_id=source_message_id,
        )
        if source_goal_file:
            task = self.tasks.update(task["task_id"], source_goal_file=source_goal_file)
        try:
            task, project = self._prepare_task_workspace(
                task,
                chat,
                workspace_mode,
                workspace_path,
            )
            self._sync_prior_tasks(project)
            request = self.launch_message(
                project,
                task_instruction,
                workflow=resolved_workflow,
                backend=str(backend or ""),
                model=str(model or ""),
            )
        except Exception as exc:
            task = self.tasks.update(
                task["task_id"],
                last_status="needs_attention",
                last_error=str(exc),
            )
            return self._sync_task(task)

        request_id = str(request.get("request_id") or "")
        task = self.tasks.update(
            task["task_id"],
            backend=str(request.get("backend") or backend or ""),
            model=str(request.get("model") or model or ""),
        )
        task = self.tasks.append_execution(task["task_id"], {
            "request_id": request_id,
            "started_at": time.time(),
            "instruction": task_instruction,
            "source_goal_file": source_goal_file,
            "backend": str(request.get("backend") or backend or ""),
            "model": str(request.get("model") or model or ""),
            "workflow": str(request.get("workflow") or resolved_workflow),
            "run_id": "",
        })
        self._write_task_marker(project, task["task_id"], request_id)
        return self._sync_task(task)

    def _write_task_list(self, project: Path, task_id: str, items: list[dict], segment: int) -> Path:
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("Task List requires PyYAML") from exc
        folder = project / ".ai-task-runner" / "ui" / "task-lists"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{task_id}-{segment:03d}.yaml"
        payload = [
            dict(item.get("raw") or {
                "prompt": item["instruction"],
                "workflow_file": item["workflow"],
            })
            for item in items
        ]
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        return path

    def task_list_yaml_preview(self, chat_id: str, content: str, default_workflow: str = "") -> dict:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        command = [
            sys.executable,
            str(self.repo_root / "tool" / "yaml_list_contract.py"),
            "--project-root",
            str(chat["root_path"]),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=str(self.repo_root),
                input=json.dumps({
                    "content": str(content or ""),
                    "allow_inherited_workflow": bool(self._resolve_task_workflow(Path(chat["root_path"]), default_workflow)),
                }, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ValueError(f"Task List YAML validation unavailable: {exc}") from exc
        try:
            payload = json.loads((completed.stdout or "").strip())
        except json.JSONDecodeError as exc:
            detail = (completed.stderr or completed.stdout or "No output")[-2000:]
            raise ValueError(f"Task List YAML validation returned invalid output: {detail}") from exc
        if completed.returncode != 0 or payload.get("error"):
            raise ValueError(str(payload.get("error") or "Task List YAML validation failed"))
        return payload

    def _normalize_task_list_items(
        self,
        chat_id: str,
        items: list,
        default_workflow: str = "",
    ) -> tuple[Path, list[dict], str, str]:
        chat = self._chat_for_task(chat_id)
        if not chat.get("path_available"):
            raise ValueError("Chat path unavailable")
        if not isinstance(items, list) or not 1 <= len(items) <= MAX_TASK_LIST_ITEMS:
            raise ValueError(f"Task List requires 1-{MAX_TASK_LIST_ITEMS} items")
        project = Path(chat["root_path"])
        inherited_workflow = self._resolve_task_workflow(project, default_workflow)
        normalized: list[dict] = []
        for index, submitted in enumerate(items, 1):
            if not isinstance(submitted, dict):
                raise ValueError(f"Task List item {index} is invalid")
            raw_item = submitted.get("raw")
            item = dict(raw_item) if isinstance(raw_item, dict) else {}
            instruction = str(submitted.get("instruction") or "").strip()
            if len(instruction) > 20000:
                raise ValueError(f"Task List item {index} instruction is too long")
            if not item:
                if not instruction:
                    raise ValueError(f"Task List item {index} instruction is required")
                item["prompt"] = instruction
            elif not any(str(item.get(key) or "").strip() for key in ("prompt", "goal", "goal_file")):
                if not instruction:
                    raise ValueError(f"Task List item {index} instruction is required")
                item["prompt"] = instruction

            override = str(submitted.get("workflow") or "").strip()
            if override:
                item.pop("workflow", None)
                item["workflow_file"] = self._resolve_task_workflow(project, override)
            display_instruction = (
                str(item.get("prompt") or item.get("goal") or "").strip()
                or (f"Use file: {item.get('goal_file')}" if item.get("goal_file") else f"Task {index}")
            )
            normalized.append({
                "instruction": display_instruction,
                "workflow": str(item.get("workflow_file") or ""),
                "raw": item,
            })

        try:
            import yaml
        except ImportError as exc:
            raise ValueError("Task List requires PyYAML") from exc
        candidate_yaml = yaml.safe_dump(
            [item["raw"] for item in normalized],
            allow_unicode=True,
            sort_keys=False,
        )
        return project, normalized, candidate_yaml, inherited_workflow

    def task_list_yaml_export(
        self,
        chat_id: str,
        items: list,
        default_workflow: str = "",
    ) -> dict:
        _, normalized, candidate_yaml, inherited_workflow = self._normalize_task_list_items(
            chat_id,
            items,
            default_workflow,
        )
        preview = self.task_list_yaml_preview(chat_id, candidate_yaml, inherited_workflow)
        return {
            "canonical": str(preview.get("canonical") or candidate_yaml),
            "raw": preview.get("raw") or [],
            "items": normalized,
        }

    def create_task_list(
        self,
        *,
        chat_id: str,
        items: list,
        title: str = "",
        default_workflow: str = "",
        workspace_mode: str = "main",
        workspace_path: str = "",
        backend: str = "",
        model: str = "",
    ) -> dict:
        project, normalized, candidate_yaml, inherited_workflow = self._normalize_task_list_items(
            chat_id,
            items,
            default_workflow,
        )
        self.task_list_yaml_preview(chat_id, candidate_yaml, inherited_workflow)
        chat = self._chat_for_task(chat_id)
        task = self.tasks.create(
            chat_id=chat_id,
            root_path=str(project),
            instruction=f"Task List · {len(normalized)} items",
            title=title or normalized[0]["instruction"][:80],
            task_type="sequential",
        )
        task = self.tasks.update(task["task_id"], items=normalized)
        try:
            task, project = self._prepare_task_workspace(
                task,
                chat,
                workspace_mode,
                workspace_path,
            )
            self._sync_prior_tasks(project)
            script = self._write_task_list(project, task["task_id"], normalized, 1)
            self.launch_script_task(
                project,
                str(script),
                workflow=inherited_workflow,
                backend=str(backend or ""),
                model=str(model or ""),
            )
        except Exception as exc:
            task = self.tasks.update(task["task_id"], last_status="needs_attention", last_error=str(exc))
            return self._sync_task(task)

        task = self.tasks.update(
            task["task_id"],
            backend=str(backend or ""),
            model=str(model or ""),
            workflow=inherited_workflow,
        )
        task = self.tasks.append_execution(task["task_id"], {
            "request_id": "",
            "script_file": str(script),
            "started_at": time.time(),
            "instruction": task["instruction"],
            "workflow": inherited_workflow,
            "default_workflow": inherited_workflow,
            "backend": str(backend or ""),
            "model": str(model or ""),
            "run_id": "",
            "item_count": len(normalized),
        })
        self._write_task_marker(project, task["task_id"])
        return self._sync_task(task)

    def task_action(
        self,
        task_id: str,
        action: str,
        *,
        instruction: str = "",
        workflow: str = "",
    ) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        project = Path(task["root_path"])
        if not project.is_dir():
            raise ValueError("Task path unavailable")
        marker = self._read_task_marker(project)
        owns_runtime = marker.get("task_id") == task_id
        path_runtime = self.read_runtime(project)
        runtime = path_runtime if owns_runtime else {}
        actions = runtime.get("actions") if isinstance(runtime.get("actions"), dict) else {}
        path_actions = (
            path_runtime.get("actions")
            if isinstance(path_runtime.get("actions"), dict)
            else {}
        )
        sequential = task.get("task_type") == "sequential"
        executions = list(task.get("executions") or [])
        latest = executions[-1] if executions else {}

        if action == "stop":
            if not owns_runtime or not actions.get("stop"):
                raise ValueError("Task cannot be stopped in its current state")
            self.stop(project)
        elif action == "resume":
            if not owns_runtime or not actions.get("resume"):
                raise ValueError("Task cannot be resumed in its current state")
            if sequential:
                self.launch_script_task(
                    project,
                    str(latest.get("script_file") or ""),
                    resume=True,
                    workflow=str(latest.get("default_workflow") or latest.get("workflow") or task.get("workflow") or ""),
                    backend=str(latest.get("backend") or task.get("backend") or ""),
                    model=str(latest.get("model") or task.get("model") or ""),
                )
            else:
                self.resume(project)
        elif action == "rerun":
            allowed = bool(
                (owns_runtime and (actions.get("rerun") or actions.get("run")))
                or (not owns_runtime and path_actions.get("run"))
            )
            if not allowed:
                raise ValueError("Task cannot be rerun while its path is unavailable or busy")
            self._sync_prior_tasks(project)
            if sequential:
                script = str(latest.get("script_file") or "")
                parent_workflow = str(
                    latest.get("default_workflow")
                    or latest.get("workflow")
                    or task.get("workflow")
                    or ""
                )
                self.launch_script_task(
                    project,
                    script,
                    workflow=parent_workflow,
                    backend=str(latest.get("backend") or task.get("backend") or ""),
                    model=str(latest.get("model") or task.get("model") or ""),
                )
                task = self.tasks.append_execution(task_id, {
                    "request_id": "",
                    "script_file": script,
                    "started_at": time.time(),
                    "instruction": task.get("instruction") or "",
                    "workflow": parent_workflow,
                    "default_workflow": parent_workflow,
                    "backend": str(latest.get("backend") or task.get("backend") or ""),
                    "model": str(latest.get("model") or task.get("model") or ""),
                    "run_id": "",
                    "item_count": len(task.get("items") or []),
                })
                self._write_task_marker(project, task_id)
            else:
                resolved_workflow = self._resolve_task_workflow(
                    project,
                    str(task.get("workflow") or workflow or ""),
                )
                request = self.launch_message(
                    project,
                    str(task.get("instruction") or ""),
                    workflow=resolved_workflow,
                    backend=str(task.get("backend") or ""),
                    model=str(task.get("model") or ""),
                )
                request_id = str(request.get("request_id") or "")
                task = self.tasks.append_execution(task_id, {
                    "request_id": request_id,
                    "started_at": time.time(),
                    "instruction": task.get("instruction") or "",
                    "workflow": str(request.get("workflow") or resolved_workflow),
                    "backend": str(request.get("backend") or task.get("backend") or ""),
                    "model": str(request.get("model") or task.get("model") or ""),
                    "run_id": "",
                })
                self._write_task_marker(project, task_id, request_id)
        elif action == "continue":
            if not path_actions.get("run"):
                raise ValueError("Task cannot continue while its path is unavailable or busy")
            self._sync_prior_tasks(project)
            text = str(instruction or "").strip()
            if not text:
                raise ValueError("Continue requires a new instruction")
            resolved_workflow = self._resolve_task_workflow(
                project,
                workflow or (str(task.get("workflow") or "") if not sequential else ""),
            )
            if sequential:
                segment = len(executions) + 1
                item = {"instruction": text, "workflow": "", "raw": {"prompt": text}}
                script = self._write_task_list(project, task_id, [item], segment)
                self.launch_script_task(
                    project,
                    str(script),
                    workflow=resolved_workflow,
                    backend=str(task.get("backend") or ""),
                    model=str(task.get("model") or ""),
                )
                task = self.tasks.append_execution(task_id, {
                    "request_id": "",
                    "script_file": str(script),
                    "started_at": time.time(),
                    "instruction": text,
                    "workflow": resolved_workflow,
                    "default_workflow": resolved_workflow,
                    "run_id": "",
                    "item_count": 1,
                })
                self._write_task_marker(project, task_id)
            else:
                request = self.launch_message(
                    project,
                    text,
                    workflow=resolved_workflow,
                    backend=str(task.get("backend") or ""),
                    model=str(task.get("model") or ""),
                )
                request_id = str(request.get("request_id") or "")
                task = self.tasks.append_execution(task_id, {
                    "request_id": request_id,
                    "started_at": time.time(),
                    "instruction": text,
                    "workflow": str(request.get("workflow") or resolved_workflow),
                    "run_id": "",
                })
                self._write_task_marker(project, task_id, request_id)
        else:
            raise ValueError("Unknown Task action")
        return self.task_detail(task_id)

    def delete_task(self, task_id: str) -> dict:
        task = self._sync_task(self.tasks.get(task_id))
        project = Path(task["root_path"])
        if project.is_dir():
            marker = self._read_task_marker(project)
            if marker.get("task_id") == task_id and self.read_runtime(project).get("running"):
                raise ValueError("Stop the active Task before deleting it")
            self._clear_task_marker(project, task_id)
        self.tasks.delete(task_id)
        return {"ok": True}
