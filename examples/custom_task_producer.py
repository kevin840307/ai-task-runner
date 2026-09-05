"""Example Task producer for custom_workflow_latest.yaml."""
from __future__ import annotations

import json


def main() -> int:
    print(json.dumps({
        "tasks": [
            {
                "title": "Inspect current project",
                "description": "Inspect the current project and identify the smallest change needed by the goal.",
                "deliverable": "A focused implementation aligned with the current project.",
                "acceptance_criteria": [
                    "The requested behavior is implemented without unrelated changes."
                ],
            },
            {
                "title": "Verify the result",
                "description": "Verify the completed change with the project's available checks.",
                "deliverable": "Verification evidence for the requested behavior.",
                "acceptance_criteria": [
                    "Relevant checks pass or actionable failure evidence is reported."
                ],
            },
        ]
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
