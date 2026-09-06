from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from e2e_gate.models import GateResult, GateStatus, GateViolation

ROOT = Path.cwd().resolve()
OUT = ROOT / "result"
EXPORT = OUT / "blueprint" / "export"
ALLOWED_EVIDENCE_LEVELS = {"PROVEN", "SUPPORTED", "ASSUMPTION"}
ALLOWED_PRIORITIES = {"critical", "major", "normal"}


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default if value is None else value


def _load_yaml_checked(path: Path) -> tuple[Any, str]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        return value, ""
    except Exception as error:
        return None, str(error).strip()


def _dump_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _fingerprint(value: Any) -> str:
    raw = yaml.safe_dump(value, allow_unicode=True, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _violation(code: str, message: str, ref: str | None = None, severity: str = "MAJOR") -> GateViolation:
    return GateViolation(code, message, ref, "blueprint_final", severity)


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _nonempty_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _rows(value: Any, container_key: str) -> list[Mapping[str, Any]]:
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


def _validate() -> tuple[GateResult, dict[str, Any]]:
    violations: list[GateViolation] = []
    paths = {
        "manifest": EXPORT / "manifest.yaml",
        "architecture": EXPORT / "architecture.yaml",
        "e2e_cases": EXPORT / "e2e_cases.yaml",
        "evidence_index": EXPORT / "evidence_index.yaml",
    }
    for name, path in paths.items():
        if not path.is_file():
            violations.append(_violation(
                "BLUEPRINT_FILE_MISSING",
                f"Required Blueprint file is missing: {path.relative_to(ROOT)}",
                name,
                "CRITICAL",
            ))

    if violations:
        return GateResult("blueprint_final_python", GateStatus.FAIL, violations), {}

    loaded: dict[str, Any] = {}
    for name, path in paths.items():
        value, parse_error = _load_yaml_checked(path)
        if parse_error:
            violations.append(_violation("BLUEPRINT_YAML_INVALID", f"{name}.yaml is invalid YAML: {parse_error}", name, "CRITICAL"))
        else:
            loaded[name] = value
    if violations:
        return GateResult("blueprint_final_python", GateStatus.FAIL, violations), {}

    manifest = loaded.get("manifest")
    architecture = loaded.get("architecture")
    cases_doc = loaded.get("e2e_cases")
    evidence_doc = loaded.get("evidence_index")
    if isinstance(evidence_doc, list):
        evidence_doc = {"evidence": evidence_doc}

    for name, doc in (("manifest", manifest), ("architecture", architecture), ("e2e_cases", cases_doc), ("evidence_index", evidence_doc)):
        if not isinstance(doc, Mapping):
            violations.append(_violation("BLUEPRINT_BAD_DOCUMENT", f"{name}.yaml must contain a mapping", name, "CRITICAL"))

    if violations:
        return GateResult("blueprint_final_python", GateStatus.FAIL, violations), {}

    flows = _rows(architecture, "flows")
    components = _rows(architecture.get("components", []), "components")
    cases = _rows(cases_doc, "cases")
    evidence = _rows(evidence_doc, "evidence")
    open_questions = _nonempty_strings(architecture.get("open_questions"))

    if not flows:
        violations.append(_violation("BLUEPRINT_NO_FLOWS", "architecture.yaml must contain at least one business/E2E flow", None, "CRITICAL"))
    if not cases:
        violations.append(_violation("BLUEPRINT_NO_CASES", "e2e_cases.yaml must contain at least one E2E case", None, "CRITICAL"))

    flow_ids: set[str] = set()
    for i, flow in enumerate(flows):
        fid = str(flow.get("id") or "").strip()
        if not fid:
            violations.append(_violation("FLOW_ID_REQUIRED", f"flows[{i}] missing id", None, "CRITICAL"))
            continue
        if fid in flow_ids:
            violations.append(_violation("FLOW_ID_DUPLICATE", f"Duplicate flow id: {fid}", fid, "CRITICAL"))
        flow_ids.add(fid)
        if not str(flow.get("title") or "").strip():
            violations.append(_violation("FLOW_TITLE_REQUIRED", f"{fid} missing title", fid))
        if not str(flow.get("trigger") or "").strip():
            violations.append(_violation("FLOW_TRIGGER_REQUIRED", f"{fid} missing trigger", fid))
        if not _nonempty_strings(flow.get("steps")):
            violations.append(_violation("FLOW_STEPS_REQUIRED", f"{fid} must contain meaningful E2E steps", fid))
        if not _nonempty_strings(flow.get("terminal_outcomes")):
            violations.append(_violation("FLOW_TERMINAL_REQUIRED", f"{fid} must contain at least one observable terminal outcome", fid, "CRITICAL"))

    evidence_ids: set[str] = set()
    for i, row in enumerate(evidence):
        eid = str(row.get("id") or "").strip()
        if not eid:
            violations.append(_violation("EVIDENCE_ID_REQUIRED", f"evidence[{i}] missing id", None))
            continue
        if eid in evidence_ids:
            violations.append(_violation("EVIDENCE_ID_DUPLICATE", f"Duplicate evidence id: {eid}", eid, "CRITICAL"))
        evidence_ids.add(eid)
        if not str(row.get("source") or "").strip():
            violations.append(_violation("EVIDENCE_SOURCE_REQUIRED", f"{eid} missing source", eid))
        if not str(row.get("claim") or "").strip():
            violations.append(_violation("EVIDENCE_CLAIM_REQUIRED", f"{eid} missing claim", eid))

    case_ids: set[str] = set()
    used_flows: set[str] = set()
    referenced_evidence: set[str] = set()
    assumption_cases = 0
    for i, case in enumerate(cases):
        cid = str(case.get("id") or "").strip()
        if not cid:
            violations.append(_violation("CASE_ID_REQUIRED", f"cases[{i}] missing id", None, "CRITICAL"))
            continue
        if cid in case_ids:
            violations.append(_violation("CASE_ID_DUPLICATE", f"Duplicate case id: {cid}", cid, "CRITICAL"))
        case_ids.add(cid)

        if not str(case.get("title") or "").strip():
            violations.append(_violation("CASE_TITLE_REQUIRED", f"{cid} missing title", cid))
        if not str(case.get("intent") or "").strip():
            violations.append(_violation("CASE_INTENT_REQUIRED", f"{cid} missing intent", cid))

        flow_ref = str(case.get("flow_ref") or "").strip()
        if not flow_ref:
            violations.append(_violation("CASE_FLOW_REF_REQUIRED", f"{cid} missing flow_ref", cid, "CRITICAL"))
        elif flow_ref not in flow_ids:
            violations.append(_violation("CASE_FLOW_REF_UNKNOWN", f"{cid} references unknown flow {flow_ref}", cid, "CRITICAL"))
        else:
            used_flows.add(flow_ref)

        if not _nonempty_strings(case.get("when")):
            violations.append(_violation("CASE_WHEN_REQUIRED", f"{cid} missing business action/event", cid))
        if not _nonempty_strings(case.get("then")):
            violations.append(_violation("CASE_ORACLE_REQUIRED", f"{cid} must contain at least one observable oracle in then", cid, "CRITICAL"))

        priority = str(case.get("priority") or "normal").lower().strip()
        if priority not in ALLOWED_PRIORITIES:
            violations.append(_violation("CASE_PRIORITY_INVALID", f"{cid} priority must be critical|major|normal", cid))

        level = str(case.get("evidence_level") or "").upper().strip()
        if level not in ALLOWED_EVIDENCE_LEVELS:
            violations.append(_violation("CASE_EVIDENCE_LEVEL_INVALID", f"{cid} evidence_level must be PROVEN|SUPPORTED|ASSUMPTION", cid))
        refs = _nonempty_strings(case.get("source_refs"))
        referenced_evidence.update(refs)
        unknown_refs = [ref for ref in refs if ref not in evidence_ids]
        if unknown_refs:
            violations.append(_violation("CASE_EVIDENCE_REF_UNKNOWN", f"{cid} references unknown evidence: {unknown_refs}", cid, "CRITICAL"))
        if level in {"PROVEN", "SUPPORTED"} and not refs:
            violations.append(_violation("CASE_EVIDENCE_REQUIRED", f"{cid} is {level} but has no source_refs", cid, "CRITICAL"))
        if level == "ASSUMPTION":
            assumption_cases += 1
            if not open_questions and not str(case.get("assumption") or "").strip():
                violations.append(_violation(
                    "ASSUMPTION_MUST_BE_EXPLICIT",
                    f"{cid} is ASSUMPTION; add architecture.open_questions or case.assumption",
                    cid,
                ))

    uncovered_flows = sorted(flow_ids - used_flows)
    if uncovered_flows:
        violations.append(_violation(
            "FLOW_WITHOUT_CASE",
            f"Every declared E2E flow needs at least one case. Missing: {uncovered_flows}",
            None,
            "CRITICAL",
        ))

    # Source-code-specific completeness is deliberately NOT a machine gate.
    counts = {
        "components": len(components),
        "flows": len(flows),
        "e2e_cases": len(cases),
        "evidence_items": len(evidence),
        "referenced_evidence_items": len(referenced_evidence & evidence_ids),
        "assumption_cases": assumption_cases,
        "open_questions": len(open_questions),
    }

    normalized_manifest = dict(manifest)
    normalized_manifest.update({
        "version": 1,
        "artifact_kind": "e2e_blueprint_pack",
        "authority": "derived_hint",
        "truth_precedence": [
            "current_project_or_material_evidence",
            "this_blueprint_pack",
            "ai_assumption",
        ],
        "project_agnostic": True,
        "portable_files": ["manifest.yaml", "architecture.yaml", "e2e_cases.yaml", "evidence_index.yaml"],
        "counts": counts,
        "fingerprints": {
            "architecture": _fingerprint(architecture),
            "e2e_cases": _fingerprint(cases_doc),
            "evidence_index": _fingerprint(evidence_doc),
        },
    })
    _dump_yaml(paths["manifest"], normalized_manifest)

    details = {
        "portable_export": "result/blueprint/export",
        "counts": counts,
        "project_agnostic": True,
        "machine_gate_scope": "artifact contract, traceability, flow/case linkage, observable-oracle presence; no static-analysis completeness denominator",
    }
    status = GateStatus.FAIL if violations else GateStatus.PASS
    return GateResult("blueprint_final_python", status, violations, counts), details


def _bounded(value: Any, limit: int) -> Any:
    if isinstance(value, list):
        return value[:limit]
    return value


def _write_final_ai_context(details: Mapping[str, Any]) -> None:
    preflight = _load_yaml(OUT / "system" / "workflow1" / "preflight.yaml", {})
    architecture = _load_yaml(EXPORT / "architecture.yaml", {})
    cases_doc = _load_yaml(EXPORT / "e2e_cases.yaml", {})
    evidence_doc = _load_yaml(EXPORT / "evidence_index.yaml", {})
    payload = {
        "version": 1,
        "purpose": "Bounded starting point for independent semantic review of a project-agnostic E2E Blueprint.",
        "request": {
            "request_file": preflight.get("request_file") if isinstance(preflight, Mapping) else None,
            "request_excerpt": preflight.get("request_excerpt") if isinstance(preflight, Mapping) else None,
        },
        "inventory": preflight.get("inventory", {}) if isinstance(preflight, Mapping) else {},
        "architecture": {
            "scope": architecture.get("scope") if isinstance(architecture, Mapping) else None,
            "components": _bounded(architecture.get("components", []) if isinstance(architecture, Mapping) else [], 80),
            "flows": _bounded(architecture.get("flows", []) if isinstance(architecture, Mapping) else [], 80),
            "open_questions": _bounded(architecture.get("open_questions", []) if isinstance(architecture, Mapping) else [], 40),
        },
        "e2e_cases": _bounded(cases_doc.get("cases", []) if isinstance(cases_doc, Mapping) else [], 120),
        "evidence": _bounded(evidence_doc.get("evidence", []) if isinstance(evidence_doc, Mapping) else [], 180),
        "python_gate": dict(details),
        "rules": [
            "Review business/E2E semantics, not repository static-analysis completeness.",
            "Source code is optional; any cited project/material evidence type can support a claim.",
            "Reject only concrete MAJOR/CRITICAL defects; do not require speculative edge cases or theoretical 100% completeness.",
            "Use exact source refs when checking a claim and do not inspect .e2e-regression or .ai-task-runner implementation files.",
        ],
    }
    _dump_yaml(OUT / "system" / "workflow1" / "final_ai_context.yaml", payload)


def _write_report(result: GateResult, details: Mapping[str, Any]) -> int:
    payload = result.to_dict()
    payload["details"] = dict(details)
    path = OUT / "system" / "workflow1" / "gates" / "blueprint_final_python.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if result.ok else 1


def validate_and_export(_state_path: str | None = None) -> int:
    result, details = _validate()
    if result.ok:
        _write_final_ai_context(details)
    return _write_report(result, details)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=False)
    args = parser.parse_args()
    return validate_and_export(args.state)


if __name__ == "__main__":
    raise SystemExit(main())
