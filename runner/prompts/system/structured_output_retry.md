The previous output did not match the required structured contract.
Do not redo the task or re-analyze the project. Preserve the previous semantic decision and repair only the output structure unless parser feedback proves that the original result cannot be mapped to the contract.
Return exactly one complete valid JSON object matching the original contract.
For PASS/FAIL verdict contracts: if there is no concrete unsatisfied or blocking item, return PASS (`completed=true` or `passed=true`) with `missing_items: []`. Never invent placeholder `missing_items` merely to satisfy the schema. If returning FAIL, every missing item must describe a concrete unsatisfied requirement.
Parser feedback: {{ error }}
