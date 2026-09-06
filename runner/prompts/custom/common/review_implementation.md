Review only the implementation from the previous stage.

{{ rules }}

Use this original goal as the review target:
{{ goal }}

Return exactly one JSON object:

```json
{"completed": true, "reason": "short reason", "missing_items": []}
```

Set `completed` to false when the implementation does not satisfy the goal,
misses tests or verification evidence, or includes unrelated edits. Put
actionable missing items in `missing_items`.
