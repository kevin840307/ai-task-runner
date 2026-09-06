from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_environment_check_json_contract_is_machine_readable() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tool" / "environment_check.py"), "--repo-root", str(ROOT), "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )
    # Optional backends may warn, but required local Runner checks must pass in tests.
    assert result.returncode == 0, result.stderr or result.stdout
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["status"] in {"pass", "warn"}
    names = {row["name"] for row in data["checks"]}
    assert {"Python", "PyYAML", "Jinja2", "Runner entrypoint", "Workflow dry-run", "Default workflow"} <= names
