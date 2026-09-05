#!/usr/bin/env python3
"""Validate a generated Workflow draft before it is published."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate AI-generated Workflow draft files")
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file")
    parser.add_argument("--draft-workflow", required=True)
    parser.add_argument("--draft-prompt-dir", required=True)
    return parser


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _prompt_refs(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"prompt", "continuation_prompt"} and isinstance(child, str) and child.strip():
                yield child.strip()
            yield from _prompt_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _prompt_refs(child)


def validate_draft(project_root: Path, draft_workflow: Path, draft_prompt_dir: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    draft_workflow = draft_workflow.resolve()
    draft_prompt_dir = draft_prompt_dir.resolve()
    if not _inside(draft_workflow, project_root) or not _inside(draft_prompt_dir, project_root):
        raise ValueError("draft paths must stay inside project root")
    if not draft_workflow.is_file():
        raise ValueError(f"missing generated Workflow: {draft_workflow}")
    if not draft_prompt_dir.is_dir():
        raise ValueError(f"missing generated Prompt directory: {draft_prompt_dir}")

    import yaml
    try:
        data = yaml.safe_load(draft_workflow.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid generated Workflow YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("generated Workflow must be a YAML object")
    if not isinstance(data.get("stages"), dict):
        raise ValueError("generated Workflow requires stages")
    if not isinstance(data.get("flow"), list) or not data["flow"]:
        raise ValueError("generated Workflow requires a non-empty flow")

    missing: list[str] = []
    refs: list[str] = []
    for ref in _prompt_refs(data):
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            candidate = (draft_workflow.parent / candidate).resolve()
        refs.append(ref)
        if not candidate.is_file():
            missing.append(ref)
    if missing:
        raise ValueError("missing Prompt file(s): " + ", ".join(sorted(set(missing))))

    command = [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(draft_workflow), "--matrix", "--json", "--max-steps", "500"]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=45)
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0:
        raise ValueError("workflow dry-run failed: " + output[-12000:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("workflow dry-run did not return JSON") from exc
    if not payload.get("closed"):
        raise ValueError("workflow dry-run matrix did not reach closure")
    return {
        "ok": True,
        "workflow": str(draft_workflow),
        "prompt_refs": sorted(set(refs)),
        "paths_passed": payload.get("paths_passed", 0),
        "paths_total": payload.get("paths_total", 0),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = validate_draft(
            Path(args.project_root),
            Path(args.draft_workflow) if Path(args.draft_workflow).is_absolute() else Path(args.project_root) / args.draft_workflow,
            Path(args.draft_prompt_dir) if Path(args.draft_prompt_dir).is_absolute() else Path(args.project_root) / args.draft_prompt_dir,
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1
    print("PASS: " + json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
