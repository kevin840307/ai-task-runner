Build a practical multi-environment configuration auditor CLI.

Required command:
python config_auditor.py --input <root_dir> --baseline <env_name> --output <output_dir>

Directory layout:
<input>/<ENV>/...
Environment names are runtime data and must never be hardcoded.

Supported config formats:
- YAML / YML
- JSON
- INI / CFG
- XML

The tool recursively scans every environment directory and compares normalized configuration entries against the selected baseline environment.

Normalization rules:
- Each config value becomes one flattened key/value entry.
- Flatten nested objects using "." separators.
- Flatten arrays using numeric indexes, e.g. servers.0.host.
- INI/CFG keys use section.key; top-level keys use key.
- XML element paths use element names.
- Repeated XML sibling elements use an index after the repeated element name, e.g. root.server.0.host.
- XML attributes use @attribute, e.g. root.server.0.@id.
- All output file paths use forward slashes.
- The environment-relative file path is part of the logical key:
  <relative-file>::<flattened-key>

Comparison rules for each non-baseline environment:
- missing: key exists in baseline but not target
- extra: key exists in target but not baseline
- changed: both exist, same normalized value type, different value
- type_mismatch: both exist but normalized value types differ
- equal: both exist, same type and same value
- malformed supported files must not stop auditing other files
- unsupported files are ignored

Normalized value types:
- null
- bool
- number
- string

Numeric-looking strings remain strings.
Boolean-looking strings remain strings.

Create exactly:
- report.json
- summary.yaml
- errors.json

report.json:
{
  "baseline": "<baseline>",
  "environments": {
    "<ENV>": {
      "missing": [{"key": "...", "baseline_value": <value>}],
      "extra": [{"key": "...", "target_value": <value>}],
      "changed": [{"key": "...", "baseline_value": <value>, "target_value": <value>}],
      "type_mismatch": [{
        "key": "...",
        "baseline_type": "<type>",
        "target_type": "<type>",
        "baseline_value": <value>,
        "target_value": <value>
      }]
    }
  }
}

Rules for report.json:
- Do not include equal entries.
- Sort environment names lexicographically.
- Sort each category list by key.

summary.yaml:
baseline: <baseline>
environment_count: <count including baseline>
environments:
  <ENV>:
    missing: <count>
    extra: <count>
    changed: <count>
    type_mismatch: <count>
files:
  discovered: <all files under all environment directories>
  parsed: <supported files parsed successfully>
  malformed: <supported files that failed parsing>
  ignored: <unsupported files>

errors.json:
[
  {
    "environment": "<ENV>",
    "file": "<path relative to that environment>",
    "type": "file",
    "message": "<human-readable parse error>"
  }
]

Sort errors.json by environment then file.

Additional requirements:
- The baseline directory must exist; otherwise exit non-zero with a useful message.
- Discover all other environment directories dynamically.
- Create output directory if necessary.
- Output UTF-8.
- Re-running identical input must produce byte-for-byte identical output.
- Write no temporary or extra files into output.
- Do not hardcode environment names, file names, keys, URLs, hosts, sections, or fixture values.
- Implementation is unrestricted: one file or many files, functions or classes. Only externally observable behavior and genericity matter.
