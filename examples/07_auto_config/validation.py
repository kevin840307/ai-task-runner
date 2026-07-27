#!/usr/bin/env python3
"""Validate a generic multi-workflow auto-config renderer."""
from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


GENERIC_FORBIDDEN_SOURCE_TOKENS = ("ans",)
CENTRAL_LIST_KEYS = (
    "apps",
    "applications",
    "services",
    "versions",
    "images",
    "profiles",
    "phases",
)
RENDER_MATRIX_KEYS = ("render_targets", "outputs", "files")


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
    samples = find_samples(root)
    failures: list[str] = []

    checks = (
        check_required_files,
        check_renderer_source,
        check_templates,
        check_config_shape,
        check_rendered_output,
        check_config_mutation_changes_output,
    )
    for check in checks:
        try:
            check(root, samples)
        except AssertionError as error:
            failures.append(format_failure(check.__name__, str(error)))
        except Exception as error:
            failures.append(
                format_failure(
                    check.__name__,
                    f"crashed: {type(error).__name__}: {error}",
                )
            )

    if failures:
        print("VALIDATION FAILED: auto config renderer")
        print("Fix all items below, then rerun this validator.")
        print("Validator contract: exit code 0 means PASS; non-zero means FAIL.")
        for index, failure in enumerate(failures, 1):
            print(f"\n[{index}] {failure}")
        return 1

    print(f"PASS: auto config renderer ({len(samples)} samples)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--state-file")
    return parser.parse_args()


def format_failure(check_name: str, problem: str) -> str:
    return (
        f"Check: {check_name}\n"
        f"Problem: {problem}\n"
        "Expected fix: update rander.py, config YAML, or Template files so this "
        "check passes without hardcoding sample-specific answers."
    )


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


def check_required_files(root: Path, samples: list[Sample]) -> None:
    for path in (root / "rander.py", root / "config" / "values.yaml"):
        assert path.is_file(), f"missing required file: {relative(root, path)}"
        assert path.read_text(encoding="utf-8").strip(), (
            f"required file is empty: {relative(root, path)}"
        )

    for sample in samples:
        workflow_values = root / "config" / sample.workflow / "values.yaml"
        assert workflow_values.is_file(), (
            f"{sample_name(sample)} missing workflow values: "
            f"{relative(root, workflow_values)}"
        )
        assert workflow_values.read_text(encoding="utf-8").strip(), (
            f"{sample_name(sample)} workflow values is empty: "
            f"{relative(root, workflow_values)}"
        )

        alternatives = (
            (
                root / "config" / "phase" / f"{sample.target_family}.yaml",
                root / "config" / "phases" / f"{sample.target_family}.yaml",
            ),
            (
                root / "config" / sample.workflow / f"{sample.env}.yaml",
                root / "config" / sample.workflow / sample.target / f"{sample.env}.yaml",
            ),
        )
        for candidates in alternatives:
            existing = [path for path in candidates if path.is_file()]
            assert existing, (
                f"{sample_name(sample)} missing one of required config layers: "
                + " or ".join(relative(root, path) for path in candidates)
            )
            assert any(path.read_text(encoding="utf-8").strip() for path in existing), (
                f"{sample_name(sample)} required config layer is empty: "
                + " or ".join(relative(root, path) for path in existing)
            )


def check_renderer_source(root: Path, samples: list[Sample]) -> None:
    source = (root / "rander.py").read_text(encoding="utf-8")
    assert source.strip(), "rander.py is empty"
    ast.parse(source)
    assert "jinja2" in source.lower(), "rander.py must use Jinja2"

    lowered = source.lower()
    tokens = sorted(
        {token for sample in samples for token in forbidden_source_tokens(sample)},
        key=lambda value: (len(value), value),
    )
    for token in tokens:
        assert token.lower() not in lowered, (
            "rander.py appears to hardcode answer-specific token: "
            f"{token!r}"
        )


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
        value for value in scalar_strings(values) if is_specific_scalar_token(value)
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
    suffixes = {path.suffix.lower() for path in templates}
    assert suffixes & {".j2", ".jinja", ".jinja2", ".tpl", ".yml", ".yaml", ".xml"}, (
        "templates should represent the generated YAML/XML files"
    )


def check_config_shape(root: Path, samples: list[Sample]) -> None:
    config_root = root / "config"
    config_files = sorted(path for path in config_root.rglob("*.yaml") if path.is_file())
    assert config_files, "config has no YAML files"

    global_values = load_yaml(root / "config" / "values.yaml")
    global_keys = set(all_keys(global_values))
    assert global_keys & set(RENDER_MATRIX_KEYS), (
        "config/values.yaml should contain one central render target/output matrix"
    )
    assert any(key in global_keys for key in ("template", "templates", "template_map")), (
        "config/values.yaml should centralize template mapping"
    )
    assert len(global_keys & set(CENTRAL_LIST_KEYS)) >= 2, (
        "config/values.yaml should centralize shared app/version/profile lists"
    )

    repeated = repeated_tokens_across_files(config_files, samples)
    assert not repeated, (
        "common app/version/profile tokens are repeated across too many config files: "
        + ", ".join(repeated)
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


def check_config_mutation_changes_output(root: Path, samples: list[Sample]) -> None:
    for sample in samples:
        with tempfile.TemporaryDirectory(prefix="auto-config-mut-") as temp:
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
            candidate = mutate_config_scalar(copied, copied_sample)
            assert candidate is not None, (
                f"{sample_name(sample)} could not find a string config value "
                "that flows into generated values.yaml"
            )
            old_value, new_value = candidate

            output_root = copied / "mutation-output"
            run_renderer(copied, output_root, copied_sample)
            rendered_values = (
                output_root / sample.workflow / sample.target / sample.env / "values.yaml"
            ).read_text(encoding="utf-8")
            assert new_value in rendered_values and old_value not in rendered_values, (
                f"{sample_name(sample)} mutating a config value did not affect "
                "generated values.yaml; renderer may not be driven by config values"
            )


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


def mutate_config_scalar(root: Path, sample: Sample) -> tuple[str, str] | None:
    expected_values = (sample.expected_root / "values.yaml").read_text(encoding="utf-8")
    config_files = sorted(path for path in (root / "config").rglob("*.yaml") if path.is_file())
    for path in config_files:
        data = load_yaml(path)
        replacement = replace_first_matching_scalar(data, expected_values)
        if replacement is None:
            continue
        path.write_text(
            yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        return replacement
    return None


def replace_first_matching_scalar(data: Any, expected_text: str) -> tuple[str, str] | None:
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str) and is_mutation_candidate(value, expected_text):
                new_value = value + "-validator-mutated"
                data[key] = new_value
                return value, new_value
            result = replace_first_matching_scalar(value, expected_text)
            if result is not None:
                return result
    elif isinstance(data, list):
        for index, value in enumerate(data):
            if isinstance(value, str) and is_mutation_candidate(value, expected_text):
                new_value = value + "-validator-mutated"
                data[index] = new_value
                return value, new_value
            result = replace_first_matching_scalar(value, expected_text)
            if result is not None:
                return result
    return None


def is_mutation_candidate(value: str, expected_text: str) -> bool:
    stripped = value.strip()
    return (
        len(stripped) >= 4
        and "{{" not in stripped
        and "{%" not in stripped
        and stripped in expected_text
    )


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return {} if data is None else data


def all_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from all_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from all_keys(child)


def scalar_strings(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from scalar_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from scalar_strings(child)
    elif isinstance(value, str):
        yield value


def repeated_tokens_across_files(paths: Iterable[Path], samples: list[Sample]) -> list[str]:
    tokens = {
        value
        for sample in samples
        for value in scalar_strings(load_yaml(sample.expected_root / "values.yaml"))
        if is_repetition_candidate(value)
    }
    repeated: list[str] = []
    for token in tokens:
        owners = [
            path
            for path in paths
            if token.lower() in path.read_text(encoding="utf-8").lower()
        ]
        if len(owners) > 2:
            repeated.append(token)
    return repeated


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


def is_repetition_candidate(value: str) -> bool:
    stripped = value.strip()
    if len(stripped) < 2 or len(stripped) > 40:
        return False
    if "/" in stripped or "://" in stripped:
        return False
    if stripped.isdigit():
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
