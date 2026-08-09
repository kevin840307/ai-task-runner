# Prompt and Session Contract

Version: 1.1.1

## General rule
Fresh/rebuilt sessions must be self-contained for the stage. Same-session calls should send only new information and the next instruction. This reduces context growth and loop risk while preserving recoverability.

## Planning

All in-run continuations reuse the existing logical client/session whenever it is still usable. Planning Understand/Finalize/Judge/Rewrite stay on one planning client/session; Executor retries and later TODOs stay on the main Executor session; Review alone intentionally starts fresh, then its Finalize reuses that Reviewer session. A single recoverable error does not discard a session. Invalid sessions reset immediately; repeated loop/no-progress failures trigger fresh rebuild. Transient API/network/rate-limit failures back off and retry without consuming session/task recovery. Structured-output errors use a short same-session correction before any rebuild. Process-level `--resume` may reconstruct the main client from saved state because the old Python client no longer exists.
- Understand: fresh session, goal/project root/progress/rules, bounded project read tools, no writes. No precomputed `Project files:` tree is injected.
- Finalize: same Understand session, no tools, only plan output contract and bounded-TODO rules.
- Fresh planning fallback: only after the current planning session cannot recover, clear its session and use the same planner client with a full-context prompt containing goal, project root, progress, validator feedback, and available inspection summary.
- Judge and Rewrite reuse the planning client/session. Judge may perform bounded read-only inspection if supplied/session context is insufficient; if Judge cannot produce a usable verdict, the quality gate remains fail-soft to the last valid plan. Rewrite runs only after rejection. Judge prompts include both FAIL and PASS examples.

## Execution
- Fresh/rebuilt: Original Goal is supplied once as context/global constraints; Current TODO is the only executable scope. The prompt keeps only cross-stage safety boundaries plus executor-specific rules, shared constraints, and relevant validator/review recovery evidence. Scope/session wording is not duplicated inside `Run context`.
- Next TODO in the same Executor session: short `execution_next_todo` prompt containing only the new Current TODO plus a strict scope reminder and new feedback.
- Same-TODO retry/review-fix: short `execution_continue` prompt only. Do not repeat Original Goal, full task JSON, static rules, or old output; send only new review/validator/recovery information.

## Review
- Fresh, read-only, scoped to the Current TODO. It receives task/global constraints plus executor and relevant validator evidence, but does not preload a changed-files list or generic write/git/shell rules. It reads only the smallest directly related file subset needed for unresolved acceptance criteria.
- Same-session Finalize after resumable error: no tools, use already gathered evidence and emit JSON verdict. Both FAIL and PASS examples are shown.

## Final validation
Final AI Validator always uses a fresh independent session and sees the complete goal. File validator is deterministic and model-independent.

## Rule injection
`instructions.always` from project policy is appended to every relevant model call. `instructions.project` is maintained in generated project agent-rule files. Same behavior should not be duplicated in individual prompt templates.

Planning uses bounded read-only Qwen tools when evidence is needed, while mutating/shell tools remain excluded. Stages whose prompt explicitly requires no further inspection simply avoid using those read tools. This keeps one planning tool policy across the same remote session and avoids empty-tool API compatibility issues.

## Unified recovery order
`reuse -> short correction/recovery -> rebuild only when repeated/unusable`. Review is the intentional fresh quality-gate session. Review FAIL returns to the existing Executor TODO; Review infrastructure/format failure is retried/corrected first and may then be skipped. Final Validator never runs early because of TODO/Review recovery.
