from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_qwen_live_reliability_imports_from_tool_cwd():
    code = "import runpy; runpy.run_path('qwen_live_reliability.py', run_name='tool_import_probe')"
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT / "tool", capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr

def test_workflow_dryrun_help_from_tool_cwd():
    p = subprocess.run([sys.executable, "workflow_dryrun.py", "--help"], cwd=ROOT / "tool", capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
