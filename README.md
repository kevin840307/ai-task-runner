# AI Task Runner

Version: 1.2.15

A small reusable Python orchestrator for long-running AI coding tasks. It separates model work from deterministic validation, keeps resumable state, isolates the current TODO, and tolerates model/CLI failures without embedding project-specific logic in the Runner.

## Key properties
- Qwen and OpenCode backends; Qwen prompt transport is stdin-only.
- Adaptive Planning: bounded read-only Understand -> same planning client/session Plan Finalize -> same-session Judge/Rewrite as needed; only an unrecoverable planning session falls back to fresh full-context planning.
- Bounded TODO execution keeps one Executor session across TODOs; each next-TODO prompt contains only the new TODO and scope reminder. Review remains a fresh read-only session.
- Deterministic final validator as the hard correctness gate; optional fresh-session Final AI voting can be used alone or after the hard gate.
- Retry/resume, session rebuild, no-progress recovery, protected paths, Git write guard, JSONL events, Python API, YAML script mode with optional per-item `project_root` and `goal_file`.
- Shared model-result parser: lenient JSON envelope, strict stage payload/schema.
- Bounded debug history with current/last prompt-result files.
- Project policy in `<project-root>/.ai-task-runner.yaml`; the policy file protects itself automatically.

## Quick start
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py"
```

Validator-specific arguments are repeatable:
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --validator-arg "--fab" --validator-arg "FAB23"
```
The Runner invokes the validator as `python validation.py --project-root <root> --state-file <state> --fab FAB23`. Do not combine validator arguments into the `--validator` path string.

Mixed hard + AI validation:
```bat
python ai_task_runner.py --goal-file "prompt.md" --project-root "." --validator "validation.py" --ai-validator-prompt-file "ai_validation.md" --ai-validator-count 3
```
The file validator must PASS first; then 3 fresh AI sessions vote independently and strict majority is required by default.

## Documentation map
- [Full documentation index](docs/INDEX.md) / [中文索引](docs/INDEX.zh-TW.md)
- [繁體中文首頁](README.zh-TW.md)
- [Design](docs/design/DESIGN.md) / [設計](docs/design/DESIGN.zh-TW.md)
- [Architecture](docs/design/ARCHITECTURE.md) / [架構](docs/design/ARCHITECTURE.zh-TW.md)
- [User Guide](docs/user/USER_GUIDE.md) / [使用指南](docs/user/USER_GUIDE.zh-TW.md)
- [CLI Reference](docs/user/CLI_REFERENCE.md) / [CLI 參考](docs/user/CLI_REFERENCE.zh-TW.md)
- [Python API Reference](docs/user/API_REFERENCE.md) / [API 中文](docs/user/API_REFERENCE.zh-TW.md)
- [Prompt / Session Contract](docs/design/PROMPT_SESSION.md) / [Prompt / Session 中文](docs/design/PROMPT_SESSION.zh-TW.md)
- [State / Events](docs/design/STATE_EVENTS.md) / [State / Events 中文](docs/design/STATE_EVENTS.zh-TW.md)
- [Protection / Safety](docs/operations/SECURITY_PROTECTION.md) / [保護與安全](docs/operations/SECURITY_PROTECTION.zh-TW.md)
- [Operations](docs/operations/OPERATIONS.md) / [24H 運行與故障排查](docs/operations/OPERATIONS.zh-TW.md)
- [Project / Maintainer Guide](docs/development/PROJECT_GUIDE.md) / [專案 / 維護者指南](docs/development/PROJECT_GUIDE.zh-TW.md)
- [Test Matrix](docs/development/TEST_MATRIX.md) / [測試矩陣](docs/development/TEST_MATRIX.zh-TW.md)
- [Validator templates](docs/validator_templates/README.md) / [Validator 範本](docs/validator_templates/README.zh-TW.md)
- [Examples](examples/README.md) / [範例](examples/README.zh-TW.md)
- [Smoke](smoke/README.md) / [Smoke 測試](smoke/README.zh-TW.md)

## Development contract
See `AGENTS.md` and `QWEN.md`. The core rules are: no project-specific hardcode, one shared implementation for the same behavior, minimum production code, high readability, and no duplicated generic logic.

## Validator feedback and external validators
Validator feedback stored in state is capped at 20,000 characters, preserving both the beginning and end of long logs. Reusable validator templates live in `docs/validator_templates/`. `external_command_validator.py` wraps an exe, bat, jar, or other CLI and can copy external log folders into `.ai-task-runner/validator-reports/external-command/`.

## Agent rule files
- Qwen Code: `QWEN.md`
- OpenCode: `AGENTS.md`

OpenCode's official project rule filename is `AGENTS.md`, not `AGENT.md`.

### Optional Loop context compression
Disabled by default. Enable only for Loop Detection recovery:
`--loop-context-compress --loop-context-compress-threshold 50`
The threshold is a context-usage percentage (0-100). If the backend cannot report current context usage, compression is skipped. Qwen uses its session `/compress-fast` capability; normal retries and transient API errors do not trigger it.

YAML task items may also set `loop_context_compress: true` and `loop_context_compress_threshold: 50`.
