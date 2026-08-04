$rules

Review only. Do not edit project files or ask questions.

Inspect the current project and verify every acceptance criterion in the task. Also verify that the implementation is correctly scoped, maintainable, and preserves relevant existing behavior.

You may run read-only checks. Any generated artifacts are temporary and will be discarded.

Base the decision on the current project state, not only on the executor report.

If validator feedback is provided, treat it as authoritative evidence from the final validation. Do not mark the task complete unless every relevant reported failure has been fixed or is clearly proven unrelated or impossible.

Task:
$task_json

Executor report:
$output

$validator_section

Decision rules:

- Return PASS only when every acceptance criterion is satisfied.
- Return FAIL when any acceptance criterion is missing, incorrect, unverified, incomplete, or contradicted by validator feedback.
- For FAIL, list concrete remaining work in `missing_items`.
- Each `missing_items` entry must describe an actionable missing result, not a vague suggestion.
- Do not return FAIL with an empty `missing_items` array.
- Do not include Markdown, code fences, commentary, or text outside the JSON object.

Return exactly one JSON object using one of these forms:

FAIL:
{"completed":false,"reason":"One or more acceptance criteria are not satisfied.","missing_items":["Describe the specific missing or incorrect result."]}

PASS:
{"completed":true,"reason":"All acceptance criteria are satisfied.","missing_items":[]}
