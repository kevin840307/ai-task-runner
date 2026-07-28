# Validator Templates

These files are copy-and-edit templates for Python validators.

The runner contract stays intentionally small:

- exit code `0` means validation passed
- any non-zero exit code means validation failed and should be retried
- stdout/stderr become feedback for the next agent attempt
- validators must accept `--project-root` and `--state-file`

Recommended validator behavior:

- print a short stdout summary for the agent:
  `VALIDATION_*`, error count, warning count, `report_dir`, and the first few actionable findings
- write full error, warning, diff, score, and command output reports under `.ai-task-runner/validator-reports/`
- write standard files such as `summary.txt`, `errors.txt`, and `warnings.txt`
- include `Full report:` paths in stdout when a finding has a specific detailed file
- fail only for issues that block completion
- keep warnings as exit code `0` unless the project decides they are required

The runner clears `.ai-task-runner/validator-reports/` before each Python validator run. Do not store long-term history there; write only the current validation attempt's detailed evidence.

## Templates

| File | Purpose |
| --- | --- |
| `validator_interface.py` | Copyable helper that handles summary stdout, errors, warnings, standard report files, `Full report` paths, and exit code. |
| `basic_validator.py` | Minimal skeleton using `validator_interface.py`. Start here for custom checks. |
| `command_and_files_validator.py` | Starter using `validator_interface.py` for projects that must run a command and then verify generated files. |
| `folder_compare_validator.py` | Standalone ready-to-use comparison for two folders. It checks subfolder names plus `.yml`, `.yaml`, `.cfg`, and `.xml` file names and content. It also emits a warning-only config value sharing score. |

## Interface Example

Copy `validator_interface.py` next to your `validator.py`, then write only project-specific checks:

```python
from pathlib import Path
import argparse
import sys

from validator_interface import ValidatorReport


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    result = ValidatorReport(root, "my-validator")

    output = root / "output.txt"
    if not output.exists():
        result.error(
            "E001",
            "Missing output.txt",
            fix="Create output.txt from the implementation.",
        )

    result.warning(
        "W001",
        "Example warning",
        ["Warnings are visible to the model but do not cause retry."],
    )

    return result.finish()


if __name__ == "__main__":
    sys.exit(main())
```

`result.finish()` writes `summary.txt`, `errors.txt`, and `warnings.txt`, prints a compact stdout summary, and returns `1` when errors exist.

## Folder Compare Example

```bat
python docs\validator_templates\folder_compare_validator.py ^
  --project-root C:\work\project ^
  --state-file C:\work\project\.ai-task-runner\state.json ^
  --expected-dir ans ^
  --actual-dir output
```

If hundreds of files differ, stdout stays short and points to:

```text
.ai-task-runner/validator-reports/folder-compare/
```

The folder comparison fails on structural or content mismatches. The config value score is only a warning/reference:

```text
W101 Config value sharing score: 76/100
```

The score scans `--config-dir config` by default and looks for repeated scalar values across `.yml`, `.yaml`, `.cfg`, and `.xml` files. A lower score suggests values may be too distributed and could be moved to shared config. Repeated values can still be valid, so this warning does not change the exit code.

Useful options:

```bat
--config-dir config
--config-min-value-length 4
--no-config-score
```
