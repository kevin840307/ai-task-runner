from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
try:
    from ai_task_runner_validator import ValidatorReport, parse_json
except ModuleNotFoundError:
    import importlib.util as _importlib_util
    from pathlib import Path as _HelperPath

    _helper_path = _HelperPath(__file__).with_name("ai_task_runner_validator.py")
    _spec = _importlib_util.spec_from_file_location("_atr_validator_helper", _helper_path)
    if _spec is None or _spec.loader is None:
        raise
    _helper = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_helper)
    ValidatorReport, parse_json = _helper.ValidatorReport, _helper.parse_json

ROOT = Path(__file__).resolve().parent
ENTRY = ROOT / "config_auditor.py"
OUTPUTS = {"report.json", "summary.yaml", "errors.json"}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_yaml(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def load_outputs(out: Path, case: str):
    names = {p.name for p in out.iterdir()} if out.exists() else set()
    assert names == OUTPUTS, (
        f"{case}: output files mismatch; expected={sorted(OUTPUTS)}, actual={sorted(names)}"
    )
    report = parse_json((out / "report.json").read_text(encoding="utf-8"), f"{case} report.json")
    errors = parse_json((out / "errors.json").read_text(encoding="utf-8"), f"{case} errors.json")
    summary = yaml.safe_load((out / "summary.yaml").read_text(encoding="utf-8"))
    return report, summary, errors


def assert_errors(case: str, actual, expected):
    assert len(actual) == len(expected), (
        f"{case}: error count mismatch; expected={len(expected)}, actual={len(actual)}"
    )
    for want, got in zip(expected, actual):
        for field in ("environment", "file", "type"):
            assert got.get(field) == want.get(field), (
                f"{case}: error {field} mismatch; expected={want.get(field)!r}, actual={got.get(field)!r}"
            )
        message = str(got.get("message", "")).lower()
        hints = [w.strip(",:.") for w in want["message"].lower().split() if len(w.strip(",:.")) >= 4]
        assert any(h in message for h in hints), (
            f"{case}: error message lacks useful context; expected≈{want['message']!r}, actual={got.get('message')!r}"
        )


def run_case(case: str, build, baseline: str, expected_report, expected_summary, expected_errors):
    work = Path(tempfile.mkdtemp(prefix=f"atr09-{case}-"))
    try:
        inp, out = work / "input", work / "output"
        inp.mkdir()
        build(inp)

        cmd = [
            sys.executable, str(ENTRY),
            "--input", str(inp),
            "--baseline", baseline,
            "--output", str(out),
        ]
        result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, (
            f"{case}: command failed; stdout={result.stdout!r}; stderr={result.stderr!r}"
        )

        report, summary, errors = load_outputs(out, case)

        assert report == expected_report, (
            f"{case}: report mismatch\nexpected={expected_report!r}\nactual={report!r}"
        )
        assert summary == expected_summary, (
            f"{case}: summary mismatch\nexpected={expected_summary!r}\nactual={summary!r}"
        )
        assert_errors(case, errors, expected_errors)

        before = {name: (out / name).read_bytes() for name in OUTPUTS}
        repeat = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=30)
        assert repeat.returncode == 0, f"{case}: repeated run failed"
        after = {name: (out / name).read_bytes() for name in OUTPUTS}
        assert before == after, f"{case}: outputs are not byte-for-byte deterministic"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def mixed_formats_case():
    def build(inp: Path):
        write_yaml(inp / "BASE" / "app.yaml", {
            "server": {"host": "base.local", "port": 8080, "enabled": True},
            "features": ["a", "b"],
        })
        write_json(inp / "BASE" / "db.json", {"db": {"pool": 20, "ssl": True}})
        write_text(inp / "BASE" / "extra.ini", "[api]\nurl=https://base/api\ntimeout=30\n")
        write_text(
            inp / "BASE" / "service.xml",
            '<config mode="safe"><node><host>x.local</host><port>9000</port></node></config>',
        )

        write_yaml(inp / "QA" / "app.yaml", {
            "server": {"host": "qa.local", "port": "8080", "enabled": True},
            "features": ["a"],
            "newKey": "x",
        })
        write_json(inp / "QA" / "db.json", {"db": {"pool": 25, "ssl": True}})
        write_text(inp / "QA" / "extra.ini", "[api]\nurl=https://base/api\n")
        write_text(
            inp / "QA" / "service.xml",
            '<config mode="fast"><node><host>x.local</host><port>9000</port></node></config>',
        )
        write_text(inp / "QA" / "notes.txt", "ignored")

        write_yaml(inp / "DEV" / "app.yaml", {
            "server": {"host": "base.local", "port": 8080, "enabled": False},
            "features": ["a", "b"],
        })
        write_text(inp / "DEV" / "broken.json", "{bad-json")
        write_text(inp / "DEV" / "notes.md", "ignored")

    expected_report = {
        "baseline": "BASE",
        "environments": {
            "DEV": {
                "missing": [
                    {"key": "db.json::db.pool", "baseline_value": 20},
                    {"key": "db.json::db.ssl", "baseline_value": True},
                    {"key": "extra.ini::api.timeout", "baseline_value": "30"},
                    {"key": "extra.ini::api.url", "baseline_value": "https://base/api"},
                    {"key": "service.xml::config.@mode", "baseline_value": "safe"},
                    {"key": "service.xml::config.node.host", "baseline_value": "x.local"},
                    {"key": "service.xml::config.node.port", "baseline_value": "9000"},
                ],
                "extra": [],
                "changed": [
                    {"key": "app.yaml::server.enabled", "baseline_value": True, "target_value": False},
                ],
                "type_mismatch": [],
            },
            "QA": {
                "missing": [
                    {"key": "app.yaml::features.1", "baseline_value": "b"},
                    {"key": "extra.ini::api.timeout", "baseline_value": "30"},
                ],
                "extra": [
                    {"key": "app.yaml::newKey", "target_value": "x"},
                ],
                "changed": [
                    {"key": "app.yaml::server.host", "baseline_value": "base.local", "target_value": "qa.local"},
                    {"key": "db.json::db.pool", "baseline_value": 20, "target_value": 25},
                    {"key": "service.xml::config.@mode", "baseline_value": "safe", "target_value": "fast"},
                ],
                "type_mismatch": [
                    {
                        "key": "app.yaml::server.port",
                        "baseline_type": "number",
                        "target_type": "string",
                        "baseline_value": 8080,
                        "target_value": "8080",
                    },
                ],
            },
        },
    }

    # Fixture accounting:
    # BASE = 4 files, QA = 5 files, DEV = 3 files => discovered = 12
    # Parsed supported files: BASE 4 + QA 4 + DEV app.yaml 1 => parsed = 9
    # DEV broken.json => malformed = 1
    # QA notes.txt + DEV notes.md => ignored = 2
    expected_summary = {
        "baseline": "BASE",
        "environment_count": 3,
        "environments": {
            "DEV": {"missing": 7, "extra": 0, "changed": 1, "type_mismatch": 0},
            "QA": {"missing": 2, "extra": 1, "changed": 3, "type_mismatch": 1},
        },
        "files": {"discovered": 12, "parsed": 9, "malformed": 1, "ignored": 2},
    }

    expected_errors = [
        {"environment": "DEV", "file": "broken.json", "type": "file", "message": "invalid json"},
    ]
    return build, "BASE", expected_report, expected_summary, expected_errors


def dynamic_environment_case():
    def build(inp: Path):
        write_json(inp / "golden" / "settings.json", {
            "x": 1,
            "flag": False,
            "label": "1",
        })
        write_json(inp / "canary-2" / "settings.json", {
            "x": 1,
            "flag": False,
            "label": 1,
            "added": None,
        })
        write_json(inp / "zebra" / "settings.json", {
            "x": 2,
            "flag": False,
            "label": "1",
        })

    expected_report = {
        "baseline": "golden",
        "environments": {
            "canary-2": {
                "missing": [],
                "extra": [{"key": "settings.json::added", "target_value": None}],
                "changed": [],
                "type_mismatch": [{
                    "key": "settings.json::label",
                    "baseline_type": "string",
                    "target_type": "number",
                    "baseline_value": "1",
                    "target_value": 1,
                }],
            },
            "zebra": {
                "missing": [],
                "extra": [],
                "changed": [
                    {"key": "settings.json::x", "baseline_value": 1, "target_value": 2},
                ],
                "type_mismatch": [],
            },
        },
    }
    expected_summary = {
        "baseline": "golden",
        "environment_count": 3,
        "environments": {
            "canary-2": {"missing": 0, "extra": 1, "changed": 0, "type_mismatch": 1},
            "zebra": {"missing": 0, "extra": 0, "changed": 1, "type_mismatch": 0},
        },
        "files": {"discovered": 3, "parsed": 3, "malformed": 0, "ignored": 0},
    }
    return build, "golden", expected_report, expected_summary, []


def nested_xml_case():
    def build(inp: Path):
        write_text(
            inp / "main" / "cluster.xml",
            '<root><server id="a"><host>A</host></server><server id="b"><host>B</host></server></root>',
        )
        write_yaml(inp / "main" / "nested.yml", {
            "items": [
                {"name": "one", "enabled": True},
                {"name": "two", "enabled": False},
            ]
        })
        write_text(
            inp / "next" / "cluster.xml",
            '<root><server id="a"><host>A</host></server><server id="c"><host>C</host></server></root>',
        )
        write_yaml(inp / "next" / "nested.yml", {
            "items": [
                {"name": "one", "enabled": True},
                {"name": "two", "enabled": True},
            ]
        })

    expected_report = {
        "baseline": "main",
        "environments": {
            "next": {
                "missing": [],
                "extra": [],
                "changed": [
                    {"key": "cluster.xml::root.server.1.@id", "baseline_value": "b", "target_value": "c"},
                    {"key": "cluster.xml::root.server.1.host", "baseline_value": "B", "target_value": "C"},
                    {"key": "nested.yml::items.1.enabled", "baseline_value": False, "target_value": True},
                ],
                "type_mismatch": [],
            }
        },
    }
    expected_summary = {
        "baseline": "main",
        "environment_count": 2,
        "environments": {
            "next": {"missing": 0, "extra": 0, "changed": 3, "type_mismatch": 0},
        },
        "files": {"discovered": 4, "parsed": 4, "malformed": 0, "ignored": 0},
    }
    return build, "main", expected_report, expected_summary, []


def missing_baseline_case():
    work = Path(tempfile.mkdtemp(prefix="atr09-missing-"))
    try:
        inp, out = work / "input", work / "output"
        inp.mkdir()
        write_json(inp / "A" / "x.json", {"x": 1})
        result = subprocess.run(
            [
                sys.executable, str(ENTRY),
                "--input", str(inp),
                "--baseline", "DOES_NOT_EXIST",
                "--output", str(out),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=20,
        )
        assert result.returncode != 0, "missing baseline must return non-zero"
        combined = (result.stdout + "\n" + result.stderr).lower()
        assert "baseline" in combined, (
            f"missing baseline error should mention baseline; "
            f"stdout={result.stdout!r}; stderr={result.stderr!r}"
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    report = ValidatorReport(ROOT, "example-09-config-environment-auditor")
    try:
        assert ENTRY.exists(), "config_auditor.py is missing"
        for name, factory in [
            ("mixed-formats", mixed_formats_case),
            ("dynamic-envs", dynamic_environment_case),
            ("nested-xml", nested_xml_case),
        ]:
            run_case(name, *factory())
        missing_baseline_case()
    except Exception as e:
        report.error("E001", "Black-box configuration audit validation failed", [str(e)])
    return report.finish()


if __name__ == "__main__":
    raise SystemExit(main())
