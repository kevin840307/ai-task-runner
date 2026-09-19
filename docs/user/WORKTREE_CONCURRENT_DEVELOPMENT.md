# Concurrent Development With Git Worktrees

Version: 1.2.66

This guide describes the recommended way to run multiple requirements against the same Git project at the same time without letting parallel AI or CLI runs overwrite each other.

The Runner does not need native worktree support for this workflow. Create one Git worktree per requirement, then point each Runner invocation at that worktree with `--project-root`.

## Why Worktrees
Running multiple tasks in the same physical project directory is risky because every process reads and writes the same files. Read-only safety modes can reduce accidental restoration, but they do not provide true isolation and cannot know which external process changed a file.

Git worktrees solve the isolation problem at the filesystem level:

- each requirement gets its own folder;
- each folder has its own branch;
- build outputs, tests, caches, and Runner state stay separate;
- final integration still uses normal Git merge, rebase, cherry-pick, or pull request review.

Prefer worktrees over copying the whole project directory. A copied project is easy to create, but harder to keep synchronized and easier to merge incorrectly. A worktree remains connected to the same Git repository history.

## Basic Shape
Assume the main project is:

```powershell
C:\Users\kevin\projects\shop-api
```

Create one worktree per requirement:

```powershell
cd C:\Users\kevin\projects\shop-api

git worktree add ..\shop-api-login -b feature/login
git worktree add ..\shop-api-payment -b feature/payment
git worktree add ..\shop-api-admin -b feature/admin
```

This gives you:

```text
C:\Users\kevin\projects\shop-api          # main checkout
C:\Users\kevin\projects\shop-api-login    # login requirement
C:\Users\kevin\projects\shop-api-payment  # payment requirement
C:\Users\kevin\projects\shop-api-admin    # admin requirement
```

Each requirement now has a different project path and a different branch.

## Running the Runner
Run each requirement against its own worktree:

```powershell
python C:\Users\kevin\ai-task-runner\ai_task_runner.py `
  --project-root C:\Users\kevin\projects\shop-api-login `
  --goal-file C:\Users\kevin\goals\login.md `
  --validator C:\Users\kevin\validators\shop_api_validator.py
```

In another terminal:

```powershell
python C:\Users\kevin\ai-task-runner\ai_task_runner.py `
  --project-root C:\Users\kevin\projects\shop-api-payment `
  --goal-file C:\Users\kevin\goals\payment.md `
  --validator C:\Users\kevin\validators\shop_api_validator.py
```

The important rule is simple: do not point concurrent runs at the same `--project-root`.

## Recommended Naming
Use names that make the requirement obvious:

```text
<repo-name>-<requirement-slug>
```

Examples:

```text
shop-api-login
shop-api-payment
shop-api-admin
```

Use branch names that match:

```text
feature/login
feature/payment
feature/admin
```

For AI-heavy or experimental work, a dedicated prefix is also reasonable:

```text
ai-task/login
ai-task/payment
ai-task/admin
```

## YAML Script Mode
YAML script mode can use existing per-item `project_root` support. Create the worktrees first, then point each item at a different worktree:

```yaml
- goal_file: goals/login.md
  project_root: C:\Users\kevin\projects\shop-api-login
  validator: C:\Users\kevin\validators\shop_api_validator.py

- goal_file: goals/payment.md
  project_root: C:\Users\kevin\projects\shop-api-payment
  validator: C:\Users\kevin\validators\shop_api_validator.py
```

The Runner stores each item state under that item's worktree root, so each requirement keeps separate `.ai-task-runner` state.

## Project Policy
If the source project uses `.ai-task-runner.yaml`, keep it committed in the repository so every worktree receives the same policy:

```yaml
protected_paths:
  - input/
  - ans/
instructions:
  always: |
    Keep changes minimal.
    Reuse existing architecture and helpers.
```

The Runner does not search parent directories for policy. The policy file must exist inside each effective `--project-root`, which happens automatically when the policy is part of the Git project.

## Reviewing One Requirement
Inspect a worktree like any normal checkout:

```powershell
cd C:\Users\kevin\projects\shop-api-login

git status
git diff
python -m pytest
```

When the requirement is ready, commit or otherwise review it using your normal human-owned Git process.

## Merging Back
From the main checkout, merge finished branches one by one:

```powershell
cd C:\Users\kevin\projects\shop-api

git merge feature/login
git merge feature/payment
git merge feature/admin
```

If two requirements touched the same code, Git will surface a normal merge conflict. Resolve it in the target branch, run the deterministic validator and test suite again, then continue the merge.

For higher-safety review, use pull requests instead of direct local merges.

## Updating Worktrees
Before starting a new requirement, refresh the main checkout:

```powershell
cd C:\Users\kevin\projects\shop-api
git pull
```

Then create the worktree from the updated branch. If an existing worktree needs the latest main branch, update it with your normal Git workflow, for example:

```powershell
cd C:\Users\kevin\projects\shop-api-login
git fetch
git rebase main
```

Use the branch name that matches your repository, such as `main`, `master`, or `develop`.

## Cleaning Up
After a requirement is merged and no longer needed:

```powershell
cd C:\Users\kevin\projects\shop-api
git worktree list
git worktree remove ..\shop-api-login
git branch -d feature/login
```

If a worktree folder was deleted manually, repair Git's worktree metadata:

```powershell
git worktree prune
```

## What This Does Not Do
This workflow does not automatically merge code, resolve conflicts, delete worktrees, or decide which requirement should win when two branches change the same behavior.

It provides clean isolation while development is happening. Final integration remains a Git review and merge decision.

## Practical Recommendation
For multiple simultaneous requirements on the same project:

1. Use one Git worktree per requirement.
2. Use one branch per worktree.
3. Run one Runner task against one worktree path.
4. Keep `.ai-task-runner.yaml` committed in the project.
5. Merge completed branches through normal Git review.

This is the safest current workflow because it avoids same-folder file contention while preserving the normal Git integration model.
