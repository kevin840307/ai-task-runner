# 兩個 Runner + Worktree + 自動衝突 Recovery 範例

這個範例不是單純 `git merge` mock，而是實際走：

```text
同一個 Project Main HEAD
        |
        +---- Task A isolated worktree ---- real Runner
        |
        +---- Task B isolated worktree ---- real Runner
                    |
Task A snapshot -> Merge Main
                    |
Task B snapshot -> Merge Main -> shared.txt conflict
                    |
                    v
       prepare_recovery(latest Main)
                    |
        Recovery isolated worktree
                    |
              real Runner
                    |
           recovery snapshot
                    |
                    v
               Merge Main
```

> 這裡 Task 的 `requested_mode=main` 代表「最後要送回 Main」。
> 執行本身仍然是 **每個 Task 一個獨立 worktree**；這正是 production 的 Concurrent Main 模式。

## Windows 執行

在 repo 內執行：

```bat
examples\13_concurrent_worktree_conflict\run_example.bat
```

成功時會看到：

```text
Task A merge: merged
Task B merge intentionally conflicted: shared.txt
Recovery merge: merged
FINAL shared.txt:
TASK-A
TASK-B
[PASS]
```

預設會把暫存 Git repo 留在 Windows TEMP 下，方便檢查：

```bat
git worktree list
git branch
git log --graph --oneline --all
type shared.txt
```

要執行後刪除暫存資料：

```bat
examples\13_concurrent_worktree_conflict\run_example.bat --cleanup
```

也可指定固定位置：

```bat
examples\13_concurrent_worktree_conflict\run_example.bat --root C:\temp\atr-conflict-demo
```

這個範例使用 deterministic mock agent，因此 **不需要真的呼叫 Qwen API**；但是 Runner、StageExecutor、Qwen backend command adapter、WorkspaceManager、Git worktree、snapshot、MergeManager、durable merge queue、recovery worktree 都是 production code。


## 自動 Recovery Orchestration 測試

除了上面的可執行 Demo，repo 內還有一個更接近 UI/Task production orchestration 的 pytest：

```bat
python -m pytest -q tests\test_runner_worktree_conflict_recovery_example.py
```

這個測試會：

1. 透過 `TaskRunService.start()` 同時啟動兩個 Task。
2. 每個 Task 都由獨立的 **real `ai_task_runner.py` subprocess** 在自己的 worktree 執行。
3. 兩個 Task 從相同 Main HEAD 開始，並故意修改同一個 `app.txt`。
4. Task A 先合併。
5. Task B 合併時產生真實 Git conflict。
6. `TaskRunService` 自動建立 recovery worktree、recovery patch 與 merge-repair prompt。
7. 系統自動再啟動第三個 Runner subprocess 修復衝突。
8. Recovery snapshot 最後由 production `MergeManager` 合併回 Main。

因此這個 pytest 驗證的是：

```text
Task A Runner ─┐
               ├─ concurrent isolated worktrees
Task B Runner ─┘
       │
       ├─ A merge -> Main
       │
       └─ B merge -> conflict
                    │
                    v
          TaskRunService auto recovery
                    │
             Recovery Runner
                    │
             Recovery snapshot
                    │
                    v
                Merge Main
```

AI 本身仍使用 deterministic test agent，所以 CI 不需要外部 Qwen；Runner process、worktree、snapshot、conflict detection、recovery orchestration 與 merge 都是 production code。
