$goal = Get-Content -Raw "examples/04_ai_validator_bugfix/prompt.txt"
$validation = Get-Content -Raw "examples/04_ai_validator_bugfix/validator_prompt.txt"
python ai_task_runner.py `
  --backend opencode `
  --command opencode.exe `
  --project-root "examples/04_ai_validator_bugfix/project" `
  --goal $goal `
  --validator ai `
  --validator-prompt $validation `
  --force-new
