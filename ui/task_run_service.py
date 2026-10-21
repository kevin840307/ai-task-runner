"""Task execution orchestrator: Task lifecycle -> workspace -> existing Runner UI API."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from workspace import MergeManager, PreparedWorkspace, WorkspaceManager, WorkspaceSnapshot

from .task_service import TaskService


RuntimeReader = Callable[[Path], dict[str, Any]]
RuntimeAction = Callable[[Path], Any]
RuntimeLaunch = Callable[..., None]
WorkflowResolver = Callable[[Path, str], Path]
PreferencesReader = Callable[[Path], dict[str, Any]]
ExecutionSettingsReader = Callable[[], dict[str, Any]]
BackendResolver = Callable[[Path], str]


class TaskRunService:
    """Single owner of Task Run / Workspace sequencing; Runner remains Git-unaware."""

    def __init__(
        self,
        tasks: TaskService,
        *,
        execution_settings: ExecutionSettingsReader,
        preferences: PreferencesReader,
        backend_default: BackendResolver,
        resolve_workflow: WorkflowResolver,
        launch: RuntimeLaunch,
        read_runtime: RuntimeReader,
        stop_runtime: RuntimeAction,
        resume_runtime: RuntimeAction,
        workspace_manager: WorkspaceManager | None = None,
        merge_manager: MergeManager | None = None,
        poll_interval: float = 1.0,
        auto_watch: bool = True,
    ) -> None:
        self.tasks = tasks
        self._execution_settings = execution_settings
        self._preferences = preferences
        self._backend_default = backend_default
        self._resolve_workflow = resolve_workflow
        self._launch = launch
        self._read_runtime = read_runtime
        self._stop_runtime = stop_runtime
        self._resume_runtime = resume_runtime
        self._workspaces = workspace_manager or WorkspaceManager()
        self._merges = merge_manager or MergeManager()
        self._poll_interval = max(0.05, float(poll_interval))
        self._auto_watch = bool(auto_watch)
        self._watch_lock = threading.Lock()
        self._watching: set[tuple[str, str]] = set()

    def list(self, project: Path) -> dict[str, Any]:
        return {"tasks": [self._project_runtime(project, row) for row in self.tasks.list(project)["tasks"]]}

    def get(self, project: Path, task_id: str) -> dict[str, Any]:
        return self._project_runtime(project, self.tasks.get(project, task_id))

    def start(self, project: Path, task_id: str, *, request_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task = self.tasks.get(project, task_id)
        items = task.get("items") if isinstance(task.get("items"), list) else []
        completed = int(task.get("completed_item_count", 0))
        if len(items) != 1:
            raise ValueError("Task List Run must use the ordered YAML execution path")
        if completed >= len(items):
            raise ValueError("Task has no remaining item to run")
        item = items[completed]

        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        if task.get("status") == "paused" and run.get("phase") == "launch_failed":
            prepared = self._workspaces.restore(run.get("workspace") or {})
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="launching",
                status="ongoing",
                error="",
            )
            return self._launch_task(project, task_id, item, prepared)

        run_number = int(task.get("run_count", 0)) + 1
        settings = self._execution_settings()
        main_running = self._main_running(project, task_id)
        prepared = self._workspaces.prepare(
            project,
            task_id=task_id,
            run_number=run_number,
            requested_mode=str(item.get("workspace") or "auto"),
            execution_settings=settings,
            main_running=main_running,
        )
        attached = self.tasks.begin_run(
            project,
            task_id,
            request_id=request_id,
            workspace=prepared.as_dict(),
        )
        if attached.get("duplicate"):
            self._ensure_watcher(project, task_id)
            return self.get(project, task_id)
        return self._launch_task(project, task_id, item, prepared)

    def stop(self, project: Path, task_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task, prepared = self._current_workspace(project, task_id)
        if task.get("status") != "ongoing":
            raise ValueError("Task is not Ongoing")
        self._stop_runtime(prepared.project_root)
        self.tasks.transition_run(
            project,
            task_id,
            prepared.run_number,
            phase="stopping",
            status="ongoing",
        )
        return self.get(project, task_id)

    def resume(self, project: Path, task_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task, prepared = self._current_workspace(project, task_id)
        if task.get("status") != "paused":
            raise ValueError("Task is not Paused")
        run = task.get("run") or {}
        if run.get("phase") == "launch_failed":
            item = task["items"][int(run.get("item_index") or 0)]
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="launching",
                status="ongoing",
                error="",
            )
            return self._launch_task(project, task_id, item, prepared)
        self._resume_runtime(prepared.project_root)
        self.tasks.transition_run(
            project,
            task_id,
            prepared.run_number,
            phase="running",
            status="ongoing",
            error="",
        )
        self._ensure_watcher(project, task_id)
        return self.get(project, task_id)

    def merge(self, project: Path, task_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task, prepared = self._current_workspace(project, task_id)
        run = task.get("run") or {}
        result = run.get("workspace_result") if isinstance(run.get("workspace_result"), dict) else {}
        snapshot_data = result.get("snapshot")
        if not isinstance(snapshot_data, dict):
            raise ValueError("Task result has not been snapshotted")
        snapshot = WorkspaceSnapshot(
            task_snapshot_sha=str(snapshot_data.get("task_snapshot_sha") or ""),
            no_changes=bool(snapshot_data.get("no_changes")),
            created_commit=bool(snapshot_data.get("created_commit")),
        )
        return self._apply_merge(project, task_id, prepared, snapshot)

    def reconcile(self, project: Path, task_id: str) -> dict[str, Any]:
        """Advance only lifecycle projection for one already-started Task Run."""
        project = Path(project).expanduser().resolve()
        task, prepared = self._current_workspace(project, task_id)
        if task.get("status") != "ongoing":
            return self.get(project, task_id)
        runtime = self._read_runtime(prepared.project_root)
        if runtime.get("running") or runtime.get("launching"):
            phase = "running" if runtime.get("running") else "launching"
            if (task.get("run") or {}).get("phase") != phase:
                self.tasks.transition_run(project, task_id, prepared.run_number, phase=phase, status="ongoing")
            return self.get(project, task_id)

        if runtime.get("completed"):
            snapshot = self._workspaces.snapshot_result(
                prepared,
                excluded_paths=(prepared.project_root / ".ai-task-runner",),
            )
            base_result = {
                "snapshot": snapshot.as_dict(),
                "effective_mode": prepared.effective_mode,
                "branch": prepared.task_branch,
                "path": str(prepared.worktree_path),
            }
            if prepared.effective_mode == "worktree":
                self.tasks.transition_run(
                    project,
                    task_id,
                    prepared.run_number,
                    phase="worktree_ready",
                    status="closed",
                    workspace_result={**base_result, "merge": {"status": "worktree_ready"}},
                    completed_item_count=len(task.get("items") or []),
                )
                return self.get(project, task_id)
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="merging",
                status="ongoing",
                workspace_result=base_result,
            )
            return self._apply_merge(project, task_id, prepared, snapshot)

        if runtime.get("resumable") or (runtime.get("actions") or {}).get("resume"):
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="stopped",
                status="paused",
                error=str(runtime.get("last_error") or ""),
            )
            return self.get(project, task_id)

        if runtime.get("stale") or runtime.get("has_state"):
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="needs_attention",
                status="paused",
                error=str(runtime.get("last_error") or "Runner stopped without completing"),
            )
        return self.get(project, task_id)

    def recover(self, projects: list[Path]) -> None:
        for project in projects:
            try:
                rows = self.tasks.list(project)["tasks"]
            except (OSError, ValueError):
                continue
            for task in rows:
                if task.get("status") == "ongoing" and isinstance(task.get("run"), dict):
                    self._ensure_watcher(project, str(task.get("task_id") or ""))

    def _launch_task(
        self,
        source_project: Path,
        task_id: str,
        item: dict[str, Any],
        prepared: PreparedWorkspace,
    ) -> dict[str, Any]:
        preferences = self._preferences(source_project)
        backend = str(preferences.get("agent") or "").strip() or self._backend_default(source_project)
        workflow = self._resolve_workflow(source_project, str(item.get("workflow") or ""))
        mode = str(preferences.get("mode") or "auto")
        try:
            self._launch(
                prepared.project_root,
                str(item.get("prompt") or "") or None,
                mode="run",
                backend=backend,
                model=str(preferences.get("model") or ""),
                validator=self._runtime_input_path(
                    source_project, prepared.project_root, str(item.get("validator") or "")
                ),
                workflow=str(workflow),
                goal_file=self._runtime_input_path(
                    source_project, prepared.project_root, str(item.get("goal_file") or "")
                ),
                ai_validator_prompt_file=self._ai_prompt_path(
                    source_project, prepared, item
                ),
                readonly_safety="observe" if mode == "read" else "restore",
            )
        except Exception as exc:
            self.tasks.transition_run(
                source_project,
                task_id,
                prepared.run_number,
                phase="launch_failed",
                status="paused",
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self.tasks.transition_run(
            source_project,
            task_id,
            prepared.run_number,
            phase="running",
            status="ongoing",
            error="",
        )
        self._ensure_watcher(source_project, task_id)
        return self.get(source_project, task_id)

    def _apply_merge(
        self,
        project: Path,
        task_id: str,
        prepared: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
    ) -> dict[str, Any]:
        result = self._merges.merge(prepared, snapshot, validate=None)
        task = self.tasks.get(project, task_id)
        current = (task.get("run") or {}).get("workspace_result")
        value = dict(current) if isinstance(current, dict) else {}
        value.setdefault("snapshot", snapshot.as_dict())
        value.update({
            "effective_mode": prepared.effective_mode,
            "branch": prepared.task_branch,
            "path": str(prepared.worktree_path),
            "merge": result.as_dict(),
        })
        if result.status in {"merged", "no_changes"}:
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="merged",
                status="closed",
                workspace_result=value,
                completed_item_count=len(task.get("items") or []),
            )
        elif result.real_merge_failure:
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase=result.status,
                status="paused",
                workspace_result=value,
                increment_merge_failure=True,
                error=result.detail,
            )
        else:
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase=result.status,
                status="ongoing",
                workspace_result=value,
                error=result.detail,
            )
        return self.get(project, task_id)

    def _project_runtime(self, project: Path, task: dict[str, Any]) -> dict[str, Any]:
        value = dict(task)
        run = value.get("run")
        if not isinstance(run, dict) or not isinstance(run.get("workspace"), dict):
            value["runner_runtime"] = {}
            return value
        try:
            prepared = self._workspaces.restore(run["workspace"])
            value["runner_runtime"] = self._read_runtime(prepared.project_root)
        except Exception as exc:
            value["runner_runtime"] = {
                "running": False,
                "status": "needs_attention",
                "last_error": f"{type(exc).__name__}: {exc}",
            }
        return value

    def _current_workspace(self, project: Path, task_id: str) -> tuple[dict[str, Any], PreparedWorkspace]:
        task = self.tasks.get(project, task_id)
        run = task.get("run")
        if not isinstance(run, dict) or not isinstance(run.get("workspace"), dict):
            raise ValueError("Task does not have a prepared Run workspace")
        return task, self._workspaces.restore(run["workspace"])

    def _main_running(self, project: Path, current_task_id: str) -> bool:
        for task in self.tasks.list(project)["tasks"]:
            if task.get("task_id") == current_task_id or task.get("status") != "ongoing":
                continue
            run = task.get("run")
            workspace = run.get("workspace") if isinstance(run, dict) else None
            if isinstance(workspace, dict) and workspace.get("effective_mode") == "main":
                return True
        return False

    @staticmethod
    def _runtime_input_path(source_project: Path, runtime_project: Path, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        path = Path(text).expanduser()
        if path.is_absolute():
            return str(path.resolve())
        runtime_candidate = (runtime_project / path).resolve()
        if runtime_candidate.is_file():
            return str(runtime_candidate)
        source_candidate = (source_project / path).resolve()
        return str(source_candidate) if source_candidate.is_file() else text

    @staticmethod
    def _ai_prompt_path(
        source_project: Path,
        prepared: PreparedWorkspace,
        item: dict[str, Any],
    ) -> str:
        file_value = str(item.get("ai_validator_prompt_file") or "").strip()
        if file_value:
            return TaskRunService._runtime_input_path(
                source_project, prepared.project_root, file_value
            )
        content = str(item.get("ai_validator_prompt") or "")
        if not content:
            return ""
        root = prepared.project_root / ".ai-task-runner" / "ui" / "task-inputs"
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{prepared.task_id}-r{prepared.run_number}-ai-validator.md"
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return str(path)

    def _ensure_watcher(self, project: Path, task_id: str) -> None:
        if not self._auto_watch:
            return
        key = (str(Path(project).resolve()), str(task_id))
        with self._watch_lock:
            if key in self._watching:
                return
            self._watching.add(key)
        thread = threading.Thread(
            target=self._watch_loop,
            args=(Path(project).resolve(), str(task_id), key),
            name=f"task-run-{str(task_id)[-12:]}",
            daemon=True,
        )
        thread.start()

    def _watch_loop(self, project: Path, task_id: str, key: tuple[str, str]) -> None:
        try:
            while True:
                try:
                    task = self.reconcile(project, task_id)
                except Exception as exc:
                    try:
                        current, prepared = self._current_workspace(project, task_id)
                        self.tasks.transition_run(
                            project,
                            task_id,
                            prepared.run_number,
                            phase="needs_attention",
                            status="paused",
                            error=f"{type(exc).__name__}: {exc}",
                        )
                    except Exception:
                        pass
                    return
                run = task.get("run") if isinstance(task.get("run"), dict) else {}
                phase = str(run.get("phase") or "")
                if task.get("status") != "ongoing":
                    return
                if phase in {"validation_required", "waiting_target_history", "waiting_target_branch", "conflict", "source_fail", "technical_error"}:
                    return
                time.sleep(self._poll_interval)
        finally:
            with self._watch_lock:
                self._watching.discard(key)
