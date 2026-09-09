# 09 Config Environment Auditor — Clean Rerun

Practical mixed-validation example.

Hard validator is black-box only and validates:
- YAML/YML, JSON, INI/CFG, XML
- nested objects and arrays
- repeated XML siblings using element-name indexes
- XML attributes
- missing / extra / changed / type mismatch
- dynamic environment names
- malformed-file isolation
- unsupported-file accounting
- exact file counters
- missing baseline behavior
- deterministic byte-for-byte reruns

Verified fixture totals in mixed-formats case:
- discovered = 12
- parsed = 9
- malformed = 1
- ignored = 2

AI validation:
- 3 fresh independent validators
- majority vote
- genericity / hardcode / fixture-shortcut / over-design checks

This package intentionally contains no implementation, runner state, debug scripts, or prior AI artifacts.

Run:
    run_example.bat --backend qwen

`run_example.bat` runs this example from a fresh temporary repository copy; the source example is never modified.
