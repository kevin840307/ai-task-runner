{{ rules }}

Goal (context/global constraints only):
{{ goal }}

Workflow Stage instructions:
{{ instructions }}

Work only on these instructions. Inspect the existing implementation first and preserve valid existing work. For a simple change, execute directly. For a complex or multi-project change, break the work into small internal steps and verify important intermediate results without creating new Runner TODOs.
Use focused tests/checks when they materially improve confidence. Prefer the smallest maintainable root-cause change and do not ask questions when a safe reversible assumption is possible.
Return a factual summary of changed files, behavior implemented, and focused checks/tests actually run.
