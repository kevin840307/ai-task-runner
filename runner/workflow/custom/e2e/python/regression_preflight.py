from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

import yaml

from e2e_gate.workspace import scan_workspace_inventory

ROOT = Path.cwd().resolve()
OUT = ROOT / "result"
MATERIAL = (ROOT.parent / "material").resolve()


def _load_yaml(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if value is None else value


def _find_blueprint(material: Path) -> Path | None:
    candidates = [material / "e2e_blueprint", material / "blueprint", material / "architecture"]
    for candidate in candidates:
        if candidate.is_dir() and any((candidate / name).is_file() for name in ("manifest.yaml", "e2e_cases.yaml", "architecture.yaml")):
            return candidate.resolve()
    return None


def _count_files(root: Path, suffixes: set[str]) -> int:
    if not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in suffixes)


def _hint_summary(hints: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for hint in hints:
        counts[str(hint.get("type") or hint.get("kind") or "OTHER")] += 1
    return dict(sorted(counts.items()))


def _planning_units(inventory: Mapping[str, Any], *, max_projects: int = 30, max_hints_per_project: int = 6) -> list[dict[str, Any]]:
    projects = [x for x in inventory.get("projects", []) or [] if isinstance(x, Mapping)]
    hints = [x for x in inventory.get("discovery_hints", []) or [] if isinstance(x, Mapping)]
    by_root: dict[str, list[Mapping[str, Any]]] = {}
    for hint in hints:
        by_root.setdefault(str(hint.get("project_root") or ""), []).append(hint)
    units: list[dict[str, Any]] = []
    for project in projects[:max_projects]:
        root = str(project.get("path") or "")
        rows = sorted(by_root.get(root, []), key=lambda x: str(x.get("id") or ""))
        units.append({
            "project_ref": project.get("id"),
            "project_path": root,
            "project_type": project.get("type"),
            "hint_counts": _hint_summary(rows),
            "key_hints": [
                {k: row.get(k) for k in ("id", "type", "file", "symbol", "detail", "line") if row.get(k) not in (None, "")}
                for row in rows[:max_hints_per_project]
            ],
        })
    return units


def _blueprint_case_units(blueprint: Path | None, *, limit: int = 40) -> list[dict[str, Any]]:
    if blueprint is None:
        return []
    doc = _load_yaml(blueprint / "e2e_cases.yaml", {})
    cases = doc.get("cases", []) if isinstance(doc, Mapping) else []
    result: list[dict[str, Any]] = []
    for case in cases or []:
        if not isinstance(case, Mapping):
            continue
        result.append({
            "id": case.get("id"),
            "title": case.get("title"),
            "flow_ref": case.get("flow_ref"),
            "covers": list(case.get("covers", []) or [])[:12],
            "source_refs": list(case.get("source_refs", []) or [])[:12],
        })
        if len(result) >= limit:
            break
    return result


def build_preflight(root: Path = ROOT, material: Path = MATERIAL) -> dict[str, Any]:
    blueprint = _find_blueprint(material)
    source = material / "source_code"
    auxiliary = [p for p in (material / "ddl", material / "config", material / "doc", material / "workflow", material / "sample") if p.exists()]
    inventory = scan_workspace_inventory([source] if source.exists() else [], auxiliary_roots=auxiliary)
    planning_units = _planning_units(inventory)
    blueprint_units = _blueprint_case_units(blueprint)
    return {
        "workflow": "workflow2_regression_generation",
        "workspace": str(root),
        "material_root": str(material),
        "source_root": str(source) if source.exists() else None,
        "optional_blueprint": str(blueprint) if blueprint else None,
        "blueprint_policy": "Optional seed only. Verify every relevant claim against current source/material evidence; source wins on conflict.",
        "inventory": {
            "projects": len(inventory.get("projects", []) or []),
            "source_files": _count_files(source, {".py", ".java", ".kt", ".vb", ".cs", ".xml", ".sql", ".yml", ".yaml"}),
            "ddl_files": _count_files(material / "ddl", {".sql", ".ddl"}),
            "hint_counts": _hint_summary([x for x in inventory.get("discovery_hints", []) or [] if isinstance(x, Mapping)]),
        },
        "planning_units": planning_units,
        "blueprint_case_units": blueprint_units,
        "planning_contract": {
            "small_model": True,
            "rule": "Create bounded implementation TODOs from the supplied planning units; never create one repository-wide umbrella TODO.",
            "preferred_task_scope": "one business flow / one coherent test cluster / one shared test-infrastructure change",
            "max_parallel_concepts_per_todo": 1,
            "repair_rule": "Final-validator repair plans address only the reported failure delta and preserve passing tests.",
        },
        "delivery_contract": [
            "Modify only the writable Test Project/workspace for generated regression tests.",
            "Maintain result/regression/manifest.yaml with test intent and exact test file/method references.",
            "Do not fabricate coverage reports; Final Python executes the protected real test/coverage commands.",
            "Prefer fewer high-confidence tests over speculative tests solely to inflate coverage.",
            "Use optional Blueprint as a seed, never as higher authority than current source/material.",
        ],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = build_preflight()
    path = OUT / "system" / "workflow2" / "preflight.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # PlanStage receives prior command output. Keep this deterministic summary compact enough for small models.
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
