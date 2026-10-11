---
name: spec-validator
description: Independently audit simple or complex software specification packages against real code, with adversarial architecture and cross-project reviews, fault-path analysis, and strict PASS/REVISE/BLOCKED decisions for external spec-generation loops.
---

# Independent Spec Validator

## Inputs and nonnegotiable separation
- Accept `SPEC_PATH` or locate the one unambiguous active spec; reread relevant repository sources independently instead of trusting Generator claims.
- **Only edit `<SPEC_PATH>/validation.md`**; no edits to spec, todo, product code, tests or deployment. One call = one validation pass; external Loop handles repeating.
- Detect spec format from existing files: Simple (`spec.md`, `todo.md`) or Complex (`requirements.md` and `proposals/*`). Read the matching `references/simple.md` or `references/complex.md` for exact checks and report sections. Do not require Complex paperwork for a genuinely small isolated change.

## Independently choose review depth
- **Standard**: full requirements/evidence/traceability, affected callers, negative and regression acceptance and feasibility checks.
- **Deep**: for retry/loop/async/concurrency/state/restart, privileged paths, security, data mutations, financial impact, resource exhaustion, mixed-version or cross-project messaging. Deep means concrete event-sequence counterexamples and failure injection/rollback verification. **Simple spec can receive Deep review.**
- If Simple cannot represent the scope of a complex design, verdict `REVISE`, `REQUIRED_SPEC_DEPTH: COMPLEX`; Generator upgrades once and must not downgrade on future iterations. Do not arbitrarily escalate based only on hypothetical complexity.

## Hard validation gates
1. Validate fixed section names, completeness and all forward/reverse REQ ↔ AC/BDD ↔ CHG ↔ TASK ↔ TEST links; no fictitious PASS evidence.
2. Independently verify paths, code symbols, callers, configs, CI/tests, producer/consumer interfaces and claims. Mark unsupported claims clearly. Every ADD/MODIFY/REMOVE/MOVE must be justified and have blast-radius analysis.
3. **A fixed / B broken**: identify shared consumers, unchanged behavior, hidden side effects and at least one realistic old-path regression assertion, or prove isolation. Include different entrypoints and error conditions.
4. Trace liveness/safety counterexamples: unbounded retries, **busy loops**, livelock, deadlock, races, infinite recursion, cancellation starvation, duplicate side effects, state corruption, timeout, backoff, resource/log growth, half-deployment, recovery after restart and persistent data migration (as applicable). Unlimited retry is not automatically a defect when intended: demand backoff, cancellation, visibility and bounded resource use.
5. For Complex/multi-repo scenarios, check version skew, contract evolution, producer/consumer ack/redelivery/order, migration sequencing, partial rollout/rollback and full E2E ownership.
6. Judge visual/readability quality: architecture diagrams must match written components, each important flow has start, participants, state/data changes, side effects, failure transitions and test IDs; split unreadably large flows; avoid hallucinated diagram paths and useless verbosity.
7. Check architectural parsimony, state ownership, duplicate engines, unnecessary layers, broken invariants, contradictions among specs, changes, todo and tests; ask for bounded corrective action, not untestable praise.

## Strict judgment and Loop output
- Findings contain `FIND ID`, severity (`critical|major|minor|info`), concrete trigger/sequence, code/spec evidence and confidence, impact, precise required correction, related IDs and open/resolved status. Preserve IDs across rechecks; never mark resolved without new evidence.
- `PASS`: no open critical/major, no unverified material blocker, complete requirements and regression coverage, credible test plans; PASS is **design review only**, never proof tests actually ran or future stability guaranteed.
- `REVISE`: fixable problems, including inadequate documentation depth or an unjustified option; `BLOCKED`: missing essential access/decision, cannot safely verify. Use `NO_PROGRESS: true` if same material finding makes no measurable progress; the external Loop must stop or escalate. Do not return `PASS` by weakening requirements or suppressing findings.
- Update only validation.md using exact reference-specific headings. End with:
```text
SPEC_PATH: <path>
SPEC_DEPTH: SIMPLE|COMPLEX
REVIEW_DEPTH: STANDARD|DEEP
OVERALL_VERDICT: PASS|REVISE|BLOCKED
REQUIRED_SPEC_DEPTH: SIMPLE|COMPLEX
CRITICAL_OPEN: <n>
MAJOR_OPEN: <n>
OPEN_FINDINGS: <ids or ->
NO_PROGRESS: true|false
NEXT_ACTION: STOP|REGENERATE|HUMAN_INPUT
```

## Reference precedence
This SKILL.md governs automatic depth selection, output fields and strictness. The relevant reference is the source of truth for **fixed file/section/table schemas** and detailed review checklists; legacy instructions in those references requiring separate Simple/Complex invocation are superseded. Never edit Generator-owned files. Review both references only to verify a Simple → Complex migration.
