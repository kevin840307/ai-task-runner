# 保護與安全模型

版本：1.2.13

## Project root
Project root 是 task workspace boundary。Project policy 只從 `<project-root>/.ai-task-runner.yaml` 讀取，不會往 parent directory 搜尋。

## Protected paths
`protected_paths` 是 project-relative file/directory。Directory 會保護整個 subtree。Path 會 normalize；已有 protected parent 時 descendant 會折疊。Absolute path 與 `..` escape 會被拒絕。Policy 本身永遠自動 protected。

Protected-path snapshot 可偵測修改、刪除，以及 protected directory 底下的新檔，並還原違規變更。CLI `--protect-file` 可臨時增加保護；長期規則建議放 project policy。

## 應保護什麼
Immutable input、answer/reference fixture、位於 project root 內的 validator helper，以及「Agent 可以讀但絕對不能改」的檔案。Task 本來就要改的 source/output 不可 protected。

## Runner source / Validator
Runner source/backend files 與 configured goal/validator 由 orchestrator 加入保護。Validator 若位於 Agent 可寫的 project root，應明確 protected，或放在 project root 外。

## Git
AI child-process PATH guard 阻擋 `git add`、`git commit`、`git push`；Git read/diagnostic 可使用。這是 guardrail，不是 OS sandbox；stage/commit/push 最終由人類負責。

## Backend capability limits
Qwen Planning 是 read-only，當目前 planning step 需要證據時可 bounded 使用 project read tools；write/edit/shell 仍關閉。Review 關閉 write/edit/shell；Runtime 排除不相關 agent/skill/computer-use tools。這些 capability policy 是 filesystem protection 的額外一層。
