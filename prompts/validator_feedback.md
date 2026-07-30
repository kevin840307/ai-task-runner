Validator feedback below is the final validator's failure report. It describes the current rejected behavior or output, not the desired result.

Treat stdout/stderr as a compact summary for the next repair attempt. Detailed evidence may be stored at any project-readable path printed by the validator. The default convention is `.ai-task-runner/validator-reports/`.

If this feedback mentions `report_dir` or `Full report`, use the exact reported path:
1. Read `summary.txt` first when it exists.
2. Read `errors.txt` next when it exists.
3. Read only the first relevant `Full report` file needed to fix the first blocking error.
4. Do not repeatedly read the same report file.
5. After reading the evidence, make one concrete project change.

Fix blocking errors before warnings. Warnings are useful context but do not imply retry unless the validator exits non-zero.

If the feedback says `unexpected ...` and shows a block, that block is the actual bad value to change away from. If the bad value is in generated output, fix the program behavior that produces it; do not only edit the current generated file.

Fix the first reported blocking failure, then preserve the original goal.
$feedback
