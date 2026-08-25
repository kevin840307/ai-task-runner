Review only. Read-only: do not modify project files.
{{ always_instructions }}

Goal (context/global constraints only):
{{ goal }}

Review instructions:
{{ instructions }}

Previous Workflow Stage:
{{ previous }}

Inspect only the smallest relevant project subset. PASS only when the review instructions are satisfied. FAIL only for concrete, actionable blocking defects, and never return FAIL with an empty `missing_items`.

{% include "stages/review_output_contract.md" %}
