"""Example Task producer with producer-defined child Workflow."""
from __future__ import annotations

import json


def main() -> int:
    print(json.dumps({
        "tasks": [
            {
                "id": "inspect",
                "title": "Inspect current project",
                "description": "Inspect the current project and identify the smallest change needed by the goal.",
                "deliverable": "A focused implementation aligned with the current project.",
                "acceptance_criteria": [
                    "The requested behavior is implemented without unrelated changes."
                ],
            },
            {
                "id": "verify",
                "title": "Verify the result",
                "description": "Verify the completed change with the project's available checks.",
                "deliverable": "Verification evidence for the requested behavior.",
                "acceptance_criteria": [
                    "Relevant checks pass or actionable failure evidence is reported."
                ],
            },
        ],
        "stages": [
            {
                "name": "inspect_execute",
                "type": "base",
                "profile": "execute",
                "task_id": "inspect",
            },
            {
                "name": "inspect_review",
                "type": "base",
                "profile": "review",
                "task_id": "inspect",
                "task_complete": True,
                "error_policy": {"retries": 2},
                "max_failures": 3,
                "routes": {"fail": "inspect_execute"},
            },
            {
                "name": "verify_execute",
                "type": "base",
                "profile": "execute",
                "task_id": "verify",
            },
            {
                "name": "verify_review",
                "type": "base",
                "profile": "review",
                "task_id": "verify",
                "task_complete": True,
                "error_policy": {"retries": 2},
                "max_failures": 3,
                "routes": {"fail": "verify_execute"},
            },
        ],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
