Review only. Finalize the current review now.

Stop inspecting the project and do not use any more tools. Use only the task and evidence already gathered in this review session. Do not redo implementation, broaden scope, or require later TODOs or whole-project completion.

Return the best supported decision now. PASS only when the current TODO acceptance criteria are satisfied. FAIL only for a concrete missing or incorrect result in the current TODO.
If the decision uses validator feedback with expected/actual values, stdout/stored output, or command results, preserve the reported direction exactly. Do not infer a different expected shape or reverse expected and actual.

Return exactly one JSON object with no Markdown or commentary.

FAIL:
{"completed":false,"reason":"One or more acceptance criteria are not satisfied.","missing_items":["Describe the specific missing or incorrect result."]}

PASS:
{"completed":true,"reason":"All acceptance criteria are satisfied.","missing_items":[]}
