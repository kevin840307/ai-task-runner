from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_support_is_compatibility_facade_not_project_guard_or_model_retry_owner():
    support = (ROOT / "runner" / "support.py").read_text(encoding="utf-8")
    project_guard = (ROOT / "runner" / "project_guard.py").read_text(encoding="utf-8")
    model_call = (ROOT / "runner" / "model_call.py").read_text(encoding="utf-8")
    validation = (ROOT / "runner" / "validation.py").read_text(encoding="utf-8")
    assert "def snapshot(" not in support
    assert "def readonly_project_call(" not in support
    assert "def retry_model_call(" not in support
    assert "def snapshot(" in project_guard
    assert "def readonly_project_call(" in project_guard
    assert "def retry_model_call(" in model_call
    assert "def run_file_validator(" in validation

def test_internal_modules_use_responsibility_modules_directly():
    core = (ROOT / "runner" / "core.py").read_text(encoding="utf-8")
    planning = (ROOT / "runner" / "planning.py").read_text(encoding="utf-8")
    reviewing = (ROOT / "runner" / "reviewing.py").read_text(encoding="utf-8")
    validation = (ROOT / "runner" / "validation.py").read_text(encoding="utf-8")
    assert "from .project_guard import (" in core
    assert "from .model_call import retry_model_call" in core
    assert "from .validation import run_ai_validator, run_file_validator" in core
    assert "from .model_call import recover_structured_output, retry_model_call" in planning
    assert "from .project_guard import readonly_ask" in planning
    assert "from .model_call import recover_structured_output, retry_model_call" in reviewing
    assert "from .project_guard import readonly_ask" in reviewing
    assert "from .process_control import run_process" in validation
