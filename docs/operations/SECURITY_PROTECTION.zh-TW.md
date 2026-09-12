# 保護與安全模型

版本：1.2.66

## Project root
Project root 是 task workspace boundary。Project policy 只從 `<project-root>/.ai-task-runner.yaml` 讀取，不會往 parent directory 搜尋。

## Protected paths
`protected_paths` 是 project-relative file/directory。Directory 會保護整個 subtree。Path 會 normalize；已有 protected parent 時 descendant 會折疊。Absolute path 與 `..` escape 會被拒絕。Policy 本身永遠自動 protected。 使用 external file validator 的 project 也應保護 `ai_task_runner_validator.py`；source-mode 執行時 Runner 可能會把這個共用 helper 放在 `validation.py` 同目錄。

Protected-path snapshot 可偵測修改、刪除，以及 protected directory 底下的新檔，並還原違規變更。CLI `--protect-file` 可臨時增加保護；長期規則建議放 project policy。

Safety snapshot 會排除明確的 technical/runtime artifact，避免工具副作用被誤判成 source 變更。內建忽略目錄包含 `.git`、`.ai-task-runner`、`.vs`、`.vscode`、`.idea`、`.gradle`、`.pytest_cache`、`.mypy_cache`、`.ruff_cache`、`.tox`、`.nox`、`.venv`、`__pycache__`、`bin`、`obj`、`build`、`dist`、`coverage`、`htmlcov`、`node_modules`、`target`、`TestResults`；也忽略 `.pyc`/`.pyo`、`.coverage`、`.DS_Store`、`Thumbs.db`。這不是「所有 `.` 開頭都忽略」：`.gitignore`、`.gitattributes`、`.editorconfig`、`.env.example`、`.github/**` 仍是正常 project/protected 內容。若真正 source 被修改需要還原，Safety 只還原 source diff，不會刪掉這些被忽略的 artifact。Runner 控制的 child process 也會設定 `PYTHONDONTWRITEBYTECODE=1`，從源頭減少 Python cache churn。

Windows 上 Safety 的檔案 I/O 會在內部使用 extended-length path，因此 protected / readonly tree 的絕對路徑超過傳統 `MAX_PATH` 時，不會因為路徑過長就靜默跳過保護；Project 邏輯路徑與 policy 寫法都不需要改。

## 應保護什麼
Immutable input、answer/reference fixture、位於 project root 內的 validator helper，以及「Agent 可以讀但絕對不能改」的檔案。Task 本來就要改的 source/output 不可 protected。

## Runner source / Validator
Runner source/backend files 與 configured goal/validator 由 orchestrator 加入保護。Validator 若位於 Agent 可寫的 project root，應明確 protected，或放在 project root 外。

## Git
AI child-process PATH guard 阻擋 `git add`、`git commit`、`git push`；Git read/diagnostic 可使用。這是 guardrail，不是 OS sandbox；stage/commit/push 最終由人類負責。

## Backend capability limits
Qwen Planning 維持 read-only，只有目前 planning step 缺少必要 evidence 時才 bounded 使用 filesystem read tools。唯讀範圍可以是 host account 可讀取的任何 path，包含目前 Project 之外；write/edit/shell 仍完全關閉。OpenCode Planning 也採相同語意：只允許 read/glob/grep/LSP 與 external-directory read，其餘 tool 仍 deny。`allow_project_read` 保留為相容既有 YAML/API 的欄位名稱；對 `PlanStage` 而言其語意是 readonly filesystem inspection，且預設為 `true`，若要禁止 Planning 讀檔可顯式設為 `false`。Review 與 final AI validation 維持既有 read-only review policy。Runtime 排除不相關 agent/skill/computer-use tools。這些 capability policy 是 filesystem protection 的額外一層。
