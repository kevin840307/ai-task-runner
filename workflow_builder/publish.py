#!/usr/bin/env python3
"""Publish a previously validated Workflow Builder draft."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from workflow_builder.run import _publish
from workflow_builder.validation import validate_draft


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Publish an existing Workflow Builder draft")
    p.add_argument("--project-root", required=True)
    p.add_argument("--draft-workflow", required=True)
    p.add_argument("--draft-prompt-dir", required=True)
    p.add_argument("--output-workflow", required=True)
    p.add_argument("--output-prompt-dir", required=True)
    p.add_argument("--overwrite", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project_root).expanduser().resolve()
    workflow = Path(args.draft_workflow).expanduser().resolve()
    prompts = Path(args.draft_prompt_dir).expanduser().resolve()
    try:
        validation = validate_draft(project, workflow, prompts)
        published = _publish(
            workflow,
            prompts,
            Path(args.output_workflow),
            Path(args.output_prompt_dir),
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps({"ok": True, "validation": validation, "output": published}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
