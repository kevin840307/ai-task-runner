#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


EXPECTED = "Qwen smoke test completed.\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()

    target = Path(args.project_root) / "hello.txt"
    if not target.is_file():
        print("missing hello.txt")
        return 1

    actual = target.read_text(encoding="utf-8")
    if actual != EXPECTED:
        print("unexpected hello.txt content")
        print(repr(actual))
        return 1

    print("PASS: hello.txt content matches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
