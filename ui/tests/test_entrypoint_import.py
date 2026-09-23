from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_direct_ui_main_imports_repo_root_shared_modules(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, str(root / "ui" / "main.py"), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "AI Task Runner local UI" in result.stdout
