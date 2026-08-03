"""Planning and deterministic task derivation helpers."""
from __future__ import annotations

import re

from .models import Task
from .prompting import format_validator_feedback


TASK_SCOPE_CRITERION = "依目前架構+用最少程式碼完成"


def derive_tasks_from_goal(
    goal: str,
    cycle: int,
    validator_feedback: str = "",
) -> list[Task]:
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
                    f"{format_validator_feedback(item, 2000)}"
                ),
                acceptance_criteria=[
                    "The validator feedback is addressed",
                    "The requested behavior is implemented",
                    TASK_SCOPE_CRITERION,
                    "Relevant validator checks pass",
                ],
            )
            for index, item in enumerate(repair_items, 1)
        ]
    deliverables = markdown_goal_sections(goal)
    if not deliverables:
        deliverables = numbered_goal_items(goal)
    if not deliverables:
        deliverables = deliverable_goal_items(goal)
    if deliverables:
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=short_task_title(item),
                description=item,
                acceptance_criteria=[
                    "This deliverable is implemented",
                    TASK_SCOPE_CRITERION,
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
                TASK_SCOPE_CRITERION,
                "Relevant validator checks pass",
            ],
        )
    ]


def validator_error_findings(feedback: str) -> list[str]:
    findings: list[list[str]] = []
    current: list[str] = []
    for line in feedback.splitlines():
        if re.match(r"^\s*\[E[^\]]*\]\s+", line):
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
    match = re.match(r"^\s*\[(E[^\]]*)\]\s*(.+?)\s*$", first)
    if match:
        return short_task_title(f"Repair {match.group(1)}: {match.group(2)}")
    return "Repair validator failure"


def right_size_planned_tasks(
    goal: str,
    cycle: int,
    planned: list[Task],
    validator_feedback: str = "",
) -> list[Task]:
    """Use deterministic splitting when the planner under-splits deliverables."""
    if validator_feedback.strip():
        return planned
    fallback = derive_tasks_from_goal(goal, cycle)
    return fallback if len(fallback) > len(planned) else planned


def numbered_goal_items(goal: str) -> list[str]:
    items: list[str] = []
    for line in goal.splitlines():
        match = re.match(r"^\s*\d+[\).]\s+(.+?)\s*$", line)
        if match and should_keep_structured_item(match.group(1)):
            items.append(match.group(1).strip())
    return items


def markdown_goal_sections(goal: str) -> list[str]:
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []
    for line in goal.splitlines():
        match = re.match(r"^\s*#{2,3}\s+(.+?)\s*$", line)
        if match:
            if current_title:
                sections.append((current_title, current_lines))
            current_title = match.group(1).strip()
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))

    items: list[str] = []
    for title, lines in sections:
        body = "\n".join(lines).strip()
        if not body:
            continue
        if not is_reference_only_body(body):
            items.append(f"{title}\n{body}")
    return items


def list_item_texts(body: str) -> list[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(
            r"(?m)^\s*(?:[-*]\s+|\d+[\).]\s+)(.+?)\s*$",
            body,
        )
    ]


def is_reference_only_body(body: str) -> bool:
    items = list_item_texts(body)
    return bool(items) and all(is_reference_item(item) for item in items)


def should_keep_structured_item(text: str) -> bool:
    return bool(text.strip()) and not is_reference_item(text)


def is_reference_item(text: str) -> bool:
    """Skip list rows that are references or values, not work items."""
    cleaned = re.sub(r"`([^`]*)`", r"\1", text).strip()
    if re.match(r"^[\w{}./\\:-]+$", cleaned):
        return True
    if re.match(r"^[\w -]+:\s*[\w{}./\\:-]+$", cleaned):
        return True
    return False


def deliverable_goal_items(goal: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", goal) if part.strip()]
    if len(parts) < 2:
        return []
    return paragraph_goal_items(parts)


def paragraph_goal_items(parts: list[str]) -> list[str]:
    return [
        normalize_item(part)
        for part in parts
        if not is_reference_item(part)
    ]


def normalize_item(text: str) -> str:
    return " ".join(text.split())


def short_task_title(text: str, limit: int = 72) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    title = " ".join(first_line.split()).rstrip(".")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."
