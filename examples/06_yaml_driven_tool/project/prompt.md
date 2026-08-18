Build release_plan.py, a YAML-driven release planning CLI.

Usage:
  python release_plan.py --input <yaml-file> --output <json-file>

Input schema:
services:
  - name: string
    version: string
    enabled: boolean (optional, default true)
    wave: integer (optional, default 0)

Output is a JSON array containing only enabled services. Each item has name, version, and wave. Sort by wave ascending, then name ascending.
Requirements:
- Accept arbitrary service names, versions, and waves.
- Missing services means an empty output array.
- Invalid item shapes/types return non-zero.
- Create output parent directories.
- Use PyYAML already provided by this project and the Python standard library.
- Keep logic data-driven and compact.
