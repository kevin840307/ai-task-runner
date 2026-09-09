import argparse
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

from ai_task_runner_validator import ValidatorReport


ROOT = Path(__file__).parent
MIN_COVERAGE = 80

FUNCTIONS = {
    "CheckLotStatus": [
        "CheckLotStatus.Execute",
    ],
}

FORBIDDEN_SQL = {
    "ANY": [
        "VALIDATION_RESULT",
    ],
    "INSERT": [
        "SCHEDULER_HISTORY",
    ],
    "UPDATE": [
        "SCHEDULER_HISTORY",
    ],
}


def cases(block):
    folder = ROOT / block
    found = sorted(folder.glob(f"{block}-SOP-*"))

    required = [
        ROOT / "Global/Create SOP.sql",
        ROOT / "Global/Create Condition.sql",
        ROOT / "Global/Create Action.sql",
        ROOT / "Global/Validation.sql",
        folder / f"{block}.vb",
    ]

    errors = [
        f"Missing: {x}"
        for x in required
        if not x.exists()
    ]

    if not found:
        errors.append(f"No {block}-SOP-*")

    for case in found:
        if not (case / "prepare.sql").exists():
            errors.append(f"{case.name}: prepare.sql missing")

    return found, errors


def sql_rules(cases):
    errors = []

    for case in cases:
        sql = (case / "prepare.sql").read_text(
            encoding="utf-8",
            errors="ignore",
        ).upper()

        for table in FORBIDDEN_SQL.get("ANY", []):
            if table.upper() in sql:
                errors.append(
                    f"{case.name}: forbidden table {table}"
                )

        for action in ("INSERT", "UPDATE", "DELETE"):
            for table in FORBIDDEN_SQL.get(action, []):
                if re.search(
                    rf"\b{action}\b.*?\b{re.escape(table.upper())}\b",
                    sql,
                    re.DOTALL,
                ):
                    errors.append(
                        f"{case.name}: forbidden {action} {table}"
                    )

    return errors


def results(block, cases):
    p = subprocess.run(
        ["python", "query_result.py", "--block", block],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    if p.returncode:
        return ["Cannot query execution result"]

    done = {
        x.strip().upper()
        for x in p.stdout.splitlines()
        if x.strip()
    }

    return [
        f"{case.name}: no execution result"
        for case in cases
        if case.name.upper() not in done
    ]


def coverage(block):
    targets = FUNCTIONS.get(block)

    if not targets:
        return [f"No function mapping: {block}"]

    p = subprocess.run(
        [
            "vstest.console.exe",
            "Scheduler.Tests.dll",
            '/collect:Code Coverage;Format=Cobertura',
        ],
        cwd=ROOT,
    )

    if p.returncode:
        return ["VS2022 coverage failed"]

    reports = list(ROOT.rglob("*.cobertura.xml"))

    if not reports:
        return ["Coverage report not found"]

    xml = ET.parse(
        max(reports, key=lambda x: x.stat().st_mtime)
    )

    errors = []

    for target in targets:
        cls, func = target.rsplit(".", 1)

        methods = [
            m
            for c in xml.findall(".//class")
            if c.get("name", "").endswith(cls)
            for m in c.findall("./methods/method")
            if m.get("name") == func
        ]

        if not methods:
            errors.append(f"{target}: not found")
            continue

        lines = [
            x
            for m in methods
            for x in m.findall("./lines/line")
        ]

        rate = (
            sum(int(x.get("hits", "0")) > 0 for x in lines)
            * 100 / len(lines)
            if lines else 0
        )

        print(f"{target}: {rate:.1f}%")

        if rate < MIN_COVERAGE:
            errors.append(
                f"{target}: {rate:.1f}% < {MIN_COVERAGE}%"
            )

    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--block", required=True)
    block = parser.parse_args().block

    report = ValidatorReport(ROOT, f"e2e-{block}")

    found, errors = cases(block)

    checks = [
        ("E001", "Test files invalid", errors),
        ("E002", "Forbidden SQL found", sql_rules(found) if not errors else []),
        ("E003", "Execution result missing", results(block, found) if not errors else []),
        ("E004", "Function coverage failed", coverage(block) if not errors else []),
    ]

    for code, message, items in checks:
        for item in items:
            report.error(code, message, [item])

    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())