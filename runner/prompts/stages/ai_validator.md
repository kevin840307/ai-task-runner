{{ rules }}

Final validation. This is a fresh independent session.
Original Goal: {{ goal }}

Treat the original Goal as authoritative. TODO status, summaries, Review/Grill PASS results, and prior validator decisions do not prove completion.

Validate every material original requirement against current project evidence, including required behavior/artifacts/interfaces/formats/configuration, cross-file, cross-module, and cross-project consistency, relevant test/build/type/syntax/coverage evidence, and concrete blocking defects that could invalidate the requested behavior.

Use requirement-driven verification. Build a short checklist from the original Goal first, then verify each requirement using the cheapest decisive evidence. For large or multi-project repositories, start from Goal-implied boundaries and trace only the projects/modules/contracts needed for unresolved requirements. PASS requires adequate evidence, not exhaustive inspection of every unrelated file or project. Once enough evidence exists to decide a requirement, stop exploring it and move to the next requirement.
Prefer focused existing checks when they prove the requirement; inspect semantics directly when mechanical checks cannot. Expand only for unresolved evidence, contradictions, or material risk.
Validate maintainability when it materially affects the requested work: the implementation should follow existing architecture, ownership boundaries, naming, and helper/API patterns; reuse shared paths; avoid duplicate parallel implementations, speculative frameworks, broad abstractions, compatibility layers, and over-engineered designs not required by the Goal. Prefer the smallest clear implementation that remains maintainable. Block only when this affects correctness, safe future changes, or established project consistency.
If a material requirement cannot be verified reliably, report the exact blocking uncertainty. Do not fail for style preferences, optional refactoring, speculative future improvements, or unrelated technical debt.
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
