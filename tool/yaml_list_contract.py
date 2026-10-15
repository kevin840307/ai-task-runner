#!/usr/bin/env python3
"""Validate/round-trip Task List YAML through runner.script's canonical parser."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runner.script import parse_yaml_script_text


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Validate Task List YAML")
    value.add_argument("--project-root", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    project = Path(args.project_root).expanduser().resolve()
    if not project.is_dir():
        print(json.dumps({"error": "project root does not exist"}))
        return 1
    try:
        import yaml
        request = json.load(sys.stdin)
        content = str(request.get("content") or "")
        raw = yaml.safe_load(content)
        normalized = parse_yaml_script_text(
            content,
            project / "task-list.yaml",
            allow_missing_files=bool(request.get("allow_missing_files", False)),
        )
        canonical = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)
        print(json.dumps({
            "raw": raw,
            "normalized": normalized,
            "canonical": canonical,
        }, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
