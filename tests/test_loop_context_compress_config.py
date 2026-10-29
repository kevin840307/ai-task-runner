from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_task_runner import parser
from runner.api import RunRequest
from runner.plugins.context_compression import ContextCompressionPlugin
from runner.script import load_yaml_script


def test_loop_context_compression_cli_defaults_off():
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])
    assert args.loop_context_compress is False
    assert args.loop_context_compress_threshold == 50.0


def test_loop_context_compression_cli_normalizes_to_runtime_config():
    args = parser().parse_args([
        "--goal", "x", "--validator", "ai",
        "--loop-context-compress",
        "--loop-context-compress-threshold", "65",
    ])
    request = RunRequest.from_namespace(args)
    config = request.normalized_config()
    assert config.plugins["context_compression"] == {
        "enabled": True,
        "threshold": 65.0,
    }


def test_loop_context_compression_threshold_is_bounded():
    with pytest.raises(ValueError, match="between 0 and 100"):
        RunRequest(
            goal="x",
            validator="ai",
            plugins={
                "context_compression": {
                    "enabled": True,
                    "threshold": 101,
                }
            },
        ).validate()


def test_yaml_item_accepts_loop_context_compression(tmp_path: Path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: x\n"
        "  validator: ai\n"
        "  loop_context_compress: true\n"
        "  loop_context_compress_threshold: 60\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    assert item["plugins"]["context_compression"] == {
        "enabled": True,
        "threshold": 60,
    }


def test_generic_plugin_mapping_uses_the_same_validation(tmp_path: Path):
    script = tmp_path / "tasks.yaml"
    script.write_text(
        "- prompt: x\n"
        "  validator: ai\n"
        "  plugins:\n"
        "    context_compression:\n"
        "      enabled: true\n"
        "      threshold: 70\n",
        encoding="utf-8",
    )
    item = load_yaml_script(script)[0]
    config = RunRequest(
        goal="x",
        validator="ai",
        plugins=item["plugins"],
    ).normalized_config()
    assert config.plugins["context_compression"]["threshold"] == 70.0



class _ContextClient:
    def __init__(self, *, usage=80.0, compression="compressed", snapshot="context snapshot"):
        self.session_id = "session-current"
        self.usage = usage
        self.compression = compression
        self.snapshot = snapshot
        self.snapshots = []
        self.compressions = []

    def context_snapshot(self, session):
        self.snapshots.append(session)
        if isinstance(self.snapshot, BaseException):
            raise self.snapshot
        return self.snapshot

    def context_usage_percent(self, snapshot):
        if snapshot.startswith("ERROR:"):
            return None
        return self.usage

    def compress_session(self, session):
        self.compressions.append(session)
        if isinstance(self.compression, BaseException):
            raise self.compression
        return self.compression


def _context_plugin(*, enabled=True, threshold=50.0):
    return ContextCompressionPlugin(
        SimpleNamespace(
            plugins={
                "context_compression": {
                    "enabled": enabled,
                    "threshold": threshold,
                }
            }
        )
    )


def _loop_error(*, session_id="session-error"):
    return SimpleNamespace(
        session_id=session_id,
        diagnostics={"loop_type": "tool_loop"},
    )


def test_loop_context_compression_runtime_compresses_loop_session_above_threshold():
    plugin = _context_plugin(enabled=True, threshold=50)
    client = _ContextClient(usage=82.5, compression="compressed 82.5% -> 31%")
    error = _loop_error()

    plugin.model_error(client, error)

    assert client.snapshots == ["session-error"]
    assert client.compressions == ["session-error"]
    assert error.diagnostics["context_snapshot"] == "context snapshot"
    assert error.diagnostics["context_used_percent"] == 82.5
    assert error.diagnostics["context_compress_enabled"] is True
    assert error.diagnostics["context_compress_threshold"] == 50.0
    assert error.diagnostics["context_compression"] == "compressed 82.5% -> 31%"
    assert error.diagnostics["context_compress_status"] == "done"


@pytest.mark.parametrize(
    ("enabled", "usage", "reason"),
    [
        (False, 90.0, "disabled"),
        (True, 49.9, "below_threshold"),
    ],
)
def test_loop_context_compression_runtime_skips_without_compressing(
    enabled, usage, reason
):
    plugin = _context_plugin(enabled=enabled, threshold=50)
    client = _ContextClient(usage=usage)
    error = _loop_error()

    plugin.model_error(client, error)

    assert client.compressions == []
    assert error.diagnostics["context_compress_status"] == "skipped"
    assert error.diagnostics["context_compress_reason"] == reason


def test_loop_context_compression_runtime_skips_when_usage_is_unknown():
    plugin = _context_plugin()
    client = _ContextClient(usage=None)
    error = _loop_error()

    plugin.model_error(client, error)

    assert client.compressions == []
    assert error.diagnostics["context_compress_status"] == "skipped"
    assert error.diagnostics["context_compress_reason"] == "context_usage_unknown"


def test_loop_context_compression_runtime_diagnostics_are_fail_soft():
    plugin = _context_plugin()
    snapshot_client = _ContextClient(snapshot=RuntimeError("snapshot unavailable"))
    snapshot_error = _loop_error()
    plugin.model_error(snapshot_client, snapshot_error)

    assert snapshot_client.compressions == []
    assert snapshot_error.diagnostics["context_snapshot"].startswith(
        "ERROR: RuntimeError: snapshot unavailable"
    )
    assert snapshot_error.diagnostics["context_compress_status"] == "skipped"
    assert snapshot_error.diagnostics["context_compress_reason"] == "context_usage_unknown"

    compression_client = _ContextClient(
        usage=99,
        compression=RuntimeError("compression unavailable"),
    )
    compression_error = _loop_error()
    plugin.model_error(compression_client, compression_error)

    assert compression_client.compressions == ["session-error"]
    assert compression_error.diagnostics["context_compression"].startswith(
        "ERROR: RuntimeError: compression unavailable"
    )
    assert compression_error.diagnostics["context_compress_status"] == "failed"


def test_loop_context_compression_runtime_ignores_non_loop_or_sessionless_errors():
    plugin = _context_plugin()
    client = _ContextClient()

    non_loop = SimpleNamespace(session_id="session-error", diagnostics={})
    plugin.model_error(client, non_loop)
    assert non_loop.diagnostics == {}

    client.session_id = ""
    no_session = _loop_error(session_id="")
    plugin.model_error(client, no_session)
    assert no_session.diagnostics == {"loop_type": "tool_loop"}
    assert client.snapshots == []
