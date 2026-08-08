#!/usr/bin/env python3
"""Validate a generic multi-workflow auto-config renderer."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from validator_interface import ValidatorReport


GENERIC_FORBIDDEN_SOURCE_TOKENS = ("ans",)
GENERIC_ALLOWED_SOURCE_TOKENS = {
    "config",
    "configs",
    "data",
    "default",
    "defaults",
    "env",
    "environment",
    "file",
    "files",
    "id",
    "matrix",
    "name",
    "output",
    "outputs",
    "path",
    "paths",
    "root",
    "target",
    "template",
    "templates",
    "value",
    "values",
    "workflow",
}
ANS_MANIFEST_SHA256 = "67ee2f09b54156e0c356142482f7657e05b8095ebffadf27da0048841dcd61ac"
MAX_RENDERER_LINES = 500


@dataclass(frozen=True)
class Sample:
    workflow: str
    target: str
    target_family: str
    env: str
    expected_root: Path


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    report = ValidatorReport(root, "auto-config")
    try:
        samples = find_samples(root)
    except AssertionError as error:
        report.error(
            "E000",
            "Sample discovery failed",
            problem_excerpt(str(error)),
            expected_fix(),
            "sample-discovery.txt",
            report_lines("find_samples", str(error)),
        )
        return report.finish()

    checks = (
        check_ans_fixture_unchanged,
        check_required_files,
        check_renderer_source,
        check_templates,
        check_deep_merge_semantics,
        check_rendered_output,
    )
    for index, check in enumerate(checks, 1):
        try:
            check(root, samples)
        except AssertionError as error:
            problem = str(error)
            report.error(
                f"E{index:03d}",
                f"{check.__name__} failed",
                problem_excerpt(problem),
                expected_fix(),
                f"{check.__name__}.txt",
                report_lines(check.__name__, problem),
            )
        except Exception as error:
            problem = f"crashed: {type(error).__name__}: {error}"
            report.error(
                f"E{index:03d}",
                f"{check.__name__} crashed",
                problem_excerpt(problem),
                expected_fix(),
                f"{check.__name__}.txt",
                report_lines(check.__name__, problem),
            )

    return report.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--state-file")
    return parser.parse_args()


def expected_fix() -> str:
    return (
        "Update rander.py, config YAML, or Template files so this check passes "
        "without hardcoding sample-specific answers."
    )


def problem_excerpt(problem: str, limit: int = 8, line_limit: int = 360) -> list[str]:
    lines = [line.strip() for line in problem.splitlines() if line.strip()]
    lines = [
        line if len(line) <= line_limit else line[:line_limit] + "... [truncated; see Full report]"
        for line in lines
    ]
    if len(lines) <= limit:
        return lines
    return lines[:limit] + [f"... {len(lines) - limit} more lines in Full report"]


def report_lines(check_name: str, problem: str) -> list[str]:
    return [
        f"Check: {check_name}",
        "Problem:",
        problem,
        "",
        f"Expected fix: {expected_fix()}",
    ]


def find_samples(root: Path) -> list[Sample]:
    ans_root = root / "ans"
    assert ans_root.is_dir(), "ans directory is missing"
    candidates = sorted(path.parent for path in ans_root.rglob("values.yaml"))
    assert candidates, "ans must contain at least one sample values.yaml"

    samples: list[Sample] = []
    for expected_root in candidates:
        parts = expected_root.relative_to(ans_root).parts
        if len(parts) < 3:
            continue
        workflow, target, env = parts[:3]
        if not any(path.is_file() for path in expected_root.rglob("*")):
            continue
        samples.append(
            Sample(
                workflow=workflow,
                target=target,
                target_family=target.split("-", 1)[0],
                env=env,
                expected_root=expected_root,
            )
        )
    assert samples, "ans sample root must be ans/<workflow>/<target>/<env>"
    return samples


def check_ans_fixture_unchanged(root: Path, samples: list[Sample]) -> None:
    del samples
    manifest_path = root / "ans_manifest.json"
    assert manifest_path.is_file(), "ans_manifest.json is missing"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    actual_manifest_hash = hashlib.sha256(
        manifest_text.encode("utf-8")
    ).hexdigest()
    assert actual_manifest_hash == ANS_MANIFEST_SHA256, (
        "ans_manifest.json was modified. The answer fixture is read-only; "
        "restore the manifest instead of changing expected answers."
    )
    expected = json.loads(manifest_text)
    assert isinstance(expected, dict), "ans_manifest.json must be a JSON object"

    ans_root = root / "ans"
    actual: dict[str, dict[str, Any]] = {}
    for path in sorted(ans_root.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(ans_root).as_posix()
        data = path.read_bytes()
        actual[relative_path] = {
            "sha256": hashlib.sha256(data).hexdigest(),
            "size": len(data),
        }

    expected_paths = set(expected)
    actual_paths = set(actual)
    missing = sorted(expected_paths - actual_paths)
    extra = sorted(actual_paths - expected_paths)
    changed = sorted(
        path
        for path in expected_paths & actual_paths
        if expected[path] != actual[path]
    )
    assert not (missing or extra or changed), (
        "ans fixture changed; ans/ is read-only validation data. "
        f"missing={missing[:20]}, extra={extra[:20]}, changed={changed[:20]}"
    )


def check_required_files(root: Path, samples: list[Sample]) -> None:
    del samples
    for path in (root / "rander.py", root / "config" / "values.yaml"):
        assert path.is_file(), f"missing required file: {relative(root, path)}"
        assert path.read_text(encoding="utf-8").strip(), (
            f"required file is empty: {relative(root, path)}"
        )

def check_renderer_source(root: Path, samples: list[Sample]) -> None:
    renderer = root / "rander.py"
    source = renderer.read_text(encoding="utf-8")
    assert source.strip(), "rander.py is empty"
    line_count = len(source.splitlines())
    assert line_count <= MAX_RENDERER_LINES, (
        f"rander.py is too large ({line_count} lines). Keep the generic renderer "
        f"within {MAX_RENDERER_LINES} lines; move data to YAML/Jinja2, not Python."
    )
    tree = ast.parse(source)
    assert "jinja2" in source.lower(), "rander.py must use Jinja2"
    local_imports = local_python_import_hits(root, tree)
    assert not local_imports, (
        "rander.py must not import local project Python modules. Keep renderer "
        "logic in rander.py and keep data in YAML/Jinja2 so hardcoded logic "
        "cannot be hidden in helper Python files. Imports: "
        + ", ".join(local_imports[:20])
    )
    local_references = local_python_reference_hits(root, tree)
    assert not local_references, (
        "rander.py must not reference other local project Python files. Do not "
        "call, read, or delegate to self-written Python to bypass the generic "
        "renderer contract. References: "
        + ", ".join(local_references[:20])
    )

    specific_tokens = {
        token.lower()
        for sample in samples
        for token in forbidden_source_tokens(sample)
    }
    literal_hits = hardcoded_literal_hits(source, specific_tokens)
    assert not literal_hits, (
        "rander.py contains sample-derived literal names. Do not branch or loop "
        "over specific app/workflow/target/env/version/profile/file names in "
        "Python; move those names to config values or a central render matrix. "
        "Examples: " + "; ".join(literal_hits[:12])
    )



def local_python_import_hits(root: Path, tree: ast.AST) -> list[str]:
    local_modules = local_python_module_names(root)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".", 1)[0]
                if top_level in local_modules:
                    hits.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                hits.append("." * node.level + (node.module or ""))
                continue
            top_level = (node.module or "").split(".", 1)[0]
            if top_level in local_modules:
                hits.append(node.module or "")
    return sorted(set(hits))


def local_python_reference_hits(root: Path, tree: ast.AST) -> list[str]:
    names = local_python_file_names(root)
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        lowered = node.value.lower().replace("\\", "/")
        for name in names:
            if name in lowered:
                hits.append(name)
    return sorted(set(hits))


def local_python_module_names(root: Path) -> set[str]:
    modules = {
        path.stem
        for path in root.glob("*.py")
        if path.name != "rander.py"
    }
    modules.update(
        path.parent.name
        for path in root.rglob("__init__.py")
        if not ignored_python_path(root, path)
    )
    return modules


def local_python_file_names(root: Path) -> set[str]:
    return {
        path.relative_to(root).as_posix().lower()
        for path in root.rglob("*.py")
        if path.name != "rander.py" and not ignored_python_path(root, path)
    } | {
        path.name.lower()
        for path in root.rglob("*.py")
        if path.name != "rander.py" and not ignored_python_path(root, path)
    }


def ignored_python_path(root: Path, path: Path) -> bool:
    ignored_parts = {".ai-task-runner", "__pycache__", ".pytest_cache", "output"}
    try:
        parts = set(path.relative_to(root).parts)
    except ValueError:
        return True
    return bool(parts & ignored_parts)


def hardcoded_literal_hits(source: str, forbidden_lower: set[str]) -> list[str]:
    hits: list[str] = []
    tree = ast.parse(source)
    lines = source.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            token = node.value.strip()
            if token.lower() in forbidden_lower:
                hits.append(format_literal_hit(token, node.lineno, lines))
    return sorted(set(hits))


def format_literal_hit(token: str, lineno: int, lines: list[str]) -> str:
    line = lines[lineno - 1].strip() if 0 < lineno <= len(lines) else ""
    return f"line {lineno}: {token!r} in {line[:120]}"


def forbidden_source_tokens(sample: Sample) -> list[str]:
    values = load_yaml(sample.expected_root / "values.yaml")
    tokens: set[str] = set(GENERIC_FORBIDDEN_SOURCE_TOKENS)
    tokens.update({sample.workflow, sample.target, sample.env})
    for path in sample.expected_root.rglob("*"):
        if not path.is_file() or path.name == "values.yaml":
            continue
        tokens.add(path.name)
        for part in path.relative_to(sample.expected_root).parts[:-1]:
            if not looks_generic_path_part(part):
                tokens.add(part)
    tokens.update(
        value
        for value in scalar_values(values)
        if is_specific_scalar_token(value)
        and value.lower() not in GENERIC_ALLOWED_SOURCE_TOKENS
    )
    return sorted(tokens, key=lambda value: (len(value), value))


def check_templates(root: Path, samples: list[Sample]) -> None:
    template_root = root / "Template"
    assert template_root.is_dir(), "Template directory is missing"
    templates = [path for path in template_root.rglob("*") if path.is_file()]
    assert templates, "Template directory contains no template files"
    assert any(
        has_placeholder(path.read_text(encoding="utf-8")) for path in templates
    ), "templates must contain Jinja2 placeholders"
def check_deep_merge_semantics(root: Path, samples: list[Sample]) -> None:
    sample = samples[0]
    with tempfile.TemporaryDirectory(prefix="auto-config-merge-") as temp:
        copied = Path(temp) / "project"
        shutil.copytree(
            root,
            copied,
            ignore=shutil.ignore_patterns(".ai-task-runner", "output", "__pycache__"),
        )
        copied_sample = Sample(
            sample.workflow,
            sample.target,
            sample.target_family,
            sample.env,
            copied / sample.expected_root.relative_to(root),
        )
        write_merge_probe(copied / "config" / "values.yaml", {
            "__merge_probe__": {
                "kept": "global-kept",
                "nested": {"a": "global-a", "b": "global-b"},
                "list_value": ["global-list"],
                "empty_dict_value": {"old": "must-be-replaced"},
                "null_value": {"old": "must-be-replaced"},
            }
        })
        write_merge_probe(copied / "config" / sample.workflow / "values.yaml", {
            "__merge_probe__": {
                "nested": {"b": "workflow-b", "c": "workflow-c"},
                "list_value": ["workflow-list"],
                "empty_dict_value": {},
                "null_value": None,
            }
        })
        output_root = copied / "merge-output"
        run_renderer(copied, output_root, copied_sample)
        rendered = load_yaml(
            output_root / sample.workflow / sample.target / sample.env / "values.yaml"
        )
        probe = rendered.get("__merge_probe__") if isinstance(rendered, dict) else None
        assert isinstance(probe, dict), (
            "merged config values should flow into generated values.yaml, including "
            "the neutral __merge_probe__ test key"
        )
        assert probe.get("kept") == "global-kept", (
            "deep merge must preserve earlier dictionary keys when later layers "
            "do not replace them"
        )
        assert probe.get("nested") == {
            "a": "global-a",
            "b": "workflow-b",
            "c": "workflow-c",
        }, "non-empty dictionaries must deep merge with later values overriding keys"
        assert probe.get("list_value") == ["workflow-list"], (
            "lists from later layers must replace earlier lists, not concatenate or merge"
        )
        assert probe.get("empty_dict_value") == {}, (
            "an empty dictionary in a later layer is an explicit replacement"
        )
        assert probe.get("null_value") is None, (
            "null/None in a later layer is an explicit replacement"
        )


def write_merge_probe(path: Path, values: dict[str, Any]) -> None:
    data = load_yaml(path) if path.is_file() else {}
    assert isinstance(data, dict), f"config file must be a YAML object: {path}"
    data.update(values)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def check_rendered_output(root: Path, samples: list[Sample]) -> None:
    output_root = root / "output"
    for sample in samples:
        target = output_root / sample.workflow / sample.target / sample.env
        if target.exists():
            shutil.rmtree(target)
        run_renderer(root, output_root, sample)
        assert target.is_dir(), (
            f"{sample_name(sample)} renderer did not create output root: "
            f"{relative(root, target)}"
        )
        compare_trees(sample.expected_root, target, sample)


def run_renderer(root: Path, output_root: Path, sample: Sample) -> None:
    command = [
        sys.executable,
        "rander.py",
        "--workflow",
        sample.workflow,
        "--fab",
        sample.target,
        "--env",
        sample.env,
        "--output",
        str(output_root),
    ]
    result = subprocess.run(
        command,
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"{sample_name(sample)} renderer command failed:\n"
        + " ".join(command)
        + "\n"
        + result.stdout[-4000:]
    )


def compare_trees(expected: Path, actual: Path, sample: Sample) -> None:
    expected_files = sorted(
        path.relative_to(expected) for path in expected.rglob("*") if path.is_file()
    )
    actual_files = sorted(
        path.relative_to(actual) for path in actual.rglob("*") if path.is_file()
    )
    assert actual_files == expected_files, (
        f"{sample_name(sample)} output file tree mismatch\n"
        f"missing: {sorted(set(expected_files) - set(actual_files))}\n"
        f"extra: {sorted(set(actual_files) - set(expected_files))}"
    )
    for relative_path in expected_files:
        assert (actual / relative_path).read_bytes() == (
            expected / relative_path
        ).read_bytes(), f"{sample_name(sample)} content mismatch: {relative_path.as_posix()}"


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return {} if data is None else data


def scalar_values(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for child in value.values():
            yield from scalar_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_values(child)
    elif isinstance(value, str):
        yield value


def looks_generic_path_part(value: str) -> bool:
    return value.lower() in {
        "config",
        "conf",
        "templates",
        "template",
        "output",
        "outputs",
    }


def is_specific_scalar_token(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) < 4:
        return False
    if stripped.lower() in {"true", "false", "none", "null"}:
        return False
    return any(character.isalpha() for character in stripped)


def has_placeholder(text: str) -> bool:
    return ("{{" in text and "}}" in text) or ("{%" in text and "%}" in text)


def sample_name(sample: Sample) -> str:
    return f"{sample.workflow}/{sample.target}/{sample.env}"


def relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
