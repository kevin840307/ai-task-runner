# Project Chat API Contract

Project Chat is the ordinary conversation surface. It shares the existing UI server and Agent adapter boundary, but it does not execute Runner workflows or own Runner runtime state.

## Ownership

```text
Project Chat UI
  -> UIServer
     -> ChatService          durable sessions/messages/queue/Ask/events
     -> ChatAgentService     one ordinary Agent turn + cancellation
     -> Agent capability/settings services
     -> TaskDraftService     transient TaskDraft generation

Explicit Task Create / Run
  -> Task service / Runner public boundary
```

Ordinary Chat never infers Runner execution intent or creates a Task. The explicit `@goal` command is the exception by design: it calls one backend-owned idempotent create-then-run action, which reuses the canonical Task service, Workspace resolver, and TaskRunService. `@task*` remains Draft/Review/Create only.

## Durable identity and state

Chat sessions, messages, turns, Queue items, Ask requests, and TaskDrafts use backend-issued stable IDs. Mutating requests use `request_id` where the operation can be retried, so HTTP retries do not silently duplicate durable work.

Chat state is stored per Project under `.ai-task-runner/ui/chat/`. Message history is separate from Runner Task history.

## Main HTTP surfaces

| Capability | Surface |
| --- | --- |
| Session list/create/select/rename/delete | `/api/chat/sessions`, `/api/chat/session/*` |
| Message history | `/api/chat/messages` |
| Ordinary Agent turn / cancel | `/api/chat/turn`, `/api/chat/turn/cancel` |
| Queue/status | `/api/chat/queue`, `/api/chat/queue/*` |
| Ask read/submit/cancel | `/api/chat/ask`, `/api/chat/ask/*` |
| Durable event cursor | `/api/chat/events` |
| TaskDraft generate/update/dismiss | `/api/chat/task-draft*` |
| TaskDraft validate/create | `/api/tasks/validate-draft`, `/api/tasks/create-from-draft` |
| Explicit Quick Goal create + run | `/api/tasks/goal` |
| Task Workspace result / direct merge / explicit Publish | `/api/tasks`, `/api/tasks/merge`, `/api/tasks/publish` |
| Project Agent/Model/Mode/Reasoning/Workflow | Project preferences + backend capability/catalog APIs |

The event feed is bounded durable polling because the existing UI already owns non-overlapping polling. It does not introduce a second SSE/WebSocket connection manager, and Chat events remain separate from Runner runtime events.

Queue order is intentionally service-owned FIFO. Edit/delete are public operations; there is no reorder endpoint because the product contract does not allow user sorting. Merge preflight/status is returned through the canonical Task Workspace result used by `/api/tasks/merge`; Merge Chat builds its handoff prompt from that same Task result instead of maintaining a duplicate merge-context API. Publish is an explicit, separate result action and is never invoked by the normal Task lifecycle.

## Cancel, reconnect, and restart

- Turn cancellation is idempotent for the active turn and also cancels a waiting Ask.
- Agent subprocess timeouts are bounded; cancellation unwinds through the canonical backend process runner so child process trees are cleaned up.
- Client disconnect only stops writing that HTTP response. It does not erase durable Chat state.
- After restart, an unowned `dispatching` Queue item is recovered to `queued` before drain. A turn whose assistant message is already durable is not sent to the Agent again.
- An interrupted Ask resolution returns to `waiting`; an expired Ask is durably cancelled.
- If a persisted native Agent session no longer exists, Chat reuses the canonical `runner.agent.is_session_invalid_error` classifier and compare-and-clears only that stale session pointer. The failed turn is not replayed automatically because an Agent turn may have tool side effects. The next explicit turn starts fresh.

## Public projection and sensitive data

Public Session, Ask, Queue, and Event responses are explicit projections. Native Agent session IDs and native Ask transport request IDs are internal state and are not returned by those projections.

Chat API responses must not expose full system prompts, credentials, API keys, or process environment material. Provider-specific native payloads stay behind the Agent adapter boundary; the browser receives normalized capability/Ask data only.

## Tests

`ui/tests/test_chat_service.py` covers service and HTTP contracts including session CRUD, durable Queue recovery, resend idempotency, cancellation, Ask timeout/recovery, event cursors, stale Agent-session recovery, and public projection redaction. Browser fixtures reuse the same production ChatService and TaskDraftService schema owners.
