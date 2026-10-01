# Test Matrix

This file describes what is covered by deterministic CI and what still requires a real backend or soak run.

## Deterministic CI

The normal GitHub gate runs compile + pytest on Ubuntu and Windows plus the React Studio build. It also rebuilds Full Designer and verifies the committed `ui/static/workflow-studio-app` exactly matches `ui/studio-src`; CI is verify-only and never rewrites the branch.

| Area | Coverage |
| --- | --- |
| Workflow schema | supported Stage types/options, unknown option rejection, PASS/FAIL-only routes, target existence, task-scope topology |
| Semantic routing | PASS next, explicit PASS/FAIL, done/stop, backward loop, unrouted FAIL safe stop |
| Technical ERROR | Stage/global retry limits, unlimited `-1`, Same Session retry, Fresh Session rotation, partial-write recovery, Review finite-retry fail-soft Skip, non-Review fail-closed exhaustion, KeyboardInterrupt/SystemExit propagation |
| Session policy | main/role/fresh acceptance, invalid mode, role durable restore/persist, fresh non-persistence, per-role reset, global reset, recovery rotation |
| Dynamic Handoff | target allow-list, disallowed target rejection, exactly-one target routing, role -> coordinator loop, final validator FAIL -> coordinator, durable resume |
| Prompts | shared Dynamic worker renders role `instructions`; prompt ownership/category references; shared retry/continue/recover control envelope |
| Validators | File command validators, AI validators, multiple validators anywhere, repeated AI runs/voting, validator FAIL rollback |
| Task production | Plan Task[], custom command/Python `produces: tasks`, contiguous task scope |
| Resume/state | workflow position, task step, transition_previous, role Sessions, corrupt/incompatible state rejection |
| Dry Run | normal closure, fail loops, Dynamic Handoff, custom Task producer, non-converging loop cutoff, invalid schema/route controls |
| Stage Probe | isolated Real Stage execution with real backend, fixed-prompt Agent Ping, bounded test retry safety, result/next target without continuing the workflow |
| Studio backend | YAML graph save/validation, stage add/delete, asset roots, prompt references, Stage test sandbox |
| Studio React | PASS/FAIL/Handoff handles, searchable palette, safe duplicate, Review max_failures UI, Dynamic branch layout, session-policy UI normalization, no ERROR edge/Discussion runtime |
| Process/runtime | ownership/orphan/supervisor/control-file probes, repeated same-checkpoint crash restart, capped process backoff |

## Negative/removed-contract coverage

Tests must reject or prove absence of:

- `routes.error`;
- repair/recover/restart_at/repeat/max_attempts/on_exhausted graph controls;
- removed Discussion runtime Stage types/state;
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
- custom Stage / custom Task producer;
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
