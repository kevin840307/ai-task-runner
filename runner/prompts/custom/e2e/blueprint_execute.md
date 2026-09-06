# Generic E2E Blueprint Task

Goal: {{ goal }}
Project root: {{ project.root }}

Current TODO:
{{ task | tojson }}

Read `result/system/workflow1/preflight.yaml` first. Complete only the current TODO.

## Language contract

- Prefer Traditional Chinese (zh-TW) for human-readable output fields when practical, especially `title`, `description`, `intent`, `role`, `claim`, summaries, review reasons, and open questions.
- Keep machine/technical identifiers unchanged: IDs, YAML keys, enum values, file paths, code symbols, API/SQL/table/class/function names, protocol/status tokens, and test references.
- Do not translate identifier values such as `FLOW-001`, `critical`, `SUPPORTED`, endpoint paths, method names, or SQL object names.

## Core rule

Work from **business / user-observable E2E behavior**, not from a fixed static-analysis pipeline.
Source code is only one possible evidence source. This workflow must also work for projects described by documentation, SPEC, OpenAPI, SQL/DDL, configuration, workflow files, samples, existing tests, logs, or combinations of these.

For the current flow, answer only what is useful:

`trigger -> important conditions/branches -> participating components/boundaries -> observable outcome/terminal state`

Use implementation details only when they help prove that behavior. Do not enumerate every class/function/file just because it exists.

## Evidence rules

- Prefer current project/material truth over prior generated output.
- Never modify `../material/`, `Runner E2E framework files`, Runner state, request files, or other protected inputs.
- A source locator may point to code, docs, API/SPEC, DDL/SQL, config, workflow, sample/test, or runtime evidence.
- If something is plausible but not proven, mark it `ASSUMPTION` and state the open question. Never promote a guess to `PROVEN`/`SUPPORTED`.
- Do not create speculative edge cases merely to increase case count.
- Preserve valid Blueprint content produced by earlier TODOs. Merge; do not rewrite unrelated flows.

## Canonical portable output

Maintain these four files under `result/blueprint/export/`.

### `architecture.yaml`

```yaml
version: 1
artifact_kind: e2e_architecture_blueprint
scope: <what system/feature this blueprint covers>
components:
  - id: CMP-001
    name: <name>
    kind: internal | external | actor | data_store | queue | other
    role: <繁體中文 E2E role>
    source_refs: [EV-001]
flows:
  - id: FLOW-001
    title: <繁體中文 business flow title>
    trigger: <繁體中文：what starts it>
    entrypoint: <optional user/API/job/event entry>
    steps:
      - <繁體中文 meaningful E2E step>
    terminal_outcomes:
      - <繁體中文 observable success/failure/end state>
    source_refs: [EV-001]
open_questions: []
```

### `e2e_cases.yaml`

```yaml
version: 1
artifact_kind: e2e_case_blueprint
cases:
  - id: E2E-001
    title: <繁體中文 case title>
    flow_ref: FLOW-001
    intent: <繁體中文：what risk/behavior this proves>
    priority: critical | major | normal
    given: [<繁體中文 precondition>]
    when: [<繁體中文 business action/event>]
    then: [<繁體中文 observable oracle/state>]
    evidence_level: PROVEN | SUPPORTED | ASSUMPTION
    source_refs: [EV-001]
    tags: []
```

### `evidence_index.yaml`

```yaml
version: 1
artifact_kind: evidence_index
evidence:
  - id: EV-001
    kind: source_code | documentation | api_spec | database | configuration | workflow | sample | test | runtime | user_requirement | other
    source: <portable path/ref>
    locator: <symbol/section/line/key/table/endpoint when useful>
    claim: <繁體中文：what this evidence supports>
```

### `manifest.yaml`

Keep it minimal. Final Python recomputes counts/fingerprints.

```yaml
version: 1
artifact_kind: e2e_blueprint_pack
authority: derived_hint
```

## Case design

Prefer a small set of meaningful cases covering materially different behavior: primary success, business-changing branches/modes, important failures/retries, async/concurrency/idempotency behavior, and recovery paths **only when relevant evidence exists**. Assertions must end at a meaningful observable outcome, durable state, emitted event/message, external response, or other real oracle—not merely “method was called”.

Finish only the current TODO. Final Python and fresh AI perform the final qualification.
