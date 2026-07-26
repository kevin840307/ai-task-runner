$ErrorActionPreference = "Stop"

$prompt = Get-Content -Raw "smoke/qwen_sorting/prompt.txt"
$timeoutSeconds = 180

Push-Location "smoke/qwen_sorting/project"
try {
  New-Item -ItemType Directory -Force ".ai-task-runner" | Out-Null
  $stdout = Join-Path (Resolve-Path ".ai-task-runner").Path "qwen_sorting_stdout.json"
  $stderr = Join-Path (Resolve-Path ".ai-task-runner").Path "qwen_sorting_stderr.txt"
  Remove-Item -LiteralPath $stdout, $stderr -Force -ErrorAction SilentlyContinue

  $process = Start-Process `
    -FilePath "qwen.cmd" `
    -ArgumentList @(
      "--approval-mode", "yolo",
      "--output-format", "json",
      "--max-tool-calls", "3",
      "-p", $prompt
    ) `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -WindowStyle Hidden `
    -PassThru

  if (-not $process.WaitForExit($timeoutSeconds * 1000)) {
    taskkill /PID $process.Id /T /F | Out-Null
    throw "qwen timed out after $timeoutSeconds seconds"
  }

  if (Test-Path $stdout) { Get-Content -Raw $stdout }
  if (Test-Path $stderr) { Get-Content -Raw $stderr }
  if ($process.ExitCode -ne 0) {
    throw "qwen exited with code $($process.ExitCode)"
  }
}
finally {
  Pop-Location
}

python smoke/qwen_sorting/validator.py `
  --project-root "smoke/qwen_sorting/project" `
  --state-file "smoke/qwen_sorting/project/.ai-task-runner/state.json"
