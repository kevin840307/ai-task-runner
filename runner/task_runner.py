"""Single-task workflow orchestration."""
from __future__ import annotations

from pathlib import Path

from .ai import create_ai_client
from .config import RuntimeConfig
from .errors import RunnerError
from .project.files import cleanup_stale_artifacts
from .runtime import progress
from .runtime.run_state import StateStore, normalize_state, set_stage
from .workflow.pipeline import build_pipeline
from .workflow.stages import StageContext, StageExecutor


class TaskRunner:
    """Run one task request until final validation completes."""

    def __init__(self, config: RuntimeConfig) -> None:
        self.config = config
        if not self.config.validator:
            raise RunnerError("--validator is required unless --script is used")

        self.root = Path(self.config.project_root).resolve()
        self.validator_is_ai = self.config.validator.lower() == "ai"
        self.validator_path = None if self.validator_is_ai else Path(self.config.validator).resolve()
        self.work = self.root / self.config.work_dir
        self.state_store = StateStore(self.root, self.work)
        self.state_file = self.state_store.path
        self._validate_paths()
        cleanup_stale_artifacts(self.work)

        self.state = self.state_store.load_or_create(
            self.config.goal,
            resume=self.config.resume,
            force_new=self.config.force_new,
        )
        self.ai_client = create_ai_client(
            self.config,
            self.root,
            self.work / "debug",
            session_id=self.state.ai_session_id,
            timeout=self.config.agent_timeout,
        )
        self.ai_client.prepare_project()
        self.ai_client.update_goal_reference(self.config.goal_file)
        if not self.config.resume:
            self._save_state()
        if normalize_state(self.state):
            self._save_state()
        progress.bind(self.state)

        self.context = StageContext(
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
        self.pipeline = build_pipeline(self.context)
        self.stage_executor = StageExecutor()

    def run(self) -> int:
        if self.config.plan_only and self.state.tasks:
            progress.set_status("Plan ready", "plan-only completed without execution")
            return 0
        return self.pipeline.run(self.stage_executor, plan_only=self.config.plan_only)

    def _validate_paths(self) -> None:
        if not self.root.is_dir() or (
            self.validator_path is not None and not self.validator_path.is_file()
        ):
            raise RunnerError("invalid project root or validator")

    def _save_state(self) -> None:
        self.state_store.save(self.state)

    def _set_stage(self, stage: str, detail: str = "") -> None:
        set_stage(self.state, stage, detail)
        self._save_state()
