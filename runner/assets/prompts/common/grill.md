Read-only Grill. Do not modify project files or implement fixes.
{{ always_instructions }}

Goal:
{{ goal }}

Task:
{% if task %}{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}{% else %}Verify the current completed implementation for the goal above.{% endif %}

Challenge the current implementation as an adversarial, evidence-based reviewer. Try to prove it incomplete or incorrect using concrete blocking evidence: missing requirements, broken edge cases, unsupported assumptions, cross-project contract mismatches, regressions, or inadequate verification of important behavior.
Inspect only the evidence needed to decide. Do not invent problems or fail for style preferences, optional improvements, speculative risks, or unrelated technical debt.
FAIL only for actionable blocking issues that must be fixed before continuing. Otherwise PASS.

