import os

from runner.runtime.run_state import RunState
from runner.plugins.console import LiveUI


class FakeStdout:
    def __init__(self):
        self.output = ""

    def isatty(self):
        return True

    def write(self, text):
        self.output += text

    def flush(self):
        pass


def _plain_ui(monkeypatch, width=120):
    stdout = FakeStdout()
    monkeypatch.setattr("runner.plugins.console.sys.stdout", stdout)
    monkeypatch.setattr("runner.plugins.console.supports_ansi_screen", lambda: False)
    monkeypatch.setattr(
        "runner.plugins.console.shutil.get_terminal_size",
        lambda fallback: os.terminal_size((width, 20)),
    )
    ui = LiveUI()
    ui.bind(RunState("run", "goal", "/project"))
    return ui, stdout


def test_plain_spinner_flattens_multiline_status_and_detail(monkeypatch):
    ui, stdout = _plain_ui(monkeypatch)
    ui.set("AI 正在建立最小任務規劃\nretry", "qwen exit 1:\r\nLoop detection halted")

    frame = stdout.output.rsplit("\r", 1)[-1]
    assert "\n" not in frame
    assert "\r" not in frame
    assert "AI 正在建立最小任務規劃 retry" in frame
    assert "qwen exit 1: Loop detection halted" in frame


def test_spinner_redraw_does_not_accumulate_newlines(monkeypatch):
    ui, stdout = _plain_ui(monkeypatch, width=80)
    ui.status = "AI 正在建立最小任務規劃"
    ui.detail = "qwen exit 1:\nLoop detection halted the run"
    before = stdout.output.count("\n")

    for index in range(20):
        ui._frame = index
        ui.draw()

    assert stdout.output.count("\n") == before


def test_observer_events_keep_original_multiline_detail(tmp_path):
    from types import SimpleNamespace

    from runner.plugins.observability import ObservabilityObserver

    events = []
    detail = "qwen exit 1:\nLoop detection halted"
    observer = ObservabilityObserver(SimpleNamespace(
        config=SimpleNamespace(event_callback=events.append, json_events=False),
        work=tmp_path,
    ))
    observer({
        "type": "runner.status",
        "status": "AI 正在建立最小任務規劃",
        "detail": detail,
    })

    assert events[-1]["detail"] == detail


def test_single_line_text_handles_crlf_and_blank_lines():
    assert LiveUI._single_line_text("a\r\n\r\nb\nc") == "a  b c"
