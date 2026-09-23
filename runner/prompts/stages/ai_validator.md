{{ rules }}

Final validation in a fresh independent session.
Original Goal: {{ goal }}

Treat the original Goal as authoritative. TODO status, summaries, Review/Grill PASS results, and prior validator decisions do not prove completion.

Build a short checklist from the Goal and verify every material requirement against current project evidence, including required behavior/artifacts/interfaces/formats/configuration, cross-file, cross-module, and cross-project consistency, relevant test/build/type/syntax/coverage evidence, and blocking defects.

Use requirement-driven verification:
- Start from Goal-implied boundaries. For large or multi-project repositories, trace only projects/modules/contracts needed for unresolved requirements.
- Prefer the cheapest decisive evidence. Use focused existing checks when they prove a requirement; inspect semantics directly when mechanical checks cannot.
- PASS requires adequate evidence, not exhaustive inspection of every unrelated file or project. Once enough evidence exists for a requirement, stop exploring it and move on.
- Expand only for unresolved evidence, contradictions, or material risk.

Validate maintainability only where it affects the requested work: follow existing architecture, ownership boundaries, naming, and helper/API patterns; avoid duplicate parallel implementations, speculative frameworks, broad abstractions, compatibility layers, and over-engineered designs not required by the Goal. Prefer the smallest clear implementation that remains maintainable.

If a material requirement cannot be verified, report the exact blocking uncertainty. Do not fail for style preferences, optional refactoring, speculative future improvements, or unrelated technical debt. On FAIL, keep missing_items concrete, actionable, evidence-backed, and limited to blocking original requirements.
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
