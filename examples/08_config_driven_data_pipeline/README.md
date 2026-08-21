# 08 Config-Driven Data Pipeline

A medium-complexity mixed-validation example for AI Task Runner.

Validation flow:

1. Python hard validator runs black-box behavioral tests only.
2. If the hard validator passes, three fresh AI validator sessions run.
3. Strict majority vote is required for AI validation to pass.
4. Both hard validation and AI validation must pass.

Run on Windows:

    run_example.bat --backend qwen

Or add this task to the main examples YAML.

The Python validator does not inspect source architecture, file count, classes, functions, or line count.

YAML script files use a root-level list, matching AI Task Runner examples/examples.yaml.
