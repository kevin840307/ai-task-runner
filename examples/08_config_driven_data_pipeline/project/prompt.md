Build a generic config-driven multi-format data pipeline CLI.

Required command:
python pipeline_cli.py --input <input_dir> --config <config.yaml> --output <output_dir>

The program recursively scans the input directory and processes JSON, YAML/YML, and CSV files.

Behavior is controlled by config.yaml. Do not hardcode sample field names, field values, group names, target names, or test data.

Config supports:
- field_map: input field name -> normalized output field name
- required_fields: normalized fields that every valid record must contain with a non-empty value
- allowed_values: normalized field -> list of allowed values
- dedupe_key: normalized field used as record identity
- timestamp_field: normalized field used to select the newest duplicate
- group_by: normalized field used for summary grouping
- output_fields: normalized fields written to records.json

Input rules:
- Scan recursively.
- .json may contain one object or a list of objects.
- .yaml/.yml may contain one object or a list of objects.
- .csv contains one record per row.
- Unsupported files are ignored.
- A malformed supported file must not stop processing other files.
- Invalid records must not stop processing valid records from the same or other files.

Record processing:
1. Apply field_map to input keys. Keys not present in field_map keep their original name.
2. Validate required_fields.
3. Validate allowed_values when configured.
4. Valid records participate in deduplication.
5. Duplicate records use dedupe_key. Keep the record with the newest timestamp_field value.
6. Sort final records deterministically by the string value of dedupe_key.
7. records.json contains only output_fields, in the configured field order.
8. summary grouping uses group_by from the final deduplicated records.

Create the output directory if needed and write exactly:
- records.json
- summary.json
- errors.json

summary.json must contain:
{
  "total_files": <all discovered files>,
  "parsed_files": <supported files parsed successfully>,
  "invalid_files": <supported files that could not be parsed>,
  "ignored_files": <unsupported discovered files>,
  "input_records": <records read from successfully parsed supported files>,
  "valid_records_before_dedupe": <records that passed validation>,
  "output_records": <records after dedupe>,
  "invalid_records": <records rejected by validation>,
  "duplicate_records_removed": <valid records removed by dedupe>,
  "by_group": {<group value>: <final record count>}
}

errors.json is a list. Each entry must contain:
- file: path relative to --input, using forward slashes
- type: "file" or "record"
- message: short human-readable reason

For record errors also include:
- index: zero-based record index inside that file

Output requirements:
- UTF-8 JSON.
- Deterministic output across repeated runs.
- JSON arrays/objects must be valid JSON.
- Do not write temporary or extra files into the output directory.

Implementation is intentionally unrestricted. One file or multiple files, functions or classes are all acceptable. Only externally observable behavior and genericity matter.
