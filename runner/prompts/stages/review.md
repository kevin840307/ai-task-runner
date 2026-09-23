Review the current TODO only. {{ always_instructions }}

Start from the deliverable, acceptance criteria, and executor evidence. Reuse specific, internally consistent evidence; verify only material claims that remain uncertain. Inspect only the smallest files, tests, interfaces, or cross-project contracts needed to resolve a concrete uncertainty. Do not perform a fresh broad code review.

PASS and decide immediately when every acceptance criterion has adequate concrete evidence. FAIL only for an actual unsatisfied criterion or a material evidence gap. Check maintainability only where it affects correctness: prefer the smallest coherent solution, clear ownership, and no ad-hoc patch chain or unnecessary abstraction. Optional improvements are not blocking and are not stylistic preferences.

Task:
{{ {"title": task.title, "description": task.description, "deliverable": task.deliverable, "acceptance_criteria": task.acceptance_criteria} | tojson }}
Executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}

Only report concrete current-task requirements still unsatisfied. Runner appends the immutable review decision protocol automatically.
