# Workflow Builder Skill

You are generating an AI Task Runner Workflow package.

Goal:
{{ goal }}

Rules:
- Create only the draft Workflow and Prompt files requested by the goal.
- Do not edit application source code or Runner source code.
- Keep the Workflow small and explicit. Prefer Stage defaults over repeated YAML options.
- Use only supported Stage types: base, task, review, plan, ai_validator, command.
- A standard top-level plan automatically expands the default per-task execute/review SOP; do not duplicate that task flow unless the requested SOP explicitly needs a custom task producer or task-scoped stages.
- Python validation is a command Stage with `result_kind: validation` and the standard `{validator}` command contract when requested.
- AI validation is an `ai_validator` Stage with a Prompt reference when custom instructions are needed.
- Every Prompt reference must point to a Prompt file that you actually create in the requested draft Prompt directory.
- The Workflow must end with its final validation Stage when validation is present.
- Never create fake Prompt references, missing files, unsupported fields, or placeholder TODO content.
- Before finishing, read the generated Workflow and Prompt files back and self-check paths, Stage order, recover targets, and validation topology.

The external workflow-builder validator will reject missing files and will run the real `tool/workflow_dryrun.py` contract. Keep repairing the draft until that validator passes.
