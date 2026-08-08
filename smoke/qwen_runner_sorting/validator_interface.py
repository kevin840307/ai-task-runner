#!/usr/bin/env python3
"""Small copyable helper for Python validators.

Copy this file next to your validator.py, then:

    from validator_interface import ValidatorReport

Runner contract stays unchanged:
- exit code 0: pass
- exit code != 0: fail and retry
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


DEFAULT_STDOUT_ITEMS = 8


@dataclass
class Finding:
    code: str
    title: str
    details: list[str] = field(default_factory=list)
    fix: str = ""
    report: Path | None = None


class ValidatorReport:
    """Collect errors/warnings, write reports, print a compact model summary."""

    def __init__(
        self,
        project_root: Path | str,
        name: str = "validator",
        stdout_items: int = DEFAULT_STDOUT_ITEMS,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.report_dir = self.project_root / ".ai-task-runner" / "validator-reports" / name
        self.stdout_items = stdout_items
        self.errors: list[Finding] = []
        self.warnings: list[Finding] = []

    def error(
        self,
        code: str,
        title: str,
        details: Iterable[object] = (),
        fix: str = "",
        report_name: str | None = None,
        report_content: str | Iterable[object] | None = None,
    ) -> None:
        self.errors.append(self._finding(code, title, details, fix, report_name, report_content))

    def warning(
        self,
        code: str,
        title: str,
        details: Iterable[object] = (),
        fix: str = "",
        report_name: str | None = None,
        report_content: str | Iterable[object] | None = None,
    ) -> None:
        self.warnings.append(self._finding(code, title, details, fix, report_name, report_content))

    def write_report(self, name: str, content: str | Iterable[object]) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        path = self.report_dir / name
        text = content if isinstance(content, str) else "\n".join(str(item) for item in content)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        return path

    def finish(self) -> int:
        """Write standard reports, print summary, and return the process exit code."""
        self.write_standard_reports()
        self.print_summary()
        return 1 if self.errors else 0

    def status(self) -> str:
        if self.errors:
            return "VALIDATION_FAILED"
        if self.warnings:
            return "VALIDATION_PASSED_WITH_WARNINGS"
        return "VALIDATION_PASSED"

    def print_summary(self) -> None:
        print(self.status())
        print(f"errors: {len(self.errors)}")
        print(f"warnings: {len(self.warnings)}")
        print(f"report_dir: {self.display_path(self.report_dir)}")
        self._print_group("ERRORS", self.errors)
        self._print_group("WARNINGS", self.warnings)

    def write_standard_reports(self) -> None:
        self.write_report("summary.txt", [
            self.status(),
            f"errors: {len(self.errors)}",
            f"warnings: {len(self.warnings)}",
            f"report_dir: {self.display_path(self.report_dir)}",
        ])
        self.write_report("errors.txt", self._full_findings(self.errors, "No errors."))
        self.write_report("warnings.txt", self._full_findings(self.warnings, "No warnings."))

    def display_path(self, path: Path) -> str:
        try:
            return path.relative_to(self.project_root).as_posix()
        except ValueError:
            return str(path)

    def _finding(
        self,
        code: str,
        title: str,
        details: Iterable[object],
        fix: str,
        report_name: str | None,
        report_content: str | Iterable[object] | None,
    ) -> Finding:
        report = self.write_report(report_name, report_content) if report_name and report_content is not None else None
        return Finding(
            code=code,
            title=title,
            details=[str(item) for item in details],
            fix=fix,
            report=report,
        )

    def _print_group(self, label: str, findings: list[Finding]) -> None:
        if not findings:
            return
        print()
        print(f"{label}:")
        for finding in findings[: self.stdout_items]:
            print(f"[{finding.code}] {finding.title}")
            for detail in finding.details[: self.stdout_items]:
                print(f"- {detail}")
            if finding.fix:
                print(f"Fix: {finding.fix}")
            if finding.report:
                print(f"Full report: {self.display_path(finding.report)}")
        if len(findings) > self.stdout_items:
            print(f"... {len(findings) - self.stdout_items} more {label.lower()} omitted from stdout")

    def _full_findings(self, findings: list[Finding], empty: str) -> list[str]:
        if not findings:
            return [empty]
        lines: list[str] = []
        for finding in findings:
            lines.append(f"[{finding.code}] {finding.title}")
            lines.extend(f"- {detail}" for detail in finding.details)
            if finding.fix:
                lines.append(f"Fix: {finding.fix}")
            if finding.report:
                lines.append(f"Full report: {self.display_path(finding.report)}")
            lines.append("")
        return lines

def run_validation(report: ValidatorReport, check) -> int:
    """Run one validator check function and convert failures to the standard report."""
    try:
        check()
    except AssertionError as error:
        report.error("E001", "Validation failed", [str(error)], fix="Fix the reported project issue and rerun validation.")
    except Exception as error:
        report.error(
            "E999",
            "Validator crashed",
            [f"{type(error).__name__}: {error}"],
            fix="Fix the project or validator input that caused this unexpected validation error.",
        )
    return report.finish()

