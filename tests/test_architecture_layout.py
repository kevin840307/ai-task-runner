from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_support_is_compatibility_facade_not_project_guard_or_model_retry_owner():
    support = (ROOT / "runner" / "support.py").read_text(encoding="utf-8")
    project_guard = (ROOT / "runner" / "project_guard.py").read_text(encoding="utf-8")
    model_call = (ROOT / "runner" / "model_call.py").read_text(encoding="utf-8")
    validation = (ROOT / "runner" / "validation.py").read_text(encoding="utf-8")
    file_validation = (ROOT / "runner" / "file_validation.py").read_text(
        encoding="utf-8"
    )
    assert "def snapshot(" not in support
    assert "def readonly_project_call(" not in support
    assert "def retry_model_call(" not in support
    assert "def snapshot(" in project_guard
    assert "def readonly_project_call(" in project_guard
    assert "def retry_model_call(" in model_call
    assert "def run_file_validator(" not in validation
    assert "def run_file_validator(" in file_validation


def test_internal_modules_use_responsibility_modules_directly():
    core = (ROOT / "runner" / "core.py").read_text(encoding="utf-8")
    planning = (ROOT / "runner" / "planning.py").read_text(encoding="utf-8")
    reviewing = (ROOT / "runner" / "reviewing.py").read_text(encoding="utf-8")
    ai_validation = (ROOT / "runner" / "ai_validation.py").read_text(
        encoding="utf-8"
    )
    file_validation = (ROOT / "runner" / "file_validation.py").read_text(
        encoding="utf-8"
    )
    assert "from .project_guard import (" in core
    assert "from .model_call import retry_model_call" in core
    assert "from .ai_validation import run_ai_validator" in core
    assert "from .file_validation import run_file_validator" in core
    assert "from .state_store import StateStore" in core
    assert "from .model_call import recover_structured_output, retry_model_call" in planning
    assert "from .project_guard import readonly_ask" in planning
    assert "from .model_call import recover_structured_output, retry_model_call" in reviewing
    assert "from .project_guard import readonly_ask" in reviewing
    assert "from .process_control import run_process" in file_validation
    assert "def run_ai_validator(" in ai_validation


def test_validation_facade_keeps_existing_import_contract():
    from runner import ai_validation, file_validation, validation

    assert validation.run_ai_validator is ai_validation.run_ai_validator
    assert (
        validation.format_ai_validator_runs
        is ai_validation.format_ai_validator_runs
    )
    assert validation.run_file_validator is file_validation.run_file_validator
    assert (
        validation.clear_validator_reports
        is file_validation.clear_validator_reports
    )
