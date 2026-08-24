# Prompt and Session Contract

## Prompt variables

Prompt variables are a public contract, not ad-hoc dictionaries. `runner/prompts/context.py` builds the supported Stage context. Templates may use these top-level names:

- `goal`: original user goal.
- `stage`: current Stage name.
- `task`: current TODO data or `None`.
- `tasks`: normalized TODO list.
- `workflow`: cycle/progress/validator feedback/shared constraints.
- `validation`: validator path, feedback, and optional validator instructions.
- `project`: project/work paths.
- `session`: current AI session facts.
- `failure`: current attempt/error facts.
- `planning`: planning-only normalized context.
- `previous`: previous StageResult summary when supplied.
- `rules`, `always_instructions`: shared rendered instruction text.

Templates must not reference internal Python objects such as `state`, `args`, or `scratch`.

All bundled prompts use one Jinja loader with `StrictUndefined`. A missing or misspelled variable fails immediately instead of silently rendering an empty value. `{% include %}` is supported for shared prompt fragments/output contracts.

## Stage prompt ownership

Ordinary AI Stage: `workflow/definitions.py` + `prompts/stages/<name>.md`.

Planning-specific computed context is handled inside `PlanStage`. Ordinary AI stages use only `workflow/definitions.py` plus `prompts/stages/<name>.md`; there is no prompt-builder registry.

## Session policy

- Initial call: render the full Stage prompt.
- Same-session recovery: send only a short stage-aware delta: current Stage identity, new failure evidence, readonly reminder when applicable, and the required next action/output contract. Do not resend known full context.
- Fresh/rebuilt session: resend the original goal, current task when present, current project-state instruction, and full Stage instructions.
- Final AI validation runs use independent fresh sessions; three configured runs therefore use three different sessions.
- Structured-output parse failure first uses short same-session JSON-only correction; configured fresh fallback starts a new session and resends the full Stage prompt.

Full prompts are passed to Qwen through stdin, never embedded in argv.
