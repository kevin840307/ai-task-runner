$goal = Get-Content -Raw "examples/01_config_template_roundtrip/prompt.txt"
python ai_task_runner.py `
  --backend qwen `
  --command qwen.cmd `
  --project-root "examples/01_config_template_roundtrip/project" `
  --goal $goal `
  --validator "examples/01_config_template_roundtrip/validator.py" `
  --force-new
