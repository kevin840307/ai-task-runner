Improve the existing route_config.py CLI while preserving its simple interface.

Usage:
  python route_config.py --config <json-file> --env <name> --service <name>

The JSON file contains an environments object. Each environment contains arbitrary service names mapped to URLs.
The CLI must print the selected URL or return non-zero when the environment/service is absent.
The implementation must be data-driven: new environment and service names added only to the JSON must work without code changes.
Keep the implementation small; do not add a framework or encode known sample names in branches/mappings.
