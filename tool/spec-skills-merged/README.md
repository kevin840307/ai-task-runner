# Spec Skills — Auto-depth Generator + Independent Validator

Two self-contained AI agent skills. Copy `spec-generator/` and `spec-validator/` into your agent's skills folder. Both use `SKILL.md` with bundled detailed references.

- `spec-generator`: supply goal as `{{goal}}`; automatically selects Simple or Complex spec layout, writes only spec documents.
- `spec-validator`: supply `SPEC_PATH`; independently inspects repository and writes only `validation.md`.

**External Loop:** Generator → Validator → (`REVISE` → Generator) until `PASS`, `BLOCKED` or `NO_PROGRESS`. The external orchestrator must also impose an iteration/timeout budget. When Validator requests `REQUIRED_SPEC_DEPTH: COMPLEX`, keep Complex for this task. No product code modification occurs in either skill.

**Simple layout:** `spec.md`, `todo.md`, `validation.md`.

**Complex layout:** `requirements.md`, `comparison.md`, `validation.md`, plus per proposal `design.md`, `changes.md`, `todo.md`, `tests.md`, `tradeoffs.md` and conditional `details/`. One proposal by default, additional proposals only for meaningful architecture differences.
