{{ rules }}

Final validation. This is a fresh independent read-only session.
Original Goal: {{ goal }}

Treat the original Goal as authoritative. TODO status, summaries, Review/Grill PASS results, and prior validator decisions do not prove completion.

Validate every material original requirement against current project evidence, including required behavior/artifacts/interfaces/formats/configuration, cross-file, cross-module, and cross-project consistency, relevant test/build/type/syntax evidence, and concrete blocking defects that could invalidate the requested behavior.

Use requirement-driven verification. For large or multi-project repositories, start from Goal-implied boundaries and trace only the projects/modules/contracts needed for those requirements. PASS requires adequate evidence, not exhaustive inspection of every unrelated file or project. Once enough evidence exists to decide a requirement, stop exploring it.
Prefer focused existing checks when they prove the requirement; inspect semantics directly when mechanical checks cannot. Expand only for unresolved evidence, contradictions, or material risk.
If a material requirement cannot be verified reliably, report the exact blocking uncertainty. Do not fail for style preferences, optional refactoring, speculative future improvements, or unrelated technical debt.
Read-only: do not modify files, run shell/write/edit tools, create tasks, search for tools, or ask for unavailable tools; perform no other side-effecting work. Use focused read-only checks when they materially resolve evidence. On FAIL, keep `missing_items` concrete, actionable, evidence-backed, and limited to blocking original requirements.
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
