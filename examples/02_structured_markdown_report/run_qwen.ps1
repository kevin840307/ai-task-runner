$goal = Get-Content -Raw "examples/02_structured_markdown_report/prompt.txt"
python ai_task_runner.py `
  --backend qwen `
  --command qwen.cmd `
  --project-root "examples/02_structured_markdown_report/project" `
  --goal $goal `
  --validator "examples/02_structured_markdown_report/validator.py" `
  --force-new
