"""Small Stage-list orchestration runner."""
from __future__ import annotations

import argparse
from pathlib import Path

from .model import create_model
from .config import RuntimeConfig
from .errors import RunnerError
from .runtime import progress as runner_status
from .utils.project import cleanup_stale_artifacts
from .flow.stages import StageContext, StageExecutor
from .flow.pipeline import build_pipeline
from .runtime.state import StateStore, normalize_state, set_stage

show_todo = runner_status.show_todo


class TaskRunner:
    """Run a pipeline until Final Validator completion."""

    def __init__(self, args: RuntimeConfig | argparse.Namespace) -> None:
        self.args = args if isinstance(args, RuntimeConfig) else RuntimeConfig.from_namespace(args)
        if not self.args.validator:
            raise RunnerError("--validator is required unless --script is used")
        self.root = Path(self.args.project_root).resolve()
        self.ai_validation = self.args.validator.lower() == "ai"
        self.validator = None if self.ai_validation else Path(self.args.validator).resolve()
        self.work = self.root / self.args.work_dir
        self.state_store = StateStore(self.root, self.work)
        self.state_file = self.state_store.path
        self._validate_paths()
        cleanup_stale_artifacts(self.work)

        self.state = self.state_store.load_or_create(
            self.args.goal, resume=self.args.resume, force_new=self.args.force_new
        )
        self.model = create_model(
            self.args,
            self.root,
            self.work / "debug",
            session_id=self.state.model_session_id,
            timeout=self.args.agent_timeout,
        )
        self.backend_files = self.model.prepare_project()
        self.model.update_goal_reference(self.args.goal_file)
        if not self.args.resume:
            self._save_state()
        if normalize_state(self.state):
            self._save_state()
        runner_status.bind(self.state)

        self.context = StageContext(
            args=self.args,
            root=self.root,
            work=self.work,
            state=self.state,
            model=self.model,
            state_file=self.state_file,
            validator=self.validator,
            ai_validation=self.ai_validation,
            save_state=self._save_state,
            set_stage=self._set_stage,
        )
        self.pipeline = build_pipeline(self.context)
        self.stage_executor = StageExecutor()

    def run(self) -> int:
        if self.args.plan_only and self.state.tasks:
            runner_status.set_status("Plan ready", "plan-only completed without execution")
            return 0
        return self.pipeline.run(self.stage_executor, plan_only=self.args.plan_only)

    def _validate_paths(self) -> None:
        if not self.root.is_dir() or (self.validator is not None and not self.validator.is_file()):
            raise RunnerError("invalid project root or validator")

    def _save_state(self) -> None:
        self.state_store.save(self.state)

    def _set_stage(self, stage: str, detail: str = "") -> None:
        set_stage(self.state, stage, detail)
        self._save_state()
