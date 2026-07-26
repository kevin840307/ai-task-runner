#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def score_document(text: str, data: dict) -> tuple[int, list[str]]:
    score = 0
    issues: list[str] = []
    lines = text.splitlines()
    h1 = [line for line in lines if line.startswith("# ")]
    h2 = [line for line in lines if line.startswith("## ")]
    expected_h2 = [
        "## Overview",
        "## Complexity Table",
        "## Worked Example",
        "## Selection Guide",
    ]
    if h1 == ["# Sorting Guide"]:
        score += 15
    else:
        issues.append(f"invalid H1: {h1}")
    if h2 == expected_h2:
        score += 20
    else:
        issues.append(f"invalid H2 order: {h2}")
    if "| Algorithm | Best | Average | Stable |" in text and "|---|---|---|---|" in text:
        score += 15
    else:
        issues.append("missing exact complexity table header")
    for item in data["algorithms"]:
        row = f"| {item['name']} | {item['best']} | {item['average']} | {item['stable']} |"
        if text.count(row) == 1:
            score += 7
        else:
            issues.append(f"missing or duplicated row: {row}")
    if "[5, 1, 3, 1]" in text and "[1, 1, 3, 5]" in text:
        score += 12
    else:
        issues.append("missing worked example input/output")
    guide = text.split("## Selection Guide", 1)[-1]
    bullets = [line for line in guide.splitlines() if re.match(r"^- ", line)]
    if len(bullets) >= 3:
        score += 10
    else:
        issues.append("selection guide needs at least three bullets")
    if len([line for line in lines if line.strip()]) <= 80:
        score += 8
    else:
        issues.append("document is not concise")
    return score, issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    root = Path(args.project_root)
    data = json.loads((root / "input" / "sorting_notes.json").read_text(encoding="utf-8"))
    path = root / "docs" / "sorting_guide.md"
    if not path.is_file():
        print("Missing docs/sorting_guide.md")
        return 1
    score, issues = score_document(path.read_text(encoding="utf-8"), data)
    print(f"score={score}/100")
    if score < 90:
        print("\n".join(issues))
        return 1
    print("PASS: sorting guide markdown")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
