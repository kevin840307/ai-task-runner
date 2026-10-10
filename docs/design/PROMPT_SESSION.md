# Prompt and Session Contract

The runtime keeps prompt semantics small and shared across Stage types.

## One Stage prompt, one shared control envelope

A Stage template defines only its semantic responsibility. Retry/continue/recover behavior is not maintained as separate prompt files.

The effective AI input is:

```text
Stage prompt
+ Runner-owned shared control envelope when needed
+ immutable structured output protocol when the Stage requires one
```

The shared control envelope may contain:
- current Stage name;
- mode: continue / retry / recover;
- attempt number;
- whether the current call is using the same Session;
- bounded previous error;
- bounded Review/Validator feedback;
- bounded current Task evidence.

It must not duplicate large unchanged Goal/project context unnecessarily.

## Initial vs same-session continuation vs fresh recovery

### Initial
Render the complete Stage prompt.

### Same Session continuation/retry
When the Session has already seen this Stage prompt contract, send only new control/evidence context plus the immutable output protocol. Preserve valid prior work and do not restart unchanged discovery.

### Fresh/rebuilt Session
Render the complete Stage prompt again, prefixed only by a short recovery control envelope. The Stage prompt remains the single source of semantic role/goal instructions.

## Dynamic Handoff prompts

The coordinator uses `common/handoff.md` and returns one structured allowed target.

Ordinary Dynamic specialist roles normally share `common/dynamic_worker.md`:

```text
Goal
+ Assigned responsibility (Stage instructions)
+ Handoff context
+ shared specialist rules
```

Role specialization belongs in the Stage's `instructions`. Use a dedicated prompt only when a role needs a materially different protocol, tool contract or output format.

Independent final validation uses the normal AI Validator prompt and should normally use `session_policy: fresh`.

## Session policy

Routing and Session lifetime are independent.

- `session_policy: role` — durable reusable Session owned by the Stage name. Dynamic specialist default.
- `session_policy: main` — reuse the Runner primary Session.
- `session_policy: fresh` — clear/start a new Session on every invocation.
- `session_policy: auto` — built-in/default profile behavior.

`RunState.stage_sessions` stores durable role Sessions. If a role repeatedly fails technically, StageExecutor may reset only that role Session and continue in a fresh Session. Other roles are not reset.

## Read-only Stages

Review/validation/read-only roles must make a verdict from available evidence. They must not silently turn themselves into repair/implementation agents.

If Review or Validator returns FAIL, FlowEngine follows the configured semantic FAIL route. Technical ERROR remains StageExecutor-owned and never becomes a graph edge.

## Prompt maintenance rules

- Keep one core prompt per semantic Stage behavior.
- Put role-specific differences in `instructions` when the protocol is otherwise identical.
- Do not create separate retry/recover/continue prompt files.
- Keep global engineering/safety rules in shared rules.
- Keep feedback bounded.
- Keep immutable result protocols Runner-owned.
- Do not introduce a prompt-builder hierarchy unless a real Stage protocol cannot be expressed by the existing template/context model.
