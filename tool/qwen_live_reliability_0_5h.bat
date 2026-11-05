@echo off
setlocal
pushd "%~dp0\.."
set "PYTHONPATH=%~dp0..;%PYTHONPATH%"

echo Short confidence gate. PASS increases engineering confidence; it is not a mathematical reliability percentage.
echo Includes repeated multi-Project + concurrent Task + worktree + merge + conflict recovery stress.
python "tool\qwen_live_reliability.py" --hours 0.5 --high-density --require-transient --single-process-yaml-items 4 ^
  --soak-multi-project-every 1 --multi-project-count 2 ^
  --example-smoke-matrix-project "examples\01_basic_command_validator\project" ^
  --example-smoke-matrix-project "examples\10_skill_prompt_review_workflow\project" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\file.yaml" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\mixed.yaml" ^
  --example-smoke-matrix-workflow "runner\assets\workflows\ralphy_ai_validate.yaml" %*

set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
