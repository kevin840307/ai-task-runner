# Git Worktree Parallel Task Merge TODO

> Status: design / implementation TODO
>
> Scope: add isolated Task worktrees + automatic local merge around the existing Runner. **Do not redesign Runner execution.**
>
> Core rule: the captured Project branch is the canonical truth. Every Task runs in its own local worktree/branch. Effective Main is complete only after the Task result is successfully merged back into the captured Project branch.

---

## 1. Final architecture

Effective `Main`:

```text
Project branch = canonical truth
↓
Task isolated worktree / local Task branch
↓
Runner
↓
Runner Complete
↓
git add -A + commit remaining Task changes
↓
local Task branch owns the completed result
↓
normal Git merge Task branch → captured Project branch
├─ merge success
│   ↓
│ record merged target HEAD
│   ↓
│ Closed · merged
│
└─ merge fail
    ↓
  git merge --abort
    ↓
  merge_failure_count += 1
    ↓
  read Global Settings.merge_failure_limit
    ↓
  merge_failure_count > limit ?
  ├─ No
  │   ↓
  │ existing Runner redo/recovery against latest Project branch
  │   ↓
  │ Runner Complete
  │   ↓
  │ commit recovered local branch
  │   ↓
  │ retry normal merge → Project branch
  │
  └─ Yes
      ↓
    stop automatic Main merge
      ↓
    retain Task branch/worktree
      ↓
    delivery_fallback = isolated_worktree
      ↓
    Closed · worktree_ready
```

Effective `Isolated Worktree`:

```text
Project branch
↓
Task isolated worktree / local Task branch
↓
Runner
↓
Runner Complete
↓
git add -A + commit remaining Task changes
↓
Closed · worktree_ready
↓
no automatic Project-branch merge
```

### Important: no local push step

The Task worktree is attached to a local Git branch in the same repository.

After committing in the worktree:

```text
local/task/T-001-r1
```

already points to the new commit locally.

Do not add a fake/local `git push` step. Use `git push` only for explicit remote publication.

---

## 2. Runner contract stays unchanged

Runner continues to own only normal task execution:

```text
Runner(project_root, task/workflow input)
→ Workflow / Agent
→ Review / Validate
→ Completed
```

Do not add Git merge ownership into:

- FlowEngine
- StageExecutor
- Supervisor
- normal Workflow Stage routing
- Runner retry/recovery state

Git orchestration stays outside Runner.

If a merge conflict requires source changes, Integration Manager calls the **same existing Runner** again with the latest Project code and merge-conflict context.

---

## 3. Modes: Auto / Main / Isolated Worktree

All modes execute in isolated Task worktrees.

```text
Task mode
├─ Auto
├─ Main
└─ Isolated Worktree

Execution
→ local/task/<task-id>-r<run>
→ isolated worktree
→ Runner(project_root = worktree)
```

The mode controls what happens after Runner Complete.

### Main

```text
Runner Complete
→ commit local Task branch
→ automatic normal merge into captured Project branch
→ merge success
→ Closed
```

Runner Complete alone is **not** Main completion.

Main stays Ongoing while waiting for merge, merging, or recovering from a merge conflict.

### Isolated Worktree

```text
Runner Complete
→ commit local Task branch
→ retain branch/worktree
→ Closed · worktree_ready
```

No automatic Project-branch merge.

### Auto

Auto uses the existing single Global workspace resolver.

Do not add a second resolver inside Git integration.

---

## 4. Auto policy × Concurrent Main

Global Settings → Execution owns:

- Auto workspace policy
- Merge failure limit
- Allow concurrent Main tasks

`Allow concurrent Main tasks` only controls whether a Task that resolves/selects **Main** may start while another Main Task is already running.

It does not rewrite Auto policy.

| Auto policy / selection | Main already running | Concurrent Main = Off | Concurrent Main = On |
| --- | --- | --- | --- |
| Busy project → Worktree / Auto | yes | Isolated Worktree | Isolated Worktree |
| Always Main / Auto | yes | Block Main start | Main |
| Always Worktree / Auto | yes | Isolated Worktree | Isolated Worktree |
| Explicit Main | yes | Block Main start | Main |

Therefore:

```text
Busy project → Worktree
+ Concurrent Main = On
+ another Main already running
+ new Task uses Auto
→ Isolated Worktree
```

When Concurrent Main is On, multiple Main Tasks may run in parallel worktrees, but merges into the same captured Project branch are serialized.

---

## 5. Capture target branch at Task run start

Do not hardcode `main`.

At Task run start capture:

```text
target_branch
target_head_sha_at_start
```

Examples:

```text
Project on feature/ui → target_branch = feature/ui
Project on release/v4 → target_branch = release/v4
Project on main       → target_branch = main
```

The captured target remains fixed for that Task run.

If the user switches Project branch afterward, do not silently retarget the old Task.

### Task base

Create the Task branch from captured target HEAD.

```text
feature/ui:
A ─ B ─ C
        ↑
      Task base
```

Uncommitted Project working-tree changes are not part of the Task base.

If they should be visible to new Tasks, commit them first.

### Detached HEAD

If Project is detached HEAD, fail closed or require an explicit target branch.

---

## 6. Task branch / worktree identity

Use Task + Run identity.

```text
local/task/T-001-r1
local/task/T-001-r2
local/task/T-002-r1
```

Recommended worktree paths:

```text
.worktrees/
├─ T-001-r1/
├─ T-001-r2/
└─ T-002-r1/
```

Do not create a branch named exactly `local`; it conflicts with hierarchical refs such as `local/task/...`.

Reset/Rerun must create a new Run identity so retained prior results never collide.

---

## 7. Task start

For every Task run:

1. resolve requested/effective workspace mode;
2. capture target branch + HEAD;
3. create local Task branch from captured HEAD;
4. create Task worktree;
5. pass worktree path to Runner.

Conceptually:

```bash
git worktree add -b local/task/T-001-r1 <worktree-path> <target-head-sha>
```

Use a short repository Git lock only for ref/worktree mutation.

Do not hold it during Runner execution.

---

## 8. Runner Complete → local Task commit

Before automatic Main merge or Isolated close:

```text
Runner Complete
↓
verify Task worktree is not in unresolved merge/rebase state
↓
git add -A
↓
commit remaining Task changes
↓
record task_snapshot_sha
```

If Agent already created commits, keep them and commit only remaining changes.

If there is no effective diff:

```text
Main              → Closed · no_changes
Isolated Worktree → Closed · worktree_ready · no_changes
```

This is the one normal Main completion exception that does not require a Project-branch merge: there is nothing to deliver.

Do not create empty commits just to advance state.

---

## 9. Main merge queue

Tasks may execute in parallel, but merges into the same target branch must be serialized.

```text
A Runner ───── Complete ─┐
B Runner ─ Complete ─────┼→ target_branch merge queue
C Runner ─────── Complete ┘
```

Core rule:

> **Execution parallel; merge serialized per repository + target branch.**

Queue order is deterministic FIFO by durable `merge_queue_seq`.

When an effective Main Task reaches Runner Complete and has a deliverable commit:

```text
atomically allocate next merge_queue_seq for repository + target_branch
↓
persist merge_queue_seq on the Task
↓
enqueue pending merge
```

Rules:

- lower `merge_queue_seq` merges first;
- restart/process recovery must preserve the persisted order;
- a later Task finishing earlier must not jump ahead of an already-enqueued lower sequence;
- waiting/restart does not consume merge failure count;
- this is a serialized Git-delivery queue, not a second Runner scheduler.

Different repositories are independent.

Different target branches may have independent merge queues, while short repository-wide ref/worktree mutation still uses the repository Git lock.

---

## 10. Direct Main merge transaction

The merge must remain abortable until required merge validation has passed.

```text
merge source commit ready
↓
Task stays Ongoing · pending_merge
↓
wait for lowest merge_queue_seq
↓
acquire target-branch merge lock
↓
resolve safe worktree for target_branch
↓
read latest target HEAD
↓
git merge --no-ff --no-commit <merge_source_branch>
↓
Git conflict?
├─ Yes
│   ↓
│ git merge --abort
│   ↓
│ real merge failure handling
│
└─ No
    ↓
  run required merge validation, if configured
    ↓
  validation result
  ├─ PASS
  │   ↓
  │ git commit
  │   ↓
  │ record merge commit / merged_target_head_sha
  │   ↓
  │ Closed · merged
  │
  ├─ SOURCE_FAIL
  │   ↓
  │ git merge --abort
  │   ↓
  │ real merge failure handling
  │
  └─ TECHNICAL_ERROR
      ↓
    git merge --abort
      ↓
    do NOT increment merge_failure_count
      ↓
    existing technical retry/backoff or Needs Attention
```

Conceptual merge:

```bash
git merge --no-ff --no-commit local/task/T-001-r1
# run configured merge validation while merge is still uncommitted
git commit
```

If no separate merge validation is configured, a conflict-free merge may proceed directly to `git commit`.

Validation result semantics:

- `PASS`: merged code is acceptable; commit it.
- `SOURCE_FAIL`: merged code requires source changes; abort and count exactly one real merge failure.
- `TECHNICAL_ERROR`: validation could not produce a trustworthy code verdict because of infrastructure/tooling failure; abort the uncommitted merge, do not increment `merge_failure_count`, and reuse the existing technical retry/backoff / Needs Attention owner.

Do not create another validation or technical-retry engine. Reuse existing configured deterministic/project validation and existing technical retry/backoff ownership where applicable; source-code correction still belongs to the existing Runner recovery path.

`--no-ff` gives one consistent Task-delivery merge boundary even when fast-forward would otherwise be possible. `--no-commit` keeps the merge abortable before acceptance.

Normal merge preserves ancestry so later Tasks based on older Project commits can conflict correctly.

---

## 11. Merge conflict / fail handling

Every **real merge failure** follows exactly one path:

```text
git merge --no-ff --no-commit attempted
↓
Git conflict OR required merge validation fails and source changes are needed
↓
git merge --abort
↓
merge_failure_count += 1
↓
read Global Settings.merge_failure_limit
↓
merge_failure_count > merge_failure_limit ?
├─ No
│   ↓
│ collect merge error + latest Project context
│   ↓
│ existing Runner redo/recovery
│   ↓
│ Runner Complete
│   ↓
│ commit recovered result to local recovery/source branch
│   ↓
│ retry normal merge → captured Project branch
│
└─ Yes
    ↓
  stop automatic Main merge
    ↓
  retain Task branch/worktree
    ↓
  delivery_fallback = isolated_worktree
    ↓
  Closed · worktree_ready
```

### What counts as merge fail

Count only a real merge attempt that fails because the Task result cannot be merged/accepted without source-code redo.

Examples:

- Git source conflict;
- conflict-free merge enters uncommitted merge state but required merge validation fails and source changes are needed;
- recovered source still cannot merge/validate against the latest Project code.

Do not count:

- merge validation returns `TECHNICAL_ERROR` because infrastructure/tooling cannot produce a trustworthy code verdict;
- waiting in merge queue;
- merge lock busy;
- dirty target checkout;
- target branch unavailable;
- transient Git lock/file-system error;
- Runner failure before a new merge attempt.

---

## 12. Conflict recovery uses existing Runner

Integration Manager owns deterministic Git mechanics only:

- target-branch merge lock;
- target worktree selection;
- merge invocation;
- conflict detection;
- `git merge --abort`;
- merge failure counting;
- context collection;
- fallback decision;
- safe cleanup.

It does not become another code-repair engine.

### Recovery context

Provide existing Runner with:

```text
Original Task prompt / intent
Original Task base SHA
Task snapshot SHA
Captured target branch
Latest target HEAD
Task branch / commits
Conflicting files
Git conflict/error output
Relevant project development rules
```

Recovery intent:

```text
Latest Project branch is authoritative.

Redo the original Task against the latest Project code.
Preserve compatible newer changes.
Do not merely remove conflict markers.
Run normal Workflow / Review / Validate.
```

### Recovery worktree and merge source

The Task has exactly one **current merge source**.

Initially after Runner Complete:

```text
merge_source_branch   = local/task/T-001-r1
merge_source_sha      = task_snapshot_sha
merge_source_worktree = .worktrees/T-001-r1
```

After a real merge failure that requires source redo, create a system-owned recovery branch/worktree from latest target HEAD:

```text
latest target branch
↓
local/recovery/T-001-r1-f1
↓
existing Runner redoes original Task
↓
Runner Complete
↓
commit recovered result
↓
atomically update:
  merge_source_branch
  merge_source_sha
  merge_source_worktree
↓
next merge attempt uses ONLY this latest merge source
```

Do not merge the original Task branch again after a recovery result has become the current merge source.

If another real merge failure occurs, create the next recovery identity, for example:

```text
local/recovery/T-001-r1-f2
```

and replace the current merge source only after the new recovery result is durably committed.

If the Global failure limit is exceeded, `worktree_ready` must point to/retain the **latest current merge source**, not the stale original Task result.

Original Task/recovery artifacts may be cleaned only after the latest source pointer and final merge/fallback state are durable.

Recovery branches exist only after real merge failures; they are not a normal integration layer.

---

## 13. Merge failure limit

Keep exactly two concepts.

### Global Settings

```text
merge_failure_limit
```

Default: `3`.

This value belongs only to the single Global Settings owner.

### Task

```text
merge_failure_count
```

This is the actual count of real merge failures for the Task.

Do not copy another merge-limit field into Task metadata.

### Limit rule

```text
real merge fail
↓
merge_failure_count += 1
↓
read Global Settings.merge_failure_limit
↓
merge_failure_count > merge_failure_limit ?
├─ No  → automatic Runner recovery + retry merge
└─ Yes → Isolated Worktree fallback · Closed · worktree_ready
```

With limit `3`, failures 1/2/3 retry automatically; failure 4 falls back.

---

## 14. Safe Project-branch merge workspace

Do not automatically switch the user's Project checkout branch.

### Captured target is checked out in managed Project root

Require it to be safe for merge.

If unrelated uncommitted changes exist:

```text
Ongoing · waiting_target_clean
Needs Attention
```

Do not auto-stash, reset, discard, stage, or commit user changes.

### Captured target is not checked out anywhere

The system may create a temporary managed delivery worktree for that target branch and run the normal merge there.

The merge still updates the real target branch directly.

### Captured target is checked out in an unmanaged/user worktree

Do not switch or mutate that worktree automatically.

```text
Ongoing · waiting_target_workspace
Needs Attention
```

Retain the Task result.

---

## 15. Main completion rule

> **Effective Main is not complete at Runner Complete. It is complete only after the current merge source has been successfully merged into the captured Project branch. The only normal exception is `no_changes`, where there is nothing to deliver.**

| Situation | Board | Merge detail |
| --- | --- | --- |
| Created | New | not_started |
| Runner executing/reviewing | Ongoing | execution_running |
| Runner Complete, waiting to merge | Ongoing | pending_merge |
| Project merge running | Ongoing | merging |
| Conflict Runner recovery | Ongoing | conflict_recovery |
| Target checkout dirty | Ongoing | waiting_target_clean |
| Target workspace unavailable | Ongoing | waiting_target_workspace |
| Main has no effective changes | Closed | no_changes |
| Merge success | Closed | merged |
| Merge failures exceed limit | Closed | worktree_ready · Main fallback · merge_failure_limit_exceeded |
| Isolated Worktree Runner Complete + commit | Closed | worktree_ready |

Paused remains execution-only.

---

## 16. Suggested Task Git metadata

Effective Main:

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

  merge_status: pending_merge
  merge_queue_seq: 42

  merge_source_branch: local/task/T-001-r2
  merge_source_sha: def456
  merge_source_worktree: .worktrees/T-001-r2

  merge_failure_count: 0
  last_merge_failure: null

  delivery_fallback: null
  merged_target_head_sha: null
```

Effective Isolated Worktree:

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
  merge_status: worktree_ready
```

Global `merge_failure_limit` is not duplicated into Task metadata.

---

## 17. Restart / idempotency

Normal merge preserves ancestry, so restart detection is simple.

After restart:

1. restore pending Main Tasks ordered by persisted `merge_queue_seq`;
2. restore the persisted current `merge_source_branch / merge_source_sha / merge_source_worktree`;
3. if `merge_source_sha` is already an ancestor of the captured target branch:

```text
already merged
→ finalize Task as Closed · merged
→ do not merge again
```

4. otherwise continue the pending merge/recovery state without changing queue order.

If a crash happens while the target worktree is in an unfinished merge state, Integration Manager must first reconcile ownership and either finalize the already-durable merge or safely abort its own incomplete merge before retrying.

Do not create duplicate merge commits after a crash.

---

## 18. Ownership boundaries

### Task Manager / UI backend

Owns:

- Task lifecycle;
- requested/effective mode;
- captured target branch;
- enqueueing effective Main merge;
- exposing merge status/actions.

### Workspace Manager

Owns:

- Task branch/worktree create/remove;
- optional recovery worktree create/remove;
- ownership-safe cleanup;
- returning `project_root` to Runner.

### Runner

Owns normal task/recovery execution only.

### Integration Manager

Owns:

- merge queue/lock;
- safe target worktree resolution;
- direct normal merge;
- merge abort/conflict detection;
- merge failure counting;
- invoking existing Runner for recovery;
- fallback decision;
- merged target SHA/idempotency;
- cleanup coordination.

### Publish

Owns explicit remote push/reconciliation only.

---

## 19. Cleanup / retention

Fail-safe defaults:

- successful Main Task branch/worktree may be removed only after merged state is durable;
- recovery worktree may be removed after merge transaction is durably finalized;
- Main fallback-to-Isolated retains the latest current merge source branch/worktree;
- Isolated Worktree `worktree_ready` is retained until explicit cleanup/delete;
- failed/blocked Task output is retained;
- never delete unknown/unowned paths by name alone.

Workspace Manager must verify Git worktree registration + Task/run ownership before destructive cleanup.

---

## 20. Remote Git policy

Normal lifecycle is local:

```text
Project branch
→ local Task branch/worktree
→ local commit
→ normal local merge back to Project branch
```

No automatic remote push.

Remote publication is a separate explicit action.

---

## 21. Example: A / B concurrent Main

Initial:

```text
feature/ui = C

A = branch from C
B = branch from C
```

A finishes first:

```text
A Runner Complete
→ commit TA
→ normal merge TA into feature/ui
→ success
→ feature/ui now contains A
→ A Closed
```

B then merges:

```text
B Runner Complete
→ commit TB
→ normal merge TB into latest feature/ui
→ Git uses original common ancestor C
→ conflict?
   ├─ no  → merge success → B Closed
   └─ yes → merge_failure_count +1
            → Runner redo against latest feature/ui
            → commit recovery result
            → update current merge source
            → retry merge with --no-ff --no-commit
```

Therefore concurrent Tasks still get real Git conflict detection while keeping the merge path direct.

---

## 22. Implementation TODO

### Phase A — settings / contracts

- [ ] Preserve Auto / Main / Isolated Worktree.
- [ ] Global Settings owns `merge_failure_limit` (default 3) and `allow_concurrent_main_tasks` (default false).
- [ ] Task persists only actual `merge_failure_count`; Global Settings owns the merge failure limit.
- [ ] Capture target branch + HEAD per Task run.
- [ ] Keep Runner architecture unchanged.

### Phase B — Workspace Manager

- [ ] Create Task branch/worktree directly from captured target HEAD.
- [ ] Pass Task worktree to Runner as project_root.
- [ ] Support unique Task + Run identity.
- [ ] Create recovery worktree only after a merge failure that needs source redo.
- [ ] Ownership-safe cleanup.

### Phase C — Runner Complete snapshot

- [ ] `git add -A` + commit remaining Task changes.
- [ ] Preserve Agent-created commits.
- [ ] Record task_snapshot_sha.
- [ ] Handle no_changes without empty commits; Main no_changes is the only normal completion path that skips Project merge.

### Phase D — Main merge

- [ ] Serialize merge per repository + target branch with durable FIFO `merge_queue_seq`; restart preserves order.
- [ ] Resolve safe worktree for captured target branch.
- [ ] Use `git merge --no-ff --no-commit <merge_source_branch>` directly in target worktree.
- [ ] Run required configured merge validation before commit with PASS / SOURCE_FAIL / TECHNICAL_ERROR semantics; only SOURCE_FAIL counts as a real merge failure.
- [ ] Commit merge only after acceptance and record merged_target_head_sha.
- [ ] Merge success is the effective Main completion boundary.

### Phase E — fail merge / recovery

- [ ] On real merge fail: abort merge, increment `merge_failure_count` exactly once, record structured failure.
- [ ] Read current Global `merge_failure_limit` after each real failure.
- [ ] If count <= limit: call existing Runner against latest target-based recovery worktree, commit recovered result, atomically replace merge_source_branch/SHA/worktree, then retry merge.
- [ ] If count > limit: stop automatic Main merge, retain latest merge source, and close as Isolated Worktree / worktree_ready with reason merge_failure_limit_exceeded.
- [ ] Do not count queue wait, target dirty/unavailable, lock contention, transient Git error, or Runner failure before merge.

### Phase F — UI

- [ ] Effective Main remains Ongoing from Runner Complete until merge succeeds or fallback closes it.
- [ ] Show pending_merge / merging / conflict_recovery / waiting_target_clean / waiting_target_workspace / merged / worktree_ready.
- [ ] Main fallback visibly indicates original Main + merge_failure_limit_exceeded reason.
- [ ] No top-level Git Worktree page; Task Info + Project Workspace Results remain enough.

### Phase G — remote

- [ ] Normal lifecycle never executes `git push origin`.
- [ ] Keep Publish explicit and separate.

---

## 23. Test TODO

### Isolation / concurrency

- [ ] Start 2 / 5 / 10 Tasks from one target branch concurrently.
- [ ] Confirm durable merge_queue_seq FIFO is preserved across process restart.
- [ ] Every Runner uses a unique Task worktree.
- [ ] Concurrent Main Off blocks a second Main; On allows it.
- [ ] Busy→Worktree Auto remains Worktree while busy even when Concurrent Main is On.

### Merge success

- [ ] Runner Complete does not close Main before merge.
- [ ] Task source merges directly into target branch with --no-ff --no-commit.
- [ ] Conflict-free merge remains uncommitted until configured merge validation passes.
- [ ] SOURCE_FAIL validation aborts cleanly and counts exactly one real merge failure.
- [ ] TECHNICAL_ERROR validation aborts cleanly, does not change merge_failure_count, and uses existing technical retry/backoff / Needs Attention behavior.
- [ ] Merge success commits and closes Main.
- [ ] Main no_changes closes without a Project merge.
- [ ] Restart after merge recognizes ancestry and does not duplicate merge.

### Merge conflict

- [ ] Start A/B from same target commit and edit incompatible same lines.
- [ ] Merge A first.
- [ ] Merge B into latest target and confirm real Git conflict.
- [ ] Confirm merge abort + `merge_failure_count += 1` exactly once.
- [ ] Confirm existing Runner redoes B against latest target.
- [ ] Confirm recovery updates merge_source_branch/SHA/worktree and stale original Task source is not merged again.
- [ ] Confirm recovery branch merges successfully when fixed.
- [ ] Confirm fallback retains latest recovery source after repeated failures.

### Merge failure limit

- [ ] Global limit=3: failures 1/2/3 recover, failure 4 falls back.
- [ ] Fallback retains Task branch/worktree and closes as worktree_ready.
- [ ] Task does not store a duplicate merge limit or retry-attempt counter.

### Target safety

- [ ] Dirty target => waiting_target_clean; do not mutate user changes.
- [ ] Target in unmanaged worktree => waiting_target_workspace.
- [ ] User branch switch after Task start never retargets old Task.

### Local-only

- [ ] No remote credentials required.
- [ ] No automatic `git push` occurs.

---

## 24. Non-goals

- Do not redesign Runner.
- Do not add a Git Workflow Stage.
- Do not add a second retry/recovery engine.
- Do not create a permanent integration branch.
- Do not auto-switch user Project checkout branch.
- Do not auto-stash/reset/discard/commit unrelated dirty Project files.
- Do not auto-push every Task to remote.

---

## 25. Final invariant summary

```text
Project branch = canonical truth
↓
Task isolated worktree / local branch
↓
Runner
↓
Runner Complete
↓
commit Task result locally
↓
git merge --no-ff --no-commit current merge source → Project branch
├─ conflict / SOURCE_FAIL
│   → git merge --abort
│   → merge_failure_count +1
│   → real merge fail
├─ TECHNICAL_ERROR
│   → git merge --abort
│   → no merge_failure_count change
│   → existing technical retry/backoff / Needs Attention
├─ accepted
│   → git commit
│   → Closed / finish
└─ no_changes
    → Closed / finish

real merge fail
           ↓
           read Global merge_failure_limit
             ↓
           count <= limit
           → existing Runner redo against latest Project
           → commit recovery result
           → retry normal merge

           count > limit
           → Isolated Worktree fallback
           → Closed · worktree_ready
```
