# Git Worktree Parallel Task Integration TODO

> Status: design / implementation TODO
>
> Scope: add parallel Task worktree + local Git integration around the existing Runner. **Do not redesign Runner execution.**
>
> Core rule: **all Tasks execute in isolated Git worktrees.** Preserve the existing Task modes: `Auto` / `Main` / `Isolated Worktree`. These modes decide post-execution delivery behavior, not whether Runner edits the original checkout.

---

## 1. Current AS-IS

The current execution boundary is:

```text
UI
  ↓
Create Task
  ↓
Runner(project_root)
  ↓
Workflow / Agent
  ↓
Review / Validate
  ↓
Completed
```

Runner only receives a `project_root`. It does not need to know whether that path is the original checkout or a Git worktree.

### Preserve this Runner contract

```text
Runner(project_root)
→ execute Workflow
→ Agent changes files
→ Review / Validate
→ Completed
```

The worktree / branch / integration lifecycle must remain outside this contract unless a future requirement proves otherwise.

---

## 2. Target TO-BE

```text
UI
  ↓
Create Task
  ↓
Workspace Manager
  ↓
sync local/integration to target branch committed HEAD
  ↓
git worktree add -b local/task/<task-id> <worktree-path> local/integration
  ↓
isolated Task worktree ready
  ↓
Runner(project_root = Task worktree)
  ↓
Workflow / Agent
  ↓
Review / Validate
  ↓
Execution Completed
  ↓
Closed · pending_merge
  ↓
Integration Queue
  ↓
integrate one Task at a time
  ↓
local/integration
  ↓
Project target branch: git merge --squash local/integration
  ↓
commit locally
  ↓
reset local/integration = target branch HEAD
  ↓
Closed · integrated

If automatic merge recovery is exhausted:
  ↓
Closed · Awaiting merge
  ├─ Retry merge
  └─ Keep Worktree (explicit fallback; target branch remains unchanged)
```

No remote push is required by this flow.

Remote Git changes only when the user or a separate publish policy explicitly runs:

```bash
git push origin <target-branch>
```

---

## 3. Branch naming convention

Use one predictable local namespace.

```text
Target branch
  main
  feature/ui
  release/v4
  ...the branch originally selected for the Project

Runner-owned local integration branch
  local/integration

Per-Task temporary branches
  local/task/<task-id>
```

Example:

```text
feature/ui
local/integration
local/task/T-001
local/task/T-002
local/task/T-003
```

### Important Git ref rule

Do **not** create a branch named exactly:

```text
local
```

because it conflicts with hierarchical refs such as:

```text
local/integration
local/task/T-001
```

---

## 4. Worktree naming convention

Task working directories should be deterministic and Runner-owned.

Example:

```text
.worktrees/
├─ T-001/
├─ T-002/
├─ T-003/
└─ integration/
```

Recommended ownership:

```text
.worktrees/<task-id>     → Agent / Runner execution
.worktrees/integration   → Integration Manager only
```

Do not let two Tasks share the same worktree.

---

## 5. Preserve existing modes: Auto / Main / Isolated Worktree

All three modes execute the Task inside an isolated Task worktree.

```text
Task mode
├─ Auto
├─ Main
└─ Isolated Worktree

Execution for all three
→ local/task/<task-id>
→ isolated Task worktree
→ Runner(project_root = worktree)
```

The mode controls what happens **after Runner execution completes**.

### Auto

`Auto` remains the default mode and resolves through the existing Global workspace policy.

Conceptually:

```text
Task mode = Auto
↓
Global policy resolves effective mode
├─ Main
└─ Isolated Worktree
↓
persist resolved mode for this Task run
```

Do not duplicate Global Auto policy logic in the worktree/integration layer. Reuse the existing single resolver/owner.

Examples of existing Global policy choices may include:

```text
Busy → Worktree
Always Main
Always Worktree
```

The exact Global policy remains owned by the existing workspace resolver.

### Main

`Main` is a product mode name. It does **not** mean the Git branch must literally be named `main`.

It means:

```text
run inside isolated Task worktree
→ Runner Completed
→ Closed · pending_merge
→ automatic integration/recovery
→ git merge --squash local/integration into captured target_branch
→ local commit
→ Closed · integrated
```

The actual destination branch is the Project branch captured when the Task starts, for example:

```text
feature/ui
release/v4
main
hotfix/xxx
```

### Main fallback after repeated merge failure

`Main` keeps trying automatic integration/recovery only within the configured merge-failure budget.

When real merge/integration failure exceeds the limit:

```text
mode remains Main
→ stop automatic merge recovery
→ preserve local/task/<task-id>
→ preserve Task worktree/result
→ Closed · Awaiting merge
→ integration_status = merge_retry_exhausted
→ fallback = worktree_retained
```

This is the **only automatic Keep behavior for Main**.

Do not silently rewrite the user's mode from `Main` to `Isolated Worktree`; preserve the original mode and failure history so Retry Merge can continue later.

### Isolated Worktree

`Isolated Worktree` is a normal explicit mode, not an error fallback.

It means:

```text
run inside isolated Task worktree
→ Runner Completed
→ Closed · Worktree ready
→ keep local/task/<task-id>
→ keep worktree/result
→ do not automatically integrate into target_branch
```

The existing Merge / Merge Chat style actions may still be offered later if the user wants to integrate that retained result manually.

---

## 6. Target branch = Project current branch at Task start

Do not hardcode `main`.

When a Task is about to start, resolve the Project repository's currently checked-out branch and persist it as that Task's `target_branch`.

Examples:

```text
Project currently on feature/ui
→ Task target_branch = feature/ui

Project currently on release/v4
→ Task target_branch = release/v4

Project currently on main
→ Task target_branch = main
```

Recommended metadata:

```yaml
git:
  target_branch: feature/ui
  target_sha_at_start: <sha>
```

### Capture once per Task

`target_branch` is captured when the Task starts and then remains stable for that Task.

Example:

```text
Task T-001 starts while Project = feature/ui
later the user switches the Project checkout to release/v4

T-001 still targets feature/ui
new Task T-002 would capture release/v4
```

Do not silently retarget an existing Task based on whatever branch happens to be checked out later.

### Detached HEAD

If the Project is in detached HEAD state at Task start, fail closed or require an explicit target branch. Do not invent `main`.

---

## 7. Task start: synchronize only committed target state

Before creating a Task worktree:

1. Read target branch HEAD.
2. Synchronize `local/integration` to that committed SHA.
3. Create the Task branch and Task worktree in one operation from `local/integration`.
4. Pass the Task worktree path to Runner.

Example:

```bash
git rev-parse feature/ui
# → TARGET_SHA

# under the Git integration lock
git switch local/integration
git reset --hard TARGET_SHA

git worktree add -b local/task/T-001 <worktree-path> local/integration
```

### Uncommitted target files must NOT be copied

Example:

```text
feature/ui committed:
A → B → C

feature/ui working tree:
M task-editor.js
M styles.css

Task base:
C
```

The uncommitted modifications are intentionally excluded.

Reason:

- Git can reproduce the committed SHA.
- Git cannot safely treat arbitrary dirty working-tree state as a stable Task base.
- An Agent must always have a deterministic base.

### Parallel Task starts

Synchronizing `local/integration` and creating a Task branch is a short serialized operation.

A Task records its base SHA at creation:

```yaml
git:
  target_branch: feature/ui
  base_sha: <sha>
  task_branch: local/task/T-001
```

Once created, the Task worktree is independent.

---

## 8. Runner execution remains unchanged

Runner receives only the Task worktree root.

Example:

```text
Runner(
  project_root = C:\repo\.worktrees\T-001
)
```

Runner continues to own:

- Workflow execution
- Agent execution
- Review
- Validation
- normal retry/recovery behavior
- execution Completed result

Runner does **not** need to own:

- Task worktree creation
- Git branch naming
- `local/integration`
- target branch squash merge
- integration queue
- remote push

### Hard invariant: do not modify Runner architecture for Git integration

Git worktree/integration support is an orchestration layer around the existing Runner, not a new Runner execution subsystem.

Do not add:

- a Git Integration Stage
- a second Runner state machine
- a second recovery engine
- Git branch/worktree ownership inside FlowEngine / StageExecutor / Supervisor
- special Git-aware behavior inside normal Workflow execution

The existing Runner API remains conceptually:

```text
Runner(project_root, task/workflow input)
→ Workflow / Agent
→ Review / Validate
→ Completed
```

If integration later needs code changes, it calls this same Runner contract again with a recovery worktree and recovery task context.

---

## 9. Every completed Project-Branch Task enters Integration Queue

Execution may be parallel:

```text
T-001 → Runner ───────────── Done
T-002 → Runner ───── Done
T-003 → Runner ───────────────── Done
```

Integration must be serialized per target repository/branch:

```text
Done Tasks
    ↓
Integration Queue
    ↓
one Task at a time
    ↓
local/integration
    ↓
target branch
```

Core rule:

> **Execution parallel, integration serial.**

Do not allow two processes to mutate `local/integration` or the same target branch simultaneously.

---

## 10. One Task integration transaction

For an effective `Main` Task, treat the following as one serialized transaction:

```text
Task completed
  ↓
verify target branch is safe to update
  ↓
take latest local/integration
  ↓
replay/rebase Task changes onto latest integration base
  ↓
resolve code conflicts if needed
  ↓
validate
  ↓
advance local/integration
  ↓
switch target branch
  ↓
git merge --squash local/integration
  ↓
git commit
  ↓
reset local/integration to new target HEAD
  ↓
cleanup Task branch/worktree
  ↓
Integrated
```

Do not release the integration lock in the middle of this transaction.

---

## 11. Why reset local/integration after every squash

`git merge --squash` copies the final diff but does not record merge ancestry.

Example before delivery:

```text
target:
A

local/integration:
A ─ X1 ─ X2
```

Run:

```bash
git switch <target>
git merge --squash local/integration
git commit -m "T-001: ..."
```

Target becomes:

```text
A ─ S1
```

After that, immediately realign the integration branch:

```bash
git switch local/integration
git reset --hard <target>
```

Result:

```text
A ─ S1
    ├─ target
    └─ local/integration
```

This guarantees the next Task starts/integrates against the canonical committed target state and prevents old squash history from accumulating inside `local/integration`.

---

## 12. Per-Task local squash commit

For effective `Main`, each completed Task should normally produce one local commit on the captured target branch.

Example:

```text
feature/ui

A
└─ T-003 squash commit
   └─ T-001 squash commit
      └─ T-002 squash commit
```

Agent internal history may contain many temporary commits:

```text
implementation
fix tests
review fix
conflict repair
retry
```

Those do not need to appear on the target branch.

Target receives one logical Task commit.

---

## 13. Target branch dirty policy

### Task start

Dirty target is allowed.

Only the target branch committed HEAD is used as the Task base.

```text
target dirty
→ read target HEAD commit
→ create worktree from committed SHA
→ continue
```

### Task integration / squash

Dirty target must fail closed.

```text
target working tree dirty
→ do NOT run merge --squash
→ do NOT mix Agent changes with user uncommitted changes
→ mark Task integration_pending / needs attention
→ keep artifacts safe
```

### Important queue rule

Because the design wants **one target commit per Task**, do not allow later Tasks to accumulate into canonical `local/integration` while an earlier Task cannot finish its target squash.

Preferred behavior:

```text
dirty target
→ current integration transaction waits
→ integration queue for that target branch pauses
→ parallel Runner execution may continue in independent Task worktrees
```

This preserves:

```text
1 Task
→ 1 integration transaction
→ 1 squash commit
```

---

## 14. Conflict handling

A normal Git conflict is not automatically a Task execution failure.

Integration Manager owns deterministic Git operations:

- inspect latest target/integration SHA
- replay/rebase/cherry-pick mechanics
- conflict detection
- integration worktree lifecycle
- retry after branch movement
- cleanup

If Git reports a **code/semantic conflict**, collect recovery context and call the existing Runner again.

### Recovery context

Include at least:

```text
Original Task prompt / intent
Original Task base SHA
Current target branch
Latest target/integration SHA
Task branch / Task commit(s)
Conflicting files
Git conflict/error output
Validation/test errors, if any
Relevant project development rules
```

### Recovery intent

Do not prompt only:

```text
Resolve the Git conflict.
```

Use semantics closer to:

```text
Latest integrated code is authoritative.

Re-evaluate the original Task against the current codebase.
Preserve compatible changes already present in the latest code.
Resolve the conflict semantically.

If the previous implementation no longer fits the current architecture,
redo the affected part against the latest code instead of blindly
preserving the old patch.

Run the required verification.
```

Then invoke the existing Runner against a safe integration/recovery worktree.

```text
Runner(project_root = recovery_worktree)
→ Workflow / Agent
→ Review
→ Validate
→ Completed
→ retry integration transaction
```

### Any failure that requires changing code goes back through Runner

Integration Manager may retry deterministic Git operations itself, but it must not become another code-repair agent.

Examples that stay inside Integration Manager:

```text
lock contention
temporary worktree creation failure
branch moved before transaction started
retryable Git command failure with no code change required
cleanup retry
```

Examples that must call the existing Runner again:

```text
merge/rebase conflict requiring source edits
latest target changed architecture and old patch no longer applies
validation/test failure after replay
review failure caused by integration result
generated code no longer matches latest interfaces/contracts
semantic conflict even when Git has no textual conflict
```

The recovery Runner may repair the existing candidate or re-do the affected part from the latest integrated code. It must still run the normal Review / Validate path before integration is retried.

Do not bypass Runner validation by directly accepting AI-edited conflict files from Integration Manager.

---

## 15. Prefer a temporary integration/recovery worktree

Do not leave canonical `local/integration` in an unresolved conflict state.

Recommended:

```text
local/integration
      ↓
temporary integration worktree
      ↓
replay Task
      ↓
conflict?
├─ no  → validate → advance local/integration
└─ yes → Runner repair/rework → validate → advance local/integration
```

Only update canonical `local/integration` after the candidate result is valid.

This protects the integration base if AI recovery fails or is interrupted.

---

## 16. Remote Git policy

The entire parallel-Agent system must be usable without modifying remote Git.

Normal Task lifecycle:

```text
clone / existing repo
→ local Task worktrees
→ local/task/*
→ local/integration
→ local target branch commits
```

No automatic remote push is required.

Publishing is a separate explicit action/policy:

```bash
git push origin feature/ui
```

This allows many Tasks to run and integrate locally before anything is sent to GitHub.

---

## 17. Do not call local integration "push"

Internally use names such as:

```text
integrate_local(task)
integrate_task(task)
squash_to_target(task)
publish_remote()
```

Avoid naming local branch movement:

```text
push_local()
```

because `git push` should remain reserved for actual remote publication semantics.

---

## 18. Ownership boundaries

### Task Manager / UI backend

Owns:

- Task lifecycle
- selected Project
- target branch
- delivery policy
- scheduling Integration Queue after Runner completes
- exposing integration status to UI

### Workspace Manager

Owns:

- Task branch naming
- Task worktree create/remove
- integration/recovery worktree create/remove
- returning `project_root` to Runner

### Runner

Owns only its current execution contract:

```text
project_root
→ Workflow
→ Agent
→ Review
→ Validate
→ Completed
```

### Integration Manager

Owns:

- target HEAD snapshot checks
- `local/integration`
- integration lock / queue
- replay/rebase mechanics
- conflict collection
- invoking Runner recovery when semantic repair is required
- validation before advancing integration
- `merge --squash` to target
- local Task commit
- reset `local/integration` to target HEAD
- safe cleanup

### Publish

Owns only:

- optional remote fetch/reconciliation policy
- explicit `git push origin <target>`

Do not mix remote publishing into normal local Task integration.

---

## 19. Merge failure counting / retry exhaustion

Track merge/integration failures explicitly so conflict recovery cannot loop forever and burn Agent time.

### Counters

Recommended metadata:

```yaml
git:
  merge_failure_count: 0
  merge_retry_attempt: 0
  max_merge_failures: 3
  last_merge_failure: null
```

Semantics:

- `merge_failure_count` = lifetime diagnostic count for this Task delivery cycle; preserve it for history.
- `merge_retry_attempt` = automatic retry budget used in the current retry session.
- `max_merge_failures` = configurable automatic merge-failure limit. Suggested initial default: `3`.
- `last_merge_failure` = structured summary of the latest merge/integration failure.

### Exactly when a merge failure counts

Increment the merge failure counters only when:

```text
Runner execution/recovery completed successfully
  ↓
Integration Manager actually attempted to replay/merge/validate delivery
  ↓
delivery still failed because the integrated code cannot be accepted
  ↓
merge_failure_count += 1
merge_retry_attempt += 1
```

Examples that **count**:

- replay/rebase produces a source conflict that requires Runner repair/rework
- recovery Runner completes, but the next merge/replay attempt still conflicts
- replay succeeds textually, but integration validation/test fails and requires Runner code changes
- semantic incompatibility with latest target requires Runner to redo part of the implementation

Examples that **do not count**:

- waiting in Integration Queue
- target branch is dirty
- integration lock is busy
- Task has not reached integration yet
- temporary worktree creation transiently fails
- deterministic Git command retry where no code repair/rework is required
- Runner itself fails before reaching a new merge/integration attempt
- user cancels or pauses before integration is attempted

This is intentionally a **merge-delivery failure counter**, not a generic Runner retry counter.

### Retry loop

```text
Runner Completed
  ↓
attempt integration
  ↓
success ─────────────────────────────→ squash/commit → Closed
  ↓ fail requiring code change
count +1
  ↓
count within automatic budget?
  ├─ yes
  │    ↓
  │  existing Runner recovery/rework
  │    ↓
  │  Review / Validate
  │    ↓
  │  attempt integration again
  │
  └─ no
       ↓
     stop automatic integration recovery
       ↓
     Closed · Awaiting merge
```

### Retry exhaustion state

For effective mode `Main`, keep the Task in `Closed` when automatic merge retries are exhausted.

Recommended Board projection:

```text
Board:       Closed
Reason:      Awaiting merge
Integration: merge_retry_exhausted
Failures:    4 / max 3
```

Rationale:

- the Runner execution itself is already finished
- existing product semantics already allow Closed Tasks to have unmerged Worktree results
- merge/integration is a post-execution delivery state, not a resumable execution pause
- Task artifacts/worktree must remain available
- the UI must show clearly that delivery to the target branch is still pending

`Closed` therefore means **Runner execution finished**, not necessarily **merged/integrated into the target branch**. In Main mode, exhausted merge retries automatically retain the Task worktree.

### Main behavior after exhaustion

When the Main-mode retry budget is exhausted, the system automatically keeps the existing Task branch/worktree instead of deleting it.

```text
mode = Main
integration_status = merge_retry_exhausted
fallback = worktree_retained
Board = Closed
Reason = Awaiting merge
```

Recommended actions:

```text
Retry merge
Open worktree
Open conflict details
Open Task Info
Delete (only with explicit confirmation)
```

`Retry merge`:

- starts a new automatic merge-retry session
- resets `merge_retry_attempt = 0`
- preserves lifetime `merge_failure_count`
- keeps the original Task mode as `Main`
- re-syncs against the latest committed target/integration base
- calls the existing Runner again only if code repair/rework is required

There is no need to convert the Task to `Isolated Worktree`; the retained worktree is a Main-mode failure fallback, not a mode change.

### Failure record

Persist enough information for UI and restart recovery:

```yaml
last_merge_failure:
  at: <timestamp>
  integration_base_sha: <sha>
  target_sha: <sha>
  task_sha: <sha>
  kind: conflict | validation | semantic
  files:
    - path/to/file
  summary: <short reason>
  runner_recovery_used: true
```

Do not store only a free-form error string if structured fields are available.

---

## 19. UI / Task status model

Do not add another Board lifecycle column just for Git integration.

Keep the existing Board lifecycle meanings:

```text
New
Ongoing
Paused
Closed
```

Git integration is a secondary Task projection shown inside the Task card / Info Drawer / runtime detail.

### Recommended lifecycle mapping

| Situation | Board status | Integration status / detail |
| --- | --- | --- |
| Task created, Runner not started | New | preparing / not_started |
| Runner executing | Ongoing | execution_running |
| Runner Review / Validate | Ongoing | execution_validating |
| Effective Main: Runner Completed, waiting in Integration Queue | Closed | pending_merge |
| Effective Main: replay/squash transaction running | Closed | integrating |
| Effective Main: conflict is being repaired/reworked by Runner | Closed | conflict_recovery |
| Effective Main: target branch dirty | Closed | waiting_target_clean + Needs Attention |
| Effective Main: validation fails and Runner is redoing/fixing | Closed | recovery |
| Effective Main: squash commit created successfully | Closed | integrated |
| Isolated Worktree: Runner Completed; result intentionally retained without auto integration | Closed | worktree_ready / not_required |
| User explicitly stops a resumable running Task before execution completes | Paused | integration must not start until execution is completed/resumed |
| Main: automatic merge retry budget exhausted; worktree retained | Closed | merge_retry_exhausted · Awaiting merge |
| Integration irrecoverable for another reason / requires user action | Closed | failed / Needs Attention |

### Important completion rule

Board lifecycle and delivery state are separate.

> **Runner execution Completed → Task Closed.**

Then delivery depends on the resolved Task mode.

Main:

```text
Runner Completed
→ Closed · pending_merge
→ Closed · integrating / conflict_recovery / waiting_target_clean / recovery
├─ success → Closed · integrated
└─ retries exhausted → Closed · Awaiting merge + worktree retained
```

Isolated Worktree:

```text
Runner Completed
→ Closed · worktree_ready
→ no automatic integration
```

Auto:

```text
resolve Global policy first
→ behave exactly as resolved Main or Isolated Worktree
```

This preserves the existing product meaning that Closed means execution has finished while Merge remains a separate delivery concern.

### Paused remains execution-only

Do not use `Paused` for Git delivery states.

`Paused` means the Runner execution itself was stopped before completion and can be resumed/reset.

After Runner execution completes, the Task is `Closed`; all merge/integration states remain secondary states under Closed:

```text
Closed · pending_merge
Closed · integrating
Closed · conflict_recovery
Closed · waiting_target_clean
Closed · recovery
Closed · merge_retry_exhausted / Awaiting merge
Closed · integrated
Closed · worktree_ready
```

This matches the existing product behavior where a Closed Worktree Task may still be waiting for Merge.

### Suggested UI placement

#### Board card

Keep the normal lifecycle column and add one compact secondary line/badge when relevant:

```text
T-001  Closed
Integrating · feature/ui

T-002  Closed
Needs Attention · target has uncommitted changes

T-003  Closed
Conflict recovery · Runner retry 2

T-004  Closed
Awaiting merge · 4 failures

T-005  Closed
Integrated · feature/ui
```

Do not add Git controls directly to every card.

#### Task Info Drawer

Add an `Integration` section only when the Task uses Git worktree delivery metadata.

Example:

```text
Integration
Target branch     feature/ui
Delivery          Project Branch
Task branch       local/task/T-001
Base              abc123
State             Integrating
Latest target     def456
Attempt           2
Attention         —
```

When blocked:

```text
State             Waiting for target clean
Attention         feature/ui has uncommitted changes
Action            Commit/stash/revert those changes, then integration can continue
```

#### Task List / child items

Do not give every child its own integration state if the Board Task is the delivery unit.

The parent Task owns:

- Task worktree
- integration transaction
- target squash commit
- integration status

Child execution progress remains Runner/Task List execution detail.

### Runtime / projection separation

Keep three concepts separate:

```text
Board lifecycle
New / Ongoing / Paused / Closed

Runner runtime
idle / running / recovering / stopped / completed / attention / ...

Git integration
not_started / pending_merge / integrating / conflict_recovery /
waiting_target_clean / recovery / merge_retry_exhausted /
integrated / failed / worktree_ready / not_required
```

UI composes these into one readable Task view, but no layer re-derives or replaces another owner's state machine.

### Allowed actions during integration

Initial policy:

- While `pending_merge/integrating/conflict_recovery/recovery`: the Task is Closed but disable destructive Reset/Rerun/Delete that could invalidate the integration transaction.
- `Open Info`, logs, worktree path, target branch and conflict details remain available.
- While `waiting_target_clean`: show the blocking reason; execution remains finished and integration waits.
- After `integrated`: normal Closed actions apply.
- For `worktree_ready`: normal Closed actions apply while retaining the worktree according to retention policy.

Exact action guards must come from one backend-owned Task projection, not duplicated button logic.


---

### Compatibility with existing Closed + Merge behavior

The current product already has Closed Worktree Tasks whose execution is done while the result is still waiting for Merge. Preserve that model.

Therefore this design must not redefine Closed as “already merged”. Instead:

```text
Closed = execution finished
Integration status = delivery progress/result
```

This keeps existing Merge / Merge Chat concepts compatible with the future automatic local integration flow.

---

## 20. Suggested Task metadata

Keep metadata minimal and outside generic Runner execution.

Example:

```yaml
git:
  workspace_mode: main
  target_branch: feature/ui
  base_sha: abc123
  integration_base_sha: def456
  task_branch: local/task/T-001
  worktree: .worktrees/T-001
  integration_status: pending
  integration_attempt: 0
  integration_attention: null
  merge_failure_count: 0
  merge_retry_attempt: 0
  max_merge_failures: 3
  last_merge_failure: null
```

For an explicit Keep Worktree outcome:

```yaml
git:
  workspace_mode: isolated_worktree
  target_branch: feature/ui
  base_sha: abc123
  task_branch: local/task/T-001
  worktree: .worktrees/T-001
  integration_status: not_required
```

Do not duplicate Runner RunState inside this metadata.

---

## 21. Skill / prompt policy

Do not make deterministic Git mechanics into AI Skills.

Do **not** create Skills for:

- `git worktree add`
- branch creation
- reset
- rebase invocation
- squash merge
- lock handling
- queue handling
- cleanup
- remote push

These belong in deterministic code.

### Conflict Skill is optional

Start with an internal integration-recovery prompt that calls the existing Runner.

Only extract a reusable Skill such as:

```text
integration-conflict
```

if real usage proves that semantic conflict recovery requires a larger stable methodology.

Avoid speculative Skill complexity in the first implementation.

---

## 22. Failure / recovery principles

- Count a merge failure only after a successful Runner execution/recovery reaches a real integration attempt and delivery still fails for a code/semantic/validation reason.
- Do not count queue waits, dirty target, lock contention, or deterministic transient Git failures as merge failures.
- Stop automatic Runner recovery when the configured merge-failure budget is exhausted; preserve the Main-mode Task branch/worktree and keep the Task `Closed · Awaiting merge`.
- Preserve lifetime `merge_failure_count` for diagnostics even when a user starts a new retry session.
- Never destroy the original completed Task worktree before integration succeeds.
- Never overwrite user uncommitted target changes.
- Never advance canonical `local/integration` to an unvalidated candidate.
- Never run two integration transactions against the same target simultaneously.
- A conflict should preserve enough context to resume/retry after process restart.
- A failed integration must not make the completed Agent result disappear.
- Cleanup happens only after the target squash commit is safely created, or by explicit user action.
- Remote Git remains untouched unless explicitly published.

---

## 23. Example: three Agents in parallel

Initial:

```text
feature/ui = C
local/integration = C

T-001 starts from C
T-002 starts from C
T-003 starts from C
```

T-003 finishes first:

```text
T-003 Done
→ Integration Queue
→ replay T-003 onto latest local/integration
→ validate
→ local/integration = C + T-003'
→ feature/ui: merge --squash local/integration
→ commit S3
→ reset local/integration = feature/ui
```

Now:

```text
feature/ui = C-S3
local/integration = C-S3
```

T-001 finishes:

```text
T-001 was based on C
→ replay onto C-S3
→ conflict?
   ├─ no  → continue
   └─ yes → Runner recovery/rework against latest code
→ validate
→ local/integration = C-S3-T1'
→ feature/ui: merge --squash local/integration
→ commit S1
→ reset local/integration = feature/ui
```

Result:

```text
feature/ui

C
└─ S3
   └─ S1
```

T-002 then repeats against the latest committed target.

---

## 24. Implementation TODO

### Phase A — contracts / metadata

- [ ] Add merge failure metadata: lifetime `merge_failure_count`, current-session `merge_retry_attempt`, configurable `max_merge_failures`, and structured `last_merge_failure`.
- [ ] Define exact counter semantics so only a Runner-complete → real integration-failure cycle consumes the merge retry budget.
- [ ] Lock the architecture invariant: Git worktree/integration orchestration must not modify Runner / FlowEngine / StageExecutor / Supervisor execution structure.
- [ ] Define that any integration failure requiring source-code changes re-enters the existing Runner using a recovery worktree; Integration Manager itself never repairs application code.
- [ ] Preserve Task modes Auto / Main / Isolated Worktree. All execute in isolated worktrees; Auto reuses the existing Global resolver, Main auto-integrates to the captured Project branch, Isolated Worktree keeps the result without auto integration.
- [ ] Resolve `target_branch` from the Project repository's currently checked-out branch when the Task starts; persist it for that Task and never hardcode `main`.
- [ ] Define minimal Git metadata for Task base SHA, Task branch, worktree path, and integration status.
- [ ] Define stable local branch naming: `local/integration`, `local/task/<task-id>`.
- [ ] Define deterministic worktree paths.

### Phase B — Workspace Manager

- [ ] Create the Task branch and Task worktree atomically from the committed target snapshot with `git worktree add -b local/task/<task-id> <worktree-path> local/integration`.
- [ ] Before Task creation, under a short Git lock, synchronize `local/integration` to target branch committed HEAD.
- [ ] Explicitly exclude uncommitted target working-tree changes from new Task bases.
- [ ] Return Task worktree path as the existing Runner `project_root`.
- [ ] Add safe cleanup without deleting unresolved/failed Task output.
- [ ] Ensure multiple Task worktrees can execute concurrently.

### Phase C — Integration Queue

- [ ] Stop automatic recovery for a Task when merge retry budget is exhausted; remove it from active integration execution without losing its queued/artifact state.
- [ ] Support Retry merge to start a new retry session while preserving lifetime failure history and original Main mode.
- [ ] Add one serialized Integration Queue per repository/target branch.
- [ ] Completed Tasks whose effective mode resolves to Main enqueue automatically.
- [ ] Completed Isolated Worktree Tasks do not auto-enqueue for integration; they close as worktree_ready.
- [ ] Do not block parallel Runner execution while integration is busy.
- [ ] Persist enough queue/integration state to recover after UI/backend restart.

### Phase D — Task integration

- [ ] Verify target branch and expected committed SHA before integration.
- [ ] Fail closed if target working tree is dirty at squash time.
- [ ] Pause that target's Integration Queue while target is dirty.
- [ ] Use a temporary integration/recovery worktree for replay/conflict resolution.
- [ ] Replay/rebase the completed Task changes onto latest `local/integration`.
- [ ] Validate the candidate result before advancing canonical `local/integration`.
- [ ] Advance `local/integration` only after successful validation.

### Phase E — Conflict recovery through existing Runner

- [ ] Detect Git/code conflicts deterministically.
- [ ] Build recovery context: original Task, old/new SHA, conflict files, Git output, validation errors.
- [ ] Call the existing Runner with the recovery/integration worktree as `project_root`.
- [ ] Prompt for semantic repair/reimplementation against latest code, not blind conflict-marker removal.
- [ ] Run normal Review / Validate.
- [ ] Retry integration after recovery completes.
- [ ] Keep original Task result until integration succeeds.

### Phase F — squash to target branch

- [ ] Switch/update the clean local target branch.
- [ ] Run `git merge --squash local/integration`.
- [ ] Create exactly one local target commit for the Task.
- [ ] Record resulting target commit SHA.
- [ ] Reset `local/integration` hard to the new target branch HEAD immediately after commit.
- [ ] Release the integration lock only after the entire cycle completes.
- [ ] Cleanup successful Task/recovery worktrees according to retention policy.

### Phase G — UI

- [ ] Show merge failure count and retry budget in Task Info and compactly on the Board when nonzero.
- [ ] On retry exhaustion, keep the Task `Closed · Awaiting merge` with `merge_retry_exhausted`; Closed means execution finished, not necessarily merged.
- [ ] After Main retry exhaustion, automatically retain the worktree, show Retry merge, and preserve mode=Main; do not silently rewrite it to Isolated Worktree.
- [ ] Keep Board columns as New / Ongoing / Paused / Closed; do not add an Integration column.
- [ ] Runner execution Completed moves the Task to Closed immediately; effective Main continues through Closed integration states, while Isolated Worktree closes as worktree_ready.
- [ ] Isolated Worktree closes as worktree_ready when Runner completes and does not auto-integrate.
- [ ] Add secondary integration badge/detail: pending / integrating / conflict_recovery / waiting_target_clean / recovery / integrated / failed / not_required.
- [ ] Keep Paused reserved for unfinished resumable Runner execution; all post-execution Git delivery states stay under Closed.
- [ ] Add Integration details to Task Info Drawer (target, delivery, Task branch, base/latest SHA, state, attempt, attention reason).
- [ ] Disable destructive Reset/Rerun/Delete during active integration/recovery through one backend-owned allowed-actions projection.
- [ ] Keep current Workspace choices Auto / Main / Isolated Worktree, while clarifying that every mode executes in an isolated worktree.
- [ ] Main description: execute in isolated worktree, then auto-integrate/squash into the Project branch captured when the Task starts; `Main` is a mode label, not a literal branch name.
- [ ] Isolated Worktree description: execute in isolated worktree and keep the result without automatic integration.
- [ ] Auto remains the default and reuses the existing Global workspace policy resolver; persist the resolved effective mode for the Task run.
- [ ] Show integration status without creating another Runner state machine.
- [ ] Show `waiting_target_clean` when user has uncommitted target changes.
- [ ] Expose conflict/recovery details without forcing the user to understand Git internals for normal success paths.

### Phase H — local-only / publish

- [ ] Ensure normal Task integration never runs `git push origin`.
- [ ] Add explicit/manual Publish separately if needed.
- [ ] Publish must target the Project-selected branch, not hardcoded main.
- [ ] Keep remote reconciliation/publish policy independent from local Integration Manager.

---

## 25. Test TODO

### Worktree isolation

- [ ] Start 2, 5, and 10 Tasks from the same target branch concurrently.
- [ ] Confirm every Runner receives a unique worktree path.
- [ ] Confirm no Task edits another Task worktree.
- [ ] Confirm original checkout dirty files never appear in Task worktrees unless committed.

### Integration ordering

- [ ] Verify queue wait / target dirty / lock contention do not increment merge failure counters.
- [ ] Force repeated Runner-complete → merge-fail cycles and verify each real failed delivery attempt increments exactly once.
- [ ] Verify retry exhaustion stops automatic Runner recovery and projects `Closed · Awaiting merge`.
- [ ] Retry manually and confirm retry-session budget resets while lifetime merge failure count is preserved.
- [ ] Exhaust Main merge retries and confirm the Task automatically retains its worktree/branch, remains mode=Main, target branch is untouched, and UI shows `Closed · Awaiting merge`.
- [ ] Finish Tasks out of creation order.
- [ ] Confirm Integration Queue serializes them safely.
- [ ] Confirm later Tasks replay against the latest integrated target state.
- [ ] Confirm each Project-Branch Task creates one squash commit on target.

### Dirty target

- [ ] Make uncommitted user edits before Task start; Task must use committed HEAD only.
- [ ] Make target dirty before Task integration; squash must not run.
- [ ] Confirm Task becomes/waits in integration pending state.
- [ ] Confirm later integrations for the same target do not accumulate behind the dirty target into one squash commit.
- [ ] Clean/commit user changes and confirm queued integration resumes safely.

### Conflict recovery

- [ ] Force a textual merge/rebase conflict and confirm Integration Manager does not edit code itself; it calls the existing Runner with a recovery worktree.
- [ ] Force a no-text-conflict validation failure caused by latest target changes and confirm the existing Runner redoes/fixes the affected implementation.
- [ ] Confirm recovery still passes the normal Runner Review / Validate path before integration continues.
- [ ] Two Tasks modify the same lines.
- [ ] Confirm conflict context is generated.
- [ ] Confirm existing Runner is called against the recovery worktree.
- [ ] Confirm semantic repair can preserve latest integrated code and original Task intent.
- [ ] Confirm failed recovery does not destroy the original Task worktree.
- [ ] Confirm retry can eventually produce one valid squash commit.

### Restart / unattended behavior

- [ ] Restart UI/backend while Tasks are running.
- [ ] Restart while integration is queued.
- [ ] Restart while waiting for target clean.
- [ ] Restart during conflict recovery.
- [ ] Recover without duplicate squash commits.
- [ ] Recover without deleting unintegrated Agent output.

### Local-only guarantee

- [ ] Run the entire suite with remote credentials unavailable.
- [ ] Confirm Task execution and local integration still succeed.
- [ ] Confirm no automatic `git push` occurs.
- [ ] Explicit publish remains a separate action.

---

## 26. Non-goals for the first implementation

- Do not redesign Runner.
- Do not add a new Workflow Stage for Git integration.
- Do not add a second retry/recovery engine inside Runner.
- Do not let browser frontend execute Git directly.
- Do not auto-stash or overwrite user dirty target files.
- Do not push every Task to remote.
- Do not create multiple competing canonical integration branches.
- Do not add an AI Skill for deterministic Git commands.
- Do not make `local/integration` long-lived accumulated history after a Task has already been squash-committed to target.

---

## 27. Design invariant summary

```text
Task modes:
  Auto / Main / Isolated Worktree

Execution:
  every mode uses isolated Task worktree
  Runner(project_root) unchanged

Auto:
  resolve via existing Global workspace policy
  persist effective Main or Isolated Worktree behavior

Main:
  Task → local/integration
  → captured target_branch merge --squash
  → one local commit
  → local/integration reset to target HEAD
  → merge failures over limit: retain worktree + Closed · Awaiting merge

Isolated Worktree:
  Runner Completed → Closed · worktree_ready
  keep isolated result
  no automatic target modification

Target branch:
  Project current branch captured when Task starts
  never hardcode literal main

Runner:
  no Git integration knowledge required

Remote:
  untouched until explicit publish
```
