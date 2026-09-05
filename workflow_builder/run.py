#!/usr/bin/env python3
"""Generate a Workflow through the system Workflow Builder and publish only after validation."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_WORKFLOW = ROOT / "runner" / "workflow" / "system" / "workflow_builder.yaml"
VALIDATOR = ROOT / "workflow_builder" / "validation.py"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate and validate an AI Task Runner Workflow package")
    p.add_argument("--project-root", required=True, help="Project the model may inspect while designing the Workflow")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="Workflow requirements text")
    source.add_argument("--request-file", help="UTF-8 file containing Workflow requirements")
    p.add_argument("--output-workflow", required=True, help="Final Workflow YAML path")
    p.add_argument("--output-prompt-dir", help="Final Prompt directory; defaults to <workflow-parent>/prompts")
    p.add_argument("--backend", default="", help="Optional Runner backend override")
    p.add_argument("--overwrite", action="store_true", help="Allow replacing existing output files")
    return p


def _request_text(args: argparse.Namespace) -> str:
    if args.request is not None:
        text = args.request
    else:
        text = Path(args.request_file).expanduser().read_text(encoding="utf-8")
    text = str(text or "").strip()
    if not text:
        raise ValueError("Workflow Builder request is empty")
    return text


def _prompt_refs(value: Any) -> list[tuple[dict[str, Any], str]]:
    result: list[tuple[dict[str, Any], str]] = []
    if isinstance(value, dict):
        for key, child in list(value.items()):
            if key in {"prompt", "continuation_prompt"} and isinstance(child, str) and child.strip():
                result.append((value, key))
            result.extend(_prompt_refs(child))
    elif isinstance(value, list):
        for child in value:
            result.extend(_prompt_refs(child))
    return result


def _publish(
    draft_workflow: Path,
    draft_prompt_dir: Path,
    output_workflow: Path,
    output_prompt_dir: Path,
    *,
    overwrite: bool,
) -> dict[str, Any]:
    data = yaml.safe_load(draft_workflow.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("validated draft Workflow is not a mapping")

    output_workflow = output_workflow.resolve()
    output_prompt_dir = output_prompt_dir.resolve()
    if output_workflow.exists() and not overwrite:
        raise FileExistsError(f"output Workflow already exists: {output_workflow}")

    prompt_sources: dict[Path, Path] = {}
    for owner, key in _prompt_refs(data):
        raw = str(owner[key]).strip()
        source = Path(raw).expanduser()
        if not source.is_absolute():
            source = (draft_workflow.parent / source).resolve()
        if not source.is_file():
            raise ValueError(f"validated Prompt disappeared before publish: {raw}")
        try:
            rel = source.relative_to(draft_prompt_dir.resolve())
        except ValueError:
            # System/absolute references are kept as-is; only generated draft Prompts are published.
            continue
        target = (output_prompt_dir / rel).resolve()
        prompt_sources[source] = target
        owner[key] = os.path.relpath(target, output_workflow.parent).replace(os.sep, "/")

    conflicts = [target for target in prompt_sources.values() if target.exists() and not overwrite]
    if conflicts:
        raise FileExistsError("output Prompt already exists: " + ", ".join(str(p) for p in conflicts))

    output_workflow.parent.mkdir(parents=True, exist_ok=True)
    output_prompt_dir.mkdir(parents=True, exist_ok=True)

    copied: list[Path] = []
    try:
        for source, target in prompt_sources.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".workflow-builder.tmp")
            shutil.copy2(source, tmp)
            if target.exists() and overwrite:
                target.unlink()
            os.replace(tmp, target)
            copied.append(target)

        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)
        tmp_workflow = output_workflow.with_name(output_workflow.name + ".workflow-builder.tmp")
        tmp_workflow.write_text(text, encoding="utf-8")

        # Validate the rewritten, final-path form before publication.
        result = subprocess.run(
            [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(tmp_workflow), "--matrix", "--json", "--max-steps", "500"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            raise ValueError("published-path dry-run failed: " + (result.stdout or result.stderr or "")[-12000:])
        if output_workflow.exists() and overwrite:
            output_workflow.unlink()
        os.replace(tmp_workflow, output_workflow)
    except Exception:
        for path in copied:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            output_workflow.with_name(output_workflow.name + ".workflow-builder.tmp").unlink()
        except OSError:
            pass
        raise

    return {
        "workflow": str(output_workflow),
        "prompts": [str(path) for path in sorted(prompt_sources.values())],
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    project = Path(args.project_root).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"project root does not exist: {project}")
    output_workflow = Path(args.output_workflow).expanduser().resolve()
    output_prompt_dir = (
        Path(args.output_prompt_dir).expanduser().resolve()
        if args.output_prompt_dir
        else (output_workflow.parent / "prompts").resolve()
    )
    if output_workflow.exists() and not args.overwrite:
        raise FileExistsError(f"output Workflow already exists: {output_workflow}")

    request_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    run_root = project / ".ai-task-runner" / "workflow-builder" / request_id
    draft_root = run_root / "draft"
    draft_prompt_dir = draft_root / "prompts"
    draft_workflow = draft_root / "workflow.yaml"
    draft_prompt_dir.mkdir(parents=True, exist_ok=False)

    user_request = _request_text(args)
    goal_file = run_root / "request.md"
    goal_file.write_text(
        "# Workflow Builder Request\n\n"
        f"Draft Workflow path: `{draft_workflow.relative_to(project).as_posix()}`\n"
        f"Draft Prompt directory: `{draft_prompt_dir.relative_to(project).as_posix()}`\n\n"
        "Create all generated files only under the draft paths above. The validator will run the real Workflow dry-run.\n\n"
        "## User requirements\n\n"
        + user_request.rstrip()
        + "\n",
        encoding="utf-8",
    )

    rel_workflow = draft_workflow.relative_to(project).as_posix()
    rel_prompt_dir = draft_prompt_dir.relative_to(project).as_posix()
    command = [
        sys.executable,
        str(ROOT / "ai_task_runner.py"),
        "--project-root",
        str(project),
        "--goal-file",
        str(goal_file),
        "--workflow",
        str(SYSTEM_WORKFLOW),
        "--validator",
        str(VALIDATOR),
        f"--validator-arg=--draft-workflow",
        f"--validator-arg={rel_workflow}",
        f"--validator-arg=--draft-prompt-dir",
        f"--validator-arg={rel_prompt_dir}",
    ]
    if args.backend:
        command += ["--backend", args.backend]
    result = subprocess.run(command, cwd=ROOT)
    if result.returncode != 0:
        raise RuntimeError(f"Workflow Builder Runner failed with exit code {result.returncode}; draft kept at {draft_root}")

    # Defense in depth: validate once more immediately before publishing.
    verify = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--project-root",
            str(project),
            "--draft-workflow",
            rel_workflow,
            "--draft-prompt-dir",
            rel_prompt_dir,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=45,
    )
    if verify.returncode != 0:
        raise RuntimeError("Workflow Builder final validation failed: " + (verify.stdout or verify.stderr or "")[-12000:])

    published = _publish(
        draft_workflow,
        draft_prompt_dir,
        output_workflow,
        output_prompt_dir,
        overwrite=args.overwrite,
    )
    manifest = {
        "schema_version": 1,
        "request_id": request_id,
        "draft_root": str(draft_root),
        "output": published,
    }
    (run_root / "result.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = build(args)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
