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
FILES = {
    "manifest": EXPORT / "manifest.yaml",
    "architecture": EXPORT / "architecture.yaml",
    "e2e_cases": EXPORT / "e2e_cases.yaml",
    "evidence_index": EXPORT / "evidence_index.yaml",
}


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


def _violation(check: str, code: str, message: str, ref: str | None = None, severity: str = "MAJOR") -> GateViolation:
    return GateViolation(code, message, ref, f"blueprint_{check}", severity)


def _nonempty_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _evidence_reference_sets(case: Mapping[str, Any], evidence: list[Mapping[str, Any]]) -> tuple[list[str], list[str], list[str]]:
    """Resolve canonical Evidence IDs while keeping direct source locators separate.

    `evidence_refs` is the canonical Case -> Evidence ID relation. `source_refs` is a
    direct locator list. Legacy source_refs are accepted when they exactly match an
    evidence row's `source`, so existing Blueprints can migrate without a full rerun.
    """
    evidence_ids = {str(row.get("id") or "").strip() for row in evidence if str(row.get("id") or "").strip()}
    source_to_id = {
        str(row.get("source") or "").strip(): str(row.get("id") or "").strip()
        for row in evidence
        if str(row.get("source") or "").strip() and str(row.get("id") or "").strip()
    }
    evidence_refs = _nonempty_strings(case.get("evidence_refs"))
    source_refs = _nonempty_strings(case.get("source_refs"))
    resolved = [ref for ref in evidence_refs if ref in evidence_ids]
    unknown_ids = [ref for ref in evidence_refs if ref not in evidence_ids]
    unknown_sources: list[str] = []
    for locator in source_refs:
        eid = source_to_id.get(locator)
        if eid:
            if eid not in resolved:
                resolved.append(eid)
        else:
            unknown_sources.append(locator)
    return resolved, unknown_ids, unknown_sources


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


def _load_documents(check: str) -> tuple[dict[str, Any], list[GateViolation]]:
    violations: list[GateViolation] = []
    loaded: dict[str, Any] = {}
    for name, path in FILES.items():
        if not path.is_file():
            violations.append(_violation(check, "BLUEPRINT_FILE_MISSING", f"Required Blueprint file is missing: {path.relative_to(ROOT)}", name, "CRITICAL"))
            continue
        value, parse_error = _load_yaml_checked(path)
        if parse_error:
            violations.append(_violation(check, "BLUEPRINT_YAML_INVALID", f"{name}.yaml is invalid YAML: {parse_error}", name, "CRITICAL"))
            continue
        loaded[name] = value
    if violations:
        return loaded, violations

    evidence_doc = loaded.get("evidence_index")
    if isinstance(evidence_doc, list):
        loaded["evidence_index"] = {"evidence": evidence_doc}

    required_roots = {
        "manifest": None,
        "architecture": "flows",
        "e2e_cases": "cases",
        "evidence_index": "evidence",
    }
    for name, root_key in required_roots.items():
        doc = loaded.get(name)
        if not isinstance(doc, Mapping):
            violations.append(_violation(check, "BLUEPRINT_ROOT_INVALID", f"{name}.yaml must contain a YAML mapping", name, "CRITICAL"))
        elif root_key and root_key not in doc:
            violations.append(_violation(check, f"{name.upper()}_ROOT_REQUIRED", f"{name}.yaml must contain canonical root key {root_key}", name, "CRITICAL"))
    return loaded, violations


def _contract() -> tuple[GateResult, dict[str, Any]]:
    check = "contract"
    loaded, violations = _load_documents(check)
    if violations:
        return GateResult("blueprint_contract", GateStatus.FAIL, violations), {}

    architecture = loaded["architecture"]
    cases_doc = loaded["e2e_cases"]
    evidence_doc = loaded["evidence_index"]
    flows = _rows(architecture, "flows")
    cases = _rows(cases_doc, "cases")
    evidence = _rows(evidence_doc, "evidence")

    if not flows:
        violations.append(_violation(check, "BLUEPRINT_NO_FLOWS", "architecture.yaml must contain at least one business/E2E flow", severity="CRITICAL"))
    if not cases:
        violations.append(_violation(check, "BLUEPRINT_NO_CASES", "e2e_cases.yaml must contain at least one E2E case", severity="CRITICAL"))

    def validate_ids(rows: list[Mapping[str, Any]], kind: str) -> set[str]:
        ids: set[str] = set()
        for i, row in enumerate(rows):
            rid = str(row.get("id") or "").strip()
            if not rid:
                violations.append(_violation(check, f"{kind}_ID_REQUIRED", f"{kind.lower()}[{i}] missing id", severity="CRITICAL"))
                continue
            if rid in ids:
                violations.append(_violation(check, f"{kind}_ID_DUPLICATE", f"Duplicate {kind.lower()} id: {rid}", rid, "CRITICAL"))
            ids.add(rid)
        return ids

    flow_ids = validate_ids(flows, "FLOW")
    case_ids = validate_ids(cases, "CASE")
    evidence_ids = validate_ids(evidence, "EVIDENCE")

    for flow in flows:
        fid = str(flow.get("id") or "").strip()
        if fid and not str(flow.get("title") or "").strip():
            violations.append(_violation(check, "FLOW_TITLE_REQUIRED", f"{fid} missing title", fid))
        if fid and not str(flow.get("trigger") or "").strip():
            violations.append(_violation(check, "FLOW_TRIGGER_REQUIRED", f"{fid} missing trigger", fid))
        if fid and not _nonempty_strings(flow.get("steps")):
            violations.append(_violation(check, "FLOW_STEPS_REQUIRED", f"{fid} must contain meaningful E2E steps", fid))
        if fid and not _nonempty_strings(flow.get("terminal_outcomes")):
            violations.append(_violation(check, "FLOW_TERMINAL_REQUIRED", f"{fid} must contain at least one observable terminal outcome", fid, "CRITICAL"))

    for case in cases:
        cid = str(case.get("id") or "").strip()
        if cid and not str(case.get("title") or "").strip():
            violations.append(_violation(check, "CASE_TITLE_REQUIRED", f"{cid} missing title", cid))
        if cid and not str(case.get("intent") or "").strip():
            violations.append(_violation(check, "CASE_INTENT_REQUIRED", f"{cid} missing intent", cid))

    for row in evidence:
        eid = str(row.get("id") or "").strip()
        if eid and not str(row.get("source") or "").strip():
            violations.append(_violation(check, "EVIDENCE_SOURCE_REQUIRED", f"{eid} missing source", eid))
        if eid and not str(row.get("claim") or "").strip():
            violations.append(_violation(check, "EVIDENCE_CLAIM_REQUIRED", f"{eid} missing claim", eid))

    details = {"flows": len(flow_ids), "cases": len(case_ids), "evidence": len(evidence_ids)}
    return GateResult("blueprint_contract", GateStatus.FAIL if violations else GateStatus.PASS, violations, details), details


def _traceability() -> tuple[GateResult, dict[str, Any]]:
    check = "traceability"
    loaded, violations = _load_documents(check)
    if violations:
        return GateResult("blueprint_traceability", GateStatus.FAIL, violations), {}

    flows = _rows(loaded["architecture"], "flows")
    cases = _rows(loaded["e2e_cases"], "cases")
    evidence = _rows(loaded["evidence_index"], "evidence")
    flow_ids = {str(x.get("id") or "").strip() for x in flows if str(x.get("id") or "").strip()}
    evidence_ids = {str(x.get("id") or "").strip() for x in evidence if str(x.get("id") or "").strip()}
    used_flows: set[str] = set()
    referenced_evidence: set[str] = set()

    for case in cases:
        cid = str(case.get("id") or "").strip() or "<unknown>"
        flow_ref = str(case.get("flow_ref") or "").strip()
        if not flow_ref:
            violations.append(_violation(check, "CASE_FLOW_REF_REQUIRED", f"{cid} missing flow_ref", cid, "CRITICAL"))
        elif flow_ref not in flow_ids:
            violations.append(_violation(check, "CASE_FLOW_REF_UNKNOWN", f"{cid} references unknown flow {flow_ref}", cid, "CRITICAL"))
        else:
            used_flows.add(flow_ref)

        resolved_ids, unknown_ids, unknown_sources = _evidence_reference_sets(case, evidence)
        referenced_evidence.update(resolved_ids)
        if unknown_ids:
            violations.append(_violation(
                check,
                "CASE_EVIDENCE_REF_UNKNOWN",
                f"{cid} evidence_refs contains unknown Evidence IDs: {unknown_ids}",
                cid,
                "CRITICAL",
            ))
        # source_refs are direct locators, not Evidence IDs. They are allowed to remain
        # unindexed; only canonical evidence_refs participate in hard ID traceability.

    uncovered = sorted(flow_ids - used_flows)
    if uncovered:
        violations.append(_violation(check, "FLOW_WITHOUT_CASE", f"Every declared E2E flow needs at least one case. Missing: {uncovered}", severity="CRITICAL"))

    details = {
        "declared_flows": len(flow_ids),
        "covered_flows": len(used_flows),
        "declared_evidence": len(evidence_ids),
        "referenced_evidence": len(referenced_evidence & evidence_ids),
    }
    return GateResult("blueprint_traceability", GateStatus.FAIL if violations else GateStatus.PASS, violations, details), details


def _quality() -> tuple[GateResult, dict[str, Any]]:
    check = "quality"
    loaded, violations = _load_documents(check)
    if violations:
        return GateResult("blueprint_quality", GateStatus.FAIL, violations), {}

    manifest = loaded["manifest"]
    architecture = loaded["architecture"]
    cases_doc = loaded["e2e_cases"]
    evidence_doc = loaded["evidence_index"]
    components = _rows(architecture, "components")
    flows = _rows(architecture, "flows")
    cases = _rows(cases_doc, "cases")
    evidence = _rows(evidence_doc, "evidence")
    open_questions = _nonempty_strings(architecture.get("open_questions"))
    evidence_ids = {str(x.get("id") or "").strip() for x in evidence if str(x.get("id") or "").strip()}
    referenced_evidence: set[str] = set()
    assumption_cases = 0

    for case in cases:
        cid = str(case.get("id") or "").strip() or "<unknown>"
        if not _nonempty_strings(case.get("when")):
            violations.append(_violation(check, "CASE_WHEN_REQUIRED", f"{cid} missing business action/event", cid))
        if not _nonempty_strings(case.get("then")):
            violations.append(_violation(check, "CASE_ORACLE_REQUIRED", f"{cid} must contain at least one observable oracle in then", cid, "CRITICAL"))

        priority = str(case.get("priority") or "normal").lower().strip()
        if priority not in ALLOWED_PRIORITIES:
            violations.append(_violation(check, "CASE_PRIORITY_INVALID", f"{cid} priority must be critical|major|normal", cid))

        level = str(case.get("evidence_level") or "").upper().strip()
        if level not in ALLOWED_EVIDENCE_LEVELS:
            violations.append(_violation(check, "CASE_EVIDENCE_LEVEL_INVALID", f"{cid} evidence_level must be PROVEN|SUPPORTED|ASSUMPTION", cid))
        resolved_ids, unknown_ids, unknown_sources = _evidence_reference_sets(case, evidence)
        referenced_evidence.update(resolved_ids)
        if level in {"PROVEN", "SUPPORTED"} and not resolved_ids:
            violations.append(_violation(
                check,
                "CASE_EVIDENCE_REQUIRED",
                f"{cid} is {level} but has no resolvable evidence_refs (or legacy source_refs indexed by evidence_index)",
                cid,
                "CRITICAL",
            ))
        if unknown_ids:
            violations.append(_violation(check, "CASE_EVIDENCE_REF_UNKNOWN", f"{cid} evidence_refs contains unknown Evidence IDs: {unknown_ids}", cid, "CRITICAL"))
        # Unindexed source_refs are informational locators and do not fail quality.
        if level == "ASSUMPTION":
            assumption_cases += 1
            if not open_questions and not str(case.get("assumption") or "").strip():
                violations.append(_violation(check, "ASSUMPTION_MUST_BE_EXPLICIT", f"{cid} is ASSUMPTION; add architecture.open_questions or case.assumption", cid))

    counts = {
        "components": len(components),
        "flows": len(flows),
        "e2e_cases": len(cases),
        "evidence_items": len(evidence),
        "referenced_evidence_items": len(referenced_evidence & evidence_ids),
        "assumption_cases": assumption_cases,
        "open_questions": len(open_questions),
    }

    if not violations:
        normalized_manifest = dict(manifest)
        normalized_manifest.update({
            "version": 1,
            "artifact_kind": "e2e_blueprint_pack",
            "authority": "derived_hint",
            "truth_precedence": ["current_project_or_material_evidence", "this_blueprint_pack", "ai_assumption"],
            "project_agnostic": True,
            "portable_files": ["manifest.yaml", "architecture.yaml", "e2e_cases.yaml", "evidence_index.yaml"],
            "counts": counts,
            "fingerprints": {
                "architecture": _fingerprint(architecture),
                "e2e_cases": _fingerprint(cases_doc),
                "evidence_index": _fingerprint(evidence_doc),
            },
        })
        _dump_yaml(FILES["manifest"], normalized_manifest)

    details = {
        "portable_export": "result/blueprint/export",
        "counts": counts,
        "project_agnostic": True,
        "machine_gate_scope": "observable oracles, evidence levels, explicit assumptions, normalized manifest",
    }
    result = GateResult("blueprint_quality", GateStatus.FAIL if violations else GateStatus.PASS, violations, counts)
    if result.ok:
        _write_final_ai_context(details)
    return result, details


def _bounded(value: Any, limit: int) -> Any:
    return value[:limit] if isinstance(value, list) else value


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
        ],
    }
    _dump_yaml(OUT / "system" / "workflow1" / "final_ai_context.yaml", payload)


def _write_report(check: str, result: GateResult, details: Mapping[str, Any]) -> int:
    payload = result.to_dict()
    payload["details"] = dict(details)
    path = OUT / "system" / "workflow1" / "gates" / f"blueprint_{check}_validation.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if result.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", choices=("contract", "traceability", "quality"), required=True)
    parser.add_argument("--state")
    parser.add_argument("--state-file")
    parser.parse_known_args()
    args, _ = parser.parse_known_args()
    fn = {"contract": _contract, "traceability": _traceability, "quality": _quality}[args.check]
    result, details = fn()
    return _write_report(args.check, result, details)


if __name__ == "__main__":
    raise SystemExit(main())
