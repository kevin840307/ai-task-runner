#!/usr/bin/env python3
"""Compare two folders without flooding stdout.

Checks:
- all subfolder relative paths match
- .yml, .yaml, .cfg, and .xml file relative paths match
- matching target files have identical content

Large details are written under:
.ai-task-runner/validator-reports/folder-compare/
"""

from __future__ import annotations

import argparse
import configparser
import difflib
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

import yaml


TARGET_EXTENSIONS = {".yml", ".yaml", ".cfg", ".xml"}
MAX_STDOUT_ITEMS = 10
MAX_DIFF_FILES = 100
MAX_DIFF_LINES_PER_FILE = 200
CONFIG_EXTENSIONS = {".yml", ".yaml", ".cfg", ".xml"}
SKIPPED_SCALAR_VALUES = {"true", "false", "null", "none"}


@dataclass
class FolderSnapshot:
    dirs: set[str]
    files: set[str]
    ignored_files: set[str]


@dataclass
class ScalarOccurrence:
    file: str
    path: str


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return str(path)


def collect_folder(root: Path) -> FolderSnapshot:
    dirs: set[str] = set()
    files: set[str] = set()
    ignored_files: set[str] = set()
    for path in root.rglob("*"):
        relative = rel(path, root)
        if path.is_dir():
            dirs.add(relative)
        elif path.suffix.lower() in TARGET_EXTENSIONS:
            files.add(relative)
        else:
            ignored_files.add(relative)
    return FolderSnapshot(dirs=dirs, files=files, ignored_files=ignored_files)


def read_text(path: Path, exact_bytes: bool) -> str:
    if exact_bytes:
        return path.read_bytes().decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")


def write_report(report_dir: Path, name: str, lines: list[str]) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / name
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def sorted_lines(values: set[str]) -> list[str]:
    return sorted(values, key=lambda item: item.lower())


def format_examples(values: set[str]) -> list[str]:
    items = sorted_lines(values)
    lines = [f"- {item}" for item in items[:MAX_STDOUT_ITEMS]]
    if len(items) > MAX_STDOUT_ITEMS:
        lines.append(f"- ... {len(items) - MAX_STDOUT_ITEMS} more")
    return lines


def diff_for_file(expected_path: Path, actual_path: Path, label: str, exact_bytes: bool) -> list[str]:
    expected = read_text(expected_path, exact_bytes).splitlines()
    actual = read_text(actual_path, exact_bytes).splitlines()
    diff = list(
        difflib.unified_diff(
            expected,
            actual,
            fromfile=f"expected/{label}",
            tofile=f"actual/{label}",
            lineterm="",
        )
    )
    if len(diff) > MAX_DIFF_LINES_PER_FILE:
        omitted = len(diff) - MAX_DIFF_LINES_PER_FILE
        diff = diff[:MAX_DIFF_LINES_PER_FILE] + [f"... {omitted} diff lines omitted for this file"]
    return diff


def normalize_scalar(value: object, min_length: int) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    if len(text) < min_length:
        return None
    if text.lower() in SKIPPED_SCALAR_VALUES:
        return None
    return text


def walk_yaml_scalars(data: object, path: str = "$") -> list[tuple[str, object]]:
    if isinstance(data, dict):
        values: list[tuple[str, object]] = []
        for key, value in data.items():
            values.extend(walk_yaml_scalars(value, f"{path}.{key}"))
        return values
    if isinstance(data, list):
        values = []
        for index, value in enumerate(data):
            values.extend(walk_yaml_scalars(value, f"{path}[{index}]"))
        return values
    return [(path, data)]


def extract_yaml_scalars(path: Path) -> list[tuple[str, object]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    return walk_yaml_scalars(data)


def extract_cfg_scalars(path: Path) -> list[tuple[str, object]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error:
        pairs = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            match = re.match(r"\s*([^#;][^:=]+?)\s*[:=]\s*(.+?)\s*$", line)
            if match:
                pairs.append((f"line:{line_number}:{match.group(1).strip()}", match.group(2).strip()))
        return pairs

    pairs = []
    for section in parser.sections():
        for key, value in parser.items(section):
            pairs.append((f"{section}.{key}", value))
    return pairs


def extract_xml_scalars(path: Path) -> list[tuple[str, object]]:
    root = ElementTree.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    pairs: list[tuple[str, object]] = []
    for element in root.iter():
        tag = element.tag
        for key, value in element.attrib.items():
            pairs.append((f"{tag}@{key}", value))
        text = (element.text or "").strip()
        if text:
            pairs.append((tag, text))
    return pairs


def extract_config_scalars(path: Path) -> list[tuple[str, object]]:
    suffix = path.suffix.lower()
    if suffix in {".yml", ".yaml"}:
        return extract_yaml_scalars(path)
    if suffix == ".cfg":
        return extract_cfg_scalars(path)
    if suffix == ".xml":
        return extract_xml_scalars(path)
    return []


def score_config_values(config_root: Path, project_root: Path, report_dir: Path, min_length: int) -> tuple[int, set[str]]:
    if not config_root.exists():
        return 100, set()

    occurrences: dict[str, list[ScalarOccurrence]] = {}
    parse_errors: list[str] = []
    for path in sorted(config_root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CONFIG_EXTENSIONS:
            continue
        relative = path.relative_to(project_root).as_posix()
        try:
            scalars = extract_config_scalars(path)
        except Exception as exc:  # noqa: BLE001 - validator feedback should include parse failures.
            parse_errors.append(f"{relative}: {exc}")
            continue
        for scalar_path, value in scalars:
            normalized = normalize_scalar(value, min_length)
            if normalized is None:
                continue
            occurrences.setdefault(normalized, []).append(ScalarOccurrence(relative, scalar_path))

    repeated = {
        value: items
        for value, items in occurrences.items()
        if len({item.file for item in items}) > 1
    }
    repeated_file_hits = sum(len({item.file for item in items}) - 1 for items in repeated.values())
    penalty = min(85, repeated_file_hits * 3) + min(15, len(parse_errors) * 5)
    score = max(0, 100 - penalty)

    lines = [
        f"score: {score}/100",
        "meaning: lower scores suggest scalar config values are repeated across many files.",
        "note: this is a warning-only heuristic; repeated values can still be valid.",
        f"config_root: {display_path(config_root, project_root)}",
        f"min_value_length: {min_length}",
        "",
        "repeated_values:",
    ]
    for value, items in sorted(repeated.items(), key=lambda item: (-len({entry.file for entry in item[1]}), item[0].lower())):
        files = sorted({item.file for item in items})
        lines.append(f"- value: {value!r}")
        lines.append(f"  files: {len(files)}")
        for item in items[:20]:
            lines.append(f"  - {item.file} :: {item.path}")
        if len(items) > 20:
            lines.append(f"  - ... {len(items) - 20} more occurrences")
    if parse_errors:
        lines.extend(["", "parse_errors:"])
        lines.extend(f"- {item}" for item in parse_errors)

    report = write_report(report_dir, "config_value_score.txt", lines)
    warning_examples = {
        f"score: {score}/100",
        f"repeated value groups: {len(repeated)}",
        f"repeated file hits: {repeated_file_hits}",
        f"Full report: {display_path(report, project_root)}",
    }
    return score, warning_examples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--expected-dir", default="ans")
    parser.add_argument("--actual-dir", default="output")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--config-min-value-length", type=int, default=4)
    parser.add_argument(
        "--no-config-score",
        action="store_true",
        help="Disable warning-only config scalar reuse scoring.",
    )
    parser.add_argument(
        "--exact-bytes",
        action="store_true",
        help="Compare exact bytes decoded as UTF-8. By default CRLF and LF are treated the same.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    _state_file = Path(args.state_file).resolve()
    expected_root = (project_root / args.expected_dir).resolve()
    actual_root = (project_root / args.actual_dir).resolve()
    report_dir = project_root / ".ai-task-runner" / "validator-reports" / "folder-compare"

    errors: list[tuple[str, str, set[str], str]] = []
    warnings: list[tuple[str, str, set[str]]] = []

    if not expected_root.exists():
        errors.append(("E001", f"Expected directory does not exist: {args.expected_dir}", set(), "Create or point --expected-dir at the reference folder."))
    if not actual_root.exists():
        errors.append(("E002", f"Actual directory does not exist: {args.actual_dir}", set(), "Generate the target folder or point --actual-dir at it."))

    if errors:
        write_standard_reports(report_dir, project_root, errors, warnings)
        print_summary(errors, warnings, report_dir, project_root)
        return 1

    expected = collect_folder(expected_root)
    actual = collect_folder(actual_root)

    missing_dirs = expected.dirs - actual.dirs
    extra_dirs = actual.dirs - expected.dirs
    missing_files = expected.files - actual.files
    extra_files = actual.files - expected.files
    common_files = expected.files & actual.files
    mismatched_files: set[str] = set()
    diff_lines: list[str] = []

    for relative_path in sorted_lines(common_files):
        expected_file = expected_root / relative_path
        actual_file = actual_root / relative_path
        if read_text(expected_file, args.exact_bytes) != read_text(actual_file, args.exact_bytes):
            mismatched_files.add(relative_path)
            if len(mismatched_files) <= MAX_DIFF_FILES:
                diff_lines.extend(diff_for_file(expected_file, actual_file, relative_path, args.exact_bytes))
                diff_lines.append("")

    if missing_dirs:
        errors.append(("E101", f"Missing folders: {len(missing_dirs)}", missing_dirs, "Create the missing folder structure in the actual folder."))
    if extra_dirs:
        errors.append(("E102", f"Unexpected folders: {len(extra_dirs)}", extra_dirs, "Remove folders that should not be generated, or update the expected folder."))
    if missing_files:
        errors.append(("E201", f"Missing target files: {len(missing_files)}", missing_files, "Generate every expected .yml, .yaml, .cfg, and .xml file."))
    if extra_files:
        errors.append(("E202", f"Unexpected target files: {len(extra_files)}", extra_files, "Remove generated target files that are not in the expected folder."))
    if mismatched_files:
        errors.append(("E301", f"Content mismatch: {len(mismatched_files)} files", mismatched_files, "Fix source/template/config logic; do not patch generated files one by one."))

    ignored = expected.ignored_files | actual.ignored_files
    if ignored:
        warnings.append(("W001", f"Ignored non-target files: {len(ignored)}", ignored))

    if not args.no_config_score:
        config_score, config_examples = score_config_values(
            (project_root / args.config_dir).resolve(),
            project_root,
            report_dir,
            args.config_min_value_length,
        )
        if config_examples and config_score < 100:
            warnings.append(("W101", f"Config value sharing score: {config_score}/100", config_examples))

    write_report(report_dir, "missing_dirs.txt", sorted_lines(missing_dirs))
    write_report(report_dir, "extra_dirs.txt", sorted_lines(extra_dirs))
    write_report(report_dir, "missing_files.txt", sorted_lines(missing_files))
    write_report(report_dir, "extra_files.txt", sorted_lines(extra_files))
    write_report(report_dir, "content_mismatches.txt", sorted_lines(mismatched_files))
    write_report(report_dir, "content_diffs.txt", diff_lines or ["No content diffs."])
    write_report(report_dir, "ignored_files.txt", sorted_lines(ignored))
    write_standard_reports(report_dir, project_root, errors, warnings)

    print_summary(errors, warnings, report_dir, project_root)
    return 1 if errors else 0


def write_standard_reports(
    report_dir: Path,
    project_root: Path,
    errors: list[tuple[str, str, set[str], str]],
    warnings: list[tuple[str, str, set[str]]],
) -> None:
    status = "VALIDATION_FAILED" if errors else ("VALIDATION_PASSED_WITH_WARNINGS" if warnings else "VALIDATION_PASSED")
    write_report(report_dir, "summary.txt", [
        status,
        f"errors: {len(errors)}",
        f"warnings: {len(warnings)}",
        f"report_dir: {display_path(report_dir, project_root)}",
    ])
    error_lines = ["No errors."] if not errors else []
    for code, title, examples, fix in errors:
        error_lines.append(f"[{code}] {title}")
        error_lines.extend(f"- {item}" for item in sorted_lines(examples))
        error_lines.append(f"Fix: {fix}")
        error_lines.append("")
    warning_lines = ["No warnings."] if not warnings else []
    for code, title, examples in warnings:
        warning_lines.append(f"[{code}] {title}")
        warning_lines.extend(f"- {item}" for item in sorted_lines(examples))
        warning_lines.append("")
    write_report(report_dir, "errors.txt", error_lines)
    write_report(report_dir, "warnings.txt", warning_lines)


def print_summary(
    errors: list[tuple[str, str, set[str], str]],
    warnings: list[tuple[str, str, set[str]]],
    report_dir: Path,
    project_root: Path,
) -> None:
    status = "VALIDATION_FAILED" if errors else ("VALIDATION_PASSED_WITH_WARNINGS" if warnings else "VALIDATION_PASSED")
    print(status)
    print(f"errors: {len(errors)}")
    print(f"warnings: {len(warnings)}")
    print(f"report_dir: {display_path(report_dir, project_root)}")

    if errors:
        print()
        print("ERRORS:")
        for code, title, examples, fix in errors:
            print(f"[{code}] {title}")
            for line in format_examples(examples):
                print(line)
            print(f"Fix: {fix}")

    if warnings:
        print()
        print("WARNINGS:")
        for code, title, examples in warnings[:MAX_STDOUT_ITEMS]:
            print(f"[{code}] {title}")
            for line in format_examples(examples):
                print(line)


if __name__ == "__main__":
    sys.exit(main())
