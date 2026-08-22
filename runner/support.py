"""Backward-compatible support facade and small generic utilities."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Sequence

from .defaults import MAX_TASK_OUTPUT_CHARS, MAX_VALIDATOR_OUTPUT_CHARS, NO_PROGRESS_LIMIT
from .errors import RunnerError
# Compatibility re-exports keep existing runner.support imports stable.
from .model_results import (
    MAX_MISSING_ITEM_CHARS,
    MAX_MISSING_ITEMS,
    MAX_RESULT_REASON_CHARS,
    parse_ai_validation,
    parse_json,
    parse_plan_judgment,
    parse_review,
    parse_tasks,
    require_non_empty_string,
    require_string_list,
)
from .model_call import recover_structured_output, retry_model_call
from .project_guard import (
    STALE_TEMP_SECONDS,
    changed_project_files,
    changed_snapshot_paths,
    cleanup_stale_artifacts,
    digest,
    normalize_protected_paths,
    progress_key,
    project_fingerprint,
    project_manifest,
    protected_ask,
    protected_change_detector,
    readonly_ask,
    readonly_project_call,
    restore_changed,
    runner_source_files,
    snapshot,
)
from .ui import LiveUI

JSON_WRITE_RETRIES = 10
JSON_WRITE_RETRY_DELAY = 0.05

def write_json(path: Path, data: Any) -> None:
    """Atomically write indented UTF-8 JSON with Windows lock tolerance."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for attempt in range(JSON_WRITE_RETRIES):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == JSON_WRITE_RETRIES - 1:
                raise
            time.sleep(JSON_WRITE_RETRY_DELAY * (attempt + 1))


def run_file_validator(
    path: Path,
    root: Path,
    state_file: Path,
    timeout: int,
    extra_args: Sequence[str],
    protected: Sequence[Path],
) -> tuple[bool, str]:
    """Compatibility wrapper; validator execution lives in validation.py."""
    from .validation import run_file_validator as run
    return run(path, root, state_file, timeout, extra_args, protected)
