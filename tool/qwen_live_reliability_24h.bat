@echo off
setlocal
pushd "%~dp0\.."
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"

echo Full 24h soak gate. PASS provides very high engineering confidence; it is not a mathematical reliability percentage.
echo The 24h workload continuously crosses real Qwen Runner + multi-Project + concurrent Task + worktree + FIFO merge + conflict recovery.
python "tool\qwen_live_reliability.py" --hours 24 --high-density --require-transient --single-process-yaml-items 8 ^
  --soak-multi-project-every 2 --multi-project-count 2 ^
  --example-smoke-matrix-project "examples\01_basic_command_validator\project" ^
  --example-smoke-matrix-project "examples\10_skill_prompt_review_workflow\project" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\file.yaml" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\mixed.yaml" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\ralphy_ai_validate.yaml" %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
