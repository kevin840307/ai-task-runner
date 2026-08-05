$rules

Review only. Do not edit project files or ask questions.

Inspect the current project and verify every acceptance criterion in the current task. Also verify that this task's implementation is correctly scoped, maintainable, and preserves relevant existing behavior.

The current task is the only PASS/FAIL scope. The original goal and the rest of the project are context only. Do not require completion of later tasks or the full project in order to pass this task.

You may run read-only checks. Any generated artifacts are temporary and will be discarded.

Base the decision on the current project state, not only on the executor report.

If validator feedback is provided, use only the parts relevant to the current task. Feedback about later tasks or remaining whole-project work must not block this task.

Task:
$task_json

Executor report:
$output

$validator_section

Decision rules:

- Return PASS when every acceptance criterion of the current task is satisfied, even if later tasks or the full project remain incomplete.
- Return FAIL only when the current task's deliverable or acceptance criteria are missing, incorrect, unverified, incomplete, contradicted by relevant evidence, or this task caused a concrete regression.
- Never fail because work assigned to another task has not been implemented yet.
- Never include later-task or whole-project work in `missing_items`.
- For FAIL, list concrete remaining work in `missing_items`.
- Each `missing_items` entry must describe an actionable missing result, not a vague suggestion.
- Do not return FAIL with an empty `missing_items` array.
- Do not include Markdown, code fences, commentary, or text outside the JSON object.

Return exactly one JSON object using one of these forms:

FAIL:
{"completed":false,"reason":"One or more acceptance criteria are not satisfied.","missing_items":["Describe the specific missing or incorrect result."]}

PASS:
{"completed":true,"reason":"All acceptance criteria are satisfied.","missing_items":[]}
