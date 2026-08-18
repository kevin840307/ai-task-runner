# Design

Version: 1.2.1

## Responsibility boundary
The Runner owns orchestration; project code and validators own application-specific behavior.

## Goals
1. Run AI coding work for long periods without losing useful project changes.
2. Keep deterministic validation authoritative.
3. Support small, medium, and large models through behavior-based recovery, not model-name branches.
4. Keep Runner generic, minimal, readable, resumable, and safe.

## Complete flow
1. Validate request and project root.
2. Load/create Runner state.
3. Build normalized protected roots.
4. Planning Understand: fresh, bounded read-only inspection.
5. Planning uses the main `AgentClient` and session. Core temporarily applies planning `--yolo` + bounded read-only Qwen args, then restores runtime `--yolo` args before TODO execution. Finalize/Judge/Rewrite use short same-session prompts; rebuilt calls use self-contained prompts.
6. If planning output fails, retry the same planning session while it remains usable. Only after the session is invalid or repeated attempts cannot recover, clear it and use the same planner client with a fresh full-context plan prompt.
7. Judge the valid plan in the same planning session. Judge may use bounded read-only inspection when needed; on rejection, rewrite in that same session and judge again. If the quality gate itself cannot produce a usable verdict, fail-soft to the last valid plan. Binary verdict prompts show both FAIL and PASS examples.
8. Execute one Current TODO. The Executor session survives successful TODO completion; the next TODO resumes that same session with only the new TODO spec and a strict current-scope reminder. Fresh/rebuilt execution receives the Original Goal only as global context.
9. Review every normally returned TODO, even when it changed no files, in a fresh read-only session. On a resumable model error, same-session logical no-tool Review Finalize uses gathered evidence; Qwen still keeps `read_file` available for strict non-empty-tools API compatibility.
10. PASS advances to the next TODO. Semantic FAIL retries the same TODO using a short same-session continuation containing only new feedback.
11. Repeated no-progress/model failure keeps the current TODO pending; the Runner retries the same session first and rebuilds only after repeated stagnation. Final Validator remains the last step after all TODOs in the cycle have finished.
12. Deterministic Final Validator runs against the complete project/goal. PASS completes. FAIL creates Repair Planning with validator feedback and starts another bounded cycle. Validator infrastructure failure retries and never fails open.
13. Optional Final AI validation uses fresh independent sessions and threshold voting (strict majority by default). A file validator remains the hard gate; when mixed validation is configured, AI voting runs only after the file validator passes and both gates must pass. AI call errors abstain.

## TODO design
Planning must create at least six concrete implementation TODOs. TODOs are bounded, executable, and should not be pure discovery tasks. Do not create umbrella tasks such as “implement everything” or “finish the project.” Discovery belongs in bounded Planning inspection; implementation belongs in TODOs.

## Executor scope isolation
Original Goal may be supplied to a fresh/rebuilt Executor so global constraints are not lost. It is not executable scope. The Current TODO is the only allowed work unit; later TODOs must be left for later Runner steps. Cross-TODO resume sends only the new TODO spec; same-TODO retries do not resend Goal/task/static rules.

## Retry/recovery principles
- Retry based on actual behavior/errors, never model size/name.
- Preserve coherent file changes when a model crashes after making progress.
- Use fresh sessions only when the previous session is unavailable/expired or bounded recovery shows repeated loop/no-progress failure.
- In-run continuation is simple and global: keep the same `AgentClient` and its session. Never create a new client merely to resume an existing session. Planning Finalize reuses the Understand planner; Review Finalize reuses the Reviewer; Executor retries and subsequent TODOs reuse the main Executor client until the Runner intentionally clears an invalid or repeatedly stagnant session. A new client with a stored session id is allowed only after process-level `--resume`, because the old Python client no longer exists.
- Avoid arbitrary short model timeouts; defaults favor long work, while idle-after-change provides bounded recovery.
- `max_attempts=0` and `max_cycles=0` mean unbounded by count.

## Validation
A configured Python validator is the hard correctness gate. It receives `--project-root` and `--state-file`, followed by each repeatable `--validator-arg`. Optional `validator_interface.py` standardizes reporting but does not contain project-specific assertions.

## Prompt design
Fresh/rebuilt sessions are self-contained. Same-session prompts contain only new information. Structured-output/schema errors are treated as valid model responses with an invalid contract: the Runner sends one short same-session JSON-only correction before stage fallback/rebuild.  Planning does not pre-inject a full `Project files:` listing; all planning steps share one bounded read-only tool policy and inspect only when current/session context is insufficient. Binary verdict prompts include explicit FAIL and PASS examples while still requiring the model to return only JSON.

## Qwen transport
The full Qwen prompt is written only to subprocess stdin and EOF is closed. It is not placed in `-p` or another command argument, avoiding Windows command-line length limits and dual-input ambiguity. Qwen stream-json events remain backend transport and are parsed separately from final model-result JSON.

## Structured result parsing
Use one generic candidate extractor and stage-specific strict validation (“lenient envelope, strict payload”). No regex brace guessing, Python literal fallback, comma/bracket repair, or automatic semantic conversion.

## Protected paths and Git
Project policy is loaded only from the project root. Directory paths protect subtrees. The policy itself is automatically protected. AI subprocess PATH guard blocks `git add`, `git commit`, and `git push`; human review owns final Git acceptance.

## Debug/history
Current/last files support immediate diagnosis. Bounded paired history supports full recent call reconstruction without unbounded disk growth. Terminal status/detail is normalized to one line; raw event/debug content keeps original newlines.

## Durable state and completion authority
A run is complete only when **Final Validator PASS** is recorded. State is written after meaningful transitions and the filesystem remains implementation truth. Model output retained per task is bounded; validator feedback stored in state is capped at **20,000** characters with beginning and end preserved. Resume does not require repeating `--goal`; the original goal is already in state.

`runner/process_control.py` owns subprocess waiting, timeout, idle detection, and termination behavior.

## External validator bridge
External commands such as exe, bat, jar, or Java tools should use `docs/validator_templates/external_command_validator.py`. It keeps the Python validator contract, stores command output, and copies configured log folders under `.ai-task-runner/validator-reports/external-command/`.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

## Compatibility cleanup
Internal helpers should use one canonical name/signature. Dead internal aliases and unused compatibility parameters are removed instead of being carried indefinitely. Compatibility aliases that may be used by external Python callers remain until an intentional public breaking change; new code should use the canonical `RunRequest`, `AgentClient`, `RunState`, and `AgentBackend` names.
