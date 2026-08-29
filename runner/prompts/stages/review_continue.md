Re-review the CURRENT result for the same TODO in this same read-only review session. The full review rules and JSON contract already remain in context.
Read protected/source files when needed; read-only means inspect but do not modify them.
Re-read the new executor evidence and the minimum directly related project evidence needed. do not reuse the previous verdict after repair.
Do not repeat the same successful inspection/tool call in this re-review attempt; once a file/range has been read successfully, use that evidence unless a different target/range is concretely needed.
At most one successful read is allowed per path/range. If a repeated read reports `Unchanged`, treat the previous content as still current and return the JSON decision immediately. If a deliverable file was read and a required item is absent, return FAIL immediately without rereading.
Prefer evidence files named by the task, deliverable, acceptance criteria, executor evidence, or validator feedback. Do not inspect workflow, runner state, prompt, or validator implementation files unless the current TODO explicitly names them as deliverables.
Do not repair, update, write, edit, run shell commands, create tasks, search for tools, or ask for unavailable tools. If the prior attempt failed because a tool was unavailable, repeated, or timed out, stop trying tools and return the JSON verdict from available evidence.
New executor evidence:
{{ task.last_output[-3000:] }}
{% if validation.feedback %}Relevant validator feedback:
{{ validation.feedback[-2000:] }}
{% endif %}
Only report concrete requirements that are still unsatisfied now. Do not repeat a previous missing item if it is now satisfied, and do not invent one to force FAIL. If no concrete missing item remains, return PASS with `missing_items: []`.
Return only one valid review JSON decision using the original contract.
