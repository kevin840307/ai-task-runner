from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from e2e_gate.code_coverage import coverage_gate_from_default
from e2e_gate.models import GateResult, GateStatus, GateViolation

ROOT = Path.cwd().resolve()
OUT = ROOT / "result"
CONFIG = ROOT / "E2E_COVERAGE.yaml"


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if value is None else value


def _write_report(result: GateResult, details: Mapping[str, Any] | None = None) -> int:
    payload = result.to_dict()
    if details:
        payload["details"] = dict(details)
    p = OUT / "system" / "workflow2" / "gates" / "regression_final_python.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if result.ok else 1


def _manifest_gate() -> GateResult:
    manifest_path = OUT / "regression" / "manifest.yaml"
    raw = _load_yaml(manifest_path, {})
    tests = raw.get("tests", []) if isinstance(raw, Mapping) else []
    violations: list[GateViolation] = []
    if not isinstance(tests, list) or not tests:
        violations.append(GateViolation(
            "REGRESSION_MANIFEST_EMPTY",
            "result/regression/manifest.yaml must contain at least one generated test entry",
            None,
            "regression_final",
            "CRITICAL",
        ))
        tests = []
    seen: set[str] = set()
    for index, row in enumerate(tests):
        if not isinstance(row, Mapping):
            violations.append(GateViolation("REGRESSION_MANIFEST_BAD_ITEM", f"tests[{index}] must be a mapping", None, "regression_final", "CRITICAL"))
            continue
        tid = str(row.get("id") or "").strip()
        if not tid:
            violations.append(GateViolation("REGRESSION_TEST_ID_REQUIRED", f"tests[{index}] missing id", None, "regression_final", "CRITICAL"))
        elif tid in seen:
            violations.append(GateViolation("REGRESSION_TEST_ID_DUPLICATE", tid, tid, "regression_final", "CRITICAL"))
        seen.add(tid)
        test_ref = str(row.get("test_ref") or row.get("file") or "").strip()
        if not test_ref:
            violations.append(GateViolation("REGRESSION_TEST_REF_REQUIRED", f"{tid or index} missing test_ref", tid or None, "regression_final", "CRITICAL"))
        else:
            p = Path(test_ref)
            candidate = p if p.is_absolute() else ROOT / p
            if not candidate.is_file():
                violations.append(GateViolation("REGRESSION_TEST_FILE_MISSING", test_ref, tid or None, "regression_final", "CRITICAL"))
        human_text = str(row.get("title") or row.get("intent") or "").strip()
        if not human_text:
            violations.append(GateViolation("REGRESSION_INTENT_REQUIRED", f"{tid or index} missing intent/title", tid or None, "regression_final"))
    return GateResult(
        "regression_manifest_gate",
        GateStatus.FAIL if violations else GateStatus.PASS,
        violations,
        {"tests": len(tests)},
    )


def _normalize_command(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return shlex.split(raw, posix=os.name != "nt")
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        return [str(x) for x in raw]
    raise ValueError(f"execution command must be string or argv list, got {type(raw).__name__}")


def _configured_commands(config: Mapping[str, Any]) -> tuple[list[list[str]], str]:
    execution = config.get("execution") if isinstance(config, Mapping) else None
    if isinstance(execution, Mapping):
        raw_commands = execution.get("commands")
        if raw_commands is None and execution.get("command") is not None:
            raw_commands = [execution.get("command")]
        if isinstance(raw_commands, list) and raw_commands:
            return [_normalize_command(x) for x in raw_commands], "protected_coverage_policy"

    command_file = OUT / "regression" / "execution_command.txt"
    runner_file = OUT / "regression" / "execution_runner.py"
    if command_file.is_file():
        return [_normalize_command(command_file.read_text(encoding="utf-8").strip())], "generated_adapter"
    if runner_file.is_file():
        return [[os.fspath(Path(os.sys.executable)), "-B", os.fspath(runner_file)]], "generated_adapter"
    raise ValueError(
        "No execution command. Prefer protected E2E_COVERAGE.yaml execution.commands; "
        "fallback result/regression/execution_command.txt or execution_runner.py is supported."
    )


def _coverage_report_path(config: Mapping[str, Any]) -> Path:
    report = config.get("report") if isinstance(config, Mapping) else None
    raw = report.get("path") if isinstance(report, Mapping) else None
    if not raw:
        raise ValueError("E2E_COVERAGE.yaml report.path is required")
    p = Path(str(raw))
    return p if p.is_absolute() else ROOT / p


def _run_commands(config: Mapping[str, Any]) -> tuple[GateResult, dict[str, Any]]:
    violations: list[GateViolation] = []
    details: dict[str, Any] = {"commands": []}
    try:
        commands, authority = _configured_commands(config)
        report = _coverage_report_path(config)
    except Exception as exc:
        return GateResult("regression_execution_gate", GateStatus.FAIL, [GateViolation(
            "REGRESSION_EXECUTION_CONFIG_INVALID", str(exc), None, "regression_final", "CRITICAL"
        )]), details

    details["execution_authority"] = authority
    marker = OUT / "regression" / "coverage_run_started.marker"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(str(time.time_ns()), encoding="utf-8")
    marker_mtime = marker.stat().st_mtime_ns

    for command in commands:
        if not command:
            violations.append(GateViolation("REGRESSION_EXECUTION_EMPTY_COMMAND", "empty command", None, "regression_final", "CRITICAL"))
            break
        proc = subprocess.run(command, cwd=ROOT, text=True)
        details["commands"].append({"argv": command, "return_code": int(proc.returncode)})
        if proc.returncode != 0:
            violations.append(GateViolation(
                "REGRESSION_TEST_COMMAND_FAILED",
                f"Command returned {proc.returncode}: {command}",
                None,
                "regression_final",
                "CRITICAL",
            ))
            break

    if not violations:
        if not report.is_file():
            violations.append(GateViolation("REGRESSION_COVERAGE_REPORT_MISSING", str(report), None, "regression_final", "CRITICAL"))
        elif report.stat().st_mtime_ns < marker_mtime:
            violations.append(GateViolation(
                "REGRESSION_COVERAGE_REPORT_STALE",
                f"Coverage report was not regenerated by the final execution: {report}",
                None,
                "regression_final",
                "CRITICAL",
            ))
    details["coverage_report"] = str(report)
    return GateResult(
        "regression_execution_gate",
        GateStatus.FAIL if violations else GateStatus.PASS,
        violations,
        {"commands": len(details["commands"])},
    ), details




def _bounded_file_excerpt(path: Path, *, max_chars: int = 6000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + "\n...<bounded>...\n" + text[-tail:]


def _write_final_ai_context(config: Mapping[str, Any], details: Mapping[str, Any], metrics: Mapping[str, Any]) -> None:
    manifest = _load_yaml(OUT / "regression" / "manifest.yaml", {})
    tests = manifest.get("tests", []) if isinstance(manifest, Mapping) else []
    report_path = str(details.get("coverage_report") or "")
    policy_functions = config.get("functions", []) if isinstance(config, Mapping) else []
    optional_blueprint = None
    for candidate in (ROOT.parent / "material" / "e2e_blueprint", ROOT.parent / "material" / "blueprint"):
        if candidate.is_dir():
            optional_blueprint = str(candidate)
            break
    payload = {
        "version": 1,
        "purpose": "Bounded input for the fresh Final AI semantic challenger. Use these exact artifacts first; do not browse the framework or Runner state.",
        "manifest_file": "result/regression/manifest.yaml",
        "generated_tests": [
            {
                **{k: row.get(k) for k in ("id", "intent", "title", "test_ref", "method") if row.get(k) not in (None, "")},
                "test_excerpt": _bounded_file_excerpt(
                    (Path(str(row.get("test_ref"))) if Path(str(row.get("test_ref"))).is_absolute() else ROOT / str(row.get("test_ref")))
                ) if row.get("test_ref") else "",
            }
            for row in tests[:30] if isinstance(row, Mapping)
        ],
        "python_gate_file": "result/system/workflow2/gates/regression_final_python.json",
        "coverage_report": report_path,
        "coverage_metrics": dict(metrics),
        "selected_coverage_targets": list(policy_functions or []),
        "optional_blueprint": optional_blueprint,
        "material_root": str((ROOT.parent / "material").resolve()),
        "rules": [
            "Challenge assertion/oracle quality and business semantics, not Python-owned arithmetic.",
            "Use exact test refs and relevant source/material evidence; do not inspect .e2e-regression or .ai-task-runner.",
            "Reject only concrete MAJOR/CRITICAL defects with evidence. Missing speculative edge cases is not a failure.",
        ],
    }
    path = OUT / "system" / "workflow2" / "final_ai_context.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def validate() -> int:
    if not CONFIG.is_file():
        return _write_report(GateResult(
            "regression_final_python",
            GateStatus.FAIL,
            [GateViolation(
                "REGRESSION_COVERAGE_POLICY_MISSING",
                "Protected workspace/E2E_COVERAGE.yaml is required for Workflow 2 final validation",
                None,
                "regression_final",
                "CRITICAL",
            )],
        ))

    config = _load_yaml(CONFIG, {})
    manifest = _manifest_gate()
    if not manifest.ok:
        return _write_report(GateResult(
            "regression_final_python",
            GateStatus.FAIL,
            manifest.violations,
            manifest.metrics,
        ))

    execution, details = _run_commands(config)
    if not execution.ok:
        return _write_report(GateResult(
            "regression_final_python",
            GateStatus.FAIL,
            execution.violations,
            {**manifest.metrics, **execution.metrics},
        ), details)

    coverage = coverage_gate_from_default(ROOT)
    violations = [*manifest.violations, *execution.violations, *coverage.violations]
    status = GateStatus.FAIL if violations or not coverage.ok else GateStatus.PASS
    metrics = {**manifest.metrics, **execution.metrics, **coverage.metrics}
    result = GateResult("regression_final_python", status, violations, metrics)
    code = _write_report(result, details)
    if result.ok:
        _write_final_ai_context(config, details, metrics)
    return code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state")
    parser.parse_args()
    return validate()


if __name__ == "__main__":
    raise SystemExit(main())
