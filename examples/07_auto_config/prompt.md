# Auto Config Renderer

Build a generic Jinja2-based config renderer for this project.

Current sample target. These names are examples only. They must not be hardcoded
in `rander.py`, templates, or config schema. The renderer must work for any
workflow/target/env values that follow the same config and ans layout:

- workflow: `WORKFLOW-A`
- target: `FAB29-FZ1`
- env: `PROD`
- expected output root: `output/WORKFLOW-A/FAB29-FZ1/PROD`
- expected answer root: `ans/WORKFLOW-A/FAB29-FZ1/PROD`

## Required CLI

`rander.py` must support this generic interface:

```bat
python rander.py --workflow WORKFLOW-A --fab FAB29-FZ1 --env PROD --output output
```

The command above is only an example. `--workflow`, `--fab`, and `--env` values
must be treated as runtime inputs. The `--fab` argument means "target id" for
this project, not necessarily a real FAB name. Do not hardcode FAB or app naming
assumptions; derive the target family from the target id only when a phase layer
is needed.

## Renderer Responsibility

`rander.py` may only:

- load YAML config
- deep merge config values
- render Jinja2 templates
- create folders and files
- write rendered output files

`rander.py` must not contain app-specific, FAB-specific, env-specific, YAML-output-specific, XML-output-specific, or answer-file business logic. Output paths and template choices must come from config values.

If the sample names are moved to different workflow/target/env names, or if app
names are replaced, the renderer should still work as long as the config values
and templates define those names. Adding or removing apps should be config-driven,
not renderer-code-driven.

## Merge Order

Use this order. Later files override earlier files:

1. `config/values.yaml`
2. `config/{workflow}/values.yaml`
3. `config/phase/{target_family}.yaml` or `config/phases/{target_family}.yaml`, where `target_family` is the part before `-`, for example `FAB29`
4. `config/{workflow}/{target}/values.yaml`
5. env override from `config/{workflow}/{env}.yaml` or `config/{workflow}/{target}/{env}.yaml`

If a file is missing, skip it. Do not fail only because an optional layer is absent.

## Config Design Goal

Move common values into shared config so future changes are localized:

- adding a target/phase should usually require changing only the target/phase config
- adding/removing a render target should be driven by one render matrix
- shared apps, versions, profiles, template mapping, defaults, and output patterns should not be duplicated across many files
- individual resources and environment overrides may remain in their specific layer

Use simple, maintainable YAML. Do not duplicate the same app/version/profile lists across multiple files.

## Templates

Use Python Jinja2 templates under `Template/`.

Templates should include dynamic placeholders such as `{{ value }}`. Do not put final answer files directly in `Template/` without placeholders.

## Expected Result

For every sample root under this layout:

```text
ans/<workflow>/<target>/<env>
```

running:

```bat
python rander.py --workflow <workflow> --fab <target> --env <env> --output output
```

must create `output/<workflow>/<target>/<env>` with the same file tree and
contents as the matching `ans/<workflow>/<target>/<env>`.

Keep the implementation small and easy to maintain. Do not ask questions; inspect the existing files and make reasonable assumptions.
