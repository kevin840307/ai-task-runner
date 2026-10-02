"""Shared Workflow runtime entry point."""
from __future__ import annotations

from pathlib import Path

from .agent import create_ai_client
from .config.runtime import RuntimeConfig
from .errors import ConfigurationError, RunnerError
from .workspace import cleanup_stale_artifacts, register_ui_project
from .runtime import events as progress
from .runtime.run_state import StateStore, normalize_state, set_stage
from .workflow.flow_engine import build_flow_engine
from .workflow.loader import workflow_fingerprint
from .resources import freeze_run_resource, freeze_workflow, load_run_resource, load_snapshot
from .workflow.stage_executor import StageExecutor
from .workflow.stages import StageContext


class WorkflowRunner:
    """Run one Workflow request through the shared Stage/Flow runtime."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        self._validate_request()
        self._prepare_paths()
        self._bind_run_resources()
        self._bind_workflow_snapshot()
        self._prepare_state()
        self._prepare_ai_client()
        self._finalize_state()
        self.context = self._build_context()
        self.flow_engine = build_flow_engine(self.context)

        self.stage_executor = StageExecutor()

    def _validate_request(self) -> None:
        if not self.config.validator and not self.config.workflow_explicit:
            raise RunnerError(
                "--validator is required unless an explicit workflow is used"
            )

    def _prepare_paths(self) -> None:
        self.root = Path(self.config.project_root).resolve()
        if self.config.auto_register_ui_project:
            register_ui_project(self.root, project_name=self.config.project_name)

        self.validator_is_ai = (
            bool(self.config.validator)
            and self.config.validator.lower() == "ai"
        )
        self.validator_path = (
            None
            if not self.config.validator or self.validator_is_ai
            else Path(self.config.validator).resolve()
        )
        self.work = self.root / self.config.work_dir
        self.state_store = StateStore(self.root, self.work)
        self.state_file = self.state_store.path

        self._validate_paths()
        cleanup_stale_artifacts(self.work)

    def _bind_workflow_snapshot(self) -> None:
        if self.config.resume and not self.config.force_new:
            frozen = load_snapshot(self.root, self.config.work_dir)
            if frozen is not None:
                self.config.workflow = frozen
            return

        self.config.workflow = freeze_workflow(
            self.config.workflow,
            self.root,
            self.config.work_dir,
        )

    def _prepare_state(self) -> None:
        self.state = self.state_store.load_or_create(
            self.config.goal,
            resume=self.config.resume,
            force_new=self.config.force_new,
        )
        fingerprint = workflow_fingerprint(self.config.workflow)
        if self.state.workflow_fingerprint not in {"", fingerprint}:
            raise ConfigurationError(
                "resume workflow differs from the saved workflow"
            )
        self._new_workflow_fingerprint = not self.state.workflow_fingerprint
        self.state.workflow_fingerprint = fingerprint

    def _prepare_ai_client(self) -> None:
        self.ai_client = create_ai_client(
            self.config,
            self.root,
            self.work / "debug",
            session_id=self.state.ai_session_id,
            timeout=self.config.agent_timeout,
        )
        self.ai_client.prepare_project()
        self.ai_client.update_goal_reference(self.config.goal_file)

    def _finalize_state(self) -> None:
        if not self.config.resume or self._new_workflow_fingerprint:
            self._save_state()
        if normalize_state(self.state):
            self._save_state()
        progress.bind(self.state)

    def _build_context(self) -> StageContext:
        return StageContext(
            config=self.config,
            root=self.root,
            work=self.work,
            state=self.state,
            ai_client=self.ai_client,
            state_file=self.state_file,
            validator_path=self.validator_path,
            validator_is_ai=self.validator_is_ai,
            save_state=self._save_state,
            set_stage=self._set_stage,
        )

    def _bind_run_resources(self) -> None:
        resources = (
            ("goal_file", "goal", "goal"),
            (
                "ai_validator_prompt_file",
                "ai_validator_prompt",
                "ai_validator_prompt",
            ),
        )
        for file_attr, content_attr, name in resources:
            value = (
                load_run_resource(self.root, self.config.work_dir, name)
                if self.config.resume and not self.config.force_new
                else freeze_run_resource(
                    getattr(self.config, file_attr),
                    self.root,
                    self.config.work_dir,
                    name,
                )
            )
            if value is None:
                continue
            filename, text = value
            setattr(self.config, file_attr, filename)
            setattr(self.config, content_attr, text)

    def run(self) -> int:
        return self.flow_engine.run(self.stage_executor)

    def _validate_paths(self) -> None:
        if not self.root.is_dir() or (
            self.validator_path is not None
            and not self.validator_path.is_file()
        ):
            raise ConfigurationError("invalid project root or validator")

    def _save_state(self) -> None:
        self.state_store.save(self.state)

    def _set_stage(self, stage: str, detail: str = "") -> None:
        set_stage(self.state, stage, detail)
        self._save_state()


__all__ = ["WorkflowRunner"]
