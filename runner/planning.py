"""Language- and technology-neutral planning helpers."""
from __future__ import annotations

import re

from .defaults import DEFAULT_TASK_FEEDBACK_LIMIT
from .models import Task
from .prompting import format_validator_feedback


_STRUCTURED_FINDING = re.compile(r"^\s*\[([^\]\r\n]+)\]\s+(.+?)\s*$")
_MARKDOWN_HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-+*]|\d+[.)])\s+(.+?)\s*$")


def _normalized(text: str) -> str:
    """Normalize text without assuming a language, domain, or file type."""
    return " ".join(re.findall(r"\w+", text.casefold(), flags=re.UNICODE))


def plan_quality_issue(
    goal: str,
    tasks: list[Task],
    validator_feedback: str = "",
) -> str:
    """Return one structural, domain-neutral reason to replan, or empty text."""
    titles = [_normalized(task.title) for task in tasks]
    if len(set(titles)) != len(titles):
        return "duplicate task titles must be merged or differentiated"

    signatures = [
        (
            _normalized(task.title),
            _normalized(task.description),
            tuple(_normalized(item) for item in task.acceptance_criteria),
        )
        for task in tasks
    ]
    if len(set(signatures)) != len(signatures):
        return "duplicate tasks must be merged or differentiated"

    findings = validator_error_findings(validator_feedback)
    if len(findings) > len(tasks):
        return "create focused repair coverage for every structured validator finding"

    explicit_items = structured_goal_items(goal)
    if len(explicit_items) > len(tasks):
        return "the plan must cover every explicitly structured goal item"

    for task in tasks:
        criteria = [_normalized(item) for item in task.acceptance_criteria]
        if len(set(criteria)) != len(criteria):
            return f"task '{task.title}' contains duplicate acceptance criteria"
    return ""


def derive_tasks_from_goal(
    goal: str,
    cycle: int,
    validator_feedback: str = "",
) -> list[Task]:
    """Create a deterministic fallback using syntax only, never domain keywords."""
    feedback = validator_feedback.strip()
    if feedback:
        findings = validator_error_findings(feedback)
        repair_items = findings if len(findings) > 1 else [feedback]
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=validator_repair_title(item),
                description=(
                    "Make the smallest maintainable project change needed "
                    "to satisfy the goal and address this validator feedback:\n"
                    f"{format_validator_feedback(item, DEFAULT_TASK_FEEDBACK_LIMIT)}"
                ),
                acceptance_criteria=[
                    "The validator feedback is addressed",
                    "The requested behavior is implemented",
                    "Relevant validator checks pass",
                ],
            )
            for index, item in enumerate(repair_items, 1)
        ]

    deliverables = _fallback_goal_units(goal)
    if len(deliverables) >= 2:
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=short_task_title(item[0]),
                description=item[1],
                acceptance_criteria=item[2] or [
                    "This explicitly requested outcome is implemented",
                    "Relevant validator checks pass",
                ],
            )
            for index, item in enumerate(deliverables, 1)
        ]

    return [
        Task(
            id=f"c{cycle:02d}-t001",
            title="Implement requested change",
            description=(
                "Make the smallest maintainable project change needed "
                f"to satisfy the goal: {goal}"
            ),
            acceptance_criteria=[
                "The requested behavior is implemented",
                "Relevant validator checks pass",
            ],
        )
    ]


def validator_error_findings(feedback: str) -> list[str]:
    """Split bracket-tagged validator findings without assuming tag names."""
    findings: list[list[str]] = []
    current: list[str] = []
    for line in feedback.splitlines():
        if _STRUCTURED_FINDING.match(line):
            if current:
                findings.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        findings.append(current)
    return ["\n".join(lines).strip() for lines in findings if lines]


def validator_repair_title(feedback: str) -> str:
    first = feedback.strip().splitlines()[0] if feedback.strip() else ""
    match = _STRUCTURED_FINDING.match(first)
    if match:
        return short_task_title(f"Repair {match.group(1)}: {match.group(2)}")
    return "Repair validator failure"


def right_size_planned_tasks(
    goal: str,
    cycle: int,
    planned: list[Task],
    validator_feedback: str = "",
) -> list[Task]:
    """Keep model semantics; deterministic fallback is only for model failure."""
    del goal, cycle, validator_feedback
    return planned


def structured_goal_items(goal: str) -> list[str]:
    """Return explicit fallback units using Markdown hierarchy, not semantics."""
    items = [description for _title, description, _criteria in _fallback_goal_units(goal)]
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _normalized(item)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _fallback_goal_units(goal: str) -> list[tuple[str, str, list[str]]]:
    """Group section bullets under their heading instead of making noisy tasks."""
    lines = goal.splitlines()
    headings: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = _MARKDOWN_HEADING.match(line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))

    if headings:
        minimum = min(level for _index, level, _title in headings)
        at_minimum = [item for item in headings if item[1] == minimum]
        deeper = [item for item in headings if item[1] > minimum]
        task_level = (
            min(level for _index, level, _title in deeper)
            if len(at_minimum) == 1 and deeper
            else minimum
        )
        selected = [item for item in headings if item[1] == task_level]
        if len(selected) >= 2:
            units: list[tuple[str, str, list[str]]] = []
            for position, (start, _level, title) in enumerate(selected):
                end = len(lines)
                for next_start, next_level, _next_title in headings:
                    if next_start > start and next_level <= task_level:
                        end = next_start
                        break
                body_lines = lines[start + 1:end]
                body = "\n".join(body_lines).strip()
                description = title if not body else f"{title}\n{body}"
                criteria = _list_items(body_lines)
                units.append((title, description, criteria))
            return _unique_units(units)

    listed = _list_items(lines)
    if len(listed) >= 2:
        return _unique_units([(item, item, []) for item in listed])
    return []


def _list_items(lines: list[str]) -> list[str]:
    return [
        match.group(1).strip()
        for line in lines
        if (match := _LIST_ITEM.match(line))
    ]


def _unique_units(
    units: list[tuple[str, str, list[str]]],
) -> list[tuple[str, str, list[str]]]:
    result: list[tuple[str, str, list[str]]] = []
    seen: set[str] = set()
    for title, description, criteria in units:
        key = _normalized(description)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append((title, description, criteria))
    return result


def short_task_title(text: str, limit: int = 72) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    title = " ".join(first_line.split()).rstrip(".")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."
