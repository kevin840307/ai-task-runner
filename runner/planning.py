"""Language- and technology-neutral planning helpers."""
from __future__ import annotations

import re

from .defaults import DEFAULT_TASK_FEEDBACK_LIMIT
from .models import Task
from .prompting import format_validator_feedback


_STRUCTURED_FINDING = re.compile(r"^\s*\[([^\]\r\n]+)\]\s+(.+?)\s*$")
_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
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
        if len(structured_goal_items(task.description)) > 1:
            return f"task '{task.title}' contains multiple explicitly structured outcomes; split it"
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

    deliverables = structured_goal_items(goal)
    if len(deliverables) >= 2:
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=short_task_title(item),
                description=item,
                acceptance_criteria=[
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
    """Use syntax-derived fallback only when it preserves more explicit items."""
    if validator_feedback.strip():
        return planned
    fallback = derive_tasks_from_goal(goal, cycle)
    return fallback if len(fallback) > len(planned) else planned


def structured_goal_items(goal: str) -> list[str]:
    """Extract explicit Markdown headings and list items without semantics."""
    segments: list[tuple[str, list[str]]] = []
    heading = ""
    lines: list[str] = []

    def flush() -> None:
        nonlocal heading, lines
        if heading or lines:
            segments.append((heading, lines))
        heading = ""
        lines = []

    for line in goal.splitlines():
        match = _MARKDOWN_HEADING.match(line)
        if match:
            flush()
            heading = match.group(1).strip()
        else:
            lines.append(line)
    flush()

    items: list[str] = []
    for section_title, section_lines in segments:
        listed = [
            match.group(1).strip()
            for line in section_lines
            if (match := _LIST_ITEM.match(line))
        ]
        if listed:
            items.extend(
                f"{section_title}: {item}" if section_title else item
                for item in listed
            )
            continue
        body = "\n".join(section_lines).strip()
        if section_title and body:
            items.append(f"{section_title}\n{body}")
        elif section_title:
            items.append(section_title)

    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = _normalized(item)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def short_task_title(text: str, limit: int = 72) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    title = " ".join(first_line.split()).rstrip(".")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."
