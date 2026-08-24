from __future__ import annotations

import os
import time

from runner.extensions.console import LiveUI
from runner.flow.default import FLOWS, STAGES
from runner.runtime.state import RunState


class _Stdout:
    def __init__(self, tty: bool):
        self.tty = tty
        self.output = ""

    def isatty(self):
        return self.tty

    def write(self, text):
        self.output += text

    def flush(self):
        pass


def _state(tmp_path):
    return RunState("run", "goal", str(tmp_path))


def test_tty_keeps_spinner_on_single_line(monkeypatch, tmp_path):
    stdout = _Stdout(True)
    monkeypatch.setattr("runner.extensions.console.sys.stdout", stdout)
    monkeypatch.setattr("runner.extensions.console.supports_ansi_screen", lambda: False)
    monkeypatch.setattr(
        "runner.extensions.console.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((120, 20)),
    )
    ui = LiveUI()
    ui.bind(_state(tmp_path))
    before_newlines = stdout.output.count("\n")

    ui.start("working")
    time.sleep(0.28)
    ui.stop()

    assert stdout.output.count("\r") >= 2
    assert stdout.output.count("working") >= 2
    assert stdout.output.count("\n") == before_newlines + 2  # start closes prior line; stop closes spinner line
    assert ui._thread is None


def test_redirected_output_has_no_spinner_and_deduplicates(monkeypatch, tmp_path):
    stdout = _Stdout(False)
    monkeypatch.setattr("runner.extensions.console.sys.stdout", stdout)
    ui = LiveUI()
    ui.bind(_state(tmp_path))

    ui.start("working")
    ui.start("working")

    assert stdout.output.count("working") == 1
    assert "\r" not in stdout.output
    assert ui._thread is None


def test_default_and_replan_flows_do_not_force_understand_stage():
    assert "understand" not in STAGES
    assert FLOWS["default"] == ["plan", "validate_file", "validate_ai"]
    assert FLOWS["replan"] == ["plan", "validate_file", "validate_ai"]


def test_repeated_tty_start_does_not_restart_spinner_or_add_lines(monkeypatch, tmp_path):
    stdout = _Stdout(True)
    monkeypatch.setattr("runner.extensions.console.sys.stdout", stdout)
    monkeypatch.setattr("runner.extensions.console.supports_ansi_screen", lambda: False)
    monkeypatch.setattr(
        "runner.extensions.console.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((120, 20)),
    )
    ui = LiveUI()
    ui.state = _state(tmp_path)

    ui.start("working")
    time.sleep(0.14)
    thread = ui._thread
    ui.start("working")
    ui.start("working")
    time.sleep(0.14)
    ui.stop()

    assert thread is not None
    assert stdout.output.count("\n") == 1
    assert stdout.output.count("\r") >= 2
