from pathlib import Path

import pytest

from ai_task_runner import parser
from runner.api import RunRequest
from runner.script_runner import load_yaml_script


def test_loop_context_compression_cli_defaults_off():
    args = parser().parse_args(["--goal", "x", "--validator", "ai"])
    assert args.loop_context_compress is False
    assert args.loop_context_compress_threshold == 50.0


def test_loop_context_compression_cli_round_trips_to_request():
    args = parser().parse_args([
        "--goal", "x", "--validator", "ai",
        "--loop-context-compress",
        "--loop-context-compress-threshold", "65",
    ])
    request = RunRequest.from_namespace(args)
    request.validate()
    namespace = request.to_namespace()
    assert namespace.loop_context_compress is True
    assert namespace.loop_context_compress_threshold == 65.0


def test_loop_context_compression_threshold_is_bounded():
    with pytest.raises(ValueError, match="between 0 and 100"):
        RunRequest(
            goal="x",
            validator="ai",
            loop_context_compress_threshold=101,
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
    assert item["loop_context_compress"] is True
    assert item["loop_context_compress_threshold"] == 60.0
