$goal = Get-Content -Raw "examples/03_csv_summary_cli/prompt.txt"
python ai_task_runner.py `
  --backend qwen `
  --command qwen.cmd `
  --project-root "examples/03_csv_summary_cli/project" `
  --goal $goal `
  --validator "examples/03_csv_summary_cli/validator.py" `
  --force-new
