from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from ai_task_runner_validator import ValidatorReport, parse_json


ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "pipeline_cli.py"


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def run_case(name: str, config: dict, build_input, expected_records, expected_summary, expected_errors):
    case = Path(tempfile.mkdtemp(prefix=f"atr-{name}-"))
    try:
        inp = case / "input"
        out = case / "output"
        cfg = case / "config.yaml"
        inp.mkdir()
        build_input(inp)
        write_yaml(cfg, config)

        cmd = [sys.executable, str(ENTRY), "--input", str(inp), "--config", str(cfg), "--output", str(out)]
        p = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert p.returncode == 0, (
            f"{name}: command failed\n"
            f"command={' '.join(cmd)}\nstdout={p.stdout!r}\nstderr={p.stderr!r}"
        )

        expected_names = {"records.json", "summary.json", "errors.json"}
        actual_names = {p.name for p in out.iterdir()} if out.exists() else set()
        assert actual_names == expected_names, (
            f"{name}: output files mismatch; expected={sorted(expected_names)}, actual={sorted(actual_names)}"
        )

        records = parse_json((out / "records.json").read_text(encoding="utf-8"), f"{name} records.json")
        summary = parse_json((out / "summary.json").read_text(encoding="utf-8"), f"{name} summary.json")
        errors = parse_json((out / "errors.json").read_text(encoding="utf-8"), f"{name} errors.json")

        assert records == expected_records, f"{name}: records mismatch\nexpected={expected_records!r}\nactual={records!r}"
        assert summary == expected_summary, f"{name}: summary mismatch\nexpected={expected_summary!r}\nactual={summary!r}"
        def normalized(items):
            rows = []
            for item in items:
                row = {
                    "file": item.get("file"),
                    "type": item.get("type"),
                    "message": str(item.get("message", "")).lower(),
                }
                if item.get("type") == "record":
                    row["index"] = item.get("index")
                rows.append(row)
            return sorted(
                rows,
                key=lambda e: (e["file"] or "", e["type"] or "", e.get("index", -1)),
            )

        actual_errors = normalized(errors)
        wanted_errors = normalized(expected_errors)
        assert len(actual_errors) == len(wanted_errors), (
            f"{name}: error count mismatch; expected={len(wanted_errors)}, actual={len(actual_errors)}"
        )
        for expected, actual in zip(wanted_errors, actual_errors):
            for field in ("file", "type", "index"):
                if field in expected:
                    assert actual.get(field) == expected.get(field), (
                        f"{name}: error {field} mismatch; expected={expected.get(field)!r}, "
                        f"actual={actual.get(field)!r}"
                    )
            hints = [w for w in expected["message"].split() if len(w) >= 4]
            assert any(h in actual["message"] for h in hints), (
                f"{name}: error message lacks expected semantic hint; "
                f"expected≈{expected['message']!r}, actual={actual['message']!r}"
            )

        # Determinism check.
        before = {
            n: (out / n).read_text(encoding="utf-8")
            for n in expected_names
        }
        p2 = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=20)
        assert p2.returncode == 0, f"{name}: repeated run failed: {p2.stderr!r}"
        after = {
            n: (out / n).read_text(encoding="utf-8")
            for n in expected_names
        }
        assert before == after, f"{name}: output is not deterministic across repeated runs"
    finally:
        shutil.rmtree(case, ignore_errors=True)


def case_people():
    config = {
        "field_map": {
            "employee_id": "id",
            "emp_id": "id",
            "employee_name": "name",
            "dept": "department",
        },
        "required_fields": ["id", "name", "status"],
        "allowed_values": {"status": ["active", "inactive"]},
        "dedupe_key": "id",
        "timestamp_field": "updated_at",
        "group_by": "department",
        "output_fields": ["id", "name", "department", "status", "updated_at"],
    }

    def build(inp: Path):
        write_json(inp / "north" / "people.json", [
            {"employee_id": "E002", "employee_name": "Ana", "dept": "OPS", "status": "active",
             "updated_at": "2026-08-01T09:00:00"},
            {"employee_id": "E001", "employee_name": "Kevin-old", "dept": "IT", "status": "active",
             "updated_at": "2026-08-01T10:00:00"},
        ])
        write_csv(
            inp / "south" / "legacy.csv",
            ["emp_id", "name", "department", "status", "updated_at"],
            [
                ["E001", "Kevin", "IT", "active", "2026-08-02T10:00:00"],
                ["E003", "Mia", "HR", "invalid-status", "2026-08-02T11:00:00"],
                ["E004", "", "HR", "inactive", "2026-08-02T12:00:00"],
            ],
        )
        (inp / "south" / "broken.json").write_text("{not-json", encoding="utf-8")
        (inp / "notes.txt").write_text("ignored", encoding="utf-8")

    records = [
        {"id": "E001", "name": "Kevin", "department": "IT", "status": "active",
         "updated_at": "2026-08-02T10:00:00"},
        {"id": "E002", "name": "Ana", "department": "OPS", "status": "active",
         "updated_at": "2026-08-01T09:00:00"},
    ]
    summary = {
        "total_files": 4,
        "parsed_files": 2,
        "invalid_files": 1,
        "ignored_files": 1,
        "input_records": 5,
        "valid_records_before_dedupe": 3,
        "output_records": 2,
        "invalid_records": 2,
        "duplicate_records_removed": 1,
        "by_group": {"IT": 1, "OPS": 1},
    }
    errors = [
        {"file": "south/broken.json", "type": "file", "message": "invalid JSON"},
        {"file": "south/legacy.csv", "type": "record", "message": "invalid value for status", "index": 1},
        {"file": "south/legacy.csv", "type": "record", "message": "missing required field: name", "index": 2},
    ]
    return config, build, records, summary, errors


def case_products():
    config = {
        "field_map": {
            "sku_code": "key",
            "product_title": "label",
            "modified_time": "modified",
        },
        "required_fields": ["key", "label", "category"],
        "allowed_values": {"category": ["book", "game"]},
        "dedupe_key": "key",
        "timestamp_field": "modified",
        "group_by": "category",
        "output_fields": ["key", "label", "category", "modified"],
    }

    def build(inp: Path):
        write_yaml(inp / "catalog.yml", [
            {"sku_code": "P2", "product_title": "遊戲", "category": "game",
             "modified_time": "2026-01-01T00:00:00"},
            {"sku_code": "P1", "product_title": "Old", "category": "book",
             "modified_time": "2025-01-01T00:00:00"},
        ])
        write_json(inp / "nested" / "more.json", {
            "sku_code": "P1", "product_title": "New", "category": "book",
            "modified_time": "2026-05-01T00:00:00"
        })

    records = [
        {"key": "P1", "label": "New", "category": "book", "modified": "2026-05-01T00:00:00"},
        {"key": "P2", "label": "遊戲", "category": "game", "modified": "2026-01-01T00:00:00"},
    ]
    summary = {
        "total_files": 2,
        "parsed_files": 2,
        "invalid_files": 0,
        "ignored_files": 0,
        "input_records": 3,
        "valid_records_before_dedupe": 3,
        "output_records": 2,
        "invalid_records": 0,
        "duplicate_records_removed": 1,
        "by_group": {"book": 1, "game": 1},
    }
    return config, build, records, summary, []


def case_empty():
    config = {
        "field_map": {"x": "id"},
        "required_fields": ["id"],
        "allowed_values": {},
        "dedupe_key": "id",
        "timestamp_field": "updated",
        "group_by": "kind",
        "output_fields": ["id"],
    }

    def build(inp: Path):
        pass

    summary = {
        "total_files": 0,
        "parsed_files": 0,
        "invalid_files": 0,
        "ignored_files": 0,
        "input_records": 0,
        "valid_records_before_dedupe": 0,
        "output_records": 0,
        "invalid_records": 0,
        "duplicate_records_removed": 0,
        "by_group": {},
    }
    return config, build, [], summary, []


def main() -> int:
    report = ValidatorReport(ROOT, "example-08-config-driven-data-pipeline")
    try:
        assert ENTRY.exists(), "pipeline_cli.py is missing"
        for name, factory in [
            ("people", case_people),
            ("products", case_products),
            ("empty", case_empty),
        ]:
            run_case(name, *factory())
    except Exception as e:
        report.error("E001", "Black-box pipeline validation failed", [str(e)])
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
