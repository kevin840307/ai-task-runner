Repair the existing range_summary.py CLI without replacing the project with a different tool.

Usage:
  python range_summary.py <integer> [<integer> ...]

It must print exactly one JSON object containing:
- count: number of values
- min: minimum value
- max: maximum value
- sum: arithmetic sum
- average: arithmetic mean as a JSON number

Requirements:
- Support negative, zero, and positive integers.
- Support one value and repeated values.
- Invalid input must return non-zero.
- Keep the solution small and use only the standard library.
- Fix root causes rather than special-casing validator examples.
