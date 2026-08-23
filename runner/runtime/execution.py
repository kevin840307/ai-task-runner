"""Generic execution boundary; optional safety behavior is supplied by hooks."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..errors import RunnerError
from .extensions import current
from .hooks import ExecutionContext, HookChain


def _hooks() -> HookChain:
    try:
        return current().hooks
    except RuntimeError:
        return HookChain()


def ask(agent, prompt: str, root: Path, work: Path, *, mode: str = "write", actor: str = "agent", timeout: int | None = None, idle_timeout: float = 0, change_detected: Callable[[], bool] | None = None) -> str:
    hooks = _hooks()
    context = ExecutionContext(root.resolve(), work.resolve(), mode, actor)
    tokens = hooks.before(context)
    detector = hooks.change_detector(context, tokens, change_detected)
    output: str | None = None
    error: BaseException | None = None
    try:
        output = agent.ask(prompt, idle_timeout_after_change=idle_timeout, change_detected=detector, timeout=timeout)
    except BaseException as caught:
        error = caught
    finally:
        violations = hooks.after(context, tokens)
    if violations:
        raise RunnerError("; ".join(item.message for item in violations)) from error
    if error is not None:
        raise error
    assert output is not None
    return output



def guarded_call(action, root: Path, work: Path, *, mode: str = "write", actor: str = "action"):
    hooks = _hooks()
    context = ExecutionContext(root.resolve(), work.resolve(), mode, actor)
    tokens = hooks.before(context)
    result = None
    error: BaseException | None = None
    try:
        result = action()
    except BaseException as caught:
        error = caught
    finally:
        violations = hooks.after(context, tokens)
    # Hooks always restore first. If the action itself timed out, preserve that
    # primary diagnostic and let its caller format the timeout details.
    if violations and not (result is not None and getattr(result, "timed_out", False)):
        raise RunnerError("; ".join(item.message for item in violations)) from error
    if error is not None:
        raise error
    return result


def readonly_ask(agent, prompt: str, root: Path, work: Path, *, timeout: int | None = None, idle_timeout: float = 0, tolerate_restored_changes: bool = False) -> tuple[str, list[str]]:
    hooks = _hooks()
    context = ExecutionContext(root.resolve(), work.resolve(), "readonly", "read-only model call")
    tokens = hooks.before(context)
    detector = hooks.change_detector(context, tokens, lambda: False)
    output: str | None = None
    error: BaseException | None = None
    try:
        output = agent.ask(prompt, idle_timeout_after_change=idle_timeout, change_detected=detector, timeout=timeout)
    except BaseException as caught:
        error = caught
    finally:
        violations = hooks.after(context, tokens)
    protected = [item.message for item in violations if item.kind == "protected"]
    restored = [path for item in violations if item.kind == "readonly" for path in item.paths]
    other = [item.message for item in violations if item.kind not in {"protected", "readonly"}]
    blocking = [*protected, *other]
    if restored and not tolerate_restored_changes:
        blocking.append("read-only model call modified files and they were restored: " + ", ".join(restored))
    if blocking:
        raise RunnerError("; ".join(blocking)) from error
    if error is not None:
        raise error
    assert output is not None
    return output, restored


def extension_instructions(root: Path) -> str:
    try:
        return current().hooks.instructions(root)
    except RuntimeError:
        return ""


__all__ = ["ask", "extension_instructions", "guarded_call", "readonly_ask"]
