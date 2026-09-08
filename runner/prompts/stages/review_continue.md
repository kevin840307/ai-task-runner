Re-review the CURRENT result for the same TODO in this same read-only review session. The original review rules and JSON contract remain in context.
do not reuse the previous verdict after repair. Re-evaluate only the requirements affected by new executor/validator evidence plus any criterion that was previously unresolved.
Read the minimum directly related project evidence needed. Do not repeat the same successful inspection/tool call in this re-review attempt. At most one successful read is allowed per path/range unless new evidence proves it changed; If a repeated read reports `Unchanged`, use the previous content and decide.
Prefer evidence named by the task, acceptance criteria, executor evidence, tests, or validator feedback. Do not inspect workflow, runner state, prompt, or validator implementation files unless the current TODO explicitly names them as deliverables.
Do not repair, update, write, edit, run shell commands, create tasks, search for tools, or ask for unavailable tools. If a tool is unavailable or repeated inspection adds no evidence, stop trying tools and decide from available evidence.

New executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
Only report concrete requirements that remain unsatisfied now. Do not repeat a previous missing item if it is now satisfied, and do not invent one to force FAIL. If no concrete missing item remains, return PASS with `missing_items: []`.
Return only one valid review JSON decision using the original contract.
