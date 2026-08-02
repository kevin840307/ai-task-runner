"""Planning and deterministic task derivation helpers."""
from __future__ import annotations

import re

from .models import Task
from .prompting import format_validator_feedback


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
                    "Relevant validator checks pass",
                ],
            )
            for index, item in enumerate(repair_items, 1)
        ]
    deliverables = markdown_goal_sections(goal)
    if len(deliverables) < 2:
        deliverables = numbered_goal_items(goal)
    if len(deliverables) < 2:
        deliverables = deliverable_goal_items(goal)
    if len(deliverables) >= 2:
        return [
            Task(
                id=f"c{cycle:02d}-t{index:03d}",
                title=short_task_title(item),
                description=item,
                acceptance_criteria=[
                    "This deliverable is implemented",
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
        if match:
            items.append(match.group(1))
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
        if not body or is_context_section_title(title):
            continue
        expanded = split_markdown_section_items(title, body)
        items.extend(expanded or [f"{title}\n{body}"])
    return items


def split_markdown_section_items(title: str, body: str) -> list[str]:
    bullets = [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*-\s+(.+?)\s*$", body)
        if should_split_list_item(match.group(1))
    ]
    numbered = [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*\d+[\).]\s+(.+?)\s*$", body)
        if should_split_list_item(match.group(1))
    ]
    if len(bullets) >= 2:
        return [f"{title}: {item}\n{body}" for item in bullets]
    if len(numbered) >= 2:
        return [f"{title}: {item}\n{body}" for item in numbered]
    return []


def should_split_list_item(text: str) -> bool:
    lowered = text.strip().lower()
    if lowered.startswith(("do not ", "don't ")):
        return False
    return bool(lowered)


def is_context_section_title(title: str) -> bool:
    lowered = title.strip().lower()
    return any(word in lowered for word in ("sample", "example", "background"))


def deliverable_goal_items(goal: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"\n\s*\n", goal) if part.strip()]
    if len(parts) >= 2:
        paragraphs = paragraph_goal_items(parts)
        if len(paragraphs) >= 2:
            return paragraphs
    parts = split_goal_sentences(goal)
    items: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not has_file_reference(part):
            continue
        normalized = " ".join(part.split())
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(normalized)
    return items


def paragraph_goal_items(parts: list[str]) -> list[str]:
    items = [
        normalize_item(part)
        for part in parts
        if not is_runner_instruction(part)
    ]
    if len(items) >= 4:
        items = items[1:]
    return items


def normalize_item(text: str) -> str:
    return " ".join(text.split())


def is_runner_instruction(text: str) -> bool:
    lowered = text.strip().lower()
    return lowered.startswith(("do not ask", "don't ask", "expected command"))


def split_goal_sentences(goal: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", goal).strip()
    if not normalized:
        return []
    pieces = re.split(
        r"(?<=[.!?。！？；;])\s+|\s+(?:and|then|also|plus)\s+",
        normalized,
        flags=re.IGNORECASE,
    )
    return [piece.strip(" -.;:") for piece in pieces if piece.strip(" -.;:")]


def has_file_reference(text: str) -> bool:
    if is_runner_instruction(text):
        return False
    return bool(re.search(r"\b[\w.-]+\.[A-Za-z0-9]{1,8}\b", text))


def short_task_title(text: str, limit: int = 72) -> str:
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    title = " ".join(first_line.split()).rstrip(".")
    return title if len(title) <= limit else title[: limit - 1].rstrip() + "..."
