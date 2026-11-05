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


## 真實 Qwen + Ralphy Workflow 測試

若要測試**真的呼叫本機 Qwen CLI**，執行：

```bat
examples\13_concurrent_worktree_conflict\run_live_qwen_conflict_test.bat
```

這個版本不使用 deterministic mock agent，也不新增專用 Workflow。
它直接使用既有：

```text
runner/assets/workflows/ralphy_ai_validate.yaml
```

因此每個初始 Task 都會實際走：

```text
Ralphy Execute (real Qwen)
        |
        v
AI Validator (fresh real Qwen session)
```

完整情境為：

```text
same Main HEAD
   |
   +-- Task A -> isolated worktree -> real Qwen / Ralphy
   |
   +-- Task B -> isolated worktree -> real Qwen / Ralphy
                       |
                  A merges first
                       |
                  B merge conflict
                       |
             TaskRunService recovery
                       |
              latest-Main worktree
                       |
             real Qwen / Ralphy repair
                       |
                recovery snapshot
                       |
                    Merge Main
```

測試故意讓兩個 Task 同時修改 `shared.txt`。
Task A 先合併後，Task B 必須產生真實 Git conflict；
production `TaskRunService` 會自動建立 recovery worktree 與 patch，
然後再次啟動 real Runner + Qwen 執行 merge repair。

### 前置條件

Windows PATH 必須能找到：

```bat
git
python
qwen.cmd
```

可先確認：

```bat
qwen.cmd --version
```

Qwen 本身也必須已完成你平常使用 Runner 所需的登入 / Provider 設定。

如果你的 Qwen command 不是 `qwen.cmd`：

```bat
set QWEN_COMMAND=C:\path\to\qwen.cmd
examples\13_concurrent_worktree_conflict\run_live_qwen_conflict_test.bat
```

預設測試資料會保留在：

```text
%TEMP%\ai-task-runner-live-qwen-worktree-conflict
```

可檢查：

```bat
type %TEMP%\ai-task-runner-live-qwen-worktree-conflict\project\shared.txt
git -C %TEMP%\ai-task-runner-live-qwen-worktree-conflict\project log --graph --oneline --all
type %TEMP%\ai-task-runner-live-qwen-worktree-conflict\logs\task-a.log
type %TEMP%\ai-task-runner-live-qwen-worktree-conflict\logs\task-b.log
type %TEMP%\ai-task-runner-live-qwen-worktree-conflict\logs\recovery-1.log
```

成功條件不是固定文字排序，而是最後 `shared.txt` 同時保有：

```text
BASE
TASK_A
TASK_B
```

並且 Main working tree 必須 clean、Git history 至少包含兩次 delivery merge。
