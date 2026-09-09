Regression DSL Generation.
Create `regression/cases.yaml` from the current E2E specification.
Keep the schema simple: each case needs `name`, `operation`, `a`, `b`, and either `expected` or `error`.
Represent only behavior supported by the current sample project.
