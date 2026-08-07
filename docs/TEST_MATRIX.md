# AI Task Runner Test Matrix v1.1.1

## Automated Suite

Run:

```bat
python -m pytest -q
```

Coverage includes:

- CLI/API public contract
- Qwen and OpenCode backend command construction
- Qwen `stream-json` final result and error parsing
- stdout/stderr plus file-change activity watchdog
- process-tree cleanup on timeout
- protected validator, state, runner source, and backend rule files
- YAML-configured protected files/folders, including subtree restore
- Git write guard blocks add/commit/push while allowing read-only Git
- review and AI-validator read-only restore
- session invalid and loop-detection session reset
- YAML batch validation and resume
- validator failure repair cycles
- task splitting and re-planning when the planner under-splits
- bounded state output and validator diagnostics
- external exe/CLI validator wrapper log copying and model-facing report paths
- long `--goal-file` input
- documentation contract tests

The public contract tests also lock the short 24h command defaults: backend `qwen`, command `qwen.cmd`, agent timeout `7200`, planning timeout `600`, activity watchdog `900`, validator timeout `1200`, and unlimited attempts/cycles. Qwen runtime argument tests cover the default `--max-tool-calls -1` compatibility value and user override behavior.

## Real Qwen Smoke Cases

| Case | What It Tests | Result |
| --- | --- | --- |
| `smoke/qwen_todo_cli` | Single prompt split into persistent todo CLI tasks; Python validator checks CLI, JSON persistence, Markdown export, README, runner state, and review completion. | 2026-07-27 local Qwen PASS via `ai_task_runner.py`; covered validator repair, protected state restore, no-project-change retry, and resume. |
| `smoke/qwen_expression_evaluator` | Single prompt split into safe evaluator, CLI, batch JSON/Markdown, README; validator forbids `eval`/`exec` and checks task review state. | 2026-07-27 local Qwen PASS via `ai_task_runner.py`; covered loop detection, longer timeout for slow local model, protected state restore, read-only review restore, and final Python validation. |
| `smoke/qwen_csv_analyzer` | Single prompt split into analyzer, JSON report, Markdown report, README; validator checks exact report values and task reviews. | 2026-07-27 local Qwen PASS via `ai_task_runner.py`; completed 3 tasks and final validator in one cycle. |
| `smoke/qwen_markdown_scoring` | Agent writes an MD file; Python validator checks format and score. | Real Qwen PASS. |
| `smoke/qwen_sorting_micro_pipeline` | YAML pipeline for multiple sorting algorithms. | Real Qwen PASS. |
| `smoke/qwen_single_prompt_todo_split` | Single prompt task splitting and TODO-by-TODO review. | Real Qwen PASS. |

## 24h Boundary

Ignoring external failures such as power loss, OOM, or OS crash, the runner can keep retrying recoverable model and validator failures while the Python process is alive. For true 24h unattended operation across process exits, run the same command under a supervisor and add `--resume`.
