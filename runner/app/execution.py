"""Application bootstrap for one run or YAML-script child run."""
from __future__ import annotations

import argparse

from ..config import RuntimeConfig
from ..engine.core import TaskRunner
from ..runtime.extensions import bootstrap
from .script_runner import execute_script as execute_yaml_script


def execute(args: RuntimeConfig | argparse.Namespace) -> int:
    if not isinstance(args, RuntimeConfig):
        args = RuntimeConfig.from_namespace(args)
    bootstrap(args)
    if args.script:
        return execute_yaml_script(args, execute)
    return TaskRunner(args).run()


__all__ = ["execute"]
