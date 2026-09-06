from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from e2e_gate.models import GateResult, GateStatus, GateViolation

ROOT = Path.cwd().resolve()
OUT = ROOT / "result"
EXPORT = OUT / "blueprint" / "export"


def _violation(code: str, message: str, ref: str | None = None, severity: str = "MAJOR") -> GateViolation:
    return GateViolation(code, message, ref, "blueprint_stage", severity)


def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_yaml_checked(path: Path) -> tuple[Any, str]:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")), ""
    except Exception as error:
        return None, str(error).strip()


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _as_text_list(value: Any) -> list[str]:
    """Accept one scalar or a list for human-authored semantic fields."""
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _rows(value: Any, container_key: str) -> list[Mapping[str, Any]]:
    """Normalize common YAML list and id-keyed mapping forms into row mappings."""
    if isinstance(value, Mapping):
        value = value.get(container_key, value)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, Mapping)]
    if isinstance(value, Mapping):
        rows: list[Mapping[str, Any]] = []
        for key, raw in value.items():
            if not isinstance(raw, Mapping):
                continue
            row = dict(raw)
            row.setdefault("id", str(key))
            rows.append(row)
        return rows
    return []




def _find_task_list(value: Any) -> list[Any] | None:
    """Find the durable Plan/TODO list without depending on one Runner state layout."""
    if isinstance(value, Mapping):
        for key in ("tasks", "todos"):
            rows = value.get(key)
            if isinstance(rows, list):
                return rows
        for child in value.values():
            found = _find_task_list(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_task_list(child)
            if found is not None:
                return found
    return None


def _validate_preflight() -> GateResult:
    path = OUT / "system" / "workflow1" / "preflight.yaml"
    violations: list[GateViolation] = []
    data = _load_yaml(path) if path.is_file() else None
    if not isinstance(data, Mapping):
        violations.append(_violation("PREFLIGHT_MISSING", "result/system/workflow1/preflight.yaml is missing or invalid", severity="CRITICAL"))
        return GateResult("blueprint_preflight_python", GateStatus.FAIL, violations)

    roots = data.get("evidence_roots")
    contract = data.get("planning_contract")
    outputs = data.get("required_outputs")
    if not isinstance(roots, list) or not roots:
        violations.append(_violation("PREFLIGHT_EVIDENCE_ROOT_REQUIRED", "Preflight must expose at least one read-only evidence root"))
    if not isinstance(contract, Mapping):
        violations.append(_violation("PREFLIGHT_PLANNING_CONTRACT_REQUIRED", "Preflight must expose the generic E2E planning contract"))
    required = {
        "result/blueprint/export/manifest.yaml",
        "result/blueprint/export/architecture.yaml",
        "result/blueprint/export/e2e_cases.yaml",
        "result/blueprint/export/evidence_index.yaml",
    }
    if not isinstance(outputs, list) or not required.issubset({str(x) for x in outputs}):
        violations.append(_violation("PREFLIGHT_OUTPUT_CONTRACT_REQUIRED", "Preflight required_outputs must contain the four portable Blueprint files"))

    planning_summary = data.get("planning_summary")
    if not isinstance(planning_summary, Mapping):
        violations.append(_violation(
            "PREFLIGHT_PLANNING_SUMMARY_REQUIRED",
            "Preflight must expose bounded source-derived planning_summary",
        ))
        planning_summary = {}

    return GateResult(
        "blueprint_preflight_python",
        GateStatus.FAIL if violations else GateStatus.PASS,
        violations,
        {
            "evidence_roots": len(roots) if isinstance(roots, list) else 0,
            # PlanStage consumes the immediately preceding command output as its
            # inspection_summary. Keep this bounded source-derived context here so
            # Planning does not need to rediscover the repository with model tools.
            "planning_summary": planning_summary,
        },
    )


def _validate_plan(state_path: str | None) -> GateResult:
    violations: list[GateViolation] = []
    if not state_path:
        violations.append(_violation("PLAN_STATE_REQUIRED", "Planning Python Gate requires Runner state", severity="CRITICAL"))
        return GateResult("blueprint_plan_python", GateStatus.FAIL, violations)

    state = _load_json(Path(state_path))
    tasks = _find_task_list(state)
    if not isinstance(tasks, list) or not tasks:
        violations.append(_violation("PLAN_TASKS_REQUIRED", "Planning must produce at least one durable TODO", severity="CRITICAL"))
        return GateResult("blueprint_plan_python", GateStatus.FAIL, violations)

    usable = 0
    for index, task in enumerate(tasks):
        if isinstance(task, str):
            if task.strip():
                usable += 1
            continue
        if not isinstance(task, Mapping):
            continue
        title = str(task.get("title") or task.get("name") or "").strip()
        body = str(task.get("description") or task.get("instruction") or task.get("deliverable") or "").strip()
        checks = task.get("acceptance_criteria") or task.get("done_when") or []
        if title and (body or (isinstance(checks, list) and any(str(x).strip() for x in checks))):
            usable += 1
        else:
            violations.append(_violation("PLAN_TASK_INCOMPLETE", f"TODO {index + 1} needs a title and a meaningful description/deliverable/check", str(index + 1)))

    if usable == 0:
        violations.append(_violation("PLAN_NO_USABLE_TASK", "Planning produced no usable TODO", severity="CRITICAL"))

    return GateResult(
        "blueprint_plan_python",
        GateStatus.FAIL if violations else GateStatus.PASS,
        violations,
        {"tasks": len(tasks), "usable_tasks": usable},
    )


def _validate_blueprint(stage: str) -> GateResult:
    """Validate only the currently accumulated Blueprint, never final completeness.

    Task-scoped TODOs intentionally build the portable pack incrementally. Intermediate
    Gates therefore validate syntax, IDs, references that can already be resolved, and
    the shape of any entries that exist. Missing later artifacts, a Flow without a Case
    yet, or a Case family that belongs to a later TODO are Final-Python concerns only.
    """
    violations: list[GateViolation] = []
    docs: dict[str, Any] = {}
    paths = {
        "manifest": EXPORT / "manifest.yaml",
        "architecture": EXPORT / "architecture.yaml",
        "e2e_cases": EXPORT / "e2e_cases.yaml",
        "evidence_index": EXPORT / "evidence_index.yaml",
    }

    for name, path in paths.items():
        if not path.is_file():
            continue
        value, parse_error = _load_yaml_checked(path)
        if parse_error:
            violations.append(_violation(
                "BLUEPRINT_YAML_INVALID",
                f"{name}.yaml is invalid YAML: {parse_error}",
                name,
                "CRITICAL",
            ))
            continue
        if name == "evidence_index" and isinstance(value, list):
            # Tolerate the portable shorthand where the evidence file itself is a row list.
            value = {"evidence": value}
        if not isinstance(value, Mapping):
            violations.append(_violation("BLUEPRINT_BAD_DOCUMENT", f"{name}.yaml must contain a YAML mapping (or a row list for evidence_index)", name, "CRITICAL"))
            continue
        docs[name] = value

    # Execute must leave at least one portable artifact. Review/Grill may be read-only,
    # but by then the current TODO must still have some accumulated Blueprint evidence.
    if not docs:
        violations.append(_violation(
            "BLUEPRINT_INCREMENT_MISSING",
            "Current TODO produced no portable Blueprint artifact under result/blueprint/export",
            severity="CRITICAL",
        ))
        return GateResult(f"blueprint_{stage}_python", GateStatus.FAIL, violations)

    architecture = docs.get("architecture", {})
    cases_doc = docs.get("e2e_cases", {})
    evidence_doc = docs.get("evidence_index", {})

    flows = _rows(architecture, "flows") if isinstance(architecture, Mapping) else []
    cases = _rows(cases_doc, "cases") if isinstance(cases_doc, Mapping) else []
    evidence = _rows(evidence_doc, "evidence") if isinstance(evidence_doc, Mapping) else []

    flow_ids: set[str] = set()
    for i, flow in enumerate(flows):
        fid = str(flow.get("id") or "").strip()
        if not fid:
            violations.append(_violation("FLOW_ID_REQUIRED", f"flows[{i}] missing id", severity="CRITICAL"))
            continue
        if fid in flow_ids:
            violations.append(_violation("FLOW_ID_DUPLICATE", f"Duplicate flow id: {fid}", fid, "CRITICAL"))
        flow_ids.add(fid)
        if not str(flow.get("title") or "").strip():
            violations.append(_violation("FLOW_TITLE_REQUIRED", f"{fid} missing title", fid))
        if not str(flow.get("trigger") or "").strip():
            violations.append(_violation("FLOW_TRIGGER_REQUIRED", f"{fid} missing trigger", fid))
        steps = flow.get("steps")
        if not isinstance(steps, list) or not any(str(x).strip() for x in steps):
            violations.append(_violation("FLOW_STEPS_REQUIRED", f"{fid} must contain meaningful E2E steps", fid))
        terminal = flow.get("terminal_outcomes")
        if not isinstance(terminal, list) or not any(str(x).strip() for x in terminal):
            violations.append(_violation("FLOW_TERMINAL_REQUIRED", f"{fid} must contain an observable terminal outcome", fid, "CRITICAL"))

    evidence_ids: set[str] = set()
    for i, row in enumerate(evidence):
        eid = str(row.get("id") or "").strip()
        if not eid:
            violations.append(_violation("EVIDENCE_ID_REQUIRED", f"evidence[{i}] missing id"))
            continue
        if eid in evidence_ids:
            violations.append(_violation("EVIDENCE_ID_DUPLICATE", f"Duplicate evidence id: {eid}", eid, "CRITICAL"))
        evidence_ids.add(eid)
        if not str(row.get("source") or "").strip():
            violations.append(_violation("EVIDENCE_SOURCE_REQUIRED", f"{eid} missing source", eid))
        if not str(row.get("claim") or "").strip():
            violations.append(_violation("EVIDENCE_CLAIM_REQUIRED", f"{eid} missing claim", eid))

    case_ids: set[str] = set()
    for i, case in enumerate(cases):
        cid = str(case.get("id") or "").strip()
        if not cid:
            violations.append(_violation("CASE_ID_REQUIRED", f"cases[{i}] missing id", severity="CRITICAL"))
            continue
        if cid in case_ids:
            violations.append(_violation("CASE_ID_DUPLICATE", f"Duplicate case id: {cid}", cid, "CRITICAL"))
        case_ids.add(cid)
        if not str(case.get("title") or "").strip():
            violations.append(_violation("CASE_TITLE_REQUIRED", f"{cid} missing title", cid))
        if not str(case.get("intent") or "").strip():
            violations.append(_violation("CASE_INTENT_REQUIRED", f"{cid} missing intent", cid))
        if not _as_text_list(case.get("when")):
            violations.append(_violation("CASE_WHEN_REQUIRED", f"{cid} missing business action/event", cid))
        if not _as_text_list(case.get("then")):
            violations.append(_violation("CASE_ORACLE_REQUIRED", f"{cid} needs an observable oracle", cid, "CRITICAL"))

        # Resolve references only when their target universe already exists. A flow/evidence
        # TODO may legally precede its case/evidence-index TODO.
        flow_ref = str(case.get("flow_ref") or "").strip()
        if not flow_ref:
            violations.append(_violation("CASE_FLOW_REF_REQUIRED", f"{cid} missing flow_ref", cid, "CRITICAL"))
        elif flow_ids and flow_ref not in flow_ids:
            violations.append(_violation("CASE_FLOW_REF_UNKNOWN", f"{cid} references unknown flow {flow_ref}", cid, "CRITICAL"))

        refs = [str(x).strip() for x in (case.get("source_refs") or []) if str(x).strip()] if isinstance(case.get("source_refs"), list) else []
        if evidence_ids:
            unknown = [x for x in refs if x not in evidence_ids]
            if unknown:
                violations.append(_violation("CASE_EVIDENCE_REF_UNKNOWN", f"{cid} references unknown evidence: {unknown}", cid, "CRITICAL"))

    metrics = {
        "after_stage": stage,
        "documents_present": sorted(docs),
        "flows_so_far": len(flows),
        "cases_so_far": len(cases),
        "evidence_so_far": len(evidence),
        "incremental_only": True,
        "project_agnostic": True,
        "machine_gate_scope": "incremental artifact contract only; no static-analysis completeness denominator",
    }
    return GateResult(
        f"blueprint_{stage}_python",
        GateStatus.FAIL if violations else GateStatus.PASS,
        violations,
        metrics,
    )


def _write(stage: str, result: GateResult) -> int:
    payload = result.to_dict()
    path = OUT / "system" / "workflow1" / "gates" / f"blueprint_{stage}_python.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if result.ok else 1


def validate(stage: str, state_path: str | None = None) -> int:
    if stage == "preflight":
        result = _validate_preflight()
    elif stage in {"planning", "repair_plan"}:
        result = _validate_plan(state_path)
    elif stage in {"execute", "review", "grill"}:
        result = _validate_blueprint(stage)
    else:
        result = GateResult(
            f"blueprint_{stage}_python",
            GateStatus.FAIL,
            [_violation("UNKNOWN_STAGE", f"Unsupported Blueprint Python Gate stage: {stage}", stage, "CRITICAL")],
        )
    return _write(stage, result)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", required=True, choices=("preflight", "planning", "repair_plan", "execute", "review", "grill"))
    parser.add_argument("--state", required=False)
    args = parser.parse_args()
    return validate(args.stage, args.state)


if __name__ == "__main__":
    raise SystemExit(main())
