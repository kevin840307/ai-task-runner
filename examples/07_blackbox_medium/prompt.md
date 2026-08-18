Build a medium-size black-box CLI named inventory_cli.py. The validator will judge only observable input/output behavior and will not care how you structure the code.

Usage:
  python inventory_cli.py scan --input <folder> --output <folder>

Recursively scan .json, .yaml/.yml, and .csv files (case-insensitive extensions). Ignore other files.
Each supported file represents records:
- JSON: either a list of objects, or {"records": [objects]}.
- YAML: same shapes as JSON.
- CSV: header row plus records; values are strings.

Normalize every record to an object and add two fields:
- _source: relative POSIX path from the input folder
- _index: zero-based record index inside that source file

Write two UTF-8 JSON files:
1. records.json: all normalized records sorted by _source then _index.
2. summary.json with keys files, records, by_format, errors.
   - files: count of successfully parsed supported files
   - records: total normalized record count
   - by_format: counts of successfully parsed files using keys json, yaml, csv; omit zero-count keys
   - errors: sorted list of relative paths that could not be parsed or had an invalid top-level/record shape

Rules:
- A bad supported file is reported in errors and does not abort the whole scan.
- Unsupported files are ignored and not counted.
- Empty input directory is valid and produces empty outputs.
- Create the output directory.
- Results must be deterministic across runs.
- Do not modify input files.
- PyYAML is available.

Implementation is intentionally unrestricted: one file or multiple files, functions or classes are all acceptable. Only behavior matters.
