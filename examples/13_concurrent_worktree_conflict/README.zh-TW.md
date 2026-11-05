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
