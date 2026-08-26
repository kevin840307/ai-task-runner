Review only the documentation changes from the previous stage.

{{ rules }}

Use this original goal as the review target:
{{ goal }}

Return exactly one JSON object:

```json
{"completed": true, "reason": "short reason", "missing_items": []}
```

Set `completed` to false when the docs do not match current behavior or the
bilingual pair is not aligned where applicable. Put actionable missing items in
`missing_items`.
