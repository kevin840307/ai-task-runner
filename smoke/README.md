# Smoke Tests

Version: 1.1.1

Smoke projects exercise focused Runner/backend behaviors and small deliverables. Every smoke `project/` root contains `.ai-task-runner.yaml`; immutable input/reference data is protected, while target implementation/output files remain writable. Deterministic validators use `validator_interface.py`.

The `qwen_single_prompt_todo_split` smoke intentionally inspects Runner task state because planning decomposition is what it tests. Other smoke validators should judge deliverable correctness rather than Planner strategy.

Smoke prompts should state only behavior the case intends to test. Validators should check observable deliverables and must not add hidden formatting requirements; only the TODO-split smoke intentionally validates Runner planning state.

Committed smoke starters must not contain prior-run state, generated outputs, validator reports, model rule copies, or bytecode caches. Intentional immutable fixtures are the only exception.
