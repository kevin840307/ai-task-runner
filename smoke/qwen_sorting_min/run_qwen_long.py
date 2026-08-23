#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runner.runtime.process_control import run_process


def main() -> int:
    root = Path(__file__).resolve().parent / "project"
    prompt = (Path(__file__).resolve().parent / "prompt.txt").read_text(
        encoding="utf-8"
    )
    command = [
        "qwen.cmd",
        "--approval-mode",
        "yolo",
        "--output-format",
        "json",
        "--max-tool-calls",
        "6",
        "-p",
        prompt,
    ]
    result = run_process(command, root, timeout=120)
    print(f"QWEN_RETURN_CODE={result.return_code}")
    print(f"QWEN_TIMED_OUT={result.timed_out}")
    print(result.output[-12000:])
    return 124 if result.timed_out else result.return_code


if __name__ == "__main__":
    raise SystemExit(main())
