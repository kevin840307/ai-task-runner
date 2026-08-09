# Prompt and Session Contract

Version: 1.1.1

## General rule
Fresh/rebuilt sessions must be self-contained for the stage. Same-session calls should send only new information and the next instruction. This reduces context growth and loop risk while preserving recoverability.

## Planning
- Understand: fresh session, goal/project root/progress/rules, bounded project read tools, no writes. No precomputed `Project files:` tree is injected.
- Finalize: same Understand session, no tools, only plan output contract and bounded-TODO rules.
- Fresh minimal fallback: new no-tool session with goal, project root, progress, validator feedback, and successful inspection summary.
- Refiner/Judge: fresh no-tool sessions with candidate tasks and required context. Judge prompts include both FAIL and PASS examples.

## Execution
- Fresh/rebuilt: Original Goal is supplied once as context/global constraints; Current TODO is the only executable scope. The prompt keeps only cross-stage safety boundaries plus executor-specific rules, shared constraints, and relevant validator/review recovery evidence. Scope/session wording is not duplicated inside `Run context`.
- Same-session retry: short `execution_continue` prompt only. Do not repeat Original Goal, full task JSON, static rules, or old output; send only new review/validator/recovery information.

## Review
- Fresh, read-only, scoped to the Current TODO. It receives task/global constraints plus executor and relevant validator evidence, but does not preload a changed-files list or generic write/git/shell rules. It reads only the smallest directly related file subset needed for unresolved acceptance criteria.
- Same-session Finalize after resumable error: no tools, use already gathered evidence and emit JSON verdict. Both FAIL and PASS examples are shown.

## Final validation
Final AI Validator always uses a fresh independent session and sees the complete goal. File validator is deterministic and model-independent.

## Rule injection
`instructions.always` from project policy is appended to every relevant model call. `instructions.project` is maintained in generated project agent-rule files. Same behavior should not be duplicated in individual prompt templates.

Decision-only Qwen stages remain logically no-tool: the prompt forbids tool use. For OpenAI-compatible endpoints that reject an empty `tools` array, Runner leaves exactly one built-in read-only compatibility tool (`read_file`) discoverable while excluding mutating, shell, skill, agent, MCP-style, and other unnecessary tools. Normal decision output must not use the compatibility tool.
