Build a small standard-library CLI that demonstrates a prompt-driven custom workflow.

Required files:
- `blueprint.md`
- `skill_runner.py`
- `README.md`
- `README.zh-TW.md`

Do not create other project files or folders. Runner-owned diagnostics such as
`.ai-task-runner/`, `__pycache__/`, and `QWEN.md` may exist and should be
preserved.

`requests.txt` and `report.json` in the CLI command below are runtime input/output
examples only. They are not project deliverables and must not remain in the
project root. If you create them for manual verification, remove them before the
stage finishes.

`skill_runner.py` must:
- expose a command line interface: `python skill_runner.py --input requests.txt --output report.json`
- read UTF-8 text from the input file
- ignore blank lines
- treat each nonblank line as `/skill-name request text`
- reject malformed lines with a non-zero exit code and a useful stderr message
- write UTF-8 JSON to the output file
- create the output parent directory when it does not exist
- use only the Python standard library

The output JSON must have this shape:

```json
{
  "items": [
    {"skill": "skill-name", "request": "request text", "words": 2}
  ],
  "summary": {
    "count": 1,
    "skills": ["skill-name"]
  }
}
```

The `skills` list must be unique and sorted alphabetically.

Both README files must document the CLI usage and include at least one
`/skill-...` input example.
