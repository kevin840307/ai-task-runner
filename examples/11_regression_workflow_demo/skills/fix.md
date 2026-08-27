Fix only the issues reported by the immediately preceding failed gate. Preserve valid existing work and avoid unrelated changes.
Previous gate: {{ previous.stage }}
Feedback: {{ previous.data | tojson }}
Inspect current files when needed; do not repeat already-correct context or redo the whole stage.
