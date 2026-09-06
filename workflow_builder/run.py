#!/usr/bin/env python3
"""Generate a Workflow draft, validate it, and optionally publish it."""
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
BUILDER_ROOT = Path(__file__).resolve().parent
BUILDER_WORKFLOW = BUILDER_ROOT / "workflow_builder.yaml"
VALIDATOR = BUILDER_ROOT / "validation.py"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate and validate an AI Task Runner Workflow package")
    p.add_argument("--project-root", required=True, help="Runner workspace root; the UI passes an isolated temporary Builder job, not the selected user Project")
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--request", help="Workflow requirements text")
    source.add_argument("--request-file", help="UTF-8 file containing Workflow requirements")
    p.add_argument("--output-workflow", help="Final Workflow YAML path; required unless --draft-only")
    p.add_argument("--output-prompt-dir", help="Final Prompt directory; defaults to <workflow-parent>/prompts")
    p.add_argument("--backend", default="", help="Optional Runner backend override")
    p.add_argument("--overwrite", action="store_true", help="Allow replacing existing output files")
    p.add_argument("--draft-only", action="store_true", help="Stop after validated draft creation; do not publish")
    p.add_argument("--job-dir", help="Optional job directory inside the Runner workspace root (used by UI draft mode)")
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


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _write_status(run_root: Path, state: str, message: str, **extra: Any) -> None:
    path = run_root / "status.json"
    current: dict[str, Any] = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            current = {}
    current.update({
        "schema_version": 1,
        "state": state,
        "message": message,
        "pid": os.getpid(),
        "updated_at": time.time(),
        **extra,
    })
    _atomic_json(path, current)


class GenerationCancelled(RuntimeError):
    pass


def _runner_process_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if flags:
            kwargs["creationflags"] = flags
    return kwargs


def _run_runner(command: list[str], run_root: Path, project: Path) -> int:
    process = subprocess.Popen(command, cwd=ROOT, **_runner_process_kwargs())
    cancel_file = run_root / "cancel.request"
    while process.poll() is None:
        if cancel_file.exists():
            _write_status(run_root, "cancelling", "Cancelling Workflow generation…")
            runtime = project / ".ai-task-runner"
            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / "stop.request").write_text("stop\n", encoding="utf-8")
            try:
                process.wait(timeout=12)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=4)
            raise GenerationCancelled("Workflow generation cancelled")
        time.sleep(0.25)
    return int(process.returncode or 0)


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
            # Existing external/System Prompt references remain unchanged.
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
        tmp_workflow = output_workflow.with_name(output_workflow.name + ".workflow-builder.tmp.yaml")
        tmp_workflow.write_text(text, encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(ROOT / "tool" / "workflow_dryrun.py"), str(tmp_workflow), "--matrix", "--json", "--max-steps", "500"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if result.returncode != 0:
            raise ValueError("published-path dry-run failed: " + (result.stdout or result.stderr or "")[-12000:])
        payload = json.loads(result.stdout)
        if not payload.get("closed"):
            raise ValueError("published-path dry-run matrix did not reach closure")
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
            output_workflow.with_name(output_workflow.name + ".workflow-builder.tmp.yaml").unlink()
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
    if not BUILDER_WORKFLOW.is_file() or not (BUILDER_ROOT / "prompt.md").is_file() or not VALIDATOR.is_file():
        raise ValueError("Workflow Builder files are incomplete")

    output_workflow: Path | None = None
    output_prompt_dir: Path | None = None
    if not args.draft_only:
        if not args.output_workflow:
            raise ValueError("--output-workflow is required unless --draft-only is used")
        output_workflow = Path(args.output_workflow).expanduser().resolve()
        output_prompt_dir = (
            Path(args.output_prompt_dir).expanduser().resolve()
            if args.output_prompt_dir
            else (output_workflow.parent / "prompts").resolve()
        )
        if output_workflow.exists() and not args.overwrite:
            raise FileExistsError(f"output Workflow already exists: {output_workflow}")

    request_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
    if args.job_dir:
        run_root = Path(args.job_dir).expanduser().resolve()
        if not _inside(run_root, project):
            raise ValueError("Workflow Builder job directory must stay inside project root")
        run_root.mkdir(parents=True, exist_ok=True)
        request_id = run_root.name
    else:
        run_root = project / ".ai-task-runner" / "workflow-builder" / request_id
        run_root.mkdir(parents=True, exist_ok=False)

    draft_root = run_root / "draft"
    draft_prompt_dir = draft_root / "prompts"
    draft_workflow = draft_root / "workflow.yaml"
    draft_prompt_dir.mkdir(parents=True, exist_ok=True)

    user_request = _request_text(args)
    _write_status(run_root, "running", "Preparing Workflow draft")
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
        str(BUILDER_WORKFLOW),
        "--validator-arg=--draft-workflow",
        f"--validator-arg={rel_workflow}",
        "--validator-arg=--draft-prompt-dir",
        f"--validator-arg={rel_prompt_dir}",
    ]
    if args.backend:
        command += ["--backend", args.backend]

    _write_status(run_root, "running", "AI is generating Workflow and Prompt draft")
    returncode = _run_runner(command, run_root, project)
    if returncode != 0:
        raise RuntimeError(f"Workflow Builder Runner failed with exit code {returncode}; draft kept at {draft_root}")

    _write_status(run_root, "running", "Validating generated Workflow draft")
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

    validation_output = (verify.stdout or "").strip()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "request_id": request_id,
        "draft_root": str(draft_root),
        "draft_workflow": str(draft_workflow),
        "draft_prompt_dir": str(draft_prompt_dir),
        "validation": validation_output[-12000:],
    }

    if args.draft_only:
        _atomic_json(run_root / "result.json", manifest)
        _write_status(run_root, "ready", "Draft ready. Review it and Save to create the Workflow.", result=manifest)
        return manifest

    assert output_workflow is not None and output_prompt_dir is not None
    _write_status(run_root, "running", "Publishing validated Workflow")
    published = _publish(
        draft_workflow,
        draft_prompt_dir,
        output_workflow,
        output_prompt_dir,
        overwrite=args.overwrite,
    )
    manifest["output"] = published
    _atomic_json(run_root / "result.json", manifest)
    _write_status(run_root, "saved", "Workflow published", result=manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run_root: Path | None = Path(args.job_dir).expanduser().resolve() if getattr(args, "job_dir", None) else None
    try:
        result = build(args)
    except GenerationCancelled as exc:
        if run_root is not None:
            try:
                _write_status(run_root, "cancelled", str(exc))
            except Exception:
                pass
        print(f"CANCELLED: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if run_root is not None:
            try:
                _write_status(run_root, "failed", str(exc))
            except Exception:
                pass
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
