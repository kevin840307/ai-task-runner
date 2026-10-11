---
name: spec-generator
description: Generate or revise evidence-backed BDD implementation specifications for software changes. Auto-select lightweight single-solution specs or detailed architectural/cross-repository specs; use for new feature plans, bug fixes, design proposals and external Generator/Validator loops.
---

# Spec Generator

## Input and boundaries
- User goal: `{{goal}}` (replace with actual request); existing `SPEC_PATH` and `validation.md` when revising.
- Read repository code, callers, existing tests, configuration, conventions and neighboring repositories where needed. Only write specification artifacts; never change production code or deploy.
- **One invocation is one Generator pass**. An external Loop invokes an independent Validator, then this Generator again if `REVISE`. Do not implement an internal self-loop. Keep IDs stable; never overwrite existing Validator findings.

## Autonomous routing: two independent dimensions
Choose **Spec Depth** from actual change scope and architectural impact, not size in lines:
- **Simple**: one bounded behavior change, fix or feature with clear scope, no major cross-project/contract/data migration. Generate `spec.md`, `todo.md`, `validation.md`; read `references/simple.md` for the exact sections and tables.
- **Complex**: cross-project/repository/service changes, major architecture/state ownership changes, substantial compatibility or migration design, or whenever Simple cannot explain necessary behavior. Generate `requirements.md`, `comparison.md`, `validation.md` and each proposal's `design.md`, `changes.md`, `todo.md`, `tests.md`, `tradeoffs.md`; read `references/complex.md` for exact sections.
- **Review Risk** is separate: a short retry, auth, destructive DB, concurrency, security or resource-lifecycle change may remain Simple but require deep failure analysis and regression coverage. Avoid increasing file count just because risk is high. If adequate analysis genuinely cannot fit Simple, upgrade to Complex.
- Default to **one** proposal. Introduce another (maximum three) only for materially different architecture with worthwhile trade-offs, not coding style or cosmetic variation.

## Mandatory design substance and readability
- Fixed headings from selected reference are mandatory; include only meaningful content in each section. Explain what is unchanged and what must not regress.
- Trace REQ/AC → change → TASK → TEST, and reverse-trace every changed shared component through affected callers/consumers: **fixing A must not break existing B**. Support claims with actual repo paths/symbols or mark `INFERRED` / `UNVERIFIED`.
- Explain current and target architecture, who owns state, data/control flow, errors, timeouts, stop/cancel, retries, idempotency and recovery as applicable. Split numerous flows into individually named scenarios with steps and narrative; use Mermaid diagrams only when helpful and always explain them in text.
- `todo.md` is always required, with dependency, completion gate and test mapping; planned tests are NOT executed tests.

## Revision handling / Loop contract
1. On first pass inspect sources, decide depth, create selected files; `validation.md` is a `NOT_RUN` placeholder.
2. On subsequent passes read existing findings; modify only Generator-owned spec files and keep user-approved requirements. Resolve or rebut each open finding with evidence; do not erase validation history.
3. Validator-requested **Complex** upgrade is sticky for this task; do not oscillate back to Simple. Preserve cross-references when upgrading; do not silently discard outstanding findings.
4. If critical user choices or unavailable essential repos block a grounded design, return `BLOCKED`; if repeated changes yield no progress, report `NO_PROGRESS`, never endlessly regenerate. External Loop owns retry budget.
5. End each response with machine-readable plain lines:
```text
SPEC_PATH: <path>
SPEC_DEPTH: SIMPLE|COMPLEX
GENERATOR_RESULT: READY_FOR_VALIDATION|BLOCKED
CHANGED_FILES: <paths or ->
ADDRESSED_FINDINGS: <ids or ->
REMAINING_BLOCKERS: <items or ->
```

## Reference precedence
The selected `references/simple.md` or `references/complex.md` supplies the **detailed, fixed Markdown section contract**. This SKILL.md overrides any older reference language requiring a manually selected separate Prompt or forbidding automatic depth changes. **Do not mix the two file layouts in one spec**; when upgrading, migrate once explicitly. Read only the relevant reference (both only when doing an upgrade).
