Review the completed project as a final semantic quality gate.

PASS only if all of the following are true:
- The implementation is genuinely config-driven.
- It does not hardcode sample field names, sample values, departments, statuses, product names, target names, or validator fixture data.
- The same implementation can reasonably handle different schemas through field_map, required_fields, allowed_values, dedupe_key, timestamp_field, group_by, and output_fields.
- The code does not contain obvious test-specific branches or behavior added only to satisfy known fixture values.
- The implementation is reasonably small and maintainable for this task.
- It does not introduce unnecessary frameworks, abstractions, or unrelated features.
- Error handling is general rather than special-cased to the supplied examples.

Do not require a specific architecture, file count, class design, function names, or coding style.
Judge the final project state only.
Return concrete missing_items when failing.
