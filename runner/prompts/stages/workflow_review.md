Review only. Read-only: do not modify project files.
{{ always_instructions }}

Goal (context/global constraints only):
{{ goal }}

Review instructions:
{{ instructions }}

Previous Workflow Stage:
{{ previous }}

Judge the requested review instructions from current evidence, not from the previous stage summary alone. Inspect only the smallest relevant project subset; when behavior crosses project/module boundaries, verify the relevant contract on both sides.
PASS only when the review instructions are supported by evidence. FAIL only for concrete actionable blocking defects, and never return FAIL with an empty `missing_items`.

