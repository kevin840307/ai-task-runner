from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path.cwd().resolve()
OUT = ROOT / "result"

EXCLUDED_DIRS = {
    ".git", ".svn", ".hg", ".idea", ".vscode",
    ".ai-task-runner", ".e2e-regression", "result",
    "node_modules", "vendor", "dist", "build", "target", "bin", "obj",
    ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache",
}
REQUEST_NAMES = (
    "BLUEPRINT_REQUEST.md",
    "E2E_REQUEST.md",
    "E2E_SPEC_REQUEST.md",
    "REQUEST.md",
)


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _walk_files(root: Path, *, limit: int = 10000) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    rows: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in EXCLUDED_DIRS for part in rel_parts[:-1]):
            continue
        rows.append(path)
        if len(rows) >= limit:
            break
    return rows


def _kind(path: Path) -> str:
    suffix = path.suffix.lower()
    name = path.name.lower()
    parts = {p.lower() for p in path.parts}
    if suffix in {".md", ".rst", ".adoc", ".txt"} or "doc" in parts or "docs" in parts:
        return "documentation"
    if suffix in {".sql", ".ddl"}:
        return "database"
    if suffix in {".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf", ".properties", ".xml"}:
        if "openapi" in name or "swagger" in name:
            return "api_spec"
        return "configuration_or_spec"
    if suffix in {".feature", ".spec", ".har"}:
        return "spec_or_sample"
    if suffix in {".log", ".trace"}:
        return "runtime_evidence"
    if suffix in {".py", ".java", ".kt", ".kts", ".cs", ".vb", ".fs", ".go", ".rs", ".c", ".cc", ".cpp", ".h", ".hpp", ".js", ".ts", ".tsx", ".jsx", ".php", ".rb", ".scala", ".swift"}:
        return "source_code"
    if "test" in parts or "tests" in parts or "sample" in parts or "samples" in parts or "example" in parts or "examples" in parts:
        return "test_or_sample"
    return "other"


def _display(path: Path, roots: list[tuple[str, Path]]) -> str:
    for label, root in roots:
        if _is_inside(path, root):
            rel = path.resolve().relative_to(root.resolve()).as_posix()
            return f"{label}://{rel}"
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _find_request() -> Path | None:
    for name in REQUEST_NAMES:
        candidate = ROOT / name
        if candidate.is_file():
            return candidate
    return None


def _request_excerpt(path: Path | None, max_chars: int = 12000) -> str:
    if path is None:
        return ""
    text = path.read_text(encoding="utf-8", errors="ignore")
    return text if len(text) <= max_chars else text[:max_chars] + "\n...<bounded>..."


def _evidence_roots() -> list[tuple[str, Path]]:
    sibling_material = (ROOT.parent / "material").resolve()
    roots: list[tuple[str, Path]] = []
    if sibling_material.is_dir():
        roots.append(("material", sibling_material))
    else:
        # Normal arbitrary-project mode: the project itself is the evidence root.
        roots.append(("project", ROOT))
    return roots



PLANNING_FILE_HINTS = (
    "readme", "spec", "openapi", "swagger", "controller", "route", "api",
    "scheduler", "job", "worker", "service", "workflow", "main", "program",
    "startup", "application", "sql", "repository", "dao", "test", "example",
)


def _planning_score(path: Path) -> tuple[int, int, str]:
    """Rank files for bounded planning discovery without doing static analysis."""
    text = path.as_posix().lower()
    kind = _kind(path)
    kind_rank = {
        "documentation": 0,
        "api_spec": 1,
        "spec_or_sample": 2,
        "configuration_or_spec": 3,
        "source_code": 4,
        "database": 5,
        "test_or_sample": 6,
        "runtime_evidence": 7,
        "other": 8,
    }.get(kind, 9)
    hint_rank = 0 if any(token in text for token in PLANNING_FILE_HINTS) else 1
    return (kind_rank * 2 + hint_rank, len(path.parts), text)


def _bounded_excerpt(path: Path, *, max_chars: int = 1400) -> str:
    """Read a tiny, safe excerpt for planning navigation only."""
    try:
        if path.stat().st_size > 2_000_000:
            return "<large file; path only>"
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "<unreadable>"
    text = text.replace("\x00", "")
    if len(text) > max_chars:
        text = text[:max_chars] + "\n...<bounded>..."
    return text


def _planning_summary(
    request: Path | None,
    files: list[Path],
    roots: list[tuple[str, Path]],
    counts: Counter,
) -> dict[str, Any]:
    """Create source-derived bounded evidence for PlanStage.

    This intentionally answers only "what kind of system is this and where are the
    likely E2E boundaries?". Deep call-chain/function/SQL reasoning belongs to Execute.
    """
    selected = sorted(files, key=_planning_score)[:8]
    return {
        "purpose": "bounded source/spec discovery for business-flow TODO planning",
        "request_excerpt": _request_excerpt(request, 3500),
        "evidence_kind_counts": dict(sorted(counts.items())),
        "selected_files": [
            {
                "ref": _display(path, roots),
                "kind": _kind(path),
                "excerpt": _bounded_excerpt(path),
            }
            for path in selected
        ],
        "budget": {
            "selected_files_max": 8,
            "excerpt_chars_per_file_max": 1400,
            "deep_call_chain": False,
            "exhaustive_repository_scan": False,
        },
        "planner_instruction": (
            "Use this source-derived summary to create the minimum coherent Business-Flow TODOs. "
            "Do not perform more repository exploration in Planning. Deep discovery belongs to Execute. "
            "Do not create TODOs for manifest/evidence-index/review/validation mechanics; those are workflow outputs. "
            "Prefer Traditional Chinese (zh-TW) for TODO title/description/deliverable/acceptance text when practical; technical identifiers remain unchanged."
        ),
    }


def build_preflight(root: Path = ROOT) -> dict[str, Any]:
    global ROOT, OUT
    ROOT = root.resolve()
    OUT = ROOT / "result"
    roots = _evidence_roots()
    files: list[Path] = []
    for _, evidence_root in roots:
        files.extend(_walk_files(evidence_root))

    counts = Counter(_kind(path) for path in files)
    ext_counts = Counter(path.suffix.lower() or "<none>" for path in files)
    request = _find_request()

    # This is navigation only. Do not turn Preflight into a static analyzer.
    priority = {
        "documentation": 0,
        "api_spec": 1,
        "configuration_or_spec": 2,
        "database": 3,
        "test_or_sample": 4,
        "spec_or_sample": 5,
        "source_code": 6,
        "runtime_evidence": 7,
        "other": 8,
    }
    representative = sorted(files, key=lambda p: (priority.get(_kind(p), 99), len(p.parts), str(p).lower()))[:160]

    payload = {
        "version": 1,
        "workflow": "workflow1_generic_e2e_blueprint",
        "project_root": str(ROOT),
        "request_file": str(request) if request else None,
        "request_excerpt": _request_excerpt(request),
        "evidence_roots": [
            {"label": label, "path": str(path), "mode": "read_only_evidence"}
            for label, path in roots
        ],
        "inventory": {
            "files_seen": len(files),
            "evidence_kind_counts": dict(sorted(counts.items())),
            "top_extensions": dict(ext_counts.most_common(30)),
            "representative_files": [
                {"ref": _display(path, roots), "kind": _kind(path)} for path in representative
            ],
        },
        "planning_summary": _planning_summary(request, files, roots, counts),
        "planning_contract": {
            "primary_axis": "business behavior / E2E flow, not source file, class, DLL, service, or static-analysis phase",
            "generic_project_rule": "Source code is optional and is only one evidence type. Documentation, API specs, SQL/DDL, configuration, workflow definitions, samples, tests, logs, and user requirements are valid evidence too.",
            "task_rule": "Create the minimum coherent Business-Flow TODOs (normally 1-5; use more only for genuinely distinct flows). Avoid manifest/evidence-index/review/validator mechanics as standalone TODOs, repository-wide umbrella TODOs, and one-TODO-per-file static analysis.",
            "unknown_rule": "When evidence is insufficient, record an assumption/open question instead of inventing a fact.",
            "output_rule": "Incrementally maintain the portable Blueprint export under result/blueprint/export/. Prefer Traditional Chinese (zh-TW) for human-readable title/description/intent/claim/role/open-question text when practical; keep IDs, enum values, code symbols, API names, SQL/table names, class/function names, paths, and protocol tokens in their original technical form.",
        },
        "required_outputs": [
            "result/blueprint/export/manifest.yaml",
            "result/blueprint/export/architecture.yaml",
            "result/blueprint/export/e2e_cases.yaml",
            "result/blueprint/export/evidence_index.yaml",
        ],
    }
    return payload


def main() -> int:
    payload = build_preflight()
    path = OUT / "system" / "workflow1" / "preflight.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # PlanStage receives this compact deterministic context.
    print(json.dumps(payload, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
