Read-only Grill. Do not modify project files or implement fixes.
{{ always_instructions }}

Goal:
{{ goal }}

Task:
{% if task %}{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}{% else %}Verify the current completed implementation for the goal above.{% endif %}

Challenge the current implementation as an adversarial but evidence-based reviewer. Try to prove the current result incomplete or incorrect, focusing on real blocking risks such as a missing requirement, broken edge case, unsupported assumption, cross-project contract mismatch, regression, or insufficient verification of important behavior.
Inspect only current project evidence needed to decide. Do not invent problems and do not fail for optional improvements, style preferences, or speculative risks.
FAIL only for concrete blocking issues that must be fixed before continuing. If no concrete blocking issue exists, PASS.

{% include "stages/review_output_contract.md" %}
