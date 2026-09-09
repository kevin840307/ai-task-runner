import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "docs" / "validator_templates" / "external_command_validator.py"


def test_external_command_validator_copies_logs_and_reports_failure(tmp_path):
    log_dir = tmp_path / "tool-logs"
    log_dir.mkdir()
    fake_external = tmp_path / "fake_external.py"
    fake_external.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "import sys",
                "root = Path(sys.argv[1])",
                "log = root / 'tool-logs' / 'latest.log'",
                "log.write_text('external detail: missing generated file\\n', encoding='utf-8')",
                "print('external stdout summary')",
                "sys.exit(7)",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(VALIDATOR),
            "--project-root",
            str(tmp_path),
            "--state-file",
            str(tmp_path / ".ai-task-runner" / "state.json"),
            "--command",
            sys.executable,
            "--command",
            str(fake_external),
            "--command",
            str(tmp_path),
            "--log-dir",
            str(log_dir),
            "--log-glob",
            "*.log",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    report_dir = tmp_path / ".ai-task-runner" / "validator-reports" / "external-command"
    copied_log = report_dir / "external-logs" / "tool-logs" / "latest.log"

    assert result.returncode == 1
    assert "VALIDATION_FAILED" in result.stdout
    assert "[E101] External validator exited with code 7" in result.stdout
    assert "report_dir: .ai-task-runner/validator-reports/external-command" in result.stdout
    assert (report_dir / "external-command-output.txt").read_text(encoding="utf-8")
    assert "latest.log" in (report_dir / "logs-index.txt").read_text(encoding="utf-8")
    assert copied_log.read_text(encoding="utf-8") == "external detail: missing generated file\n"
