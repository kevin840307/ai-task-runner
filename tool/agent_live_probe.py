#!/usr/bin/env python3
"""Opt-in live contract probe for Project Chat Agent adapters.

The probe uses the same Runner-owned discovery/catalog boundaries as production UI.
It creates one temporary cross-agent project Skill so native Slash/Skill discovery
is verified without hardcoding provider command lists.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.agent import backend_names, default_command, split_command
from runner.plugins.registry import discover_plugins
from tool.agent_catalog import capability_catalog, settings_catalog

DEFAULT_BACKENDS = ("qwen", "opencode")
SKILL_NAME = "ai-task-runner-live-probe"
PING_MARKER = "AI_TASK_RUNNER_AGENT_LIVE_OK"
MAX_REPORTED_VALUES = 40

_SKILL = f"""---
name: {SKILL_NAME}
description: Temporary AI Task Runner live adapter discovery fixture.
user-invocable: true
metadata:
  opencode/slash: "true"
---
When invoked, do not modify files. This Skill exists only to verify native capability discovery.
"""

_PING_PROMPT = (
    f"Reply with exactly {PING_MARKER} and nothing else. "
    "Do not use tools, do not inspect files, and do not modify the project."
)


def _source_head() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _evidence_payload(
    project: Path,
    requested: list[str],
    results: list[dict[str, Any]],
    *,
    ok: bool,
    discovery_only: bool,
    allow_missing: bool,
    allow_no_ask: bool,
) -> dict[str, Any]:
    sanitized = json.loads(json.dumps(results, ensure_ascii=False))
    for result in sanitized:
        if not isinstance(result, dict):
            continue
        chat = result.get("chat_ping")
        if not isinstance(chat, dict):
            continue
        session_id = str(chat.pop("session_id", "") or "").strip()
        chat["session_id_present"] = bool(session_id)

    diagnostic = bool(discovery_only or allow_missing or allow_no_ask)
    by_backend = {
        str(item.get("backend") or ""): item
        for item in sanitized
        if isinstance(item, dict)
    }
    required = set(DEFAULT_BACKENDS)
    formal_gate = bool(
        ok
        and not diagnostic
        and required.issubset(set(requested))
        and all(
            isinstance(by_backend.get(backend), dict)
            and by_backend[backend].get("status") == "pass"
            and isinstance(by_backend[backend].get("chat_ping"), dict)
            and by_backend[backend]["chat_ping"].get("ok") is True
            for backend in required
        )
    )
    return {
        "schema_version": 1,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_head": _source_head(),
        "project_root": str(Path(project).resolve()),
        "requested_backends": list(requested),
        "diagnostic": {
            "discovery_only": bool(discovery_only),
            "allow_missing": bool(allow_missing),
            "allow_no_ask": bool(allow_no_ask),
        },
        "ok": bool(ok),
        "formal_gate": formal_gate,
        "results": sanitized,
    }


def _write_evidence(path: str, payload: dict[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)
    return target


def _parse_model_overrides(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw in values:
        backend, separator, model = str(raw or "").partition("=")
        backend = backend.strip()
        model = model.strip()
        if not separator or not backend or not model:
            raise ValueError("--model must use BACKEND=MODEL")
        if backend in result:
            raise ValueError(f"duplicate --model backend: {backend}")
        result[backend] = model
    return result


def _command_available(backend: str) -> bool:
    parts = split_command(default_command(backend))
    if not parts:
        return False
    executable = parts[0]
    return Path(executable).is_file() or shutil.which(executable) is not None


@contextmanager
def _project_skill_fixture(project: Path) -> Iterator[Path]:
    """Create one shared .agents Skill and remove only paths owned by this probe."""
    project = Path(project).resolve()
    agents = project / ".agents"
    skills = agents / "skills"
    skill_dir = skills / SKILL_NAME
    skill_file = skill_dir / "SKILL.md"
    if skill_dir.exists():
        raise RuntimeError(
            f"live probe Skill path already exists; refusing to overwrite: {skill_dir}"
        )

    created_parents: list[Path] = []
    for path in (agents, skills):
        if not path.exists():
            path.mkdir()
            created_parents.append(path)
    skill_dir.mkdir()
    skill_file.write_text(_SKILL, encoding="utf-8")
    try:
        yield skill_file
    finally:
        try:
            skill_file.unlink()
        except FileNotFoundError:
            pass
        try:
            skill_dir.rmdir()
        except OSError:
            pass
        for path in reversed(created_parents):
            try:
                path.rmdir()
            except OSError:
                pass


def _validate_settings(
    backend: str,
    payload: dict[str, Any],
    *,
    require_ask: bool,
) -> dict[str, Any]:
    if str(payload.get("agent") or "") != backend:
        raise RuntimeError(f"{backend}: settings catalog returned the wrong Agent")

    models = [
        str(value).strip()
        for value in payload.get("models") or []
        if str(value).strip()
    ]
    if not models:
        raise RuntimeError(f"{backend}: native Model discovery returned no models")

    modes = {
        str(item.get("id") or ""): item
        for item in payload.get("modes") or []
        if isinstance(item, dict) and item.get("supported") is not False
    }
    missing_modes = sorted({"read", "auto"} - set(modes))
    if missing_modes:
        raise RuntimeError(
            f"{backend}: missing required Chat modes: {', '.join(missing_modes)}"
        )

    features = payload.get("features")
    if not isinstance(features, dict):
        raise RuntimeError(f"{backend}: Chat feature projection is missing")
    if str(features.get("queue_mode") or "") != "service_fifo":
        raise RuntimeError(f"{backend}: Queue contract is not service_fifo")
    if require_ask and features.get("ask") is not True:
        detail = str(features.get("detail") or "").strip()
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"{backend}: native Ask is unavailable{suffix}")
    if features.get("ask") is True and not str(features.get("ask_transport") or "").strip():
        raise RuntimeError(f"{backend}: native Ask is advertised without a transport")

    reasoning = [
        str(item.get("id") or "").strip()
        for item in payload.get("reasoning") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    return {
        "models": models,
        "modes": sorted(modes),
        "reasoning": reasoning,
        "features": {
            "ask": bool(features.get("ask")),
            "ask_transport": str(features.get("ask_transport") or ""),
            "queue_mode": str(features.get("queue_mode") or ""),
            "detail": str(features.get("detail") or ""),
        },
    }


def _validate_capabilities(
    backend: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if str(payload.get("backend") or "") != backend:
        raise RuntimeError(f"{backend}: capability catalog returned the wrong Agent")
    capabilities = [
        item for item in payload.get("capabilities") or [] if isinstance(item, dict)
    ]
    skill = next(
        (
            item for item in capabilities
            if str(item.get("kind") or "") == "skill"
            and str(item.get("name") or "") == SKILL_NAME
        ),
        None,
    )
    if skill is None:
        raise RuntimeError(
            f"{backend}: native Skill discovery did not return /{SKILL_NAME}"
        )
    if (
        str(skill.get("token") or "") != f"/{SKILL_NAME}"
        or skill.get("enabled") is not True
        or skill.get("user_invocable") is not True
    ):
        raise RuntimeError(
            f"{backend}: live probe Skill is not exposed as an enabled Slash capability"
        )

    commands = [
        item for item in capabilities
        if str(item.get("kind") or "") == "command"
        and item.get("enabled") is not False
        and str(item.get("token") or "").startswith("/")
    ]
    if not commands:
        raise RuntimeError(f"{backend}: native Slash command discovery returned no commands")

    return {
        "count": len(capabilities),
        "command_tokens": sorted(
            {str(item.get("token") or "") for item in commands}
        )[:MAX_REPORTED_VALUES],
        "skill_token": str(skill.get("token") or ""),
        "skill_source": str(skill.get("source") or ""),
    }


def _run_chat_ping(
    project: Path,
    backend: str,
    *,
    model: str,
    timeout: int,
) -> dict[str, Any]:
    command = [
        sys.executable,
        str(ROOT / "tool" / "chat_agent.py"),
        "--project-root",
        str(project),
        "--backend",
        backend,
        "--mode",
        "read",
        "--timeout",
        str(timeout),
    ]
    if model:
        command.extend(["--model", model])
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            input=_PING_PROMPT,
            text=True,
            capture_output=True,
            timeout=timeout + 30,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{backend}: live Chat ping timed out") from exc

    output = completed.stdout.strip()
    payload: dict[str, Any] | None = None
    for line in reversed(output.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            payload = candidate
            break
    if completed.returncode != 0 or payload is None:
        detail = (
            completed.stderr.strip()
            or output
            or f"exit {completed.returncode}"
        )[-2000:]
        raise RuntimeError(f"{backend}: live Chat ping failed: {detail}")
    if payload.get("error"):
        raise RuntimeError(f"{backend}: live Chat ping failed: {payload['error']}")
    text = str(payload.get("text") or "").strip()
    if PING_MARKER not in text:
        raise RuntimeError(
            f"{backend}: live Chat ping returned unexpected text: {text[:500]}"
        )
    return {
        "ok": True,
        "model_override": model,
        "session_id": str(payload.get("session_id") or ""),
    }


def probe_backend(
    project: Path,
    backend: str,
    *,
    model: str = "",
    require_ask: bool = True,
    run_chat: bool = True,
    timeout: int = 90,
) -> dict[str, Any]:
    settings = _validate_settings(
        backend,
        settings_catalog(project, backend, model),
        require_ask=require_ask,
    )
    if model and model not in settings["models"]:
        raise RuntimeError(
            f"{backend}: requested model is absent from native Model discovery: {model}"
        )
    capabilities = _validate_capabilities(
        backend,
        capability_catalog(project, backend),
    )
    chat = (
        _run_chat_ping(
            project,
            backend,
            model=model,
            timeout=timeout,
        )
        if run_chat
        else {"ok": None, "skipped": True, "model_override": model}
    )
    return {
        "backend": backend,
        "status": "pass",
        "models": settings["models"][:MAX_REPORTED_VALUES],
        "model_count": len(settings["models"]),
        "modes": settings["modes"],
        "reasoning": settings["reasoning"][:MAX_REPORTED_VALUES],
        "features": settings["features"],
        "capabilities": capabilities,
        "chat_ping": chat,
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Run real Project Chat Agent adapter discovery/transport probes"
    )
    value.add_argument("--project-root", default=".")
    value.add_argument(
        "--backend",
        action="append",
        dest="backends",
        default=[],
        help="Backend to probe; repeat for more than one. Defaults to qwen + opencode.",
    )
    value.add_argument(
        "--model",
        action="append",
        default=[],
        metavar="BACKEND=MODEL",
        help="Optional explicit model used by the live Chat ping.",
    )
    value.add_argument("--timeout", type=int, default=90)
    value.add_argument(
        "--discovery-only",
        action="store_true",
        help="Skip the real model Chat ping; catalog discovery still uses the installed CLI.",
    )
    value.add_argument(
        "--allow-missing",
        action="store_true",
        help="Report missing backend executables as skipped instead of failing.",
    )
    value.add_argument(
        "--allow-no-ask",
        action="store_true",
        help="Diagnostic mode only: do not fail when native Ask is unavailable.",
    )
    value.add_argument(
        "--output",
        default="",
        help=(
            "Optional JSON evidence path. The saved payload records source HEAD and "
            "formal-gate status while redacting native session identity."
        ),
    )
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project_root).expanduser().resolve()
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": "project root does not exist"}))
        return 2
    if args.timeout < 1:
        print(json.dumps({"ok": False, "error": "timeout must be >= 1"}))
        return 2

    try:
        model_overrides = _parse_model_overrides(args.model)
        discover_plugins()
        registered = set(backend_names())
        requested = list(dict.fromkeys(args.backends or DEFAULT_BACKENDS))
        unknown = [name for name in requested if name not in registered]
        if unknown:
            raise ValueError("unsupported backend: " + ", ".join(unknown))
        extra_models = sorted(set(model_overrides) - set(requested))
        if extra_models:
            raise ValueError(
                "--model references a backend that is not being probed: "
                + ", ".join(extra_models)
            )
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    results: list[dict[str, Any]] = []
    failed = False
    try:
        with _project_skill_fixture(project):
            for backend in requested:
                if not _command_available(backend):
                    result = {
                        "backend": backend,
                        "status": "skip" if args.allow_missing else "fail",
                        "error": f"command not found: {default_command(backend)}",
                    }
                    results.append(result)
                    failed = failed or not args.allow_missing
                    continue
                try:
                    results.append(
                        probe_backend(
                            project,
                            backend,
                            model=model_overrides.get(backend, ""),
                            require_ask=not args.allow_no_ask,
                            run_chat=not args.discovery_only,
                            timeout=args.timeout,
                        )
                    )
                except Exception as exc:
                    results.append({
                        "backend": backend,
                        "status": "fail",
                        "error": str(exc),
                    })
                    failed = True
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    output = {
        "ok": not failed,
        "project_root": str(project),
        "results": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.output:
        try:
            evidence = _evidence_payload(
                project,
                requested,
                results,
                ok=not failed,
                discovery_only=args.discovery_only,
                allow_missing=args.allow_missing,
                allow_no_ask=args.allow_no_ask,
            )
            saved = _write_evidence(args.output, evidence)
            print(json.dumps(
                {
                    "evidence": str(saved),
                    "formal_gate": evidence["formal_gate"],
                },
                ensure_ascii=False,
            ))
        except OSError as exc:
            print(json.dumps(
                {"ok": False, "error": f"failed to save live evidence: {exc}"},
                ensure_ascii=False,
            ))
            return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
