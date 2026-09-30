{{ rules }}

Final validation for a completed Discussion / Group Chat. This is a fresh independent session.

Original Goal:
{{ goal }}

Discussion history:
{{ discussion.history }}

Judge result:
{{ previous }}

Treat the Goal as authoritative and the discussion as evidence, not proof.
Independently decide whether the final conclusion adequately satisfies the Goal.
Check contradictions, unresolved blocking points, unsupported conclusions, and any material evidence gaps.
PASS only when the discussion result is sufficiently supported to complete the Workflow.
On FAIL, return concrete missing_items that the next discussion cycle can resolve.

{% if validation.instructions %}Additional validation instructions:
{{ validation.instructions }}
{% endif %}
{% if instructions %}Workflow validation instructions:
{{ instructions }}
{% endif %}
Do not ask questions. Runner appends the immutable validation output protocol automatically.
