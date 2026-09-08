"""Immutable AI stage protocols owned by Runner code.

These strings are intentionally not editable prompt resources.  Editable prompts
control *how* an agent reasons about the task; these protocols control the wire
contract Runner needs to parse results safely and resume for long-running jobs.
Keep all hard-coded AI protocol text in this module so future changes are local,
reviewable, and contract-tested.
"""
from __future__ import annotations

from typing import Final

PLAN_PROTOCOL: Final[str] = r"""
[RUNNER_IMMUTABLE_PLAN_PROTOCOL]
This block is owned by AI Task Runner and overrides conflicting editable prompt instructions.
You are producing executable TODO data for Runner, not prose or workflow orchestration.

Planning invariants:
- A simple coherent task may be one TODO.
- For a self-contained or greenfield task, do not inspect the repository unless existing project context is actually needed. If the requested artifact is absent and the Goal already provides enough information, stop discovery and produce the plan immediately.
- Once a read/search has established that a relevant file or symbol does not exist, do not repeat equivalent searches unless new evidence changes the scope.
- For existing-code work, inspect only the smallest goal-relevant entry point and expand to another file/module/project only when concrete evidence requires it.
- Complex, cross-file, cross-module, cross-project, high-risk, or limited-context work must be decomposed into the smallest practical set of independently executable and independently verifiable TODOs.
- Split by responsibility, dependency, risk, or verification boundary; do not split mechanically by file.
- Do not create one umbrella TODO when the executing agent would need to rediscover a large portion of the system before it can act.
- Each TODO must have one observable deliverable and concrete acceptance criteria.
- Include focused test/verification work inside the relevant TODO when it materially proves that TODO; do not create low-value test-count work.
- Do not put Review/Repair/Validator/Retry/Session orchestration into TODOs. Runner owns orchestration.

Return exactly one JSON object and no markdown:
{"tasks":[{"title":"string","description":"string","deliverable":"string","acceptance_criteria":["specific observable criterion"]}]}
`tasks` must contain at least the minimum number required by Runner. Every field is required; acceptance_criteria must be a non-empty array of non-empty strings.
[/RUNNER_IMMUTABLE_PLAN_PROTOCOL]
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
This stage is an independent read-only validation decision. Do not modify project files or implement repairs.
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
    "tasks": PLAN_PROTOCOL,
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
    "PLAN_PROTOCOL",
    "REVIEW_PROTOCOL",
    "VALIDATION_PROTOCOL",
    "STRUCTURED_RETRY_PROTOCOL",
    "append_stage_protocol",
    "stage_protocol",
    "structured_retry_prompt",
]
