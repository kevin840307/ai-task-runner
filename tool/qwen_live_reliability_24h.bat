@echo off
setlocal
pushd "%~dp0\.."

echo Target confidence: 99.99%% after PASS summary and full 24h wall-clock run.
python "tool\qwen_live_reliability.py" --hours 24 --high-density --require-transient ^
  --example-smoke-matrix-project "examples\01_basic_python_validator\project" ^
  --example-smoke-matrix-project "examples\10_skill_prompt_review_workflow\project" ^
  --example-smoke-matrix-workflow "runner\workflow\builtin\file.yaml" ^
  --example-smoke-matrix-workflow "runner\workflow\builtin\mixed.yaml" ^
  --example-smoke-matrix-workflow "tool\workflows\skill_prompt_review_chain.yaml"

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
