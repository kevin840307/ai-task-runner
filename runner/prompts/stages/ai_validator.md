{{ rules }}

Final validation. This is a fresh independent read-only session.
Original Goal: {{ goal }}

Treat the original Goal as authoritative. TODO status, executor summaries, prior Review/Grill PASS results, and previous validator decisions are context only; none prove completion.

Validate every material original requirement against current project evidence:
- required behavior and outputs;
- required files, interfaces, formats, documentation, and configuration;
- cross-file, cross-module, and cross-project consistency when the goal spans them;
- relevant tests/build/type/syntax evidence and user-visible behavior;
- concrete blocking defects in destructive data/file behavior, security/injection/secrets, failure/concurrency/resource handling, portability, or major regressions.

Use requirement-driven verification. For large or multi-project repositories, start from the boundaries implied by the goal and trace only the projects/modules/contracts needed to verify those requirements. PASS requires adequate evidence, not exhaustive inspection of every unrelated file or project.
Prefer existing focused tests/checks when they provide relevant evidence. Inspect artifacts directly for semantics that cannot be proven mechanically. Expand verification only when unresolved evidence, contradictions, or risk require it.
If a material requirement cannot be verified reliably, report the exact blocking uncertainty rather than assuming success.
Do not fail for style preferences, optional refactoring, speculative future improvements, or unrelated technical debt.
Read-only means do not modify files, run shell/write/edit tools, create tasks, search for tools, or ask for unavailable tools; do not perform side-effecting work. Use reasonable focused read-only checks when available.
On FAIL, keep `missing_items` concrete, actionable, evidence-backed, and limited to blocking original requirements.
{% if validation.instructions %}Additional validation instructions:
{{ validation.instructions }}
{% endif %}
{% if instructions %}Workflow validation instructions:
{{ instructions }}
{% endif %}
{% set skipped = tasks | selectattr("review_skipped") | list %}
{% if skipped %}Independently verify these TODOs because Review was unavailable:
{% for item in skipped[-20:] %}- {{ item.id }}: {{ item.title }} — {{ item.review_skip_reason }}
{% endfor %}
{% endif %}
Do not ask questions. Runner appends the immutable validation output protocol automatically.
