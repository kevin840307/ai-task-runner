@echo off
setlocal
pushd "%~dp0\.."

echo Target confidence: 99.99%% after PASS summary and full 24h wall-clock run.
python "tool\qwen_live_reliability.py" --hours 24 --high-density --require-transient ^
  --example-smoke-matrix-project "examples\01_basic_command_validator\project" ^
  --example-smoke-matrix-project "examples\10_skill_prompt_review_workflow\project" ^
  --example-smoke-matrix-workflow "runner\workflow\system\file.yaml" ^
  --example-smoke-matrix-workflow "runner\workflow\system\mixed.yaml" ^
  --example-smoke-matrix-workflow "runner\workflow\custom\skill_prompt_review_chain.yaml"

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
