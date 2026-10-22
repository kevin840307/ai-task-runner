# Git Worktree Parallel Task Merge TODO

> Status: design / implementation TODO
>
> Scope: add isolated Task worktrees + automatic local merge around the existing Runner. **Do not redesign Runner execution.**
>
> Core rule: the captured Project branch is the canonical truth. In the current UI/Task orchestration flow, every Task run is prepared in its own local worktree/branch before Runner is triggered. Standalone/CLI Runner is independent of this and simply runs against the caller-supplied `project_root`. Effective Main is complete only after the Task result is successfully merged back into the captured Project branch.
>
> **Hard invariant:** worktree/Git merge support is a removable backend adapter in a new top-level `workspace/` package. It must not live under Runner or UI, and Runner/UI must not own Git worktree/merge behavior.

---

## 0. Physical module boundary: top-level workspace/

Create a new top-level backend package:

```text
project/
├─ runner/
│   └─ existing Runner core
├─ ui/
│   └─ presentation / frontend / UI API surface
├─ workspace/
│   ├─ manager.py       # resolve/create Task workspace and project_root
│   ├─ worktree.py      # Git worktree/branch operations
│   ├─ merge.py         # direct merge transaction / queue / abort / finalize
│   ├─ recovery.py      # recovery workspace/source metadata mechanics
│   └─ model.py         # workspace/merge metadata only
└─ ...
```

Exact file names may follow the repository's existing naming conventions, but the ownership boundary is fixed.

### Removable adapter invariant

Current UI/Task product flow:

```text
UI / Task Backend
↓
workspace.prepare(...)
↓
Task worktree project_root
↓
Runner(project_root)
```

Standalone/CLI Runner flow:

```text
CLI / other caller
↓
caller-supplied project_root
↓
Runner(project_root)
```

Runner does not know whether `project_root` is:

- the original Project path;
- a Git worktree;
- a future alternate workspace implementation.

"Removable" is a module-boundary requirement, not a current product runtime toggle. The current UI Task flow still uses worktrees. If `workspace/` is removed or replaced in a future version, Runner/CLI contracts must remain unchanged; only the outer Task/workspace orchestration may change.

### Dependency direction

```text
UI
↓
Task Backend / Orchestrator
├─ workspace/ APIs
└─ Runner APIs
```

Rules:

- UI never executes Git directly.
- UI never imports workspace Git implementation.
- Runner never imports `workspace/`.
- `workspace/` never imports Runner internals.
- Task Backend / Orchestrator coordinates the two through narrow APIs.
- Worktree/merge metadata stays outside Runner RunState.
- Removing `workspace/` must not require changes to FlowEngine / StageExecutor / Supervisor / Runner recovery contracts.

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
normal Git merge current merge source → captured Project branch
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
  │ existing Runner incremental merge-repair against latest Project branch + completed Task result
  │   ↓
  │ Runner Complete
  │   ↓
  │ commit recovered local branch
  │   ↓
  │ retry current merge source → Project branch
  │
  └─ Yes
      ↓
    stop automatic Main merge
      ↓
    retain latest current merge source branch/worktree
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

Runner continues to own only execution/validation against a supplied filesystem root:

```text
run(project_root, task/workflow input)
→ Workflow / Agent
→ Review / Validate
→ Completed
```

Runner must not know:

- whether `project_root` is a worktree;
- workspace mode;
- Git branch names;
- merge queue state;
- merge failure count;
- merge/fallback status.

Do not add Git merge ownership into:

- FlowEngine;
- StageExecutor;
- Supervisor;
- normal Workflow Stage routing;
- Runner retry/recovery state.

### Thin validation API is allowed if needed

If post-merge validation cannot reuse an existing public Runner/service entry point, add only a thin Git-unaware API such as:

```text
validate(project_root, validation_config)
→ PASS | SOURCE_FAIL | TECHNICAL_ERROR
```

The API accepts a `project_root` and validation configuration only. It must not accept or interpret worktree/branch/merge concepts.

This validation entry point is verdict-only for source integration: it must not intentionally edit Project source files or run an Agent repair step. If source changes are required, return `SOURCE_FAIL`; the orchestrator aborts the pending merge and starts the normal Runner recovery flow in a separate recovery workspace.

Task Backend / Orchestrator owns sequencing:

```text
workspace.prepare()
↓
Runner.run(project_root)
↓
workspace.snapshot_result()
↓
workspace.begin_merge()
↓
post-merge validation required?
├─ No  → workspace.commit_merge()
└─ Yes → Runner.validate(merged_project_root)
          ├─ PASS            → workspace.commit_merge()
          ├─ SOURCE_FAIL     → workspace.abort_merge() → recovery flow
          └─ TECHNICAL_ERROR → workspace.abort_merge() → existing technical retry/backoff
```

For merge conflict recovery, the orchestrator prepares the latest-target recovery workspace through `workspace/`, then calls the **same existing Runner run API** with that recovery `project_root` and a scoped merge-repair instruction to integrate the already-completed Task source (not rerun the original development Task).

Neither `workspace/` nor Runner needs to import the other.

---

## 3. Modes: Auto / Main / Isolated Worktree

When worktree support is enabled, all three modes execute in isolated Task worktrees. This is a Workspace-layer policy, not a Runner requirement.

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
→ automatic normal merge of current merge source into captured Project branch
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
workspace ownership preflight:
  registered worktree still matches this Task/Run
  repository identity is expected
  current branch is the expected Task branch
  expected source base SHA is still an ancestor of current workspace HEAD
  no merge/rebase/cherry-pick/revert/bisect operation is active
↓
git add -A
↓
commit remaining Task changes
↓
record task_snapshot_sha
```

If Agent already created commits, keep them and commit only remaining changes.

If ownership/branch/ancestry/operation preflight fails, fail closed and retain the workspace for diagnosis. Do not guess the branch, switch it automatically, rewrite history, or commit to an unexpected ref. Agent-created commits are allowed only while the Task/Recovery HEAD remains descended from its expected source base.

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
- the queue-head Task keeps its delivery turn while it is in merge conflict recovery; later same-target Tasks do not overtake it;
- long Runner recovery does **not** hold the short repository/target Git lock; release that lock after abort/cleanup, keep only queue ownership, then reacquire the Git lock for the next merge attempt;
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
is merge_source_base_sha still an ancestor of latest target HEAD?
├─ No → target history rewritten/diverged → waiting_target_history · Needs Attention
└─ Yes
    ↓
  is merge_source_sha already an ancestor of target_branch?
├─ Yes → record current target HEAD → Closed · merged
└─ No
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
  │ transaction ownership pre-commit check:
  │     target HEAD still equals pre-merge target HEAD
  │     MERGE_HEAD still equals merge_source_sha
  │     target worktree/index still belongs to this merge transaction
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

Before running Git merge, check:

```bash
git merge-base --is-ancestor <merge_source_sha> <target_branch>
```

If true, delivery is already present; finalize without creating another commit.

Conceptual merge:

```bash
git merge --no-ff --no-commit local/task/T-001-r1
# run configured merge validation while merge is still uncommitted
git commit
```

### When post-merge validation is required

A Task source was already validated by Runner against its own base. Re-validating the identical tree adds no value.

Before merge, compare the current target HEAD with the base that the current merge source was built/validated against:

```text
current target HEAD == merge_source_base_sha
→ merged source introduces no unseen target changes
→ no extra post-merge validation required
→ commit conflict-free merge

current target HEAD != merge_source_base_sha
→ target changed after this source was built/validated
→ merged tree is a new combination Runner has not validated
→ post-merge validation required before merge commit
```

Persist/update `merge_source_base_sha` together with the current merge source.

Examples:

```text
Task source:
base C → Task T
target still C
→ no extra post-merge validation

Task source:
base C → Task T
target now C-A-B
→ merge produces C-A-B+T
→ post-merge validation required
```

A recovery source created from latest target `L` uses `merge_source_base_sha=L`. If target is still `L` when it merges, no second post-merge validation is necessary because Runner already reviewed/validated that recovery result against `L`.

If target advances again before delivery, post-merge validation becomes required.

If no post-merge validation is required, a conflict-free merge may proceed to the same transaction ownership pre-commit check and then `git commit`.

Validation result semantics:

- `PASS`: merged code is acceptable; commit it.
- `SOURCE_FAIL`: merged code requires source changes; abort and count exactly one real merge failure.
- `TECHNICAL_ERROR`: validation could not produce a trustworthy code verdict because of infrastructure/tooling failure; abort the uncommitted merge, do not increment `merge_failure_count`, and reuse the existing technical retry/backoff / Needs Attention owner.

The validation-only path must not repair/edit source inside the pending target merge. All source edits happen through Runner recovery in a separate recovery workspace.

Do not create another validation or technical-retry engine. Reuse existing configured deterministic/project validation only if its public validation-only path can guarantee the source-non-mutating verdict contract; otherwise add the thin validation-only API. Reuse existing technical retry/backoff ownership. Source-code correction still belongs to the existing Runner recovery path.

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
│ existing Runner incremental merge-repair (preserve completed Task result)
│   ↓
│ Runner Complete
│   ↓
│ commit recovered result to local recovery/source branch
│   ↓
│ retry current merge source → captured Project branch
│
└─ Yes
    ↓
  stop automatic Main merge
    ↓
  retain latest current merge source branch/worktree
    ↓
  delivery_fallback = isolated_worktree
    ↓
  Closed · worktree_ready
```

### What counts as merge fail

Count only a real merge attempt that fails because the Task result cannot be merged/accepted without source-code integration repair.

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

`workspace/` Merge Manager owns deterministic Git mechanics only:

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
Original Task prompt / intent (context only; no full redo)
Original Task base SHA
Immutable completed Task snapshot SHA and committed change/diff
Current merge source SHA/base SHA (may be an earlier recovery)
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

Integrate the already-completed Task changes into the latest Project code; do not restart or redo the original Task.
Use the latest Project branch as the base and the completed Task snapshot/diff as the source to preserve.
Resolve only changed/conflicting areas; retain unrelated Project changes and compatible Task results.
Do not merely remove conflict markers; run existing Workflow / Review / Validate on the integrated result.
Run normal Workflow / Review / Validate.
```

### Recovery worktree and merge source

The Task has exactly one **current merge source**.

Initially after Runner Complete:

```text
merge_source_branch   = local/task/T-001-r1
merge_source_sha      = task_snapshot_sha
merge_source_base_sha = task_base_sha
merge_source_worktree = .worktrees/T-001-r1
```

After a real merge failure that requires source integration repair, create a system-owned recovery branch/worktree from latest target HEAD:

```text
latest target branch
↓
local/recovery/T-001-r1-f1
↓
existing Runner integrates completed Task snapshot into latest Project files
↓
Runner Complete
↓
commit recovered result
↓
atomically update:
  merge_source_branch
  merge_source_sha
  merge_source_base_sha = latest target HEAD used to create recovery workspace
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

### Incremental merge-repair contract (no full Task redo)

The prior `Runner redo/recovery` wording means **integration repair**, not running the original feature-development Task from scratch. The already committed Task result is the delivery payload and must remain available throughout recovery.

1. `workspace/` captures the failed merge's structured conflict report, the original Task base and immutable `task_snapshot_sha`, the current `merge_source_sha`, and the latest target HEAD. After safely aborting the failed target merge, it prepares a **new recovery worktree based on the latest target HEAD**; never modify the user's Project checkout or discard the original Task source.
2. The orchestrator hands Runner the recovery `project_root` and an explicit **merge-repair task**: compare the completed Task source against its base and the latest Project tree (three-way intent), port the Task's completed changes into the recovery worktree, and resolve conflicts at file/function scope. The original Task prompt is context for intended behavior, **not a command to implement everything again**.
3. Preserve both sides: latest Project edits are authoritative for current context, while completed Task features must not silently disappear. Unaffected changes and files remain untouched; for conflicting logic, Runner adapts the Task implementation to the latest Project interfaces rather than overwriting newer changes. Do not mechanically replace the entire Project tree with the Task snapshot, re-clone, re-pull, or restart full feature development.
4. Run the existing Runner review/validation on the **integrated result**. If validation fails, continue repairing the specific integration defects with the same recovery execution path; do not reset to a fresh full Task. Preserve the recovery workspace across ordinary Runner resume/retry.
5. Commit the successfully integrated recovery tree on its recovery branch; only then atomically update the durable current merge-source branch/SHA/base-SHA/worktree. A failed or interrupted repair must keep the previous committed merge source intact for resume/fallback.
6. Retry the existing direct merge transaction against the captured target branch. If the target moved since recovery began, apply existing latest-target comparison/validation and real-conflict rules; never silently overwrite that target.

Runner stays Git/worktree-unaware: `workspace/` supplies file/diff/conflict context through the orchestrator, while Runner only sees a `project_root` and a merge-repair instruction. Git three-way data extraction and source pointer updates belong to `workspace/`, not Runner internals.

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

### Captured target branch no longer exists

If the captured branch was deleted/renamed and the exact captured target ref no longer resolves:

```text
Ongoing · waiting_target_branch
Needs Attention
```

Do not recreate it automatically, retarget to `main`, or guess a replacement branch.

If the branch still exists but history was rewritten/diverged so `merge_source_base_sha` is no longer an ancestor of the current target HEAD:

```text
Ongoing · waiting_target_history
Needs Attention
```

Fail closed before direct merge or source recovery. A mere common ancestor is not sufficient: merging a source whose base was removed from target history could accidentally reintroduce commits the user intentionally reset/reverted by history rewrite. This condition does not increment `merge_failure_count`. Explicit user/backend reconciliation is required.

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
| Captured target branch missing | Ongoing | waiting_target_branch |
| Captured target history rewritten/diverged from merge-source base | Ongoing | waiting_target_history |
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
  merge_source_base_sha: abc123
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
2. restore the persisted current `merge_source_branch / merge_source_sha / merge_source_base_sha / merge_source_worktree`;
3. if `merge_source_sha` is already an ancestor of the captured target branch:

```text
already merged
→ finalize Task as Closed · merged
→ do not merge again
```

4. otherwise continue the pending merge/recovery state without changing queue order.

If a crash happens while the target worktree is in an unfinished merge state, `workspace/` Merge Manager must first reconcile ownership and either finalize the already-durable merge or safely abort its own incomplete merge before retrying.

Do not create duplicate merge commits after a crash.

---

## 18. Ownership boundaries

### Task Backend / Orchestrator

Owns:

- Task lifecycle;
- requested/effective mode;
- calling `workspace/`;
- calling Runner public APIs;
- deciding orchestration sequence;
- enqueueing effective Main merge;
- exposing status/actions to UI.

It coordinates Workspace and Runner but must not duplicate either implementation.

### workspace/ Manager

Owns:

- Task branch/worktree create/remove;
- optional recovery branch/worktree create/remove;
- resolving `project_root`;
- Task/Run worktree ownership + expected-branch preflight before snapshot/destructive operations;
- ownership-safe cleanup;
- workspace metadata.

### workspace/ Merge Manager

Owns deterministic Git mechanics only:

- merge queue/lock;
- durable `merge_queue_seq`;
- safe target worktree resolution;
- `git merge --no-ff --no-commit`;
- ancestry checks;
- merge abort/conflict detection;
- merge-source metadata;
- merge failure counting;
- fallback decision;
- merged target SHA/idempotency;
- cleanup coordination.

It returns merge/validation state to the Task Backend / Orchestrator. It does **not** invoke Runner internals directly.

### Runner

Owns only:

- run against `project_root`;
- existing Workflow / Agent / Review / Validate behavior;
- optional thin verdict-only `validate(project_root, validation_config)` public API.

The validation-only API must not perform source repair/editing; required source changes return `SOURCE_FAIL` and go through normal Runner recovery in another workspace.

Runner owns no Git/worktree state.

### UI

Owns presentation and user intent only.

UI calls Task/Workspace backend APIs; it never performs Git/worktree operations itself.

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
            → Runner incrementally integrates committed TB changes with latest feature/ui
            → commit recovery result
            → update current merge source
            → retry merge with --no-ff --no-commit
```

Therefore concurrent Tasks still get real Git conflict detection while keeping the merge path direct.

---

## 22. Implementation TODO

### Phase A — settings / contracts

- [ ] Create independent top-level `workspace/` backend package; do not place worktree/merge implementation under Runner or UI.
- [ ] Enforce dependency direction: UI → Task Backend/Orchestrator → workspace + Runner; workspace and Runner do not import each other's internals.
- [ ] Preserve Auto / Main / Isolated Worktree.
- [ ] Global Settings owns `merge_failure_limit` (default 3) and `allow_concurrent_main_tasks` (default false).
- [ ] Task persists only actual `merge_failure_count`; Global Settings owns the merge failure limit.
- [ ] Capture target branch + HEAD per Task run.
- [ ] Keep Runner architecture unchanged.

### Phase B — workspace/ Manager

- [ ] Keep all Git worktree/branch creation/removal in top-level workspace package.
- [ ] Create Task branch/worktree directly from captured target HEAD.
- [ ] Pass Task worktree to Runner as project_root in the current UI/Task flow; standalone/CLI Runner remains caller-project_root driven and workspace-independent.
- [ ] Support unique Task + Run identity.
- [ ] Before snapshot/destructive operations, verify worktree registration, repository identity, expected Task branch, expected source-base ancestry and absence of active Git operation; fail closed on mismatch.
- [ ] Create recovery worktree only after a merge failure that needs source integration repair.
- [ ] Ownership-safe cleanup.

### Phase C — Runner Complete snapshot

- [ ] `git add -A` + commit remaining Task changes.
- [ ] Preserve Agent-created commits.
- [ ] Record task_snapshot_sha.
- [ ] Handle no_changes without empty commits; Main no_changes is the only normal completion path that skips Project merge.

### Phase D — workspace/ direct merge

- [ ] Keep direct merge implementation inside top-level workspace package, not Runner/UI.
- [ ] Serialize merge per repository + target branch with durable FIFO `merge_queue_seq`; restart preserves order; queue head retains its turn during Runner recovery while short Git locks are released.
- [ ] Resolve safe worktree for captured target branch.
- [ ] Before merge, require merge_source_base_sha to remain an ancestor of current target HEAD; otherwise waiting_target_history / Needs Attention without incrementing merge_failure_count.
- [ ] If merge_source_sha is already target-branch ancestry, finalize merged idempotently without another commit.
- [ ] Otherwise use `git merge --no-ff --no-commit <merge_source_branch>` directly in target worktree.
- [ ] Persist `merge_source_base_sha`; require post-merge validation only when current target HEAD differs from the base the current merge source was built/validated against.
- [ ] Reuse an existing public validation entry point or add only a thin Git-unaware, source-non-mutating `validate(project_root, validation_config)` API; no worktree/branch/merge args.
- [ ] Run required post-merge validation before commit with PASS / SOURCE_FAIL / TECHNICAL_ERROR semantics; only SOURCE_FAIL counts as a real merge failure.
- [ ] Before merge commit, verify target HEAD is still the pre-merge HEAD, MERGE_HEAD matches merge_source_sha, and target worktree/index still belongs to this transaction; fail closed/abort on mismatch.
- [ ] Commit merge only after acceptance and transaction ownership check, then record merged_target_head_sha.
- [ ] Merge success is the effective Main completion boundary.

### Phase E — fail merge / recovery

- [ ] On real merge fail: abort merge, increment `merge_failure_count` exactly once, record structured failure.
- [ ] Read current Global `merge_failure_limit` after each real failure.
- [ ] If count <= limit: prepare latest-target-based recovery worktree, hand the committed Task result + three-way conflict context to existing Runner for **incremental merge-repair, never full Task redo**, review/validate integrated result, commit recovery source, atomically replace merge_source_branch/SHA/base_SHA/worktree, then retry merge.
- [ ] If count > limit: stop automatic Main merge, retain latest merge source, and close as Isolated Worktree / worktree_ready with reason merge_failure_limit_exceeded.
- [ ] Do not count queue wait, target dirty/unavailable, lock contention, transient Git error, or Runner failure before merge.

- [ ] Merge-repair handoff includes original base, committed Task snapshot/diff, latest target HEAD, current merge source, conflict details, and relevant development rules; original Task prompt is intent context only.
- [ ] Repair incrementally within the latest-target-based recovery worktree: preserve completed Task changes and current Project changes, resolve only integration differences; no full clone/pull/redevelopment or overwrite of the target tree.
- [ ] Existing Runner reviews/validates the integrated result; resume repairs without discarding prior recovery progress. Publish the replacement merge-source pointer only after a durable recovery commit.
- [ ] Tests cover both-side edits to same file, nonconflicting changes, renamed/moved file, new target commits during repair, restart in mid-repair, validation failure, and failure-limit fallback without loss of committed Task output.

### Phase F — UI

- [x] Effective Main remains Ongoing from Runner Complete until merge succeeds or fallback closes it.
- [x] Show pending_merge / merging / conflict_recovery / waiting_target_clean / waiting_target_workspace / merged / worktree_ready.
- [x] Main fallback visibly indicates original Main + merge_failure_limit_exceeded reason.
- [x] No top-level Git Worktree page; Task Info + Project Workspace Results remain enough.

### Phase G — remote

- [x] Normal lifecycle never executes `git push origin`.
- [x] Keep Publish explicit and separate.

---

## 23. Test TODO

### Isolation / concurrency

- [ ] Verify current UI/Task flow prepares a worktree before triggering Runner, while direct CLI Runner still works from caller-supplied project_root with no workspace dependency.
- [ ] Verify replacing/removing the workspace module would not require changes to Runner/CLI public contracts.
- [ ] Verify UI has no direct Git/worktree execution path.
- [ ] Start 2 / 5 / 10 Tasks from one target branch concurrently.
- [ ] Confirm durable merge_queue_seq FIFO is preserved across process restart.
- [ ] Confirm queue-head Task remains head during conflict Runner recovery while repository Git lock is released; later same-target Tasks cannot overtake it.
- [ ] Every Runner uses a unique Task worktree.
- [ ] Concurrent Main Off blocks a second Main; On allows it.
- [ ] Busy→Worktree Auto remains Worktree while busy even when Concurrent Main is On.

### Merge success

- [ ] Runner Complete does not close Main before merge.
- [ ] Task source merges directly into target branch with --no-ff --no-commit.
- [ ] target HEAD == merge_source_base_sha: conflict-free merge may commit without redundant post-merge validation.
- [ ] target HEAD != merge_source_base_sha: conflict-free merge remains uncommitted until post-merge validation passes.
- [ ] Validation-only API does not intentionally modify Project source; required edits return SOURCE_FAIL and happen only in recovery workspace.
- [ ] SOURCE_FAIL validation aborts cleanly and counts exactly one real merge failure.
- [ ] TECHNICAL_ERROR validation aborts cleanly, does not change merge_failure_count, and uses existing technical retry/backoff / Needs Attention behavior.
- [ ] Before commit, unexpected target HEAD / MERGE_HEAD / worktree transaction changes fail closed and never commit mixed state.
- [ ] Merge success commits and closes Main.
- [ ] Main no_changes closes without a Project merge.
- [x] Restart/external pre-delivery merge recognizes merge_source_sha ancestry and does not duplicate merge.
  - Durable queue transaction ownership also reconciles an AI Task Runner MERGE_HEAD left in the Project target worktree by a crash; mismatched Git operations remain untouched.

### Merge conflict

- [ ] Start A/B from same target commit and edit incompatible same lines.
- [ ] Merge A first.
- [ ] Merge B into latest target and confirm real Git conflict.
- [ ] Confirm merge abort + `merge_failure_count += 1` exactly once.
- [ ] Confirm existing Runner incrementally integrates B's committed changes with latest target, without rerunning original development.
- [ ] Confirm recovery updates merge_source_branch/SHA/worktree and stale original Task source is not merged again.
- [ ] Confirm recovery branch merges successfully when fixed.
- [ ] Confirm fallback retains latest recovery source after repeated failures.

### Merge failure limit

- [ ] Global limit=3: failures 1/2/3 recover, failure 4 falls back.
- [ ] Fallback retains the latest current merge source branch/worktree and closes as worktree_ready.
- [ ] Task stores only actual merge_failure_count; merge_failure_limit stays Global.

### Target safety

- [ ] Dirty target => waiting_target_clean; do not mutate user changes.
- [ ] Target in unmanaged worktree => waiting_target_workspace.
- [ ] Captured target branch deleted/renamed => waiting_target_branch; never guess/recreate/retarget.
- [ ] merge_source_base_sha no longer ancestor of current target HEAD after history rewrite/divergence => waiting_target_history; do not merge/recover automatically and do not count merge failure.
- [ ] Task/Recovery branch reset/rebase that breaks expected source-base ancestry fails closed before snapshot.
- [ ] Target force-reset/divergence that removes merge_source_base_sha from target ancestry => waiting_target_history and never reintroduces removed history.
- [ ] User branch switch after Task start never retargets old Task.

### Local-only

- [ ] No remote credentials required.
- [ ] No automatic `git push` occurs.

---

## 24. Non-goals

- Do not reinterpret "removable workspace adapter" as a current UI runtime bypass; current UI Task execution still prepares worktrees before Runner.
- Do not place worktree/merge code under Runner or UI.
- Do not make Runner understand workspace mode, worktrees, branches, merge queues or merge failures.
- Do not let workspace/ import Runner internals; Task Backend/Orchestrator coordinates public APIs.
- Do not redesign Runner.
- Do not add a Git Workflow Stage.
- Do not add a second retry/recovery engine.
- Do not auto-switch user Project checkout branch.
- Do not auto-stash/reset/discard/commit unrelated dirty Project files.
- Do not auto-push every Task to remote.

---

## 25. Final invariant summary

```text
UI
↓
Task Backend / Orchestrator
├─ workspace/  (removable Git/worktree adapter)
└─ Runner      (Git-unaware; project_root only)

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
verify merge_source_base_sha is still target ancestry
├─ No → waiting_target_history / Needs Attention
└─ Yes
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
           → existing Runner incremental integration repair of completed Task source against latest Project
           → commit recovery result
           → retry current merge source

           count > limit
           → Isolated Worktree fallback
           → Closed · worktree_ready
```
