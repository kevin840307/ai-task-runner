# AI Task Runner

Version: 1.1.1

A small reusable Python orchestrator for long-running AI coding tasks. It separates model work from deterministic validation, keeps resumable state, isolates the current TODO, and tolerates model/CLI failures without embedding project-specific logic in the Runner.

## Key properties
- Qwen and OpenCode backends; Qwen prompt transport is stdin-only.
- Adaptive Planning: bounded read-only Understand -> same-session no-tool Plan -> fresh minimal fallback when needed.
- Bounded TODO execution with current-task-only scope and read-only Review.
- Deterministic final validator as the hard correctness gate; optional independent Final AI validations.
- Retry/resume, session rebuild, no-progress recovery, protected paths, Git write guard, JSONL events, Python API, YAML script mode.
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

## Documentation map
- [Full documentation index](docs/INDEX.md) / [中文索引](docs/INDEX.zh-TW.md)
- [繁體中文首頁](README.zh-TW.md)
- [Design](docs/DESIGN.md) / [設計](docs/DESIGN.zh-TW.md)
- [Architecture](docs/ARCHITECTURE.md) / [架構](docs/ARCHITECTURE.zh-TW.md)
- [User Guide](docs/USER_GUIDE.md) / [使用指南](docs/USER_GUIDE.zh-TW.md)
- [CLI Reference](docs/CLI_REFERENCE.md) / [CLI 參考](docs/CLI_REFERENCE.zh-TW.md)
- [Python API Reference](docs/API_REFERENCE.md) / [API 中文](docs/API_REFERENCE.zh-TW.md)
- [Prompt / Session Contract](docs/PROMPT_SESSION.md) / [Prompt / Session 中文](docs/PROMPT_SESSION.zh-TW.md)
- [State / Events](docs/STATE_EVENTS.md) / [State / Events 中文](docs/STATE_EVENTS.zh-TW.md)
- [Protection / Safety](docs/SECURITY_PROTECTION.md) / [保護與安全](docs/SECURITY_PROTECTION.zh-TW.md)
- [Operations](docs/OPERATIONS.md) / [24H 運行與故障排查](docs/OPERATIONS.zh-TW.md)
- [Project / Maintainer Guide](docs/PROJECT_GUIDE.md) / [專案 / 維護者指南](docs/PROJECT_GUIDE.zh-TW.md)
- [Test Matrix](docs/TEST_MATRIX.md) / [測試矩陣](docs/TEST_MATRIX.zh-TW.md)
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
