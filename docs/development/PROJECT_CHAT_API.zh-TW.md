# Project Chat API 契約

Project Chat 是一般對話介面。它共用既有 UI server 與 Agent adapter boundary，但不執行 Runner workflow，也不擁有 Runner runtime state。

## Ownership

```text
Project Chat UI
  -> UIServer
     -> ChatService          持久化 Session/Message/Queue/Ask/Event
     -> ChatAgentService     單一普通 Agent turn + cancel
     -> Agent capability/settings services
     -> TaskDraftService     暫存 TaskDraft generation

明確 Task Create / Run
  -> Task service / Runner public boundary
```

普通 Chat 永遠不會推測 Runner 執行意圖或自行建立 Task。明確輸入的 `@goal` 是刻意設計的例外：它只呼叫一個 Backend-owned、具冪等性的 create-then-run action，並重用既有 Task service、Workspace resolver 與 TaskRunService。`@task*` 仍只負責 Draft / Review / Create。

## Durable identity 與 state

Chat session、message、turn、Queue item、Ask request、TaskDraft 都使用 Backend 產生的穩定 ID。可重試的 mutation 使用 `request_id`，避免 HTTP retry 無聲建立重複 durable work。

Chat state 依 Project 儲存在 `.ai-task-runner/ui/chat/`。Message history 與 Runner Task history 分開。

## 主要 HTTP surfaces

| 能力 | Surface |
| --- | --- |
| Session list/create/select/rename/delete | `/api/chat/sessions`, `/api/chat/session/*` |
| Message history | `/api/chat/messages` |
| 普通 Agent turn / cancel | `/api/chat/turn`, `/api/chat/turn/cancel` |
| Queue/status | `/api/chat/queue`, `/api/chat/queue/*` |
| Ask read/submit/cancel | `/api/chat/ask`, `/api/chat/ask/*` |
| Durable event cursor | `/api/chat/events` |
| TaskDraft generate/update/dismiss | `/api/chat/task-draft*` |
| 明確 Quick Goal 建立 + 執行 | `/api/tasks/goal` |
| Project Agent/Model/Mode/Reasoning/Workflow | Project preferences + backend capability/catalog APIs |

Event feed 採 bounded durable polling，因為現有 UI 已擁有 non-overlapping polling。這不會建立第二套 SSE/WebSocket connection manager，而且 Chat event 與 Runner runtime event 保持分離。

## Cancel、reconnect、restart

- Turn cancel 對目前 active turn 是 idempotent，也會取消 waiting Ask。
- Agent subprocess timeout 有上限；cancel 會沿 canonical backend process runner unwind，因此 child process tree 會被清理。
- Client disconnect 只停止寫回該 HTTP response，不會刪除 durable Chat state。
- Restart 後，沒有 owner 的 `dispatching` Queue item 會在 drain 前恢復為 `queued`。若某 turn 的 assistant message 已 durable，不會再次送給 Agent。
- 中斷的 Ask resolution 會回到 `waiting`；過期 Ask 會 durable cancel。
- 若持久化的 native Agent session 已不存在，Chat 直接重用 canonical `runner.agent.is_session_invalid_error` classifier，並以 compare-and-clear 只清掉該 stale session pointer。因 Agent turn 可能已有 tool side effect，failed turn 不會自動重播；下一個明確 turn 才建立 fresh session。

## Public projection 與敏感資料

Public Session、Ask、Queue、Event response 都是明確 projection。Native Agent session ID 與 native Ask transport request ID 屬於 internal state，不會由這些 projection 回傳。

Chat API response 不得暴露完整 system prompt、credential、API key 或 process environment。Provider-specific native payload 必須留在 Agent adapter boundary；Browser 只取得 normalized capability / Ask data。

## Tests

`ui/tests/test_chat_service.py` 覆蓋 service 與 HTTP contract，包括 session CRUD、durable Queue recovery、resend idempotency、cancel、Ask timeout/recovery、event cursor、stale Agent-session recovery 與 public projection redaction。Browser fixture 直接重用同一份 production ChatService 與 TaskDraftService schema owner。
