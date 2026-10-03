# Test Matrix

This file describes what is covered by deterministic CI and what still requires a real backend or soak run.

## Deterministic CI

The normal GitHub gate runs compile + pytest on Ubuntu and Windows plus the React Studio build. It also rebuilds Workflow Editor and verifies the committed `ui/static/workflow-studio-app` exactly matches `ui/studio-src`; CI is verify-only and never rewrites the branch.

| Area | Coverage |
| --- | --- |
| Workflow schema | supported Stage types/options, AI Stage profiles, unknown option rejection, PASS/FAIL-only routes, target existence, dynamic producer child-Stage validation |
| Semantic routing | PASS next, explicit PASS/FAIL, done/stop, backward loop, unrouted FAIL safe stop |
| Technical ERROR | Stage/global retry limits, unlimited `-1`, Same Session retry, Fresh Session rotation, partial-write recovery, Review finite-retry fail-soft Skip, non-Review fail-closed exhaustion, KeyboardInterrupt/SystemExit propagation |
| Session policy | main/role/fresh acceptance, invalid mode, role durable restore/persist, fresh non-persistence, per-role reset, global reset, recovery rotation |
| Dynamic child Workflow | producer-defined tasks/stages, Plan Execute→Review expansion, nested producer isolation, child completion before parent continuation, durable resume without re-running producer |
| Dynamic Handoff | target allow-list, disallowed target rejection, exactly-one target routing, role -> coordinator loop, final validator FAIL -> coordinator, durable resume |
| Prompts | shared Dynamic worker renders role `instructions`; prompt ownership/category references; shared retry/continue/recover control envelope |
| Validators | File command validators, AI validators, multiple validators anywhere, repeated AI runs/voting, validator FAIL rollback |
| Dynamic producers | Plan producer-defined Execute/Review children, custom/plugin `produces: tasks|stages`, nested dynamic expansion |
| Resume/state | workflow position, durable expanded Workflow, dynamic task groups, transition_previous, role Sessions, corrupt/incompatible state rejection |
| Dry Run | normal closure, fail loops, Dynamic Handoff, custom dynamic producer, non-converging loop cutoff, invalid schema/route controls |
| Stage Probe | isolated Real Stage execution with real backend, fixed-prompt Agent Ping, bounded test retry safety, result/next target without continuing the workflow |
| Studio backend | YAML graph save/validation, stage add/delete, asset roots, prompt references, Stage test sandbox |
| Studio React | PASS/FAIL/Handoff handles, searchable palette, safe duplicate, Review max_failures UI, Dynamic branch layout, session-policy UI normalization, no ERROR edge, separate Workflows/Prompts navigation with Interface settings kept outside the primary nav, Stage Form/YAML/Routing/Test ownership, common desktop viewport overflow checks |
| Process/runtime | ownership/orphan/supervisor/control-file probes, repeated same-checkpoint crash restart, capped process backoff |

## Negative/removed-contract coverage

Tests must reject or prove absence of:

- `routes.error`;
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph controls;
- Discussion / Group Chat runtime or UI mode is absent;
- deleted compatibility runtime modules;
- obsolete Workflow/Prompt asset paths.

## Tool workflow preflight

Representative YAML under `tool/workflow/` must load with the production loader and remain compatible with `tool/workflow_dryrun.py`. The current examples use Review gates, validators and custom task production; there is no Grill runtime contract.

## Real-Qwen short gate

`tool/qwen_live_reliability.py` is the real-backend proof. The short Windows wrapper is:

```powershell
tool\qwen_live_reliability_0_5h.bat
```

Before soak, the tool performs deterministic preflight and then exercises real-Qwen paths including:

- file / AI / mixed built-in topologies;
- Dynamic Handoff target selection;
- main / reusable role / fresh session policies;
- the same role selected more than once and required to keep the same Session;
- Review FAIL rollback and durable `max_failures` fourth-entry bypass/reset;
- Validator FAIL rollback;
- HTTP 429 / 502 / 503 recovery;
- raw disconnect recovery;
- expired Session -> Fresh Session;
- process restart / detached UI resume;
- YAML List resume;
- custom Stage / custom dynamic producer;
- protected-file policy;
- timeout/recovery budget;
- final AI voting.

Having the probe in the script is not the same as having passed it. Record the emitted run directory/summary before claiming live reliability.

## 24H acceptance

After the short live gate passes:

```powershell
tool\qwen_live_reliability_24h.bat
```

Acceptance requires the full wall-clock duration and evidence that there is:

- no stuck ownership lock;
- no orphan worker/process after stop/crash/resume;
- no unbounded state/log growth;
- no lost committed workflow/task position;
- no role-session corruption;
- stable frozen Workflow/Prompt resources across resume.

Deterministic CI, a short live gate and a 24H soak are separate confidence layers.

- Workflow Library right-click Chat visibility (Show/Hide) and immediate Chat picker filtering.
- Chat default selection prefers `ralphy_ai_validate.yaml` when no valid saved Workflow preference exists.
- Primary navigation separates Workflows and Prompts; no duplicate Settings nav is exposed.
- Stage Editor contract: `Form | YAML | Routing | Test`, with Stage YAML using the shared source parser.
- Desktop browser layout/context-menu smoke: 1024, 1280, 1366, 1440, and 1920 widths.


## Dedicated browser CI

The CI has a separate Ubuntu Playwright/Chromium job. In that job
`AI_TASK_RUNNER_BROWSER_REQUIRED=1` forces browser tests to execute rather than
skip when no system browser is present.

Browser coverage includes:
- Workflow Settings manager + Prompt CRUD and Workflow visibility/navigation
- common desktop viewport overflow checks (1024/1280/1366/1440/1920)
- Workflow Editor Stage dialogs, YAML view and context menus
- graph CRUD round-trip for START/END, AI Stage profiles, PASS/FAIL/HANDOFF edges,
  edge retarget/delete, Stage delete, save/reload
- selected explicit edge Delete/Backspace
- Workflow draft Ctrl+Z undo
