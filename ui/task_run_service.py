"""Task execution orchestrator: Task lifecycle -> workspace -> existing Runner UI API."""
from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Any, Callable

from workspace import MergeManager, MergeResult, PreparedWorkspace, PublishManager, WorkspaceManager, WorkspaceSnapshot

try:
    from .task_service import COMPLETED_ITEM_PHASES, TaskService
except ImportError:
    from task_service import COMPLETED_ITEM_PHASES, TaskService


RuntimeReader = Callable[[Path], dict[str, Any]]
RuntimeAction = Callable[[Path], Any]
RuntimeLaunch = Callable[..., None]
WorkflowResolver = Callable[[Path, str], Path]
PreferencesReader = Callable[[Path], dict[str, Any]]
ExecutionSettingsReader = Callable[[], dict[str, Any]]
BackendResolver = Callable[[Path], str]
MergeValidation = Callable[..., str]


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
        validate_merge: MergeValidation | None = None,
        workspace_manager: WorkspaceManager | None = None,
        merge_manager: MergeManager | None = None,
        publish_manager: PublishManager | None = None,
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
        self._validate_merge = validate_merge
        self._workspaces = workspace_manager or WorkspaceManager()
        self._merges = merge_manager or MergeManager()
        self._publisher = publish_manager or PublishManager()
        self._poll_interval = max(0.05, float(poll_interval))
        self._auto_watch = bool(auto_watch)
        self._watch_lock = threading.Lock()
        self._watching: set[tuple[str, str]] = set()

    def list(self, project: Path) -> dict[str, Any]:
        return {"tasks": [self._project_runtime(project, row) for row in self.tasks.list(project)["tasks"]]}

    def get(self, project: Path, task_id: str) -> dict[str, Any]:
        return self._project_runtime(project, self.tasks.get(project, task_id))

    def start_goal(
        self,
        project: Path,
        spec: str,
        *,
        request_id: str,
        project_id: str = "",
    ) -> dict[str, Any]:
        """Backend-owned idempotent Quick Goal create -> run command."""
        project = Path(project).expanduser().resolve()
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        goal = str(spec or "").strip()
        if not goal:
            raise ValueError("@goal spec is required")

        preferences = self._preferences(project)
        workflow = str(preferences.get("workflow") or "").strip() or "ralphy_ai_validate.yaml"
        normalized_title = " ".join(goal.split())
        title = normalized_title if len(normalized_title) <= 160 else normalized_title[:157].rstrip() + "..."
        digest = hashlib.sha256(request.encode("utf-8")).hexdigest()
        task = self.tasks.create(
            project,
            {
                "title": title,
                "items": [{
                    "title": title,
                    "prompt": goal,
                    "workflow": workflow,
                    "project": str(project),
                    "workspace": "auto",
                }],
            },
            request_id=f"goal-create-{digest}",
            project_id=project_id,
        )
        try:
            value = self.start(
                project,
                str(task["task_id"]),
                request_id=f"goal-run-{digest}",
            )
        except Exception as exc:
            value = self.get(project, str(task["task_id"]))
            return {
                **value,
                "goal_run_started": False,
                "goal_run_error": f"{type(exc).__name__}: {exc}",
            }

        run = value.get("run") if isinstance(value.get("run"), dict) else None
        launch_failed = bool(run) and str(run.get("phase") or "") == "launch_failed"
        return {
            **value,
            "goal_run_started": bool(run) and not launch_failed,
            "goal_run_error": str(run.get("error") or "") if launch_failed and run else "",
        }

    def start(self, project: Path, task_id: str, *, request_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        existing = self.tasks.run_request(project, request)
        if existing is not None:
            if str(existing.get("task_id") or "") != str(task_id or "").strip():
                raise ValueError("request_id belongs to another Task")
            self._ensure_watcher(project, str(task_id))
            return self.get(project, str(task_id))
        task = self.tasks.get(project, task_id)
        items = task.get("items") if isinstance(task.get("items"), list) else []
        completed = int(task.get("completed_item_count", 0))
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
            request_id=request,
            workspace=prepared.as_dict(),
        )
        if attached.get("duplicate"):
            self._ensure_watcher(project, task_id)
            return self.get(project, task_id)
        return self._launch_task(project, task_id, item, prepared)

    def stop(self, project: Path, task_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task = self.tasks.get(project, task_id)
        if task.get("status") != "ongoing":
            raise ValueError("Task is not Ongoing")
        prepared = self._runtime_workspace(task)
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
        task = self.tasks.get(project, task_id)
        if task.get("status") != "paused":
            raise ValueError("Task is not Paused")
        run = task.get("run") or {}
        prepared = self._runtime_workspace(task)
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
        if run.get("phase") == "recovery_launch_failed":
            recovery = self._recovery_record(task)
            prompt = str(recovery.get("prompt") or "")
            if not prompt:
                raise ValueError("Merge recovery prompt is missing")
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase="conflict_recovery",
                status="ongoing",
                error="",
            )
            return self._launch_merge_recovery(project, task_id, prepared, prompt)
        self._resume_runtime(prepared.project_root)
        if self._is_recovery_workspace(task, prepared):
            value = self._workspace_result(task)
            recovery = dict(value.get("recovery") or {})
            recovery["status"] = "running"
            value["recovery"] = recovery
            phase = "conflict_recovery"
            self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase=phase,
                status="ongoing",
                error="",
                workspace_result=value,
            )
        else:
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

    def reset(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        existing = self.tasks.lifecycle_request(project, request)
        if existing is not None:
            if (
                str(existing.get("task_id") or "") != str(task_id or "").strip()
                or str(existing.get("action") or "") != "reset"
            ):
                raise ValueError("request_id belongs to another Task lifecycle action")
            return self.get(project, task_id)

        task = self.tasks.get(project, task_id)
        if task.get("status") != "paused":
            raise ValueError("Task must be Paused before Reset")
        self._release_abandoned_merge_slot(task)
        self.tasks.reset_to_new(
            project,
            task_id,
            request_id=request,
            action="reset",
        )
        return self.get(project, task_id)

    def rerun(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")
        run_request_id = "task-rerun-" + hashlib.sha256(
            request.encode("utf-8")
        ).hexdigest()
        existing = self.tasks.lifecycle_request(project, request)
        if existing is not None:
            if (
                str(existing.get("task_id") or "") != str(task_id or "").strip()
                or str(existing.get("action") or "") != "rerun"
            ):
                raise ValueError("request_id belongs to another Task lifecycle action")
            if self.tasks.run_request(project, run_request_id) is not None:
                return self.get(project, task_id)
            task = self.tasks.get(project, task_id)
            if task.get("status") != "new":
                return self.get(project, task_id)
            return self.start(project, task_id, request_id=run_request_id)

        task = self.tasks.get(project, task_id)
        if task.get("status") not in {"paused", "closed"}:
            raise ValueError("Task must be Paused or Closed before Rerun")
        self._release_abandoned_merge_slot(task)
        self.tasks.reset_to_new(
            project,
            task_id,
            request_id=request,
            action="rerun",
        )
        return self.start(project, task_id, request_id=run_request_id)

    def merge(self, project: Path, task_id: str) -> dict[str, Any]:
        project = Path(project).expanduser().resolve()
        task = self.tasks.get(project, task_id)
        recovery = self._recovery_record(task)
        if str(recovery.get("status") or "") in {"prepared", "running", "launch_failed", "stopped"}:
            raise ValueError("Task merge recovery is still in progress")
        prepared, snapshot = self._current_merge_source(task)
        return self._apply_merge(project, task_id, prepared, snapshot)

    def publish(
        self,
        project: Path,
        task_id: str,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        """Explicit remote publication; never part of Task merge/recovery lifecycle."""
        project = Path(project).expanduser().resolve()
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("request_id is required")
        if len(request) > 240:
            raise ValueError("request_id is too long")

        task = self.tasks.get(project, task_id)
        if task.get("status") != "closed":
            raise ValueError("Task must be Closed before Publish")
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        value = self._workspace_result(task)
        existing = value.get("publish")
        if isinstance(existing, dict) and str(existing.get("request_id") or "") == request:
            return self.get(project, task_id)

        source, snapshot = self._current_merge_source(task)
        merge = value.get("merge") if isinstance(value.get("merge"), dict) else {}
        merge_status = str(merge.get("status") or run.get("phase") or "")
        if merge_status in {"merged", "no_changes"}:
            branch = source.target_branch
            expected_sha = str(merge.get("merged_target_head_sha") or "")
        elif merge_status == "worktree_ready":
            branch = source.task_branch
            expected_sha = snapshot.task_snapshot_sha
        else:
            raise ValueError("Task result is not ready to Publish")
        if not expected_sha:
            raise ValueError("Task Publish SHA is missing")

        published = self._publisher.publish(
            source,
            branch=branch,
            expected_sha=expected_sha,
        )
        record = published.as_dict()
        record["request_id"] = request
        value["publish"] = record
        self.tasks.transition_run(
            project,
            task_id,
            int(run.get("run_number") or 0),
            phase=str(run.get("phase") or merge_status),
            status="closed",
            error=str(run.get("error") or ""),
            workspace_result=value,
        )
        return self.get(project, task_id)

    def reconcile(self, project: Path, task_id: str) -> dict[str, Any]:
        """Advance Task lifecycle while keeping Runner and Git orchestration separate."""
        project = Path(project).expanduser().resolve()
        task = self.tasks.get(project, task_id)
        if task.get("status") != "ongoing":
            return self.get(project, task_id)

        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        phase = str(run.get("phase") or "")
        if self._ready_for_next_item(task):
            return self._start_next_item(project, task_id, task)
        if phase in {
            "merging",
            "pending_merge",
            "validation_required",
            "waiting_target_clean",
            "waiting_target_workspace",
            "waiting_target_branch",
            "waiting_target_history",
            "technical_error",
        }:
            prepared, snapshot = self._current_merge_source(task)
            return self._apply_merge(project, task_id, prepared, snapshot)

        prepared = self._runtime_workspace(task)
        runtime = self._read_runtime(prepared.project_root)
        in_recovery = self._is_recovery_workspace(task, prepared)
        if runtime.get("running") or runtime.get("launching"):
            next_phase = "conflict_recovery" if in_recovery else (
                "running" if runtime.get("running") else "launching"
            )
            if phase != next_phase:
                self.tasks.transition_run(
                    project,
                    task_id,
                    prepared.run_number,
                    phase=next_phase,
                    status="ongoing",
                )
            return self.get(project, task_id)

        has_runtime_evidence = bool(
            runtime.get("completed")
            or runtime.get("resumable")
            or runtime.get("stale")
            or runtime.get("has_state")
            or (runtime.get("actions") or {}).get("resume")
        )
        if not has_runtime_evidence and phase == "launching":
            item_index = int(run.get("item_index") or 0)
            items = task.get("items") if isinstance(task.get("items"), list) else []
            if item_index < 0 or item_index >= len(items):
                raise ValueError("Task Run item_index is invalid")
            return self._launch_task(project, task_id, items[item_index], prepared)
        recovery_record = self._recovery_record(task)
        if (
            in_recovery
            and not has_runtime_evidence
            and str(recovery_record.get("status") or "") == "prepared"
        ):
            prompt = str(recovery_record.get("prompt") or "")
            if not prompt:
                raise ValueError("Merge recovery prompt is missing")
            return self._launch_merge_recovery(project, task_id, prepared, prompt)

        if runtime.get("completed"):
            current_result = self._workspace_result(task)
            if in_recovery:
                snapshot = self._workspaces.snapshot_result(
                    prepared,
                    excluded_paths=(prepared.project_root / ".ai-task-runner",),
                )
                recovery = dict(current_result.get("recovery") or {})
                recovery["status"] = "completed"
                recovery["snapshot"] = snapshot.as_dict()
                current_result["recovery"] = recovery
                current_result["merge_source"] = {
                    "workspace": prepared.as_dict(),
                    "snapshot": snapshot.as_dict(),
                }
                base_result = {
                    **current_result,
                    "effective_mode": prepared.effective_mode,
                    "branch": prepared.task_branch,
                    "path": str(prepared.worktree_path),
                }
                self.tasks.transition_run(
                    project,
                    task_id,
                    prepared.run_number,
                    phase="merging",
                    status="ongoing",
                    workspace_result=base_result,
                )
                return self._apply_merge(project, task_id, prepared, snapshot)

            snapshot = self._snapshot_from_result(current_result)
            if snapshot is None:
                snapshot = self._workspaces.snapshot_result(
                    prepared,
                    excluded_paths=(prepared.project_root / ".ai-task-runner",),
                )
            base_result = {
                **current_result,
                "snapshot": snapshot.as_dict(),
                "merge_source": {
                    "workspace": prepared.as_dict(),
                    "snapshot": snapshot.as_dict(),
                },
                "effective_mode": prepared.effective_mode,
                "branch": prepared.task_branch,
                "path": str(prepared.worktree_path),
            }
            if prepared.effective_mode == "worktree":
                return self._complete_item(
                    project,
                    task_id,
                    prepared.run_number,
                    phase="worktree_ready",
                    workspace_result={
                        **base_result,
                        "merge": {"status": "worktree_ready"},
                    },
                )
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
            if in_recovery:
                value = self._workspace_result(task)
                recovery = dict(value.get("recovery") or {})
                recovery["status"] = "stopped"
                value["recovery"] = recovery
                self.tasks.transition_run(
                    project,
                    task_id,
                    prepared.run_number,
                    phase="recovery_stopped",
                    status="paused",
                    error=str(runtime.get("last_error") or ""),
                    workspace_result=value,
                )
            else:
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
        task = self.tasks.get(project, task_id)
        current = (task.get("run") or {}).get("workspace_result")
        value = dict(current) if isinstance(current, dict) else {}
        value.setdefault("snapshot", snapshot.as_dict())
        value.setdefault(
            "merge_source",
            {"workspace": prepared.as_dict(), "snapshot": snapshot.as_dict()},
        )
        value.update({
            "effective_mode": prepared.effective_mode,
            "branch": prepared.task_branch,
            "path": str(prepared.worktree_path),
        })

        if (
            int(task.get("merge_failure_count", 0)) > self._merge_failure_limit()
            and isinstance(value.get("last_merge_failure"), dict)
        ):
            return self._finalize_merge_fallback(
                project,
                task_id,
                task,
                prepared,
                snapshot,
                value,
            )

        validate = self._merge_validation_callback(project, task)
        result = self._merges.merge(prepared, snapshot, validate=validate)
        value["merge"] = result.as_dict()
        if result.status in {"merged", "no_changes"}:
            return self._complete_item(
                project,
                task_id,
                prepared.run_number,
                phase=result.status,
                workspace_result=value,
            )
        elif result.real_merge_failure:
            failure = self._merge_failure_record(prepared, snapshot, result)
            increment = (
                self._merge_failure_identity(value.get("last_merge_failure"))
                != self._merge_failure_identity(failure)
            )
            value["last_merge_failure"] = failure
            task = self.tasks.transition_run(
                project,
                task_id,
                prepared.run_number,
                phase=result.status,
                status="ongoing",
                workspace_result=value,
                increment_merge_failure=increment,
                error=result.detail,
            )
            if int(task.get("merge_failure_count", 0)) > self._merge_failure_limit():
                return self._finalize_merge_fallback(
                    project,
                    task_id,
                    task,
                    prepared,
                    snapshot,
                    value,
                )
            return self._start_merge_recovery(
                project,
                task_id,
                task,
                prepared,
                snapshot,
                result,
                value,
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

    def _merge_validation_callback(
        self,
        source_project: Path,
        task: dict[str, Any],
    ) -> Callable[[Path], str] | None:
        if self._validate_merge is None:
            return None
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        item_index = int(run.get("item_index") or 0)
        items = task.get("items") if isinstance(task.get("items"), list) else []
        if item_index < 0 or item_index >= len(items):
            raise ValueError("Task Run item_index is invalid")
        item = items[item_index]
        preferences = self._preferences(source_project)
        backend = (
            str(preferences.get("agent") or "").strip()
            or self._backend_default(source_project)
        )
        workflow = self._resolve_workflow(
            source_project,
            str(item.get("workflow") or ""),
        )
        goal = str(item.get("prompt") or task.get("title") or "Merge validation").strip()

        def validate(target_project: Path) -> str:
            validator = self._runtime_input_path(
                source_project,
                target_project,
                str(item.get("validator") or ""),
            )
            verdict = self._validate_merge(
                target_project,
                goal,
                backend=backend,
                validator=validator,
                workflow=str(workflow),
            )
            return str(verdict or "").strip().upper()

        return validate

    def _start_merge_recovery(
        self,
        project: Path,
        task_id: str,
        task: dict[str, Any],
        source: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
        failure: MergeResult,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        failure_number = int(task.get("merge_failure_count", 0))
        recovery = self._workspaces.prepare_recovery(
            source,
            snapshot,
            failure_number=failure_number,
        )
        patch = self._workspaces.recovery_patch(source, snapshot)
        patch_path = self._write_recovery_patch(recovery, failure_number, patch)
        prompt = self._merge_recovery_prompt(
            task,
            source,
            snapshot,
            recovery,
            failure,
            patch_path,
        )
        recovery_record = {
            "status": "prepared",
            "failure_number": failure_number,
            "workspace": recovery.as_dict(),
            "source_workspace": source.as_dict(),
            "source_snapshot": snapshot.as_dict(),
            "patch_path": str(patch_path),
            "prompt": prompt,
        }
        value = dict(value)
        value["recovery"] = recovery_record
        self.tasks.transition_run(
            project,
            task_id,
            recovery.run_number,
            phase="conflict_recovery",
            status="ongoing",
            error="",
            workspace_result=value,
        )
        return self._launch_merge_recovery(project, task_id, recovery, prompt)

    def _launch_merge_recovery(
        self,
        source_project: Path,
        task_id: str,
        recovery: PreparedWorkspace,
        prompt: str,
    ) -> dict[str, Any]:
        task = self.tasks.get(source_project, task_id)
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        item_index = int(run.get("item_index") or 0)
        item = task["items"][item_index]
        preferences = self._preferences(source_project)
        backend = str(preferences.get("agent") or "").strip() or self._backend_default(source_project)
        workflow = self._resolve_workflow(source_project, str(item.get("workflow") or ""))
        mode = str(preferences.get("mode") or "auto")
        try:
            self._launch(
                recovery.project_root,
                prompt,
                mode="run",
                backend=backend,
                model=str(preferences.get("model") or ""),
                validator=self._runtime_input_path(
                    source_project,
                    recovery.project_root,
                    str(item.get("validator") or ""),
                ),
                workflow=str(workflow),
                goal_file=None,
                ai_validator_prompt_file=self._ai_prompt_path(
                    source_project,
                    recovery,
                    item,
                ),
                readonly_safety="observe" if mode == "read" else "restore",
            )
        except Exception as exc:
            task = self.tasks.get(source_project, task_id)
            value = self._workspace_result(task)
            recovery_record = dict(value.get("recovery") or {})
            recovery_record["status"] = "launch_failed"
            value["recovery"] = recovery_record
            self.tasks.transition_run(
                source_project,
                task_id,
                recovery.run_number,
                phase="recovery_launch_failed",
                status="paused",
                error=f"{type(exc).__name__}: {exc}",
                workspace_result=value,
            )
            raise

        task = self.tasks.get(source_project, task_id)
        value = self._workspace_result(task)
        recovery_record = dict(value.get("recovery") or {})
        recovery_record["status"] = "running"
        value["recovery"] = recovery_record
        self.tasks.transition_run(
            source_project,
            task_id,
            recovery.run_number,
            phase="conflict_recovery",
            status="ongoing",
            error="",
            workspace_result=value,
        )
        self._ensure_watcher(source_project, task_id)
        return self.get(source_project, task_id)

    @staticmethod
    def _merge_recovery_prompt(
        task: dict[str, Any],
        source: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
        recovery: PreparedWorkspace,
        failure: MergeResult,
        patch_path: Path,
    ) -> str:
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        item_index = int(run.get("item_index") or 0)
        items = task.get("items") if isinstance(task.get("items"), list) else []
        item = items[item_index] if 0 <= item_index < len(items) else {}
        intent = str(item.get("prompt") or task.get("title") or "").strip()
        conflicts = ", ".join(failure.conflict_files) or "(validation/source failure)"
        try:
            patch_label = patch_path.resolve().relative_to(recovery.project_root.resolve()).as_posix()
        except ValueError:
            patch_label = str(patch_path)
        return (
            "Merge-repair task only. Do not redo the original feature from scratch.\n\n"
            f"Original Task intent:\n{intent}\n\n"
            f"Original Task base SHA: {source.task_base_sha}\n"
            f"Committed Task snapshot SHA: {snapshot.task_snapshot_sha}\n"
            f"Current merge source branch: {source.task_branch}\n"
            f"Latest target HEAD used by this recovery workspace: {recovery.task_base_sha}\n"
            f"Conflict/source-failure files: {conflicts}\n"
            f"Git/validation detail: {failure.detail or failure.status}\n"
            f"Committed Task diff is stored at: {patch_label}\n\n"
            "Work incrementally in this latest-target-based workspace. Preserve current Project changes, "
            "port the completed Task behavior from the patch, and resolve only integration differences. "
            "Do not replace the whole tree, re-clone, re-pull, or restart full feature development. "
            "Read and obey AGENTS.md, DevFollow.txt, and any project-local development rules visible here. "
            "Leave unrelated files unchanged. The normal Workflow review/validation remains authoritative."
        )

    @staticmethod
    def _write_recovery_patch(
        recovery: PreparedWorkspace,
        failure_number: int,
        patch: str,
    ) -> Path:
        root = recovery.project_root / ".ai-task-runner" / "ui" / "merge-recovery"
        root.mkdir(parents=True, exist_ok=True)
        path = root / (
            f"{recovery.task_id}-r{recovery.run_number}-f{int(failure_number)}.patch"
        )
        path.write_text(str(patch), encoding="utf-8")
        return path

    def _finalize_merge_fallback(
        self,
        project: Path,
        task_id: str,
        task: dict[str, Any],
        prepared: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
        value: dict[str, Any],
    ) -> dict[str, Any]:
        self._merges.release_merge_slot(prepared, snapshot)
        fallback = dict(value)
        merge = dict(fallback.get("merge") or {})
        attempt_status = str(merge.get("attempt_status") or merge.get("status") or "")
        merge.update({
            "status": "worktree_ready",
            "attempt_status": attempt_status,
            "detail": str(merge.get("detail") or ""),
        })
        fallback["merge"] = merge
        fallback["delivery_fallback"] = {
            "mode": "isolated_worktree",
            "reason": "merge_failure_limit_exceeded",
        }
        return self._complete_item(
            project,
            task_id,
            prepared.run_number,
            phase="worktree_ready",
            workspace_result=fallback,
            error=str(merge.get("detail") or ""),
        )

    def _complete_item(
        self,
        project: Path,
        task_id: str,
        run_number: int,
        *,
        phase: str,
        workspace_result: dict[str, Any],
        error: str = "",
    ) -> dict[str, Any]:
        task = self.tasks.get(project, task_id)
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        if int(run.get("run_number") or 0) != int(run_number):
            raise ValueError("Task Run identity is stale")
        item_index = int(run.get("item_index") or 0)
        items = task.get("items") if isinstance(task.get("items"), list) else []
        completed = item_index + 1
        if completed <= 0 or completed > len(items):
            raise ValueError("Task Run item_index is invalid")
        final = completed >= len(items)
        updated = self.tasks.transition_run(
            project,
            task_id,
            run_number,
            phase=phase,
            status="closed" if final else "ongoing",
            workspace_result=workspace_result,
            completed_item_count=completed,
            error=error,
        )
        if final:
            return self.get(project, task_id)
        return self._start_next_item(project, task_id, updated)

    def _start_next_item(
        self,
        project: Path,
        task_id: str,
        task: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current = task or self.tasks.get(project, task_id)
        if not self._ready_for_next_item(current):
            return self.get(project, task_id)
        next_run = int(current.get("run_count", 0)) + 1
        request_id = f"task-sequence:{task_id}:{next_run}"
        return self.start(project, task_id, request_id=request_id)

    @staticmethod
    def _ready_for_next_item(task: dict[str, Any]) -> bool:
        if task.get("status") != "ongoing":
            return False
        items = task.get("items") if isinstance(task.get("items"), list) else []
        completed = int(task.get("completed_item_count", 0))
        if completed <= 0 or completed >= len(items):
            return False
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        return (
            str(run.get("phase") or "") in COMPLETED_ITEM_PHASES
            and completed == int(run.get("item_index") or 0) + 1
        )

    def _merge_failure_limit(self) -> int:
        settings = self._execution_settings()
        try:
            limit = int(settings.get("merge_failure_limit", 3))
        except (TypeError, ValueError) as exc:
            raise ValueError("Global merge_failure_limit is invalid") from exc
        if limit < 0 or limit > 99:
            raise ValueError("Global merge_failure_limit is out of range")
        return limit

    @staticmethod
    def _merge_failure_record(
        prepared: PreparedWorkspace,
        snapshot: WorkspaceSnapshot,
        result: MergeResult,
    ) -> dict[str, Any]:
        return {
            "status": result.status,
            "source_branch": prepared.task_branch,
            "source_sha": snapshot.task_snapshot_sha,
            "source_base_sha": prepared.task_base_sha,
            "source_worktree": str(prepared.worktree_path),
            "target_head_sha": result.target_head_sha,
            "verdict": result.verdict,
            "conflict_files": list(result.conflict_files),
            "merge_queue_seq": result.merge_queue_seq,
            "detail": result.detail,
        }

    @staticmethod
    def _merge_failure_identity(value: Any) -> tuple[Any, ...]:
        if not isinstance(value, dict):
            return ()
        conflicts = value.get("conflict_files")
        return (
            str(value.get("status") or ""),
            str(value.get("source_sha") or ""),
            str(value.get("target_head_sha") or ""),
            str(value.get("verdict") or ""),
            tuple(str(item) for item in conflicts) if isinstance(conflicts, list) else (),
        )

    def _project_runtime(self, project: Path, task: dict[str, Any]) -> dict[str, Any]:
        value = dict(task)
        run = value.get("run")
        if not isinstance(run, dict) or not isinstance(run.get("workspace"), dict):
            value["runner_runtime"] = {}
            return value
        try:
            prepared = self._runtime_workspace(value)
            value["runner_runtime"] = self._read_runtime(prepared.project_root)
        except Exception as exc:
            value["runner_runtime"] = {
                "running": False,
                "status": "needs_attention",
                "last_error": f"{type(exc).__name__}: {exc}",
            }
        return value

    @staticmethod
    def _snapshot_from_result(result: dict[str, Any]) -> WorkspaceSnapshot | None:
        raw = result.get("snapshot") if isinstance(result, dict) else None
        if not isinstance(raw, dict):
            return None
        sha = str(raw.get("task_snapshot_sha") or "").strip()
        if not sha:
            return None
        return WorkspaceSnapshot(
            task_snapshot_sha=sha,
            no_changes=bool(raw.get("no_changes")),
            created_commit=bool(raw.get("created_commit")),
        )

    @staticmethod
    def _workspace_result(task: dict[str, Any]) -> dict[str, Any]:
        run = task.get("run") if isinstance(task.get("run"), dict) else {}
        result = run.get("workspace_result")
        return dict(result) if isinstance(result, dict) else {}

    def _recovery_record(self, task: dict[str, Any]) -> dict[str, Any]:
        value = self._workspace_result(task).get("recovery")
        return dict(value) if isinstance(value, dict) else {}

    def _runtime_workspace(self, task: dict[str, Any]) -> PreparedWorkspace:
        run = task.get("run")
        if not isinstance(run, dict) or not isinstance(run.get("workspace"), dict):
            raise ValueError("Task does not have a prepared Run workspace")
        recovery = self._recovery_record(task)
        if (
            str(recovery.get("status") or "") in {"prepared", "running", "launch_failed", "stopped"}
            and isinstance(recovery.get("workspace"), dict)
        ):
            return self._workspaces.restore_merge_source(recovery["workspace"])
        return self._workspaces.restore(run["workspace"])

    def _is_recovery_workspace(
        self,
        task: dict[str, Any],
        prepared: PreparedWorkspace,
    ) -> bool:
        recovery = self._recovery_record(task)
        workspace = recovery.get("workspace")
        return (
            isinstance(workspace, dict)
            and str(workspace.get("task_branch") or "") == prepared.task_branch
            and prepared.task_branch.startswith("local/recovery/")
        )

    def _release_abandoned_merge_slot(self, task: dict[str, Any]) -> None:
        """Release only an owned real-failure queue head before explicit lifecycle abandonment."""
        result = self._workspace_result(task)
        merge = result.get("merge")
        if not isinstance(merge, dict):
            return
        if str(merge.get("status") or "") not in {"conflict", "source_fail"}:
            return
        try:
            queue_seq = int(merge.get("merge_queue_seq") or 0)
        except (TypeError, ValueError):
            queue_seq = 0
        if queue_seq <= 0:
            return
        prepared, snapshot = self._current_merge_source(task)
        self._merges.release_merge_slot(prepared, snapshot)

    def _current_merge_source(
        self,
        task: dict[str, Any],
    ) -> tuple[PreparedWorkspace, WorkspaceSnapshot]:
        run = task.get("run")
        if not isinstance(run, dict) or not isinstance(run.get("workspace"), dict):
            raise ValueError("Task does not have a prepared Run workspace")
        result = self._workspace_result(task)
        source = result.get("merge_source")
        if isinstance(source, dict) and isinstance(source.get("workspace"), dict):
            prepared = self._workspaces.restore_merge_source(source["workspace"])
            snapshot = self._snapshot_from_result({"snapshot": source.get("snapshot")})
            if snapshot is None:
                raise ValueError("Current merge source snapshot is missing")
            return prepared, snapshot
        prepared = self._workspaces.restore(run["workspace"])
        snapshot = self._snapshot_from_result(result)
        if snapshot is None:
            raise ValueError("Task result has not been snapshotted")
        return prepared, snapshot

    def _current_workspace(self, project: Path, task_id: str) -> tuple[dict[str, Any], PreparedWorkspace]:
        task = self.tasks.get(project, task_id)
        return task, self._runtime_workspace(task)

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
                        current = self.tasks.get(project, task_id)
                        prepared = self._runtime_workspace(current)
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
                if phase in {
                    "validation_required",
                    "waiting_target_history",
                    "waiting_target_branch",
                    "waiting_target_workspace",
                    "waiting_target_clean",
                    "technical_error",
                }:
                    return
                time.sleep(self._poll_interval)
        finally:
            with self._watch_lock:
                self._watching.discard(key)
