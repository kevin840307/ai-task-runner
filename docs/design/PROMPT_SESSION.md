# Prompt and Session Contract

## Prompt variables

Prompt variables are a public contract, not ad-hoc dictionaries. `runner/prompts/context.py` builds the supported Stage context. Templates may use these top-level names:

- `goal`: original user goal.
- `stage`: current Stage name.
- `task`: current TODO data or `None`.
- `tasks`: normalized TODO list.
- `workflow`: current cycle and validator feedback needed by Stage templates.
- `validation`: validator path, feedback, and optional validator instructions.
- `project`: project root.
- `planning`: planning-only normalized progress/inspection context.
- `rules`, `always_instructions`: shared rendered instruction text.

Templates must not reference internal Python objects such as `state`, `args`, or `scratch`.

All bundled prompts use one Jinja loader with `StrictUndefined`. A missing or misspelled variable fails immediately instead of silently rendering an empty value. `{% include %}` is supported for shared prompt fragments/output contracts.

## Stage prompt ownership

Ordinary AI work: `stage: ai` plus a Workflow-relative instruction file.

Planning-specific computed context is handled inside `PlanStage`. Write and Review behavior share `BaseStage`; `mode: review` selects the readonly structured Review contract. There is no prompt-builder registry.

## Session policy

- Initial call: render the full Stage prompt.
- Same-session recovery: send only a short stage-aware delta: current Stage identity, new failure evidence, readonly reminder when applicable, and the required next action/output contract. Do not resend known full context.
- Fresh/rebuilt session: prepend only a short recovery header, then resend the original complete Stage prompt. The Stage prompt itself owns goal/task/rules, so the wrapper never duplicates them.
- Final AI validation runs use independent fresh sessions; three configured runs therefore use three different sessions.
- Structured-output parse failure first uses a short same-session JSON-only correction containing only parser feedback; configured fresh fallback starts a new session and resends the full Stage prompt.

Full AI task prompts are passed through stdin and never embedded in argv. Qwen `/context` and `/compress-fast` are short backend control commands, not task prompts, so they may use the CLI control-argument path.

## Prompt size rules

- Global engineering/safety rules live in shared rules, not repeated in every TODO acceptance criterion.
- Planning emits only task-specific, objectively checkable acceptance criteria.
- Stage prompts prefer short scope/evidence/action/contract language over repeated prose or long example lists.
- JSON output examples are intentionally retained because they materially improve structured-output reliability on smaller models.
