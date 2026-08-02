from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
EXPECTED = {
    "01_config_template_roundtrip",
    "02_structured_markdown_report",
    "03_csv_summary_cli",
    "04_ai_validator_bugfix",
    "05_yaml_release_pipeline",
    "06_yaml_data_migration_pipeline",
    "07_auto_config",
}


def test_example_inventory_and_launchers():
    found = {p.name for p in EXAMPLES.iterdir() if p.is_dir()}
    assert found == EXPECTED
    for name in EXPECTED:
        folder = EXAMPLES / name
        if name == "07_auto_config":
            assert (folder / "prompt.md").is_file()
            assert (folder / "validation.py").is_file()
            assert (folder / "ans").is_dir()
            continue
        assert (folder / "project").is_dir()
        assert (folder / "run_qwen.ps1").is_file()
        assert (folder / "run_opencode.ps1").is_file()


def test_example_python_files_compile():
    files = sorted(EXAMPLES.rglob("*.py"))
    assert files
    for path in files:
        subprocess.run(
            [sys.executable, "-m", "py_compile", str(path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )


def test_yaml_examples_have_valid_items_and_paths():
    for name in ("05_yaml_release_pipeline", "06_yaml_data_migration_pipeline"):
        path = EXAMPLES / name / "tasks.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(data, list) and len(data) == 3
        for item in data:
            assert isinstance(item.get("prompt"), str) and item["prompt"].strip()
            validator = item.get("validator")
            assert isinstance(validator, str) and validator.strip()
            if validator != "ai":
                assert (ROOT / validator).is_file()


def test_single_prompt_examples_are_not_precompleted():
    for name in (
        "01_config_template_roundtrip",
        "02_structured_markdown_report",
        "03_csv_summary_cli",
    ):
        folder = EXAMPLES / name
        validator = folder / "validator.py"
        result = subprocess.run(
            [
                sys.executable,
                str(validator),
                "--project-root",
                str(folder / "project"),
                "--state-file",
                str(folder / "unused-state.json"),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        assert result.returncode != 0, f"starter unexpectedly passed: {name}\n{result.stdout}"


def test_auto_config_example_is_not_precompleted():
    folder = EXAMPLES / "07_auto_config"
    result = subprocess.run(
        [
            sys.executable,
            str(folder / "validation.py"),
            "--project-root",
            str(folder),
            "--state-file",
            str(folder / "unused-state.json"),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    assert result.returncode != 0, f"starter unexpectedly passed: 07_auto_config\n{result.stdout}"


def test_yaml_file_validators_are_not_precompleted():
    for name in ("05_yaml_release_pipeline", "06_yaml_data_migration_pipeline"):
        folder = EXAMPLES / name
        for validator in sorted((folder / "validators").glob("*.py")):
            result = subprocess.run(
                [
                    sys.executable,
                    str(validator),
                    "--project-root",
                    str(folder / "project"),
                    "--state-file",
                    str(folder / "unused-state.json"),
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            assert result.returncode != 0, f"starter unexpectedly passed: {validator}\n{result.stdout}"
