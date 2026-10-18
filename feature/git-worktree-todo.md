# Git Worktree Parallel Task Integration TODO

> Status: design / implementation TODO
>
> Scope: add parallel Task worktree + local Git integration around the existing Runner. **Do not redesign Runner execution.**
>
> Core rule: **all Tasks execute in isolated Git worktrees.** Preserve `Auto` / `Main` / `Isolated Worktree`. For effective Main, `local/integration` is a committed local integration branch synchronized from the captured Project branch by **commit ancestry**. Tasks branch from it, completed Task results are committed and merged back into it, and accepted integration results are squash-delivered back to the captured Project branch.

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

For effective `Main`:

```text
Project current branch HEAD = P
  ↓
create / synchronize local/integration by commit ancestry
  ├─ integration missing Project commits → bring those commits in
  └─ integration already contains P → do NOT reset just because files differ
  ↓
git worktree add -b local/task/<task-id>-r<run> <worktree-path> local/integration
  ↓
Runner(project_root = Task worktree)
  ↓
Workflow / Agent
  ↓
Review / Validate
  ↓
Runner Completed
  ↓
commit any remaining Task worktree changes
  ↓
Task branch now has a stable Git result
  ↓
Integration Queue
  ↓
normal Git merge Task branch into latest local/integration
  ├─ success → validate merged candidate
  └─ conflict / semantic failure
        ↓
      collect Git error + latest integration context
        ↓
      existing Runner redo / recovery
        ↓
      commit recovered result
        ↓
      retry merge
  ↓
validated merge becomes new local/integration HEAD
  ↓
git merge --squash local/integration into captured Project branch
  ↓
one local Project-branch commit
  ↓
re-baseline local/integration to the new Project commit
  ↓
Closed · integrated
```

For effective `Isolated Worktree`:

```text
same isolated execution
→ Runner Completed
→ commit/snapshot the Task result locally
→ keep Task branch/worktree
→ do not auto-merge into local/integration / Project branch
→ Closed · worktree_ready
```

No remote push is required. Remote Git changes only through a separate explicit Publish action.


---

## 3. Branch naming convention

Use one predictable local namespace.

```text
Target branch
  main
  feature/ui
  release/v4
  ...the Project branch captured when the Task run starts

Runner-owned local integration branch
  local/integration

Per-Run Task branches
  local/task/<task-id>-r<run>

Temporary integration candidate branches
  local/candidate/<task-id>-r<run>-a<attempt>
```

Example:

```text
feature/ui
local/integration
local/task/T-001-r1
local/task/T-002-r1
local/task/T-003-r1
```

### Important Git ref rule

Do **not** create a branch named exactly:

```text
local
```

because it conflicts with hierarchical refs such as:

```text
local/integration
local/task/T-001-r1
```

---

## 4. Worktree naming convention

Task working directories should be deterministic and Runner-owned.

Example:

```text
.worktrees/
├─ integration/
├─ T-001-r1/
├─ T-001-r2/
├─ T-002-r1/
├─ candidate/
│  └─ T-001-r2-a1/
└─ delivery/
   └─ T-001-r2/
```

Recommended ownership:

```text
.worktrees/<task-id>-r<run>               → Agent / Runner execution
.worktrees/integration                     → canonical local/integration only
.worktrees/candidate/<task-run>-a<attempt> → temporary integration/recovery candidate
.worktrees/delivery/<task-run>             → temporary target delivery worktree when needed
```

Do not let two Task runs share the same worktree. Reset/Rerun must create a new run identity so retained Isolated Worktree results never collide with a later run.

---

## 5. Preserve existing modes: Auto / Main / Isolated Worktree

All three modes execute the Task inside an isolated Task worktree.

```text
Task mode
├─ Auto
├─ Main
└─ Isolated Worktree

Execution for all three
→ local/task/<task-id>-r<run>
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

Because every effective mode now executes in an isolated worktree, old “Main busy = filesystem path is occupied” safety logic no longer applies.

Recommended interpretation:

- `Always Main`: multiple Tasks may execute concurrently in separate worktrees; all resolve to Main delivery and later serialize through the Integration Queue.
- `Always Worktree`: all resolve to Isolated Worktree delivery.
- `Busy → Worktree`: may remain a product policy where Auto chooses Isolated Worktree when the Project is already busy, but it is no longer required for path-safety.
- Do not block an explicit Main Task merely because another Main Task is running; integration serialization is the safety boundary.

The existing resolver remains the single owner, but its implementation must be updated to reflect the new all-worktree execution model rather than reused unchanged.

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
→ preserve local/task/<task-id>-r<run>
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
→ keep local/task/<task-id>-r<run>
→ keep worktree/result
→ do not automatically integrate into target_branch
```

The existing Merge / Merge Chat style actions may still be offered later if the user wants to integrate that retained result manually.

---

## 6. Target branch + commit-ancestry synchronization

Do not hardcode `main`.

When a Task run starts, capture the Project repository's currently checked-out branch as `target_branch`.

Examples:

```text
Project currently on feature/ui
→ target_branch = feature/ui

Project currently on release/v4
→ target_branch = release/v4

Project currently on main
→ target_branch = main
```

The captured `target_branch` remains stable for that Task run even if the user later switches the Project checkout.

### Synchronization source is committed branch history

`local/integration` synchronization is based on Git commit ancestry, **not file-tree equality**.

Let:

```text
P = target_branch HEAD
I = local/integration HEAD
```

Rules:

```text
local/integration missing
→ create local/integration at P

P is ancestor of I
→ integration already contains the Project branch commit history
→ do NOT reset/update merely because Task merges changed files

I is ancestor of P
→ Project branch has newer commits and integration has no unique divergent work
→ fast-forward local/integration to P

P and I diverged
→ Project branch has newer commits AND local/integration has accepted Task commits
→ merge/reconcile missing Project commits into local/integration
→ never discard accepted Task commits
→ a real code conflict follows normal Runner recovery
```

> **Different file contents are not a synchronization signal. Missing Project commits are.**

### Uncommitted Project changes

Uncommitted Project working-tree changes are **not** part of this synchronization contract.

They have no stable commit identity and cannot participate reliably in ancestry/conflict detection. If the user wants those changes to become the base for new Main tasks, they must first be committed on the Project branch.

### Detached HEAD

If the Project is detached HEAD at Task start, fail closed or require an explicit target branch. Do not invent `main`.

---

## 7. Create / update local/integration before Task worktree creation

Under the repository Git lock:

1. read `target_branch` HEAD;
2. compare ancestry with `local/integration`;
3. create/update/reconcile only Project commits missing from `local/integration`;
4. create the Task-run branch/worktree from the resulting integration HEAD.

### No extra empty sync commit is required

```text
feature/ui:
A ─ B ─ C

local/integration missing
→ create local/integration at C
```

`C` itself is already a real commit and is the common ancestor Git needs for conflict detection.

Then:

```bash
git worktree add -b local/task/T-001-r1 <worktree-path> local/integration
```

### Do not reset accepted Task history

```text
feature/ui:
A ─ B ─ C

local/integration:
A ─ B ─ C ─ M1
```

Do not reset integration back to `C`; `M1` is intentional accepted Task history.

### If the Project branch gains new commits

Simple fast-forward case:

```text
feature/ui:        A ─ B ─ C ─ D
local/integration: A ─ B ─ C
```

→ fast-forward integration to `D`.

Diverged case:

```text
feature/ui:        A ─ B ─ C ─ D
local/integration: A ─ B ─ C ─ M1
```

→ reconcile/merge `D` into integration while preserving `M1`. If that conflicts, collect error context and use existing Runner recovery.

### Delete/recreate is allowed only when safe

Deleting/recreating integration is allowed only when it has no accepted undelivered Task commits.

Typical safe moment: after the accepted integration result has been squash-delivered to Project branch and the Project branch has a new commit. Because squash does not preserve ancestry, integration can then be reset/recreated at that new Project commit.


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

## 9. Every completed effective Main Task enters Integration Queue

Execution may be parallel:

```text
T-001 → Runner ───────────── Done
T-002 → Runner ───── Done
T-003 → Runner ───────────────── Done
```

Because this design uses one fixed `local/integration` branch per repository, integration must be serialized **per repository**, not merely per target branch:

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

> **Execution parallel, integration serial per repository.**

Do not allow two integration transactions in the same repository to mutate the single `local/integration` branch concurrently. Different repositories may integrate independently.

---

## 10. Commit each completed Task result before integration

Runner remains Git-unaware, so Runner completion does not guarantee that file changes are committed.

Before a completed Task enters integration:

```text
Runner Completed
→ verify Task worktree is not in unresolved merge/rebase state
→ git add -A
→ create a local Task snapshot commit for remaining changes
→ record task_snapshot_sha
→ Task branch now has a stable mergeable Git result
```

If Runner/Agent already created commits, keep them; only commit the remaining changes.

If the Task has no effective changes versus its base, mark `no_changes` and do not create an empty Project commit.

### Why this commit boundary is required

Example with two Tasks created from the same integration commit `C`:

```text
local/integration:
A ─ B ─ C

Task T1:
A ─ B ─ C ─ T1

Task T2:
A ─ B ─ C ─ T2
```

Merge T1 first:

```text
local/integration:
A ─ B ─ C ── M1
         \   /
          T1
```

Then merge T2. Git can use `C` as the merge base and compare `C → M1` against `C → T2`. If T1 and T2 changed incompatible lines, Git can produce a real merge conflict.

This is why the Task result must become a commit before merging back.

### No extra integration baseline commit

Do not create an empty sync commit merely to mark that `local/integration` was synchronized. The Project commit it already points to is the common ancestor.

---

## 11. One effective-Main integration transaction

Use a temporary candidate branch/worktree so canonical `local/integration` is never left in a conflicted merge state.

```text
Task snapshot commit ready
  ↓
acquire repository integration lock
  ↓
synchronize Project commits missing from local/integration by ancestry
  ↓
create temporary candidate from local/integration HEAD
  ↓
git merge --no-ff --no-commit local/task/<task-id>-r<run>
  ↓
conflict?
  ├─ no
  │   ↓
  │ validate candidate
  │   ↓
  │ create candidate merge commit
  │
  └─ yes
      ↓
    abort candidate merge
      ↓
    merge_failure_count +1
      ↓
    collect original Task intent + base/snapshot SHA + latest integration SHA + conflicting files + Git output
      ↓
    existing Runner redo/recovery against latest integration context
      ↓
    Review / Validate
      ↓
    commit recovered Task result
      ↓
    retry candidate merge
  ↓
candidate valid
  ↓
advance canonical local/integration to candidate merge commit
  ↓
deliver accepted local/integration to captured target_branch
  ↓
git merge --squash local/integration
  ↓
git commit with stable Task-run identity
  ↓
record target_commit_sha
  ↓
re-baseline local/integration to new target_branch HEAD
  ↓
Closed · integrated
```

The repository integration lock stays held across canonical integration advancement and Project-branch delivery.

---

## 12. Why normal merge into local/integration, but squash merge into Project branch

These are intentionally different operations.

### Task → local/integration: preserve ancestry

Use a real Git merge on a temporary candidate:

```bash
git merge --no-ff --no-commit local/task/T-001-r1
# validate
git commit
```

Reason:

- Task branches need a shared merge base.
- Integration history must remember accepted Task commits.
- Later concurrent Tasks must merge against earlier accepted Task history so Git can detect conflicts.

### local/integration → Project branch: keep Project history clean

Use:

```bash
git merge --squash local/integration
git commit -m "T-001: ..."
```

This gives the Project branch one clean logical commit instead of temporary Agent/merge history.

Because squash does not preserve ancestry, immediately re-baseline `local/integration` to the new Project commit after successful delivery.

---

## 13. Project branch synchronization while Tasks are running

The Project branch may receive a new commit while several Tasks are still running.

Example:

```text
Task T1/T2 base:
A ─ B ─ C

Project later:
A ─ B ─ C ─ D

local/integration after another accepted Task:
A ─ B ─ C ─ M1
```

Before merging the next Task, integration must include `D`. Do not reset `M1` away.

Reconcile the new Project commit into integration while preserving accepted Task history. If that reconciliation conflicts, it is a real integration conflict and follows the same error-context + Runner recovery policy.

Only after missing Project commits are included should the next Task branch be merged.

---

## 14. Project delivery + re-baseline

After a Task is successfully merged into `local/integration`, deliver that accepted result to the captured Project branch.

```text
Project branch:
A ─ B ─ C

local/integration:
A ─ B ─ C ─ M1
```

Deliver:

```bash
git merge --squash local/integration
git commit -m "T-001: ..."
```

Project becomes:

```text
A ─ B ─ C ─ S1
```

`S1` is not an ancestor of the old integration history because squash created a new commit. Therefore, after durable delivery and only when there is no accepted undelivered integration result:

```text
reset/recreate local/integration at S1
```

Result:

```text
A ─ B ─ C ─ S1
              ├─ Project branch
              └─ local/integration
```

### Dirty Project checkout

Automatic Main delivery must not silently mix with unrelated uncommitted Project files.

If the captured target branch checkout is dirty at delivery time:

```text
Closed · waiting_target_clean
```

Do not auto-stash, reset, discard, or commit those user changes. Once the checkout is clean, retry delivery.

### Project checkout moved to another branch

Do not automatically switch the user's checkout back. If the captured target branch can be safely checked out in a managed delivery worktree, use that. Otherwise expose `waiting_target_workspace` and preserve all Task/integration artifacts.


---

## 15. Conflict handling

A normal Git conflict is not automatically a Task execution failure.

Integration Manager owns deterministic Git operations:

- inspect latest target/integration SHA
- Task snapshot + candidate normal Git merge mechanics
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
candidate normal Git merge conflict requiring source edits
latest target changed architecture and old patch no longer applies
validation/test failure after applying the Task snapshot to the latest candidate
review failure caused by integration result
generated code no longer matches latest interfaces/contracts
semantic conflict even when Git has no textual conflict
```

The recovery Runner may repair the existing candidate or re-do the affected part from the latest integrated code. It must still run the normal Review / Validate path before integration is retried.

Do not bypass Runner validation by directly accepting AI-edited conflict files from Integration Manager.

---

## 16. Temporary candidate / recovery worktree

Do not merge directly into canonical `local/integration` first.

Recommended:

```text
local/integration HEAD
      ↓
temporary candidate branch/worktree
      ↓
normal Git merge of Task branch
      ↓
conflict?
├─ no  → validate → commit merge → advance local/integration
└─ yes → abort merge
          ↓
        collect conflict/error/latest-code context
          ↓
        existing Runner redo/recovery
          ↓
        commit recovered Task result
          ↓
        retry
```

The original completed Task branch/worktree remains untouched until delivery succeeds.

Candidate branch names include Task run + attempt, for example:

```text
local/candidate/T-001-r2-a1
```

Only advance canonical `local/integration` after the candidate merge is valid.


---

## 17. Remote Git policy

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

## 18. Do not call local integration "push"

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

## 19. Ownership boundaries

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

- target HEAD snapshot + optimistic re-checks
- `local/integration`
- repository-wide integration lock / queue for the single `local/integration` branch
- completed Task snapshot creation
- candidate branch/worktree apply mechanics
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

## 20. Merge failure counting / retry exhaustion

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

- candidate normal Git merge produces a source conflict that requires Runner repair/rework
- recovery Runner completes, but the next candidate merge attempt still conflicts
- candidate merge succeeds textually, but integration validation/test fails and requires Runner code changes
- semantic incompatibility with latest target requires Runner to redo part of the implementation

Examples that **do not count**:

- waiting in Integration Queue
- target branch is dirty
- integration lock is busy
- Task has not reached integration yet
- temporary worktree creation transiently fails
- deterministic Git command retry where no code repair/rework is required
- target branch HEAD changed during integration and the candidate must be rebuilt against the newer commit
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

## 21. UI / Task status model

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
| Effective Main: target branch is checked out in an unmanaged worktree | Closed | waiting_target_workspace + Needs Attention |
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
→ Closed · integrating / conflict_recovery / project_commit_sync / recovery
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
T-003  Closed
Conflict recovery · Runner retry 2

T-004  Closed
Awaiting merge · 4 failures

T-005  Closed
Integrated · feature/ui
```

Do not add Git controls directly to every card.

Do not add a separate top-level “Git Worktree” page. Daily operations stay Task-centric. Project-level Workspace Results may provide the secondary management view for retained/orphaned worktrees, Awaiting Merge items, paths, branches and cleanup.

#### Task Info Drawer

Add an `Integration` section only when the Task uses Git worktree delivery metadata.

Example:

```text
Integration
Requested mode    Auto
Effective mode    Main
Target branch     feature/ui
Task run          T-001-r1
Task branch       local/task/T-001-r1
Base              abc123
State             Integrating
Latest target     def456
Attempt           2
Attention         —
```

When the Project changed concurrently:

```text
State             Re-syncing latest Project state
Attention         Project changed during integration
Action            Automatic rebuild/retry; only stop if a real conflict exhausts retry budget
```

#### Task List / child items

The Git integration unit is the **actual Task run/workspace result**, not automatically the Board parent.

If a Task List allows child Tasks to resolve different Workspace modes or worktrees, each child run owns its own:

- Task-run branch/worktree
- snapshot SHA
- effective mode
- integration transaction/status
- target commit or retained worktree result

The parent Board Task aggregates these results for compact UI, for example:

```text
Closed
Integration · 2 integrated · 1 worktree ready · 1 awaiting merge
```

Do not force all child Tasks into one worktree merely to simplify the UI, and do not duplicate full Git controls on every child row unless expanded.

### Runtime / projection separation

Keep three concepts separate:

```text
Board lifecycle
New / Ongoing / Paused / Closed

Runner runtime
idle / running / recovering / stopped / completed / attention / ...

Git integration
not_started / pending_merge / integrating / conflict_recovery /
waiting_target_workspace / project_commit_sync / recovery / merge_retry_exhausted /
integrated / no_changes / failed / worktree_ready / not_required
```

UI composes these into one readable Task view, but no layer re-derives or replaces another owner's state machine.

### Allowed actions during integration

Initial policy:

- While `pending_merge/integrating/conflict_recovery/recovery`: the Task is Closed but disable destructive Reset/Rerun/Delete that could invalidate the integration transaction.
- `Open Info`, logs, worktree path, target branch and conflict details remain available.
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

## 22. Suggested Task metadata

Keep Git orchestration metadata outside generic Runner RunState.

For requested `Auto` resolved to effective `Main`:

```yaml
git:
  requested_workspace_mode: auto
  effective_workspace_mode: main

  target_branch: feature/ui
  target_head_sha_at_start: abc123

  run_id: T-001-r2
  integration_base_sha: def456
  task_branch: local/task/T-001-r2
  worktree: .worktrees/T-001-r2
  task_snapshot_sha: 111aaa

  integration_tx_id: T-001-r2
  integration_status: pending_merge
  integration_head_sha: null
  target_commit_sha: null
  integration_attention: null

  merge_failure_count: 0
  merge_retry_attempt: 0
  max_merge_failures: 3
  last_merge_failure: null
```

For requested `Isolated Worktree`:

```yaml
git:
  requested_workspace_mode: isolated_worktree
  effective_workspace_mode: isolated_worktree
  target_branch: feature/ui
  target_head_sha_at_start: abc123
  run_id: T-002-r1
  integration_base_sha: def456
  task_branch: local/task/T-002-r1
  worktree: .worktrees/T-002-r1
  task_snapshot_sha: 222bbb
  integration_status: worktree_ready
```

Persist requested and effective mode so later Global Auto setting changes do not rewrite Task history.

### Idempotent Project delivery

Every automatic Main squash commit should carry a stable Task-run identity, for example:

```text
AI-Task-Run: T-001-r2
```

Persist `target_commit_sha` immediately after commit succeeds.

On restart after a crash: check the recorded commit SHA first; otherwise search the captured target branch for the stable Task-run identity. If already delivered, re-baseline integration and finalize state instead of creating a duplicate squash commit.

Do not duplicate Runner RunState inside this metadata.


---

## 23. Skill / prompt policy

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

### Cleanup / retention default

Use a fail-safe retention policy:

- temporary candidate/recovery worktrees: remove after the transaction attempt is durably finalized; stale candidates from a crash may be reconciled on startup;
- temporary delivery worktrees: remove after target commit is durably recorded;
- effective Main + `integrated` / `no_changes`: Task-run worktree/branch may be removed after target result is durably recorded and no retry needs it;
- effective Isolated Worktree + `worktree_ready`: retain until explicit user cleanup/delete;
- Main + `merge_retry_exhausted`, `failed`, or `waiting_target_workspace`: retain Task-run worktree/branch;
- never delete an unknown/unowned worktree path merely because its directory name resembles a Task ID.

Workspace Manager must verify Git worktree registration + Task/run ownership metadata before destructive cleanup.

## 24. Failure / recovery principles

- Count a merge failure only after a successful Runner execution/recovery reaches a real integration attempt and delivery still fails for a code/semantic/validation reason.
- Do not count queue waits, a newly observed Project commit by itself, lock contention, dirty target delivery state, or deterministic transient Git failures as merge failures.
- Stop automatic Runner recovery when the configured merge-failure budget is exhausted; preserve the Main-mode Task branch/worktree and keep the Task `Closed · Awaiting merge`.
- Preserve lifetime `merge_failure_count` for diagnostics even when a user starts a new retry session.
- Never destroy the original completed Task worktree before integration succeeds.
- Never auto-stash, reset, discard, or silently commit unrelated uncommitted Project checkout changes.
- Never advance canonical `local/integration` to an unvalidated candidate.
- Never run two canonical integration transactions in the same repository simultaneously.
- A conflict should preserve enough context to resume/retry after process restart.
- A failed integration must not make the completed Agent result disappear.
- Cleanup happens only after the target squash commit is safely created, or by explicit user action.
- Remote Git remains untouched unless explicitly published.

---

## 25. Example: three Agents in parallel

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
→ snapshot T-003 → candidate from latest local/integration
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
→ snapshot T-001 → candidate from C-S3
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

## 26. Implementation TODO

### Phase A — contracts / metadata

- [ ] Add merge failure metadata: lifetime `merge_failure_count`, current-session `merge_retry_attempt`, configurable `max_merge_failures`, and structured `last_merge_failure`.
- [ ] Define exact counter semantics so only a Runner-complete → real integration-failure cycle consumes the merge retry budget.
- [ ] Lock the architecture invariant: Git worktree/integration orchestration must not modify Runner / FlowEngine / StageExecutor / Supervisor execution structure.
- [ ] Define that any integration failure requiring source-code changes re-enters the existing Runner using a recovery worktree; Integration Manager itself never repairs application code.
- [ ] Preserve Task modes Auto / Main / Isolated Worktree. All execute in isolated worktrees; Auto reuses the existing Global resolver, Main auto-integrates to the captured Project branch, Isolated Worktree keeps the result without auto integration.
- [ ] Resolve `target_branch` from the Project repository's currently checked-out branch when the Task starts; persist it for that Task and never hardcode `main`.
- [ ] Define minimal Git metadata for target branch/HEAD, integration base/head SHA, Task base/snapshot SHA, worktree path, integration status, and target commit SHA.
- [ ] Define stable local branch naming: `local/integration`, `local/task/<task-id>-r<run>`, and temporary `local/candidate/<task-run>-a<attempt>`.
- [ ] Define deterministic worktree paths using Task + Run identity; Reset/Rerun must never collide with retained prior runs.

### Phase B — Workspace Manager

- [ ] Synchronize `local/integration` from the captured Project branch strictly by commit ancestry, then create the Task branch/worktree from `local/integration`.
- [ ] Keep `local/integration` checked out only in a system-owned `.worktrees/integration` path; never switch the user's Project checkout to it.
- [ ] Before Task creation, under a short repository Git lock, add only Project commits missing from `local/integration`; do not reset accepted Task merge commits merely because file contents differ.
- [ ] Keep uncommitted Project working-tree changes outside the ancestry-sync contract; they must be committed before becoming a new Main Task base.
- [ ] Return Task worktree path as the existing Runner `project_root`.
- [ ] Add ownership-verified cleanup: integrated/no_changes Main results may clean Task worktree after durable target commit; Isolated/Awaiting Merge/blocked/failed results must be retained.
- [ ] Ensure multiple Task worktrees can execute concurrently.

### Phase C — Snapshot + Integration Queue

- [ ] Stop automatic recovery for a Task when merge retry budget is exhausted; remove it from active integration execution without losing its queued/artifact state.
- [ ] Support Retry merge to start a new retry session while preserving lifetime failure history and original Main mode.
- [ ] Freeze each completed Task run into a reproducible local snapshot commit before integration; include uncommitted tracked/untracked non-ignored changes.
- [ ] Add one serialized Integration Queue/lock per repository because the repository has one fixed `local/integration` branch.
- [ ] Completed Tasks whose effective mode resolves to Main enqueue automatically.
- [ ] Completed Isolated Worktree Tasks do not auto-enqueue for integration; they close as worktree_ready.
- [ ] Do not block parallel Runner execution while integration is busy.
- [ ] Persist enough queue/integration state to recover after UI/backend restart.

### Phase D — Task integration

- [ ] Before each Task merge, reconcile Project branch commits missing from `local/integration` by ancestry while preserving accepted Task integration commits.
- [ ] Use a temporary integration/recovery worktree for replay/conflict resolution.
- [ ] Recreate/reset `local/integration` from Project HEAD only when it has no accepted undelivered Task commits; otherwise merge/reconcile missing Project commits.
- [ ] Create a temporary candidate from `local/integration` and perform a normal Git merge of the committed Task-run branch there; do not rebase/mutate the original completed Task worktree.
- [ ] Validate the candidate result before advancing canonical `local/integration`.
- [ ] Advance `local/integration` only after successful candidate validation.
- [ ] Re-check target branch HEAD immediately before delivery; if new Project commits appeared, reconcile them into integration first. A new Project commit alone does not consume merge-failure budget.

### Phase E — Conflict recovery through existing Runner

- [ ] Detect Git/code conflicts deterministically.
- [ ] Build recovery context: original Task, old/new SHA, conflict files, Git output, validation errors.
- [ ] Call the existing Runner with the recovery/integration worktree as `project_root`.
- [ ] Prompt for semantic repair/reimplementation against latest code, not blind conflict-marker removal.
- [ ] Run normal Review / Validate.
- [ ] Retry integration after recovery completes.
- [ ] Keep original Task result until integration succeeds.

### Phase F — squash-deliver local/integration to captured Project branch

- [ ] Require a clean target delivery worktree; do not auto-stash/reset/commit unrelated user changes.
- [ ] Run `git merge --squash local/integration` into the captured target branch and create exactly one local Task commit.
- [ ] Record `target_commit_sha` + stable Task-run identity trailer for restart idempotency.
- [ ] After successful delivery, reset/recreate `local/integration` at the new target HEAD because squash delivery does not preserve ancestry.
- [ ] Release the integration lock only after delivery + re-baseline is durable.
- [ ] Cleanup successful Task/recovery worktrees according to retention policy.

### Phase G — UI

- [ ] Show merge failure count and retry budget in Task Info and compactly on the Board when nonzero.
- [ ] On retry exhaustion, keep the Task `Closed · Awaiting merge` with `merge_retry_exhausted`; Closed means execution finished, not necessarily merged.
- [ ] After Main retry exhaustion, automatically retain the worktree, show Retry merge, and preserve mode=Main; do not silently rewrite it to Isolated Worktree.
- [ ] Keep Board columns as New / Ongoing / Paused / Closed; do not add an Integration column.
- [ ] Runner execution Completed moves the Task to Closed immediately; effective Main continues through Closed integration states, while Isolated Worktree closes as worktree_ready.
- [ ] Isolated Worktree closes as worktree_ready when Runner completes and does not auto-integrate.
- [ ] Add secondary integration badge/detail: pending / integrating / conflict_recovery / project_commit_sync / waiting_target_workspace / recovery / integrated / failed / not_required.
- [ ] Keep Paused reserved for unfinished resumable Runner execution; all post-execution Git delivery states stay under Closed.
- [ ] Add Integration details to Task Info Drawer (requested mode, effective mode, target branch, Task run/branch, base/latest SHA, state, attempt, attention reason).
- [ ] Disable destructive Reset/Rerun/Delete during active integration/recovery through one backend-owned allowed-actions projection.
- [ ] Keep current Workspace choices Auto / Main / Isolated Worktree, while clarifying that every mode executes in an isolated worktree.
- [ ] Update Global Auto semantics for all-worktree execution: explicit/Always Main must not block merely because another Main Task is running; Integration Queue provides serialization.
- [ ] Main description: execute in isolated worktree, then auto-integrate/squash into the Project branch captured when the Task starts; `Main` is a mode label, not a literal branch name.
- [ ] Isolated Worktree description: execute in isolated worktree and keep the result without automatic integration.
- [ ] Auto remains the default and reuses the existing Global workspace policy resolver; persist the resolved effective mode for the Task run.
- [ ] Show integration status without creating another Runner state machine.
- [ ] Show `project_commit_sync` while newly observed Project commits are being reconciled into integration, `waiting_target_clean` when squash delivery is blocked by uncommitted target changes, and `waiting_target_workspace` when the captured branch cannot be safely delivered without switching/overwriting a user workspace.
- [ ] Expose conflict/recovery details without forcing the user to understand Git internals for normal success paths.
- [ ] Do not add a top-level Git Worktree page; reuse Task Info and Project Workspace Results as the normal/secondary surfaces.

### Phase H — local-only / publish

- [ ] Ensure normal Task integration never runs `git push origin`.
- [ ] Add explicit/manual Publish separately if needed.
- [ ] Publish must target the Project-selected branch, not hardcoded main.
- [ ] Keep remote reconciliation/publish policy independent from local Integration Manager.

---

## 27. Test TODO

### Worktree isolation

- [ ] Start 2, 5, and 10 Tasks from the same target branch concurrently.
- [ ] Confirm every Runner receives a unique worktree path.
- [ ] Confirm no Task edits another Task worktree.
- [ ] Confirm uncommitted Project working-tree changes are not silently imported into `local/integration`; after committing them, the next ancestry sync includes the new Project commit.
- [ ] Complete a Runner run with only uncommitted file changes; confirm snapshot commit captures them before integration.
- [ ] Reset/Rerun the same Task while an older Isolated Worktree result is retained; confirm run-specific branch/path names do not collide.

### Integration ordering

- [ ] Verify queue wait / target dirty / lock contention do not increment merge failure counters.
- [ ] Force repeated Runner-complete → merge-fail cycles and verify each real failed delivery attempt increments exactly once.
- [ ] Verify retry exhaustion stops automatic Runner recovery and projects `Closed · Awaiting merge`.
- [ ] Retry manually and confirm retry-session budget resets while lifetime merge failure count is preserved.
- [ ] Exhaust Main merge retries and confirm the Task automatically retains its worktree/branch, remains mode=Main, target branch is untouched, and UI shows `Closed · Awaiting merge`.
- [ ] Finish Tasks out of creation order.
- [ ] Confirm one repository-wide Integration Queue serializes them safely even when Tasks target different branches in the same repository.
- [ ] Confirm later Tasks merge against the latest `local/integration` history without mutating original completed Task worktrees.
- [ ] Confirm each Project-Branch Task creates one squash commit on target.

### Dirty target

- [ ] Make uncommitted user edits before Task start and confirm ancestry sync ignores them; commit them, then confirm the new Project commit is synchronized.
- [ ] Make the target checkout dirty before squash delivery and confirm delivery waits without auto-stash/reset/commit.
- [ ] Switch the Project root to another branch after Task start; confirm the system does not switch it back automatically and uses a managed delivery worktree when safe.
- [ ] Check out target_branch in an unmanaged worktree; confirm delivery becomes `waiting_target_workspace`.
- [ ] Add a new Project commit while candidate validation is running; confirm it is reconciled into integration before delivery and only a real code conflict increments merge-failure count.

### Conflict recovery

- [ ] Start two Tasks from the same integration base, make incompatible edits to the same lines, merge one first, and confirm merging the second produces a real Git conflict and invokes Runner recovery.
- [ ] Force a no-text-conflict validation failure caused by latest target changes and confirm the existing Runner redoes/fixes the affected implementation.
- [ ] Confirm recovery still passes the normal Runner Review / Validate path before integration continues.
- [ ] Two Tasks modify the same lines.
- [ ] Confirm conflict context is generated.
- [ ] Confirm existing Runner is called against the recovery worktree.
- [ ] Confirm semantic repair can preserve latest integrated code and original Task intent.
- [ ] Confirm failed recovery does not destroy the original Task worktree.
- [ ] Confirm retry can eventually produce one valid squash commit.

### Restart / unattended / idempotency

- [ ] Restart UI/backend while Tasks are running.
- [ ] Restart while integration is queued.
- [ ] Restart while waiting for target clean.
- [ ] Restart during conflict recovery.
- [ ] Crash immediately after target `git commit` but before Task state persistence; recover using Task-run identity and do not create a duplicate squash commit.
- [ ] Recover without deleting unintegrated Agent output.

### Local-only guarantee

- [ ] Run the entire suite with remote credentials unavailable.
- [ ] Confirm Task execution and local integration still succeed.
- [ ] Confirm no automatic `git push` occurs.
- [ ] Explicit publish remains a separate action.

---

## 28. Non-goals for the first implementation

- Do not redesign Runner.
- Do not add a new Workflow Stage for Git integration.
- Do not add a second retry/recovery engine inside Runner.
- Do not let browser frontend execute Git directly.
- Do not rebase/mutate the original completed Task worktree as part of integration.
- Do not automatically switch the user's Project checkout branch.
- Do not auto-stash, reset, discard, or silently commit unrelated dirty Project checkout files.
- Do not push every Task to remote.
- Do not create multiple competing canonical integration branches.
- Do not add an AI Skill for deterministic Git commands.
- Do not make `local/integration` long-lived accumulated history after a Task has already been squash-committed to target.

---

## 29. Design invariant summary

```text
Task modes:
  Auto / Main / Isolated Worktree

Execution:
  every mode uses isolated Task worktree
  Runner(project_root) unchanged

Project sync:
  target_branch = Project branch captured at Task start
  local/integration syncs by commit ancestry only
  file-content difference alone never causes reset
  uncommitted Project changes are outside this sync contract

Main:
  Task worktree branches from committed local/integration
  → Runner completes
  → remaining Task changes become a Task snapshot commit
  → normal Git merge into local/integration
  → conflict => Git error/latest context + existing Runner redo/recovery
  → accepted local/integration squash-delivered to captured Project branch
  → one local Project commit
  → local/integration re-baselined to that new Project commit
  → merge failures over limit: retain worktree + Closed · Awaiting merge

Isolated Worktree:
  Runner Completed → snapshot commit → Closed · worktree_ready
  keep isolated result
  no automatic target modification

Concurrency:
  execution parallel
  one repository-wide integration queue/lock
  later Task merges see earlier accepted Task commits and can conflict correctly

Runner:
  no Git integration knowledge required

Remote:
  untouched until explicit publish
```

