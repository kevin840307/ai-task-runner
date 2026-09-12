@echo off
setlocal
pushd "%~dp0\.."
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"

echo Full 24h soak gate. PASS provides very high engineering confidence; it is not a mathematical reliability percentage.
python "tool\qwen_live_reliability.py" --hours 24 --high-density --require-transient --single-process-yaml-items 8 ^
  --example-smoke-matrix-project "examples\01_basic_command_validator\project" ^
  --example-smoke-matrix-project "examples\10_skill_prompt_review_workflow\project" ^
  --example-smoke-matrix-workflow "runner\workflow\system\file.yaml" ^
  --example-smoke-matrix-workflow "runner\workflow\system\mixed.yaml" ^
  --example-smoke-matrix-workflow "runner\workflow\custom\common\ralphy_ai_validate.yaml"

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
