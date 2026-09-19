# 使用 Git Worktree 同時開發多個需求

版本：1.2.66

這份文件說明：當你想讓多個需求同時修改同一個 Git 專案時，建議怎麼做，才能避免多個 AI / CLI run 互相覆蓋檔案。

目前 Runner 不需要內建 worktree 功能也能使用這個流程。做法是：每個需求先手動建立一個 Git worktree，然後每個 Runner 指令用 `--project-root` 指到自己的 worktree。

## 為什麼用 Worktree

如果多個任務同時跑在同一個實體專案資料夾，風險很高，因為所有 process 都在讀寫同一批檔案。Read-only safety mode 可以降低「read-only 階段把外部變更還原掉」的問題，但它不是真正隔離，也不能可靠判斷某個檔案是誰改的。

Git worktree 是從檔案系統層級隔離：

- 每個需求有自己的資料夾。
- 每個資料夾有自己的 branch。
- Build output、測試結果、cache、Runner state 都彼此分開。
- 最後整合仍然使用一般 Git merge、rebase、cherry-pick 或 PR review。

比起直接複製整包專案，worktree 比較乾淨。複製資料夾雖然快，但比較容易忘記同步主分支，也比較容易在合併時混亂。Worktree 仍然連到同一個 Git repo 歷史。

## 基本範例

假設主專案路徑是：

```powershell
C:\Users\kevin\projects\shop-api
```

每個需求建立一個 worktree：

```powershell
cd C:\Users\kevin\projects\shop-api

git worktree add ..\shop-api-login -b feature/login
git worktree add ..\shop-api-payment -b feature/payment
git worktree add ..\shop-api-admin -b feature/admin
```

結果會得到：

```text
C:\Users\kevin\projects\shop-api          # 主專案
C:\Users\kevin\projects\shop-api-login    # 登入需求
C:\Users\kevin\projects\shop-api-payment  # 付款需求
C:\Users\kevin\projects\shop-api-admin    # 後台需求
```

每個需求都有不同 project path，也有不同 branch。

## 執行 Runner

每個需求都指到自己的 worktree：

```powershell
python C:\Users\kevin\ai-task-runner\ai_task_runner.py `
  --project-root C:\Users\kevin\projects\shop-api-login `
  --goal-file C:\Users\kevin\goals\login.md `
  --validator C:\Users\kevin\validators\shop_api_validator.py
```

另一個 terminal 可以跑付款需求：

```powershell
python C:\Users\kevin\ai-task-runner\ai_task_runner.py `
  --project-root C:\Users\kevin\projects\shop-api-payment `
  --goal-file C:\Users\kevin\goals\payment.md `
  --validator C:\Users\kevin\validators\shop_api_validator.py
```

最重要的規則是：不要讓同時執行的多個 Runner 指到同一個 `--project-root`。

## 建議命名

資料夾名稱建議清楚表達需求：

```text
<repo-name>-<requirement-slug>
```

例如：

```text
shop-api-login
shop-api-payment
shop-api-admin
```

Branch 名稱也建議對應：

```text
feature/login
feature/payment
feature/admin
```

如果是 AI-heavy 或實驗性工作，也可以用專屬 prefix：

```text
ai-task/login
ai-task/payment
ai-task/admin
```

## YAML Script Mode

YAML script mode 已經支援每個 item 設定 `project_root`。你可以先建立好 worktree，再讓每個 item 指到不同 worktree：

```yaml
- goal_file: goals/login.md
  project_root: C:\Users\kevin\projects\shop-api-login
  validator: C:\Users\kevin\validators\shop_api_validator.py

- goal_file: goals/payment.md
  project_root: C:\Users\kevin\projects\shop-api-payment
  validator: C:\Users\kevin\validators\shop_api_validator.py
```

Runner 會把每個 item 的 state 放在該 item 對應 worktree 底下，所以每個需求都有自己的 `.ai-task-runner` state。

## Project Policy

如果專案有 `.ai-task-runner.yaml`，建議把它 commit 在專案內，這樣每個 worktree 都會拿到相同 policy：

```yaml
protected_paths:
  - input/
  - ans/
instructions:
  always: |
    Keep changes minimal.
    Reuse existing architecture and helpers.
```

Runner 不會往父資料夾尋找 policy。Policy 檔必須存在於實際的 `--project-root` 內；只要 `.ai-task-runner.yaml` 是 Git 專案的一部分，每個 worktree 就會自動有這份檔案。

## 檢查單一需求

檢查某個需求時，把它當成一般 checkout 即可：

```powershell
cd C:\Users\kevin\projects\shop-api-login

git status
git diff
python -m pytest
```

需求完成後，再用你平常的人為 Git 流程 commit 或 review。

## 合併回主專案

從主專案 checkout 逐一合併已完成的 branch：

```powershell
cd C:\Users\kevin\projects\shop-api

git merge feature/login
git merge feature/payment
git merge feature/admin
```

如果兩個需求改到同一段程式，Git 會顯示一般 merge conflict。解完 conflict 後，重新跑 deterministic validator 和測試，再繼續合併。

如果想更安全，建議用 PR review，不要直接 local merge。

## 更新 Worktree

開始新需求前，先更新主專案：

```powershell
cd C:\Users\kevin\projects\shop-api
git pull
```

然後再從更新後的 branch 建立 worktree。既有 worktree 如果要同步最新主分支，可以用一般 Git 流程，例如：

```powershell
cd C:\Users\kevin\projects\shop-api-login
git fetch
git rebase main
```

請把 `main` 換成你專案實際使用的 branch 名稱，例如 `main`、`master` 或 `develop`。

## 清理 Worktree

需求已合併且不再需要時：

```powershell
cd C:\Users\kevin\projects\shop-api
git worktree list
git worktree remove ..\shop-api-login
git branch -d feature/login
```

如果你曾經手動刪掉 worktree 資料夾，可以清理 Git 的 worktree metadata：

```powershell
git worktree prune
```

## 這個流程不做什麼

這個流程不會自動 merge 程式、不會自動解 conflict、不會自動刪 worktree，也不會替你判斷兩個需求同時修改同一個行為時誰應該贏。

它提供的是「開發期間的乾淨隔離」。最後整合仍然是 Git review 與 merge 決策。

## 實務建議

同一個專案要同時開發多個需求時：

1. 一個需求一個 Git worktree。
2. 一個 worktree 一個 branch。
3. 一個 Runner task 只指向一個 worktree path。
4. `.ai-task-runner.yaml` 放進專案並 commit。
5. 完成後走一般 Git review / merge 流程。

這是目前最安全的做法，因為它避免同資料夾檔案互撞，同時保留正常 Git 整合方式。
