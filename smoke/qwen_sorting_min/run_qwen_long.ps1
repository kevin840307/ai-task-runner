$ErrorActionPreference = "Stop"

$repo = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$root = Join-Path $PSScriptRoot "project"
$prompt = Get-Content -Raw (Join-Path $PSScriptRoot "prompt.txt")
$work = Join-Path $root ".ai-task-runner"
New-Item -ItemType Directory -Force $work | Out-Null

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$stdout = Join-Path $work "qwen_stdout_$stamp.json"
$stderr = Join-Path $work "qwen_stderr_$stamp.txt"

$process = Start-Process `
  -FilePath "qwen.cmd" `
  -ArgumentList @(
    "--approval-mode", "yolo",
    "--output-format", "json",
    "--max-tool-calls", "2",
    "-p", $prompt
  ) `
  -WorkingDirectory $root `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -WindowStyle Hidden `
  -PassThru

if (-not $process.WaitForExit(480000)) {
  taskkill /PID $process.Id /T /F | Out-Null
  Write-Output "QWEN_TIMEOUT pid=$($process.Id)"
  exit 124
}

Write-Output "QWEN_EXIT=$($process.ExitCode)"
if (Test-Path $stdout) {
  Get-Content -Raw $stdout
}
if (Test-Path $stderr) {
  Get-Content -Raw $stderr
}
exit $process.ExitCode
