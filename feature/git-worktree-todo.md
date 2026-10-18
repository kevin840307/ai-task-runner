# Git Worktree Parallel Task Integration TODO

> Status: design / implementation TODO
>
> Scope: add parallel Task worktree + local Git integration around the existing Runner. **Do not redesign Runner execution.**
>
> Final direction: **do not create or maintain a canonical `local/integration` branch.** The captured Project branch is the canonical truth. Task worktrees are isolated execution results; temporary candidate worktrees are disposable merge/recovery sandboxes.

---

## 1. Current AS-IS

The current execution boundary remains:

```text
UI
  ↓
Create / Run Task
  ↓
Runner(project_root)
  ↓
Workflow / Agent
  ↓
Review / Validate
  ↓
Completed
```

Runner only receives `project_root`.

### Hard invariant: Runner architecture stays unchanged

Do not add Git/worktree integration ownership into:

- FlowEngine
- StageExecutor
- Supervisor
- normal Workflow Stage routing
- Runner retry/recovery state

The existing Runner contract remains conceptually:

```text
Runner(project_root, task/workflow input)
→ Workflow / Agent
→ Review / Validate
→ Completed
```

If Git integration later requires source-code changes, call the **same existing Runner** again against a temporary recovery/candidate worktree.

---

## 2. Simplified target architecture

Use the Project branch directly as the canonical integration source.

```text
                    captured Project branch
                           canonical
                              │
             ┌────────────────┼────────────────┐
             ↓                ↓                ↓
       Task T1 worktree  Task T2 worktree  Task T3 worktree
             ↓                ↓                ↓
           Runner           Runner           Runner
             ↓                ↓                ↓
        Task commit       Task commit       Task commit
             │                │                │
             └────────────────┼────────────────┘
                              ↓
                      Integration Queue
                              ↓
                    latest target branch HEAD
                              ↓
                    temporary candidate
                              ↓
                    normal Git merge Task
                              ↓
                         conflict?
                       ┌──────┴──────┐
                      yes            no
                       ↓              ↓
                existing Runner     Validate
                redo / recovery       ↓
                       ↓        target merge --squash
                     retry            ↓
                                one Project commit
```

### Why remove `local/integration`

A persistent integration branch would duplicate canonical state and require extra rules for:

- synchronizing Project commits into the integration branch;
- deciding whether file differences are intentional Task results or stale state;
- preserving accepted integration-only commits;
- re-baselining after squash delivery;
- crash recovery for another canonical branch;
- locking one shared integration ref across unrelated target branches.

Those states are unnecessary when every completed Task is integrated against the latest target branch through a disposable candidate.

### User-owned feature branches remain user-owned

If the user wants work isolated from `main`, they can create/switch to a Project branch first:

```bash
git switch -c feature/ui
```

A Task started there captures `feature/ui` as its target. The system does not need to invent another permanent integration branch.

---

## 3. Preserve existing modes: Auto / Main / Isolated Worktree

All modes execute inside isolated Task worktrees.

```text
Task mode
├─ Auto
├─ Main
└─ Isolated Worktree

Execution for all three
→ local/task/<task-id>-r<run>
→ isolated worktree
→ Runner(project_root = worktree)
```

The mode decides **delivery after Runner completes**, not where Agent edits files.

### Auto

`Auto` remains the default and reuses the existing Global workspace resolver.

```text
Auto
↓
Global policy
├─ effective Main
└─ effective Isolated Worktree
```

Keep one resolver owner. Do not duplicate busy/worktree logic inside Integration Manager.

Because every mode now runs in a worktree:

- `Always Main` does not need to block merely because another Main Task is executing;
- multiple Main Tasks may execute concurrently;
- safety comes from isolated worktrees + serialized delivery to the same target branch;
- `Busy → Worktree` may remain a product policy, not a filesystem-safety requirement.

Persist both requested mode and resolved effective mode per Task run.

### Main

`Main` is a product mode name. It does **not** mean the Git branch must literally be named `main`.

Effective Main means:

```text
captured Project branch
→ isolated Task worktree
→ Runner
→ Task result commit
→ candidate merge against latest captured target branch
→ validate
→ squash-deliver to target branch
→ one local target commit
```

### Isolated Worktree

Effective Isolated Worktree means:

```text
captured Project branch
→ isolated Task worktree
→ Runner
→ Task result commit/snapshot
→ Closed · Worktree ready
→ keep branch/worktree
→ no automatic target modification
```

Existing Merge / Merge Chat actions may still integrate that retained result later.

---

## 4. Target branch semantics

At Task run start, capture the Project repository's currently checked-out branch as `target_branch`.

Examples:

```text
Project currently on feature/ui
→ target_branch = feature/ui

Project currently on release/v4
→ target_branch = release/v4

Project currently on main
→ target_branch = main
```

`target_branch` remains fixed for that Task run even if the user later switches the Project checkout.

### Task base is committed Git history

Create the Task branch from the captured target branch HEAD at Task start.

```text
feature/ui:
A ─ B ─ C
        ↑
      Task base
```

Uncommitted Project working-tree changes are **not** part of this base.

Reason:

- Git conflict detection requires a stable merge base;
- uncommitted files have no commit identity;
- importing ad-hoc working-tree state creates ambiguous ancestry and recovery semantics.

If the user wants current uncommitted Project changes to become part of new Main Task bases, commit them first.

Dirty Project state does not need to block Runner execution; it only must not be silently imported into the Task base.

### Detached HEAD

If the Project is detached HEAD at Task start, fail closed or require an explicit target branch. Do not invent `main`.

---

## 5. Branch and worktree naming

Use predictable Runner-owned local refs.

```text
Project branches
  main
  feature/ui
  release/v4
  ...

Task-run branches
  local/task/<task-id>-r<run>

Temporary candidate branches
  local/candidate/<task-id>-r<run>-a<attempt>
```

Examples:

```text
local/task/T-001-r1
local/task/T-001-r2
local/task/T-002-r1
local/candidate/T-001-r2-a1
```

Do not create a branch named exactly `local`; hierarchical refs such as `local/task/...` would conflict with it.

Recommended worktree paths:

```text
.worktrees/
├─ T-001-r1/
├─ T-001-r2/
├─ T-002-r1/
└─ candidate/
   └─ T-001-r2-a1/
```

Task + Run identity is required so Reset/Rerun never collides with retained prior results.

---

## 6. Task start

For every Task run:

1. resolve requested/effective workspace mode;
2. capture `target_branch`;
3. read `target_head_sha_at_start`;
4. create Task-run branch from that commit;
5. create Task worktree for the Task-run branch;
6. pass only that worktree path to Runner.

Conceptually:

```bash
git rev-parse feature/ui
# → C

git worktree add -b local/task/T-001-r1 <path> C
```

Use a short repository Git lock for ref/worktree creation and cleanup. Runner execution itself does not hold that lock.

Once created, Task worktrees are independent and may run in parallel.

---

## 7. Commit the completed Task result

Runner remains Git-unaware. Runner completion does not guarantee that Agent changes are committed.

Before integration:

```text
Runner Completed
→ verify Task worktree is not already in unresolved merge/rebase state
→ git add -A
→ commit any remaining changes locally
→ record task_snapshot_sha
→ original Task result becomes a stable mergeable Git branch
```

If Runner/Agent already created commits, keep them and only commit the remaining changes.

If there is no effective diff versus the Task base:

```text
Main              → Closed · no_changes / integrated
Isolated Worktree → Closed · worktree_ready (no changes)
```

Do not create an empty target commit.

### Why Task result must be committed

Example:

```text
target branch:
A ─ B ─ C

T1:
A ─ B ─ C ─ T1

T2:
A ─ B ─ C ─ T2
```

After T1 is delivered as target commit `S1`:

```text
target branch:
A ─ B ─ C ─ S1

T2 still:
A ─ B ─ C ─ T2
```

When T2 is merged into a candidate based on `S1`, Git can use `C` as the merge base and compare:

```text
C → S1
C → T2
```

Therefore incompatible edits from T1 and T2 can produce a real merge conflict without any persistent integration branch.

---

## 8. Integration Queue and locking

Execution is parallel. Delivery to the same target branch is serialized.

```text
T1 Runner ───── Done ─┐
T2 Runner ─ Done ─────┼→ target-branch Integration Queue
T3 Runner ─────── Done ┘
```

Core rule:

> **Execution parallel; integration serialized per repository + target branch.**

Different repositories are independent.

Different target branches in the same repository may have independent delivery queues, but short Git ref/worktree mutations still use the repository Git lock.

Do not serialize all Runner execution behind Git integration.

---

## 9. Temporary candidate integration transaction

Never test a Task merge by mutating the user's target checkout first.

For an effective Main Task:

```text
Task snapshot commit ready
  ↓
take target-branch integration lock
  ↓
read latest target_branch HEAD = L
  ↓
create temporary candidate branch/worktree from L
  ↓
normal Git merge Task branch into candidate
  ↓
conflict?
  ├─ no
  │   ↓
  │ validate candidate
  │
  └─ yes
      ↓
    abort/contain candidate merge
      ↓
    merge failure +1
      ↓
    existing Runner recovery / redo
      ↓
    commit recovered Task result
      ↓
    retry against latest target
  ↓
candidate valid
  ↓
re-read target branch HEAD
  ├─ changed → discard/rebuild candidate against newer HEAD
  └─ same    → continue
  ↓
squash-deliver candidate to target branch
  ↓
one target commit
  ↓
record target_commit_sha
  ↓
cleanup candidate and successful Task result by retention policy
  ↓
Closed · integrated
```

A target HEAD movement by itself is not a merge failure. Rebuild the candidate first; only a real code/semantic/validation conflict consumes the merge-failure budget.

### Candidate merge operation

Candidate uses a normal merge so Git preserves the Task branch's original merge base during conflict detection:

```bash
git merge --no-ff --no-commit local/task/T-001-r1
# inspect / validate
```

The candidate branch is disposable. The original completed Task branch/worktree remains untouched until delivery succeeds.

---

## 10. Final delivery to Project branch

After candidate validation, deliver exactly the candidate delta to the captured target branch.

Normal case:

```text
target HEAD = S1
candidate  = S1 + merged T2 result
```

Delivery:

```bash
git merge --squash local/candidate/T-002-r1-a1
git commit -m "T-002: ..."
```

Target becomes:

```text
... ─ S1 ─ S2
```

This keeps Project history to one clean logical commit per successfully delivered Task.

### No re-baseline step

There is no persistent integration branch, so nothing needs to be reset/recreated after squash delivery.

The next completed Task simply creates a fresh candidate from the then-latest target branch HEAD.

---

## 11. Target branch movement and dirty checkout

### New Project commit while Task is running

Suppose T2 started from `C`, but target is now `C-S1`.

Do not modify T2's original branch.

Create its candidate from latest `C-S1` and merge T2 there. Git uses their common ancestor `C` and can detect conflicts against S1.

### Target changes while candidate is validating

Re-read target HEAD immediately before delivery.

If it changed:

```text
candidate based on old HEAD
→ discard candidate
→ create new candidate from new HEAD
→ merge/recover/validate again
```

This rebuild itself does not increment merge failure count.

### Dirty target checkout

Automatic squash delivery must never mix with unrelated uncommitted user files.

If the worktree that owns the captured target branch is dirty:

```text
Closed · waiting_target_clean
```

Do not auto-stash, reset, discard, stage, or commit those changes.

### User switched the Project checkout

Do not switch it back automatically.

If the captured target branch is free, create/use a temporary managed delivery worktree.

If the captured target branch is already checked out in an unmanaged/user worktree and cannot be safely used:

```text
Closed · waiting_target_workspace
```

Preserve Task/candidate artifacts.

---

## 12. Conflict and semantic recovery

Integration Manager owns deterministic Git operations only:

- candidate creation/removal;
- normal merge invocation;
- conflict detection;
- target HEAD checks;
- lock/queue handling;
- squash delivery;
- safe cleanup.

It does **not** become a second code-repair agent.

### Recovery context

When merge/code validation needs source edits, provide existing Runner with:

```text
Original Task prompt / intent
Original Task base SHA
Task snapshot SHA
Captured target branch
Latest target HEAD
Task branch / commits
Conflicting files
Git conflict/error output
Validation/test errors
Relevant project development rules
```

Recovery intent:

```text
Latest target code is authoritative.

Re-evaluate the original Task against the latest code.
Preserve compatible newer changes.
Redo affected implementation if the old patch no longer fits.
Do not merely remove conflict markers.
Run normal verification.
```

Then:

```text
Runner(project_root = recovery_candidate)
→ Workflow / Agent
→ Review / Validate
→ Completed
→ commit recovered result
→ retry candidate integration
```

Do not bypass normal Runner Review / Validate by directly accepting AI-edited conflict files from Integration Manager.

---

## 13. Merge failure counting and retry exhaustion

Recommended metadata:

```yaml
git:
  merge_failure_count: 0
  merge_retry_attempt: 0
  max_merge_failures: 3
  last_merge_failure: null
```

Semantics:

- `merge_failure_count`: lifetime diagnostic count for this Task delivery;
- `merge_retry_attempt`: automatic retry count in the current retry session;
- `max_merge_failures`: configurable automatic recovery limit;
- `last_merge_failure`: structured latest failure detail.

### Count exactly once per real failed integration attempt

Increment only when:

```text
Runner / recovery completed
→ real candidate merge / validation attempted
→ result cannot be accepted due to code / semantic / validation incompatibility
→ merge_failure_count += 1
→ merge_retry_attempt += 1
```

Examples that count:

- normal Git merge produces a source conflict requiring code changes;
- Runner recovery completes but the next candidate merge still conflicts;
- merge succeeds textually but candidate validation requires code changes;
- latest target architecture makes the previous implementation semantically invalid.

Examples that do **not** count:

- waiting in Integration Queue;
- target branch dirty;
- target branch HEAD moved;
- target branch is unavailable because another worktree owns it;
- repository/target lock contention;
- temporary candidate creation failure;
- retryable Git command failure requiring no code change;
- Runner itself fails before reaching a new real integration attempt.

### Exhaustion behavior for Main

When automatic retry budget is exhausted:

```text
mode               = Main
Board              = Closed
Integration        = merge_retry_exhausted
Reason             = Awaiting merge
Task branch        = retained
Task worktree      = retained
```

Do not silently convert the mode to Isolated Worktree.

`Retry merge` starts a new retry session:

- reset `merge_retry_attempt = 0`;
- preserve lifetime `merge_failure_count`;
- preserve mode=Main;
- create a fresh candidate from latest target HEAD.

---

## 14. UI / Task status model

Do not add another Board lifecycle column.

Keep:

```text
New
Ongoing
Paused
Closed
```

Git delivery is a secondary Task state.

### Lifecycle mapping

| Situation | Board | Delivery detail |
| --- | --- | --- |
| Created, Runner not started | New | not_started |
| Runner executing | Ongoing | execution_running |
| Runner Review / Validate | Ongoing | execution_validating |
| Main Runner completed, queued | Closed | pending_merge |
| Candidate merge/validation | Closed | integrating |
| Runner repairing conflict | Closed | conflict_recovery |
| Target HEAD changed; rebuilding candidate | Closed | target_resync |
| Target checkout dirty | Closed | waiting_target_clean |
| Captured target branch unavailable | Closed | waiting_target_workspace |
| Main retries exhausted | Closed | Awaiting merge / merge_retry_exhausted |
| Main delivered | Closed | integrated |
| Isolated result retained | Closed | worktree_ready |

`Paused` remains execution-only: Runner stopped before completion and may resume/reset.

### Board card examples

```text
T-001  Closed
Integrated · feature/ui

T-002  Closed
Awaiting merge · 4 failures

T-003  Closed
Conflict recovery · retry 2

T-004  Closed
Worktree ready
```

### Task Info Drawer

```text
Integration
Requested mode    Auto
Effective mode    Main
Target branch     feature/ui
Task run          T-001-r2
Task branch       local/task/T-001-r2
Task base         abc123
Task snapshot     def456
Latest target     789xyz
State             Integrating
Failures          1
Attention         —
```

Do not add a top-level Git Worktree page.

Daily operations stay Task-centric. Project-level Workspace Results may be the secondary view for retained/orphaned worktrees, Awaiting Merge items, branches, paths and cleanup.

### Task List / child Tasks

The integration unit is the actual Task-run/workspace result.

If child Tasks resolve to separate worktrees, each child run owns:

- its Task branch/worktree;
- Task base/snapshot SHA;
- effective mode;
- delivery state;
- target commit or retained result.

The Board parent may aggregate:

```text
Closed
Integration · 2 integrated · 1 worktree ready · 1 awaiting merge
```

---

## 15. Suggested Task metadata

For requested Auto resolved to Main:

```yaml
git:
  requested_workspace_mode: auto
  effective_workspace_mode: main

  target_branch: feature/ui
  target_head_sha_at_start: abc123

  run_id: T-001-r2
  task_base_sha: abc123
  task_branch: local/task/T-001-r2
  worktree: .worktrees/T-001-r2
  task_snapshot_sha: def456

  integration_status: pending_merge
  integration_attempt: 0
  candidate_branch: null
  candidate_base_sha: null
  target_commit_sha: null
  integration_attention: null

  merge_failure_count: 0
  merge_retry_attempt: 0
  max_merge_failures: 3
  last_merge_failure: null
```

For Isolated Worktree:

```yaml
git:
  requested_workspace_mode: isolated_worktree
  effective_workspace_mode: isolated_worktree
  target_branch: feature/ui
  target_head_sha_at_start: abc123
  run_id: T-002-r1
  task_base_sha: abc123
  task_branch: local/task/T-002-r1
  worktree: .worktrees/T-002-r1
  task_snapshot_sha: fed321
  integration_status: worktree_ready
```

Do not duplicate Runner RunState in Git metadata.

### Idempotent Project delivery

Automatic Main commits should carry a stable Task-run identity:

```text
AI-Task-Run: T-001-r2
```

Persist `target_commit_sha` immediately after commit succeeds.

After a crash, check the recorded SHA or search the captured target branch for the stable Task-run identity before creating another target commit.

---

## 16. Ownership boundaries

### Task Manager / UI backend

Owns:

- Task lifecycle;
- selected Project;
- requested/effective workspace mode;
- captured target branch;
- enqueueing Main delivery;
- exposing delivery status/actions.

### Workspace Manager

Owns:

- Task-run branch naming;
- Task worktree create/remove;
- candidate/recovery worktree create/remove;
- ownership-safe cleanup;
- returning `project_root` to Runner.

### Runner

Owns only:

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

- target-branch queue/lock;
- latest target HEAD checks;
- Task snapshot commit boundary;
- candidate normal merge;
- conflict/error context;
- invoking existing Runner for code recovery;
- candidate validation;
- squash delivery;
- target commit identity/idempotency;
- cleanup coordination.

### Publish

Owns only explicit remote publication/reconciliation.

Do not mix `git push` into normal local Task delivery.

---

## 17. Cleanup / retention

Fail-safe defaults:

- temporary candidate/recovery worktrees: remove after the attempt is durably finalized;
- successful Main Task branch/worktree: may remove after target commit is durably recorded;
- Main `Awaiting merge` / failed / blocked result: retain;
- Isolated Worktree `worktree_ready`: retain until explicit cleanup/delete;
- never delete an unknown/unowned path merely because its name resembles a Task ID.

Workspace Manager must verify Git worktree registration + Task/run ownership metadata before destructive cleanup.

---

## 18. Remote Git policy

Normal lifecycle is completely local:

```text
Project branch
→ local Task worktrees/branches
→ temporary local candidates
→ local Project branch commits
```

No automatic remote push.

Publishing is a separate explicit action/policy:

```bash
git push origin feature/ui
```

Do not call local integration `push`; reserve push terminology for remote publication.

---

## 19. Example: three Agents in parallel

Initial:

```text
feature/ui = C

T1 branch = C
T2 branch = C
T3 branch = C
```

T3 finishes first:

```text
T3 → commit T3
→ candidate from feature/ui=C
→ merge T3
→ validate
→ feature/ui merge --squash candidate
→ commit S3
```

Now:

```text
feature/ui = C-S3
```

T1 finishes:

```text
T1 was based on C
→ candidate from latest feature/ui=C-S3
→ normal merge T1
→ Git merge base = C
→ conflict?
   ├─ no  → validate
   └─ yes → existing Runner redo/recovery against C-S3
→ feature/ui merge --squash validated candidate
→ commit S1
```

Now:

```text
feature/ui
C
└─ S3
   └─ S1
```

T2 repeats against the latest target and may conflict with either S3 or S1 through their shared ancestry.

---

## 20. Implementation TODO

### Phase A — contracts / metadata

- [ ] Preserve Auto / Main / Isolated Worktree semantics.
- [ ] Remove the canonical `local/integration` branch concept from the new implementation.
- [ ] Capture `target_branch` + `target_head_sha_at_start` per Task run.
- [ ] Define Task + Run branch/path identity.
- [ ] Define Git delivery metadata without duplicating Runner RunState.
- [ ] Keep Runner / FlowEngine / StageExecutor / Supervisor unchanged for Git orchestration.

### Phase B — Workspace Manager

- [ ] Create Task branch/worktree directly from captured target branch HEAD.
- [ ] Return Task worktree as Runner `project_root`.
- [ ] Create/remove temporary candidate/recovery worktrees.
- [ ] Use ownership-verified cleanup.
- [ ] Support Reset/Rerun without branch/path collisions.
- [ ] Use short repository Git lock for ref/worktree mutations only.

### Phase C — Task result snapshot

- [ ] On Runner Completed, `git add -A` + commit remaining Task changes locally.
- [ ] Preserve existing Agent commits.
- [ ] Record `task_snapshot_sha`.
- [ ] Handle no-change result without an empty target commit.

### Phase D — Integration Queue

- [ ] Serialize delivery per repository + captured target branch.
- [ ] Allow parallel Runner execution.
- [ ] Persist queue state for restart recovery.
- [ ] Re-read latest target HEAD when a queued Task begins integration.

### Phase E — Candidate integration

- [ ] Create candidate from latest target HEAD.
- [ ] Normal-merge committed Task branch into candidate.
- [ ] Do not mutate/rebase original completed Task branch.
- [ ] Validate candidate before target delivery.
- [ ] Re-check target HEAD immediately before delivery.
- [ ] Rebuild candidate if target HEAD changed.

### Phase F — Conflict recovery

- [ ] Detect Git conflict deterministically.
- [ ] Build recovery context with Task intent, base/snapshot/latest target SHA, conflict files and Git output.
- [ ] Call existing Runner against recovery candidate.
- [ ] Require normal Runner Review / Validate.
- [ ] Commit recovered result and retry candidate merge.
- [ ] Count only real code/semantic/validation integration failures.
- [ ] Stop automatic recovery after configured N and retain Main result as Closed · Awaiting merge.

### Phase G — Project delivery

- [ ] Require a safe/clean target delivery worktree.
- [ ] `git merge --squash <validated-candidate>` into captured target branch.
- [ ] Create exactly one local target commit per delivered Task.
- [ ] Add stable Task-run commit trailer and persist `target_commit_sha`.
- [ ] No integration-branch reset/re-baseline step exists.

### Phase H — UI

- [ ] Keep Board New / Ongoing / Paused / Closed.
- [ ] Show Git delivery as secondary state.
- [ ] Show requested/effective mode, target branch, Task run/branch, base/snapshot/latest target SHA, merge failures and attention reason.
- [ ] Keep Paused execution-only.
- [ ] Main retry exhaustion => Closed · Awaiting merge.
- [ ] Isolated Worktree => Closed · worktree_ready.
- [ ] Do not add top-level Git Worktree page; use Task Info + Project Workspace Results.
- [ ] Backend owns allowed actions; UI disabled state is UX only.

### Phase I — local-only / publish

- [ ] Normal Task delivery never runs `git push origin`.
- [ ] Keep Publish separate and explicit.

---

## 21. Test TODO

### Worktree isolation

- [ ] Start 2, 5 and 10 Tasks from one target branch concurrently.
- [ ] Every Runner gets a unique worktree.
- [ ] No Task edits another Task worktree.
- [ ] Reset/Rerun cannot collide with retained old run branches/worktrees.
- [ ] Uncommitted Project files are not silently imported into Task base.

### Conflict detection

- [ ] Start T1 and T2 from the same target commit.
- [ ] Make incompatible edits to the same lines.
- [ ] Deliver T1 first.
- [ ] Candidate-merge T2 against latest target and confirm Git produces a real conflict using original common ancestor.
- [ ] Confirm conflict invokes existing Runner recovery, not Integration Manager code editing.

### Ordering / target movement

- [ ] Finish Tasks out of creation order.
- [ ] Confirm same-target delivery is serialized.
- [ ] Add a new target commit while another Task runs; candidate must start from latest target.
- [ ] Move target HEAD while candidate validates; candidate must rebuild before delivery.
- [ ] Target movement alone must not increment merge failure count.

### Dirty / unavailable target

- [ ] Dirty target delivery worktree => waiting_target_clean.
- [ ] Confirm no auto-stash/reset/stage/commit of user changes.
- [ ] User switches Project checkout after Task start; do not switch it back automatically.
- [ ] Target owned by unmanaged worktree => waiting_target_workspace.

### Retry exhaustion

- [ ] Repeated real merge/validation failures increment exactly once per failed attempt.
- [ ] Queue wait / lock contention / target movement / dirty target do not increment.
- [ ] Exhaust budget => Closed · Awaiting merge and retain Task branch/worktree.
- [ ] Retry merge resets session attempt but preserves lifetime failure count.

### Restart / idempotency

- [ ] Restart while Runner runs.
- [ ] Restart while Task waits in Integration Queue.
- [ ] Restart during conflict recovery.
- [ ] Crash after target commit but before Task state persistence; stable Task-run identity prevents duplicate commit.
- [ ] Never lose unintegrated Task output.

### Local-only guarantee

- [ ] Run without remote credentials.
- [ ] Task execution + local delivery still work.
- [ ] No automatic `git push` occurs.

---

## 22. Non-goals

- Do not redesign Runner.
- Do not add a Git Workflow Stage.
- Do not add a second retry/recovery engine.
- Do not create/maintain a canonical `local/integration` branch.
- Do not let frontend execute Git directly.
- Do not mutate/rebase original completed Task worktree during integration.
- Do not auto-switch user Project checkout branch.
- Do not auto-stash/reset/discard/commit unrelated dirty Project files.
- Do not push every Task to remote.
- Do not add an AI Skill for deterministic Git commands.

---

## 23. Design invariant summary

```text
Canonical truth:
  captured Project branch

Task modes:
  Auto / Main / Isolated Worktree

Execution:
  every Task run uses isolated Task worktree
  Runner(project_root) unchanged

Task result:
  Runner Completed
  → commit remaining Task changes
  → stable local/task/<task>-r<run> branch

Main delivery:
  latest target branch HEAD
  → disposable candidate
  → normal Git merge Task branch
  → conflict => existing Runner redo/recovery
  → validate
  → target merge --squash candidate
  → one local Project commit

Isolated Worktree:
  keep Task branch/worktree
  no automatic target modification

Concurrency:
  Runner execution parallel
  delivery serialized per target branch

Permanent extra integration branch:
  none

Remote:
  untouched until explicit Publish
```
