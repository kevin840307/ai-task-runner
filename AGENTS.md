# AI / Maintainer Development Rules

These rules are mandatory for changes to this repository. `DevFollow.txt` is the concise owner contract and `Future.txt` is the UI-extension contract; maintenance must preserve both.

## Core engineering contract
- Never hardcode project-specific names, paths, workflows, FABs, environments, versions, filenames, sample values, model names, or business values into generic Runner logic.
- A behavior that is conceptually the same must use one shared function/implementation. Reuse existing helpers before adding code; do not create parallel parsers, retry loops, path guards, prompt builders, or validation wrappers.
- Prefer the smallest production change that solves the demonstrated problem. Do not add speculative frameworks, abstraction layers, or future-only configuration.
- Keep code concise, readable, and explicit. Prefer short functions with clear names over clever indirection.
- Folder, Python filename, class/function, and field names must describe their actual responsibility. Split/merge only when it makes ownership clearer; avoid vague dumping-ground modules.
- Preserve current behavior outside the requested scope.
- Remove obsolete/dead compatibility code when its replacement is complete; do not keep parallel old/new implementations.
- Public capabilities should have one clear owner/import path. Do not add re-export-only exposure modules or package-level compatibility aliases unless they enforce a real architectural boundary.
- Keep all human-facing maintained documentation bilingual: English `.md` plus matching Traditional Chinese `.zh-TW.md`, with both versions aligned to current behavior.
- Keep Workflow topology declarative so Stages can be added, moved, replaced, or removed without business branches in Pipeline/Executor.
- Do not make tests pass by weakening production guarantees or by adding project-specific branches.
- Python Runner code orchestrates generic flow/state/retry/recovery/protection/validation. Requirement-specific behavior belongs in goals, validators, project policy, templates, or project code.

## Session and prompt rules
- Final AI validation runs must use independent fresh sessions; N configured runs means N different sessions.
- Structured-output recovery retries at most twice in the same session before configured fresh fallback.
- Fresh or rebuilt sessions receive all context required for that stage.
- Same-session follow-ups receive only new information and the next instruction; do not repeat static goal/task/context unnecessarily.
- Executor may receive Original Goal in fresh/rebuilt sessions only as context/global constraints. Current TODO is always the only executable scope.
- Planning must create bounded implementation TODOs; no umbrella task may instruct the Executor to complete the whole goal.
- Review judges only the current TODO. Final Validator judges the complete goal.

## Structured model output
- All complete AI prompts must be sent through stdin, never embedded in argv/command text.
- All final model structured results must use the shared generic JSON candidate extraction path in `runner/ai/structured_output.py`.
- Envelope parsing may tolerate prose/Markdown/multiple JSON candidates; payload/schema validation remains strict.
- Do not guess, repair, or silently reinterpret malformed JSON or invalid schemas.

## Safety and state
- Respect project-root `.ai-task-runner.yaml` protected paths. The policy file itself is automatically protected.
- Do not modify protected fixtures, validator inputs, Runner source, or Runner-managed state through an AI call.
- AI must never `git add`, `git commit`, or `git push`; final Git acceptance is human-owned.
- Debug/history files must remain diagnostic side effects only and must not influence changed-file detection, progress, validation, or resume semantics.

## Validation
- Configured deterministic file validation is the authoritative correctness gate; it executes through the generic `command` Stage.
- Validators should check observable requirements, not how the Planner happened to split TODOs, except smoke tests explicitly testing planning behavior.
- Reuse `validator_interface.py` for validator reporting/entry handling.
- Keep validators deterministic and independent of model output.
