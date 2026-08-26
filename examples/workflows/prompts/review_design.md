Review only the design output from the previous stage.

{{ rules }}

Use this original goal as the review target:
{{ goal }}

Return exactly one JSON object:

```json
{"completed": true, "reason": "short reason", "missing_items": []}
```

Set `completed` to false when the design is not scoped, testable, or aligned with
the goal. Put actionable missing items in `missing_items`.
