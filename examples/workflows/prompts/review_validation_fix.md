Review only the validation fix from the previous stage.

{{ rules }}

Use this validator feedback as the review target:
{{ previous.output }}

Return exactly one JSON object:

```json
{"completed": true, "reason": "short reason", "missing_items": []}
```

Set `completed` to false when the fix ignores validator feedback, removes valid
deliverables, or introduces unrelated edits. Put actionable missing items in
`missing_items`.
