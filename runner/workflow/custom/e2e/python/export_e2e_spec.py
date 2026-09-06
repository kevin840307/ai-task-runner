from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Mapping

import yaml

ROOT = Path.cwd().resolve()
RESULT = ROOT / "result"
OUT = RESULT / "E2E_SPEC.md"


def load_yaml(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default if value is None else value


def rows(value: Any) -> list[Mapping[str, Any]]:
    return [x for x in (value if isinstance(value, list) else []) if isinstance(x, Mapping)]


def values(value: Any) -> list[str]:
    return [str(x).strip() for x in (value if isinstance(value, list) else []) if str(x).strip()]


def bullet(lines: list[str], items: list[str], indent: str = "") -> None:
    for item in items:
        lines.append(f"{indent}- {item}")


def export_workflow1() -> str:
    base = RESULT / "blueprint" / "export"
    manifest = load_yaml(base / "manifest.yaml", {})
    architecture = load_yaml(base / "architecture.yaml", {})
    cases_doc = load_yaml(base / "e2e_cases.yaml", {})
    evidence_doc = load_yaml(base / "evidence_index.yaml", {})
    required = [base / n for n in ("manifest.yaml", "architecture.yaml", "e2e_cases.yaml", "evidence_index.yaml")]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.is_file()]
    if missing:
        raise SystemExit("Cannot export E2E_SPEC.md; missing Blueprint YAML: " + ", ".join(missing))

    lines = ["# E2E 規格（E2E SPEC）", "", "> 本文件由 Python 依已通過驗證的 YAML 產物確定性產生。", "", "## 來源", ""]
    bullet(lines, [str(p.relative_to(ROOT)).replace('\\','/') for p in required])
    counts = manifest.get("counts", {}) if isinstance(manifest, Mapping) else {}
    if isinstance(counts, Mapping):
        lines += ["", "## 摘要", ""]
        for key, val in counts.items():
            lines.append(f"- **{key}**: {val}")

    lines += ["", "## 系統架構", ""]
    for comp in rows(architecture.get("components") if isinstance(architecture, Mapping) else []):
        name = comp.get("name") or comp.get("id") or "Component"
        detail = comp.get("responsibility") or comp.get("description") or comp.get("type") or ""
        lines.append(f"- **{name}**" + (f": {detail}" if detail else ""))

    lines += ["", "## E2E 流程", ""]
    for flow in rows(architecture.get("flows") if isinstance(architecture, Mapping) else []):
        fid, title = str(flow.get("id") or "FLOW"), str(flow.get("title") or "Untitled flow")
        lines += [f"### {fid} — {title}", "", f"**觸發條件：** {flow.get('trigger') or '-'}", "", "**流程步驟**", ""]
        bullet(lines, values(flow.get("steps")))
        lines += ["", "**最終可觀測結果**", ""]
        bullet(lines, values(flow.get("terminal_outcomes")))
        lines.append("")

    lines += ["## E2E 測試案例", ""]
    for case in rows(cases_doc.get("cases") if isinstance(cases_doc, Mapping) else []):
        cid, title = str(case.get("id") or "CASE"), str(case.get("title") or "Untitled case")
        lines += [f"### {cid} — {title}", "", f"- **所屬流程：** {case.get('flow_ref') or '-'}", f"- **優先級：** {case.get('priority') or 'normal'}", f"- **驗證目的：** {case.get('intent') or '-'}", f"- **證據等級：** {case.get('evidence_level') or '-'}", "", "**前置條件（Given）**", ""]
        bullet(lines, values(case.get("given")))
        lines += ["", "**操作／事件（When）**", ""]
        bullet(lines, values(case.get("when")))
        lines += ["", "**預期結果／Oracle（Then）**", ""]
        bullet(lines, values(case.get("then")))
        evidence_refs = values(case.get("evidence_refs"))
        source_refs = values(case.get("source_refs"))
        if evidence_refs:
            lines += ["", "**證據 ID 引用**", ""]
            bullet(lines, evidence_refs)
        if source_refs:
            lines += ["", "**來源定位**", ""]
            bullet(lines, source_refs)
        lines.append("")

    evidence = rows(evidence_doc.get("evidence") if isinstance(evidence_doc, Mapping) else [])
    if evidence:
        lines += ["## 證據索引", ""]
        for item in evidence:
            lines.append(f"- **{item.get('id') or 'EVIDENCE'}** — {item.get('claim') or '-'} (`{item.get('source') or '-'}`)")
    questions = values(architecture.get("open_questions") if isinstance(architecture, Mapping) else [])
    if questions:
        lines += ["", "## 待確認問題／假設", ""]
        bullet(lines, questions)
    return "\n".join(lines).rstrip() + "\n"


def export_workflow2() -> str:
    manifest_path = RESULT / "regression" / "manifest.yaml"
    manifest = load_yaml(manifest_path, {})
    if not manifest_path.is_file() or not isinstance(manifest, Mapping):
        raise SystemExit("Cannot export E2E_SPEC.md; missing result/regression/manifest.yaml")
    tests = rows(manifest.get("tests"))
    if not tests:
        raise SystemExit("Cannot export E2E_SPEC.md; regression manifest contains no tests")
    coverage_path = ROOT / "E2E_COVERAGE.yaml"
    coverage = load_yaml(coverage_path, {})
    final_ctx_path = RESULT / "system" / "workflow2" / "final_ai_context.yaml"
    final_ctx = load_yaml(final_ctx_path, {})

    lines = ["# E2E 規格（E2E SPEC）", "", "> 本文件由 Python 依已通過驗證的 Regression YAML 產物確定性產生。", "", "## 來源", "", f"- {manifest_path.relative_to(ROOT).as_posix()}"]
    if coverage_path.is_file(): lines.append(f"- {coverage_path.relative_to(ROOT).as_posix()}")
    lines += ["", "## Regression E2E 測試案例", ""]
    for test in tests:
        tid = str(test.get("id") or "TEST")
        title = str(test.get("title") or test.get("intent") or "Regression case")
        lines += [f"### {tid} — {title}", "", f"- **驗證目的：** {test.get('intent') or '-'}", f"- **測試檔案：** `{test.get('test_ref') or '-'}`"]
        if test.get("method"): lines.append(f"- **測試方法：** `{test.get('method')}`")
        if test.get("source_ref"): lines.append(f"- **來源引用：** `{test.get('source_ref')}`")
        lines.append("")
    if isinstance(coverage, Mapping) and coverage:
        lines += ["## 執行／Coverage 契約", ""]
        defaults = coverage.get("defaults", {})
        if isinstance(defaults, Mapping):
            for key, val in defaults.items(): lines.append(f"- **{key}**: {val}")
        report = coverage.get("report", {})
        if isinstance(report, Mapping) and report.get("path"): lines.append(f"- **Coverage 報告：** `{report.get('path')}`")
        functions = rows(coverage.get("functions"))
        if functions:
            lines += ["", "### Coverage 目標", ""]
            for row in functions:
                target = row.get("function") or row.get("class") or row.get("file") or "target"
                threshold = row.get("min_line_coverage") or row.get("min_coverage") or "default"
                lines.append(f"- `{target}` — 最低 {threshold}%")
    if isinstance(final_ctx, Mapping):
        metrics = final_ctx.get("coverage_metrics", {})
        if isinstance(metrics, Mapping) and metrics:
            lines += ["", "## 最終 Python 驗證指標", ""]
            for key, val in metrics.items(): lines.append(f"- **{key}**: {val}")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export validated YAML artifacts to result/E2E_SPEC.md")
    parser.add_argument("--workflow", choices=("workflow1", "workflow2"), required=True)
    args = parser.parse_args()
    text = export_workflow1() if args.workflow == "workflow1" else export_workflow2()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"E2E_SPEC_EXPORT_PASS: {OUT.relative_to(ROOT).as_posix()}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
