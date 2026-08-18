Build a small Python CLI named text_stats.py.

Usage:
  python text_stats.py --input <text-file> --output <json-file>

Requirements:
- Read UTF-8 text.
- Write UTF-8 JSON with keys: lines, words, characters, non_empty_lines.
- lines is the number of logical lines (splitlines semantics).
- words are whitespace-separated tokens.
- characters is len(text), including newlines.
- non_empty_lines counts lines whose stripped content is not empty.
- Create the output parent directory when needed.
- Return non-zero with a useful message when the input file is missing.
- Use only the Python standard library.
- Keep the implementation simple and avoid sample-specific values.
