from __future__ import annotations

import ast
import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from .models import GateResult, GateStatus, GateViolation

SUPPORTED_LANGUAGES = {"python", "java", "vbnet"}
LANGUAGE_ALIASES = {"py":"python", "python":"python", "java":"java", "vb":"vbnet", "vb.net":"vbnet", "vbnet":"vbnet", "visualbasic":"vbnet", "visual_basic":"vbnet"}
FORMAT_ALIASES = {"coverage.py":"coverage_json", "coverage":"coverage_json", "jacoco":"jacoco_xml", "cobertura":"cobertura_xml", "coverlet":"cobertura_xml", "opencover":"opencover_xml"}
SUPPORTED_FORMATS = {"auto", "coverage_json", "jacoco_xml", "cobertura_xml", "opencover_xml"}


@dataclass(frozen=True)
class CoverageValue:
    target: str
    covered: int
    missed: int
    report_locator: str

    @property
    def total(self) -> int:
        return self.covered + self.missed

    @property
    def percent(self) -> float:
        return 100.0 if self.total == 0 else (100.0 * self.covered / self.total)


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _norm_path(value: str) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _path_matches(actual: str, expected: str) -> bool:
    a = _norm_path(actual).lower()
    e = _norm_path(expected).lower()
    return a == e or a.endswith("/" + e) or e.endswith("/" + a)


def _class_matches(actual: str, expected: str) -> bool:
    a = str(actual or "").replace("/", ".").replace("+", ".").replace("$", ".").strip(".")
    e = str(expected or "").replace("/", ".").replace("+", ".").replace("$", ".").strip(".")
    return a == e or a.endswith("." + e)


def _target_label(target: Mapping[str, Any]) -> str:
    owner = str(target.get("class") or target.get("file") or "").strip()
    fn = str(target.get("function") or "").strip()
    sig = str(target.get("signature") or "").strip()
    return f"{owner}::{fn}{sig}" if owner else f"{fn}{sig}"


def _threshold(target: Mapping[str, Any], defaults: Mapping[str, Any]) -> float:
    raw = target.get("min_line_coverage", defaults.get("min_line_coverage", 80.0))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"invalid min_line_coverage: {raw!r}")
    if not 0.0 <= value <= 100.0:
        raise ValueError(f"min_line_coverage must be 0..100, got {value}")
    return value


def _read_config(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise ValueError("coverage config must be a mapping")
    return dict(raw)


def _detect_format(report: Path) -> str:
    if report.suffix.lower() == ".json":
        return "coverage_json"
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        raise ValueError(f"coverage report is neither supported JSON nor XML: {exc}") from exc
    tag = _strip_ns(root.tag).lower()
    if tag == "coveragesession":
        return "opencover_xml"
    if tag == "coverage":
        return "cobertura_xml"
    if tag == "report":
        return "jacoco_xml"
    raise ValueError(f"cannot auto-detect coverage XML format from root <{tag}>")


def _iter_python_symbols(tree: ast.AST) -> Iterable[tuple[str, ast.AST]]:
    def walk(node: ast.AST, prefix: list[str]) -> Iterable[tuple[str, ast.AST]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                q = prefix + [child.name]
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield ".".join(q), child
                yield from walk(child, q)
            else:
                yield from walk(child, prefix)
    yield from walk(tree, [])


def _resolve_python_source(target_file: str, report_file: str, base_dir: Path) -> Path | None:
    candidates: list[Path] = []
    for raw in (target_file, report_file):
        p = Path(raw)
        if p.is_absolute():
            candidates.append(p)
        else:
            candidates.append(base_dir / p)
    for p in candidates:
        if p.is_file():
            return p.resolve()
    # Coverage reports may contain absolute paths from another working directory. Fall back to
    # a unique suffix match below the configured base directory.
    suffix = _norm_path(target_file or report_file)
    matches = [p.resolve() for p in base_dir.rglob(Path(suffix).name) if p.is_file() and _path_matches(str(p), suffix)]
    return matches[0] if len(matches) == 1 else None


def _python_value(report: Mapping[str, Any], target: Mapping[str, Any], base_dir: Path) -> CoverageValue:
    files = report.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("coverage.py JSON report has no files mapping")
    expected_file = str(target.get("file") or "").strip()
    function = str(target.get("function") or "").strip()
    if not expected_file or not function:
        raise ValueError("Python coverage target requires file + function")
    matches = [(str(name), data) for name, data in files.items() if _path_matches(str(name), expected_file)]
    if len(matches) != 1:
        raise LookupError(f"Python target file {expected_file!r} matched {len(matches)} report files")
    report_file, data = matches[0]
    if not isinstance(data, Mapping):
        raise ValueError(f"bad coverage.py file payload for {report_file}")
    source = _resolve_python_source(expected_file, report_file, base_dir)
    if source is None:
        raise LookupError(f"cannot resolve Python source file {expected_file!r}")
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    symbols = [(name, node) for name, node in _iter_python_symbols(tree) if name == function]
    if len(symbols) != 1:
        raise LookupError(f"Python function {function!r} matched {len(symbols)} symbols in {source}")
    _, node = symbols[0]
    start = int(getattr(node, "lineno", 0) or 0)
    end = int(getattr(node, "end_lineno", start) or start)
    executed = {int(x) for x in data.get("executed_lines", []) or []}
    missing = {int(x) for x in data.get("missing_lines", []) or []}
    coverable = (executed | missing) & set(range(start, end + 1))
    if not coverable:
        raise LookupError(f"No executable coverage lines found for {expected_file}::{function} lines {start}-{end}")
    covered = len(executed & coverable)
    return CoverageValue(_target_label(target), covered, len(coverable) - covered, f"{report_file}:{start}-{end}")


def _jacoco_value(root: ET.Element, target: Mapping[str, Any]) -> CoverageValue:
    expected_class = str(target.get("class") or "").strip()
    expected_file = str(target.get("file") or "").strip()
    function = str(target.get("function") or "").strip()
    signature = str(target.get("signature") or "").strip()
    if not function:
        raise ValueError("Java JaCoCo target requires function")
    matches: list[tuple[str, ET.Element]] = []
    for cls in root.iter():
        if _strip_ns(cls.tag) != "class":
            continue
        cls_name = str(cls.attrib.get("name") or "")
        src = str(cls.attrib.get("sourcefilename") or "")
        if expected_class and not _class_matches(cls_name, expected_class):
            continue
        if expected_file and not _path_matches(src, expected_file):
            continue
        for method in list(cls):
            if _strip_ns(method.tag) != "method" or method.attrib.get("name") != function:
                continue
            if signature and method.attrib.get("desc") != signature:
                continue
            matches.append((cls_name, method))
    if not matches:
        raise LookupError(f"JaCoCo method not found: {_target_label(target)}")
    if len(matches) > 1 and not bool(target.get("match_all_overloads")):
        raise LookupError(f"JaCoCo target is ambiguous ({len(matches)} overloads): {_target_label(target)}; specify signature or match_all_overloads")
    selected = matches if bool(target.get("match_all_overloads")) else [matches[0]]
    covered = missed = 0
    locators = []
    for cls_name, method in selected:
        line_counter = next((x for x in method if _strip_ns(x.tag) == "counter" and x.attrib.get("type") == "LINE"), None)
        if line_counter is None:
            raise LookupError(f"JaCoCo method has no LINE counter: {cls_name}::{function}")
        covered += int(line_counter.attrib.get("covered", "0"))
        missed += int(line_counter.attrib.get("missed", "0"))
        locators.append(f"{cls_name}::{function}{method.attrib.get('desc','')}")
    if covered + missed == 0:
        raise LookupError(f"JaCoCo method has no coverable lines: {_target_label(target)}")
    return CoverageValue(_target_label(target), covered, missed, ", ".join(locators))


def _cobertura_value(root: ET.Element, target: Mapping[str, Any], *, case_insensitive: bool=False) -> CoverageValue:
    expected_class = str(target.get("class") or "").strip()
    expected_file = str(target.get("file") or "").strip()
    function = str(target.get("function") or "").strip()
    signature = str(target.get("signature") or "").strip()
    if not function:
        raise ValueError("Cobertura target requires function")
    matches: list[tuple[str, str, ET.Element]] = []
    for cls in root.iter():
        if _strip_ns(cls.tag) != "class":
            continue
        cls_name = str(cls.attrib.get("name") or "")
        filename = str(cls.attrib.get("filename") or "")
        if expected_class and not _class_matches(cls_name, expected_class):
            continue
        if expected_file and not _path_matches(filename, expected_file):
            continue
        for method in cls.iter():
            if _strip_ns(method.tag) != "method":
                continue
            method_name = str(method.attrib.get("name") or "")
            if (method_name.lower() != function.lower()) if case_insensitive else (method_name != function):
                continue
            method_sig = str(method.attrib.get("signature") or "")
            if signature and signature not in method_sig:
                continue
            matches.append((cls_name, filename, method))
    if not matches:
        raise LookupError(f"Cobertura method not found: {_target_label(target)}")
    if len(matches) > 1 and not bool(target.get("match_all_overloads")):
        raise LookupError(f"Cobertura target is ambiguous ({len(matches)} matches): {_target_label(target)}; specify class/signature or match_all_overloads")
    selected = matches if bool(target.get("match_all_overloads")) else [matches[0]]
    covered = missed = 0
    locators = []
    for cls_name, filename, method in selected:
        lines = [x for x in method.iter() if _strip_ns(x.tag) == "line"]
        if not lines:
            raise LookupError(f"Cobertura method has no line data: {cls_name}::{function}")
        for line in lines:
            hits = int(float(line.attrib.get("hits", "0") or 0))
            if hits > 0:
                covered += 1
            else:
                missed += 1
        locators.append(f"{filename}:{cls_name}::{function}{method.attrib.get('signature','')}")
    return CoverageValue(_target_label(target), covered, missed, ", ".join(locators))


def _opencover_value(root: ET.Element, target: Mapping[str, Any]) -> CoverageValue:
    expected_class = str(target.get("class") or "").strip()
    expected_file = str(target.get("file") or "").strip()
    function = str(target.get("function") or "").strip()
    signature = str(target.get("signature") or "").strip()
    if not function:
        raise ValueError("OpenCover target requires function")
    matches: list[tuple[str, str, ET.Element]] = []
    for cls in root.iter():
        if _strip_ns(cls.tag) != "Class":
            continue
        full_name_node = next((x for x in cls if _strip_ns(x.tag) == "FullName"), None)
        cls_name = (full_name_node.text or "").strip() if full_name_node is not None else ""
        if expected_class and not _class_matches(cls_name, expected_class):
            continue
        for method in cls.iter():
            if _strip_ns(method.tag) != "Method":
                continue
            name_node = next((x for x in method if _strip_ns(x.tag) == "Name"), None)
            full_method = (name_node.text or "").strip() if name_node is not None else ""
            # OpenCover names look like: System.Void Namespace.Type::Method(System.String)
            lower_method = full_method.lower()
            lower_function = function.lower()
            if f"::{lower_function}(" not in lower_method and not lower_method.endswith(f"::{lower_function}"):
                continue
            if signature and signature not in full_method:
                continue
            # OpenCover file matching uses FileRef uid -> Files/File. It is optional because class+method is normally enough.
            file_name = ""
            if expected_file:
                file_ref = next((x for x in method.iter() if _strip_ns(x.tag) == "FileRef"), None)
                uid = file_ref.attrib.get("uid") if file_ref is not None else None
                if uid:
                    for file_node in root.iter():
                        if _strip_ns(file_node.tag) == "File" and file_node.attrib.get("uid") == uid:
                            file_name = str(file_node.attrib.get("fullPath") or "")
                            break
                if not file_name or not _path_matches(file_name, expected_file):
                    continue
            matches.append((cls_name, full_method, method))
    if not matches:
        raise LookupError(f"OpenCover method not found: {_target_label(target)}")
    if len(matches) > 1 and not bool(target.get("match_all_overloads")):
        raise LookupError(f"OpenCover target is ambiguous ({len(matches)} matches): {_target_label(target)}; specify signature or match_all_overloads")
    selected = matches if bool(target.get("match_all_overloads")) else [matches[0]]
    covered_lines: set[tuple[str, int]] = set()
    missed_lines: set[tuple[str, int]] = set()
    locators = []
    for cls_name, full_method, method in selected:
        for sp in method.iter():
            if _strip_ns(sp.tag) != "SequencePoint":
                continue
            line = int(sp.attrib.get("sl", "0") or 0)
            if line <= 0:
                continue
            key = (full_method, line)
            if int(sp.attrib.get("vc", "0") or 0) > 0:
                covered_lines.add(key); missed_lines.discard(key)
            elif key not in covered_lines:
                missed_lines.add(key)
        locators.append(f"{cls_name}::{full_method}")
    if not covered_lines and not missed_lines:
        raise LookupError(f"OpenCover method has no sequence points: {_target_label(target)}")
    return CoverageValue(_target_label(target), len(covered_lines), len(missed_lines), ", ".join(locators))


def validate_code_coverage(config_path: Path, *, base_dir: Path | None = None) -> GateResult:
    """Validate selected function/method line coverage from an existing coverage report.

    The validator is intentionally report-only. Stage 7 is responsible for running the real tests
    with the language-specific coverage collector. This Gate only accepts machine-produced coverage
    facts and never asks AI to estimate coverage.
    """
    base = (base_dir or config_path.parent).resolve()
    violations: list[GateViolation] = []
    metrics: dict[str, Any] = {"enabled": True, "config": str(config_path)}
    try:
        cfg = _read_config(config_path)
        language_raw = str(cfg.get("language") or "").strip().lower()
        language = LANGUAGE_ALIASES.get(language_raw, language_raw)
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"language must be one of {sorted(SUPPORTED_LANGUAGES)}, got {language!r}")
        report_cfg = cfg.get("report")
        if not isinstance(report_cfg, Mapping):
            raise ValueError("report mapping is required")
        report_raw = str(report_cfg.get("path") or "").strip()
        if not report_raw:
            raise ValueError("report.path is required")
        report = Path(report_raw)
        if not report.is_absolute():
            report = base / report
        report = report.resolve()
        if not report.is_file():
            raise FileNotFoundError(f"coverage report not found: {report}")
        version = cfg.get("version", 1)
        if version != 1:
            raise ValueError(f"coverage config version must be 1, got {version!r}")
        freshness_raw = str(report_cfg.get("must_be_newer_than") or "").strip()
        if freshness_raw:
            freshness = Path(freshness_raw)
            if not freshness.is_absolute():
                freshness = base / freshness
            freshness = freshness.resolve()
            if not freshness.is_file():
                raise FileNotFoundError(f"coverage freshness reference not found: {freshness}")
            if report.stat().st_mtime_ns < freshness.stat().st_mtime_ns:
                raise ValueError(f"coverage report is stale: {report} is older than {freshness}")
        fmt_raw = str(report_cfg.get("format") or "auto").strip().lower()
        fmt = FORMAT_ALIASES.get(fmt_raw, fmt_raw)
        if fmt not in SUPPORTED_FORMATS:
            raise ValueError(f"report.format must be one of {sorted(SUPPORTED_FORMATS)}, got {fmt!r}")
        if fmt == "auto":
            fmt = _detect_format(report)
        targets = cfg.get("functions")
        if not isinstance(targets, list) or not targets:
            raise ValueError("functions must be a non-empty list")
        defaults = cfg.get("defaults") if isinstance(cfg.get("defaults"), Mapping) else {}
        values: list[CoverageValue] = []
        details: list[dict[str, Any]] = []
        py_report: Mapping[str, Any] | None = None
        xml_root: ET.Element | None = None
        if fmt == "coverage_json":
            py_report = json.loads(report.read_text(encoding="utf-8"))
        else:
            xml_root = ET.parse(report).getroot()
        for idx, raw_target in enumerate(targets):
            if not isinstance(raw_target, Mapping):
                violations.append(GateViolation("COVERAGE_TARGET_INVALID", f"functions[{idx}] must be a mapping", None, "final_validation", "CRITICAL"))
                continue
            target = dict(raw_target)
            label = _target_label(target) or f"functions[{idx}]"
            try:
                min_cov = _threshold(target, defaults)
                if fmt == "coverage_json":
                    if language != "python":
                        raise ValueError("coverage_json is supported for language=python")
                    value = _python_value(py_report or {}, target, base)
                elif fmt == "jacoco_xml":
                    if language != "java":
                        raise ValueError("jacoco_xml is supported for language=java")
                    value = _jacoco_value(xml_root, target)  # type: ignore[arg-type]
                elif fmt == "cobertura_xml":
                    if language not in {"java", "vbnet"}:
                        raise ValueError("cobertura_xml is supported for language=java or vbnet")
                    value = _cobertura_value(xml_root, target, case_insensitive=(language == "vbnet"))  # type: ignore[arg-type]
                elif fmt == "opencover_xml":
                    if language != "vbnet":
                        raise ValueError("opencover_xml is supported for language=vbnet")
                    value = _opencover_value(xml_root, target)  # type: ignore[arg-type]
                else:
                    raise ValueError(f"unsupported report format: {fmt}")
                values.append(value)
                details.append({
                    "target": value.target,
                    "covered_lines": value.covered,
                    "missed_lines": value.missed,
                    "total_lines": value.total,
                    "line_coverage": round(value.percent, 4),
                    "min_line_coverage": min_cov,
                    "report_locator": value.report_locator,
                })
                if value.percent + 1e-12 < min_cov:
                    violations.append(GateViolation(
                        "COVERAGE_BELOW_THRESHOLD",
                        f"{value.target}: {value.percent:.2f}% < required {min_cov:.2f}% ({value.covered}/{value.total} lines)",
                        value.target,
                        "final_validation",
                        "CRITICAL",
                    ))
            except (ValueError, LookupError) as exc:
                violations.append(GateViolation("COVERAGE_TARGET_UNRESOLVED", f"{label}: {exc}", label, "final_validation", "CRITICAL"))
        total_covered = sum(x.covered for x in values)
        total_lines = sum(x.total for x in values)
        aggregate = 100.0 if total_lines == 0 else 100.0 * total_covered / total_lines
        aggregate_raw = cfg.get("aggregate_min_line_coverage")
        if aggregate_raw is not None:
            try:
                aggregate_min = float(aggregate_raw)
                if not 0 <= aggregate_min <= 100:
                    raise ValueError
            except (TypeError, ValueError):
                violations.append(GateViolation("COVERAGE_CONFIG_INVALID", "aggregate_min_line_coverage must be 0..100", None, "final_validation", "CRITICAL"))
            else:
                if aggregate + 1e-12 < aggregate_min:
                    violations.append(GateViolation(
                        "COVERAGE_AGGREGATE_BELOW_THRESHOLD",
                        f"aggregate selected-function coverage {aggregate:.2f}% < required {aggregate_min:.2f}%",
                        None,
                        "final_validation",
                        "CRITICAL",
                    ))
                metrics["aggregate_min_line_coverage"] = aggregate_min
        metrics.update({
            "language": language,
            "report_format": fmt,
            "report": str(report),
            "functions": details,
            "function_count": len(values),
            "aggregate_line_coverage": round(aggregate, 4),
            "covered_lines": total_covered,
            "total_lines": total_lines,
        })
    except FileNotFoundError as exc:
        violations.append(GateViolation("COVERAGE_REPORT_MISSING", str(exc), None, "final_validation", "CRITICAL"))
    except (ValueError, json.JSONDecodeError, ET.ParseError, OSError) as exc:
        violations.append(GateViolation("COVERAGE_CONFIG_INVALID", str(exc), None, "final_validation", "CRITICAL"))
    return GateResult("code_coverage_gate", GateStatus.FAIL if violations else GateStatus.PASS, violations, metrics)


def coverage_gate_from_default(base_dir: Path, config_name: str = "E2E_COVERAGE.yaml") -> GateResult:
    config = (base_dir / config_name).resolve()
    if not config.is_file():
        return GateResult("code_coverage_gate", GateStatus.PASS, metrics={"enabled": False, "config": str(config)})
    return validate_code_coverage(config, base_dir=base_dir)
