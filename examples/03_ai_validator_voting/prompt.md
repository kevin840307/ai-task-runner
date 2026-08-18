Create a small Python command-line configuration lookup tool named config_lookup.py.

Usage:
  python config_lookup.py --config <json-file> --key <dot.path>

Behavior:
- Load any JSON object supplied at runtime.
- Resolve nested keys such as database.host or services.api.url.
- Print scalar values as text and objects/lists as JSON.
- Missing keys or invalid JSON must return non-zero with a useful message.
- Do not embed sample environment, service, host, or key names in the implementation.
- Use only the standard library.
- Prefer a direct, maintainable implementation over unnecessary abstractions.
