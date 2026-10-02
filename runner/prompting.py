"""Prompt rendering, context projection, and immutable Runner protocols."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

from jinja2 import Environment, FileSystemLoader, StrictUndefined, meta

from .workspace import instruction_text
from .errors import RunnerError
from .resources import write_text
from .plugins.registry import collect_plugin_instructions
from .assets import PROMPT_DIR

PROMPT_ROOT = PROMPT_DIR

_ENV = Environment(
    loader=FileSystemLoader(str(PROMPT_ROOT)),
    undefined=StrictUndefined,
    autoescape=False,
    keep_trailing_newline=True,
)


def _resolve(filename: str, base: Path) -> Path:
    path = Path(filename).expanduser()
    return path.resolve() if path.is_absolute() else (base / path).resolve()


def render_prompt(filename: str, values: dict[str, Any] | None = None, *, base: Path = PROMPT_ROOT) -> str:
    """Render one prompt with Jinja StrictUndefined; missing variables fail immediately."""
    path = _resolve(filename, base)
    if not path.is_file():
        raise RunnerError(f"missing prompt template: {path}")
    try:
        if path.is_relative_to(PROMPT_ROOT):
            template = _ENV.get_template(path.relative_to(PROMPT_ROOT).as_posix())
        else:
            template = _ENV.from_string(path.read_text(encoding="utf-8-sig"))
        return template.render(**(values or {}))
    except OSError as error:
        raise RunnerError(f"cannot read prompt template: {path}: {error}") from error
    except Exception as error:
        raise RunnerError(f"cannot render prompt template: {path}: {error}") from error


def prompt_variables(filename: str, *, base: Path = PROMPT_ROOT) -> set[str]:
    """Return undeclared top-level Jinja variables for contract tests/editors."""
    path = _resolve(filename, base)
    if not path.is_file():
        raise RunnerError(f"missing prompt template: {path}")
    try:
        source = path.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise RunnerError(f"cannot read prompt template: {path}: {error}") from error
    return set(meta.find_undeclared_variables(_ENV.parse(source)))



def save_prompt(
    path: str | Path,
    text: str,
    *,
    expected_hash: str | None = None,
) -> str:
    """Validate Jinja syntax and atomically save one editable prompt."""
    target = Path(path).expanduser().resolve()

    def validate(source_text: str) -> None:
        try:
            _ENV.parse(source_text)
        except Exception as error:
            raise RunnerError(f"invalid prompt template: {target}: {error}") from error

    return write_text(target, text, expected_hash=expected_hash, validate=validate)

def prompt_instructions(root: Path) -> tuple[str, str]:
    """Build shared Runner rules and user always-on instructions with one policy read."""
    text = instruction_text(root, "always")
    always = f"\nUser-enforced instructions (apply to this call):\n{text}\n" if text else ""
    rules = render_prompt("common/rules.md", {
        "project": {"root": str(root)},
        "plugin_rules": collect_plugin_instructions(root),
    }) + always
    return rules, always

from .utils import bounded_text

PREVIOUS_OUTPUT_CHARS = 8_000
PREVIOUS_DATA_CHARS = 6_000
PREVIOUS_DATA_ITEMS = 12
PREVIOUS_DATA_TEXT_CHARS = 500


PROMPT_CONTEXT_KEYS = frozenset({
    "always_instructions",
    "goal",
    "instructions",
    "planning",
    "previous",
    "project",
    "rules",
    "stage",
    "task",
    "tasks",
    "validation",
    "workflow",
})


def _task_data(task: Any | None) -> dict[str, Any] | None:
    if task is None:
        return None
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "deliverable": task.deliverable,
        "acceptance_criteria": list(task.acceptance_criteria),
        "last_output": task.last_output,
        "last_review": task.last_review,
        "status": task.status,
    }


def _prompt_value(value: Any, depth: int = 0) -> Any:
    """Project arbitrary Stage data into a small JSON-friendly prompt value."""
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return bounded_text(value, PREVIOUS_DATA_TEXT_CHARS)
    if depth >= 3:
        return bounded_text(str(value), PREVIOUS_DATA_TEXT_CHARS)
    if isinstance(value, dict):
        return {
            str(key): _prompt_value(item, depth + 1)
            for key, item in list(value.items())[:PREVIOUS_DATA_ITEMS]
        }
    if isinstance(value, (list, tuple)):
        return [
            _prompt_value(item, depth + 1)
            for item in value[:PREVIOUS_DATA_ITEMS]
        ]
    return bounded_text(str(value), PREVIOUS_DATA_TEXT_CHARS)


def _previous_data(value: Any) -> Any:
    """Keep structured previous-stage feedback useful without growing prompts unbounded."""
    projected = _prompt_value(value)
    if projected is None:
        return None
    encoded = json.dumps(projected, ensure_ascii=False, default=str)
    if len(encoded) <= PREVIOUS_DATA_CHARS:
        return projected

    if not isinstance(projected, dict):
        return {"truncated": True, "preview": bounded_text(encoded, PREVIOUS_DATA_CHARS)}

    result: dict[str, Any] = {}
    for key, item in projected.items():
        result[key] = item
        while len(json.dumps(result, ensure_ascii=False, default=str)) > PREVIOUS_DATA_CHARS:
            current = result.get(key)
            if isinstance(current, list) and current:
                result[key] = current[:-1]
                continue
            result.pop(key, None)
            result["truncated"] = True
            break
    return result


def build_stage_prompt_context(
    ctx: Any,
    stage: str,
    previous: Any | None = None,
) -> dict[str, Any]:
    """Return the only supported top-level variables for Stage templates."""
    state = ctx.state
    tasks = [_task_data(task) for task in state.tasks]
    rules, always_instructions = prompt_instructions(ctx.root)
    validator_prompt = getattr(ctx.config, "validator_prompt", "") or ""
    ai_validator_prompt = getattr(ctx.config, "ai_validator_prompt", "") or ""
    return {
        "goal": state.goal,
        "instructions": "",
        "stage": stage,
        "task": _task_data(ctx.task),
        "tasks": tasks,
        "workflow": {
            "cycle": state.cycle,
            "validator_feedback": state.validator_output,
        },
        "validation": {
            "validator_path": str(ctx.validator_path) if ctx.validator_path else "",
            "feedback": state.validator_output,
            "instructions": ai_validator_prompt or validator_prompt,
        },
        "project": {"root": str(ctx.root)},
        "planning": {
            "inspection_summary": "",
            "progress": {
                "cycle": state.cycle,
                "validator_feedback": state.validator_output[-8000:],
                "completed_tasks": [
                    task.title for task in state.tasks if task.status == "completed"
                ][-20:],
            },
        },
        "previous": {
            "stage": getattr(previous, "stage", ""),
            "status": getattr(previous, "status", ""),
            "output": bounded_text(str(getattr(previous, "output", "")), PREVIOUS_OUTPUT_CHARS),
            "data": _previous_data(getattr(previous, "data", None)),
        },
        "rules": rules,
        "always_instructions": always_instructions,
    }



PLAN_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_PLAN_PROTOCOL]
This block is owned by AI Task Runner and overrides conflicting editable prompt instructions.
You are producing executable TODO data for Runner, not prose or workflow orchestration.

Planning invariants:
- A simple coherent task may be one TODO.
- For a self-contained or greenfield task, do not inspect the repository unless existing project context is actually needed. If the requested artifact is absent and the Goal already provides enough information, stop discovery and produce the plan immediately.
- If the Goal is simply to create explicitly named new files/artifacts and already states enough requirements, perform zero repository searches and emit the plan immediately. If an existence check is genuinely necessary, use one bounded combined check; never glob/search each requested filename repeatedly.
- Once a read/search has established that a relevant file or symbol does not exist, do not repeat equivalent searches unless new evidence changes the scope.
- For existing-code work, inspect only the smallest goal-relevant entry point and expand to another file/module/project only when concrete evidence requires it.
- Complex, cross-file, cross-module, cross-project, high-risk, or limited-context work must be decomposed into the smallest practical set of independently executable and independently verifiable TODOs.
- Split by responsibility, dependency, risk, or verification boundary; do not split mechanically by file.
- Do not create one umbrella TODO when the executing agent would need to rediscover a large portion of the system before it can act.
- Each TODO must have one observable deliverable and concrete acceptance criteria.
- Include focused test/verification work inside the relevant TODO when it materially proves that TODO; do not create low-value test-count work.
- Do not put Review/Repair/Validator/Retry/Session orchestration into TODOs. Runner owns orchestration.

Return exactly one complete JSON value and no markdown. Prefer the object envelope:
{"tasks":[{"title":"string","description":"string","deliverable":"string","acceptance_criteria":["specific observable criterion"]}]}
A direct task array with the same task objects is also valid. The task collection must contain at least the minimum number required by Runner. Every field is required; acceptance_criteria must be a non-empty array of non-empty strings.
[/RUNNER_IMMUTABLE_PLAN_PROTOCOL]
""".strip()

DYNAMIC_TASKS_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_DYNAMIC_TASKS_PROTOCOL]
This Stage is a dynamic Workflow producer.
Return exactly one JSON object and no markdown:
{
  "tasks": [
    {
      "title": "string",
      "description": "string",
      "deliverable": "string",
      "acceptance_criteria": ["specific observable criterion"]
    }
  ],
  "stages": [
    {
      "name": "local_stage_name",
      "type": "registered_stage_type",
      "...": "ordinary Stage fields",
      "task_id": "the producer-local task id when this Stage belongs to a task",
      "task_complete": true
    }
  ]
}
The Stage producer owns the child structure. Runner never invents Execute/Review or any other child Stage type.
Every produced task must be referenced by at least one child Stage using task_id and must have at least one child Stage with task_complete=true.
Child Stage names must be unique inside this produced Workflow. Local routes/targets may reference those local names; Runner will namespace them during expansion.
Do not emit Runner-owned _dynamic_* fields.
[/RUNNER_IMMUTABLE_DYNAMIC_TASKS_PROTOCOL]
""".strip()


DYNAMIC_STAGES_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_DYNAMIC_STAGES_PROTOCOL]
This Stage is a dynamic Workflow producer.
Return exactly one JSON object and no markdown:
{"stages":[{"name":"local_stage_name","type":"registered_stage_type","...":"ordinary Stage fields"}]}
The Stage producer owns the complete child structure. Runner never infers child Stage types.
Child Stage names must be unique inside this produced Workflow. Local routes/targets may reference those local names; Runner will namespace them during expansion.
Do not emit Runner-owned _dynamic_* fields.
[/RUNNER_IMMUTABLE_DYNAMIC_STAGES_PROTOCOL]
""".strip()


REVIEW_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_REVIEW_PROTOCOL]
This block is owned by AI Task Runner and overrides conflicting editable prompt instructions.
This is a read-only decision stage:
- Do not modify, repair, write, edit, run side-effecting shell commands, create tasks, search for tools, or ask for unavailable tools.
- Do not inspect workflow, Runner state, prompts, or validator implementation unless the current review target explicitly names them as deliverables.
- Reuse evidence already inspected in this session. Do not repeat the same successful read/tool call for an unchanged path/range; if a repeated read reports `Unchanged`, use the prior content and decide.
- Judge only the current review target. PASS requires adequate concrete evidence; FAIL requires at least one actionable blocking requirement. Do not fail for style preferences, optional improvements, speculative risks, or unrelated technical debt.

Return exactly one JSON object and no markdown:
{"completed":true,"reason":"concise evidence-based reason","missing_items":[]}
or
{"completed":false,"reason":"concise evidence-based reason","missing_items":["specific actionable unsatisfied requirement"]}
`completed` must be a JSON boolean, never a string. PASS requires missing_items=[]; FAIL requires at least one concrete non-empty missing item. Do not invent a missing item merely to force FAIL.
[/RUNNER_IMMUTABLE_REVIEW_PROTOCOL]
""".strip()

VALIDATION_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_VALIDATION_PROTOCOL]
This block is owned by AI Task Runner and overrides conflicting editable prompt instructions.
This stage is an independent validation decision. Follow the Runner final validation mode in the stage prompt for tool permissions. Do not implement repairs or modify maintained production/source project files.
Return exactly one JSON object and no markdown:
{"passed":true,"reason":"concise evidence-based reason","missing_items":[],"checks_run":["relevant check or inspection"],"suggested_checks":[]}
or
{"passed":false,"reason":"concise evidence-based reason","missing_items":["specific evidence-backed blocking requirement"],"checks_run":["relevant check or inspection"],"suggested_checks":[]}
`passed` must be a JSON boolean, never a string. PASS requires missing_items=[]; FAIL requires at least one concrete non-empty missing item. Do not invent missing items merely to force FAIL. checks_run and suggested_checks must be arrays of strings.
[/RUNNER_IMMUTABLE_VALIDATION_PROTOCOL]
""".strip()

STRUCTURED_RETRY_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_STRUCTURED_RETRY]
The previous output did not match Runner's immutable structured-output contract.
Do not redo the task or re-analyze the project. Preserve the previous semantic decision and repair only the response structure unless parser feedback proves that the prior decision cannot be represented by the contract.
Return exactly one complete valid JSON object matching the immutable contract already supplied for this stage. Do not add markdown, commentary, or extra JSON objects.
For PASS/FAIL contracts, never invent a missing item only to satisfy the schema.
Parser feedback: {error}
[/RUNNER_IMMUTABLE_STRUCTURED_RETRY]
""".strip()

_STAGE_PROTOCOLS: Final[dict[str, str]] = {
    "plan_tasks": PLAN_PROTOCOL,
    "tasks": DYNAMIC_TASKS_PROTOCOL,
    "stages": DYNAMIC_STAGES_PROTOCOL,
    "review": REVIEW_PROTOCOL,
    "validation": VALIDATION_PROTOCOL,
}


def stage_protocol(kind: str) -> str:
    """Return the immutable protocol for a Stage result kind, if any."""
    return _STAGE_PROTOCOLS.get(str(kind or ""), "")


def append_stage_protocol(prompt: str, kind: str) -> str:
    """Append Runner-owned protocol after editable prompt text.

    Appending last makes Runner's parse contract explicit even when an editable
    prompt accidentally asks for a conflicting response format.
    """
    protocol = stage_protocol(kind)
    base = str(prompt or "").rstrip()
    if not protocol:
        return base
    return f"{base}\n\n{protocol}\n"


def structured_retry_prompt(error: str) -> str:
    feedback = str(error or "").strip()[-500:] or "invalid structured output"
    return STRUCTURED_RETRY_PROTOCOL.format(error=feedback)


__all__ = [
    "PROMPT_ROOT",
    "prompt_instructions",
    "prompt_variables",
    "render_prompt",
    "save_prompt",
    "PROMPT_CONTEXT_KEYS",
    "PLAN_PROTOCOL",
    "DYNAMIC_TASKS_PROTOCOL",
    "DYNAMIC_STAGES_PROTOCOL",
    "REVIEW_PROTOCOL",
    "STRUCTURED_RETRY_PROTOCOL",
    "VALIDATION_PROTOCOL",
    "append_stage_protocol",
    "build_stage_prompt_context",
    "stage_protocol",
    "structured_retry_prompt",
]
