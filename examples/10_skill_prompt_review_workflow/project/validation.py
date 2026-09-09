from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from ai_task_runner_validator import ValidatorReport, parse_json
except ModuleNotFoundError:
    import importlib.util as _importlib_util
    from pathlib import Path as _HelperPath

    _helper_path = _HelperPath(__file__).with_name("ai_task_runner_validator.py")
    _spec = _importlib_util.spec_from_file_location("_atr_validator_helper", _helper_path)
    if _spec is None or _spec.loader is None:
        raise
    _helper = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_helper)
    ValidatorReport, parse_json = _helper.ValidatorReport, _helper.parse_json


ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "skill_runner.py"
EXPECTED_TOP_LEVEL = {
    ".ai-task-runner",
    ".ai-task-runner.yaml",
    "__pycache__",
    "ai_task_runner_validator.py",
    "blueprint.md",
    "prompt.md",
    "QWEN.md",
    "README.md",
    "README.zh-TW.md",
    "skill_runner.py",
    "validation.py",
}


def assert_file(path: Path) -> str:
    assert path.is_file(), f"{path.name} is missing"
    text = path.read_text(encoding="utf-8")
    assert text.strip(), f"{path.name} is empty"
    return text


def run_cli(lines: list[str]) -> dict:
    with tempfile.TemporaryDirectory(prefix="atr-skill-workflow-") as tmp:
        work = Path(tmp)
        input_file = work / "requests.txt"
        output_file = work / "nested" / "report.json"
        input_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(ENTRY),
                "--input",
                str(input_file),
                "--output",
                str(output_file),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode == 0, (
            f"CLI failed with exit code {result.returncode}\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert output_file.is_file(), "CLI did not create the requested nested output file"
        return parse_json(output_file.read_text(encoding="utf-8"), "report.json")


def assert_bad_input_fails() -> None:
    with tempfile.TemporaryDirectory(prefix="atr-skill-workflow-bad-") as tmp:
        work = Path(tmp)
        input_file = work / "requests.txt"
        output_file = work / "report.json"
        input_file.write_text("not-a-skill request\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(ENTRY),
                "--input",
                str(input_file),
                "--output",
                str(output_file),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode != 0, "Malformed input should fail with a non-zero exit code"
        assert "malformed" in result.stderr.lower() or "/skill" in result.stderr.lower()


def assert_no_unexpected_top_level_files() -> None:
    unexpected = sorted(
        path.name for path in ROOT.iterdir() if path.name not in EXPECTED_TOP_LEVEL
    )
    assert not unexpected, f"Unexpected project files or folders: {unexpected}"


def main() -> int:
    report = ValidatorReport(ROOT, "example-10-skill-prompt-review-workflow")
    try:
        assert_no_unexpected_top_level_files()
        blueprint = assert_file(ROOT / "blueprint.md")
        assert "skill_runner.py" in blueprint, "blueprint.md should name the CLI file"

        for name in ("README.md", "README.zh-TW.md"):
            readme = assert_file(ROOT / name)
            assert (
                "python skill_runner.py --input" in readme
            ), f"{name} should document CLI usage"
            assert "/skill-" in readme, f"{name} should include a /skill- input example"

        output = run_cli([
            "/skill-review check the plan",
            "",
            "/skill-design draw the interface",
            "/skill-review verify the output",
        ])
        expected = {
            "items": [
                {"skill": "skill-review", "request": "check the plan", "words": 3},
                {"skill": "skill-design", "request": "draw the interface", "words": 3},
                {"skill": "skill-review", "request": "verify the output", "words": 3},
            ],
            "summary": {
                "count": 3,
                "skills": ["skill-design", "skill-review"],
            },
        }
        assert output == expected, (
            "report.json mismatch\n"
            f"expected={json.dumps(expected, sort_keys=True)}\n"
            f"actual={json.dumps(output, sort_keys=True)}"
        )
        assert_bad_input_fails()
    except Exception as error:
        detail = str(error)
        report.error(
            "E001",
            "Skill prompt review workflow example is incomplete",
            [detail],
            fix=(
                "Fix only the concrete validation failure above and preserve valid existing "
                "work. Runtime requests.txt/report.json files are not project deliverables; "
                "remove them if the validator reports them as unexpected."
            ),
        )
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
