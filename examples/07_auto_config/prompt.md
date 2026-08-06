Build a generic Jinja2 config renderer for this project.

Create or update rander.py to:

* load YAML
* merge values
* read one central render matrix
* render Jinja2 templates
* create directories
* write output files

Example:
python rander.py --workflow WORKFLOW-A --fab FAB29-FZ1 --env PROD --output output

All arguments are runtime values and must not be hardcoded.

Treat --fab as a generic target id.
target_family is the text before its first hyphen.

Keep rander.py generic, format-agnostic, under 500 lines, and independent of other local Python files.

Do not add app, workflow, target, env, version, profile, template, filename, format, sample, or ans-specific Python logic.

All render targets, templates, filenames, output paths, combinations, and extra context must come from YAML.

Adding or removing render targets must not require changing rander.py.

Load config in this order:
config/values.yaml
config/{workflow}/values.yaml
config/phase/{target_family}.yaml or config/phases/{target_family}.yaml
config/{workflow}/{target}/values.yaml
config/{workflow}/{env}.yaml
config/{workflow}/{target}/{env}.yaml

Skip missing optional files. Later files override earlier files.

Recursively merge only when both values are non-empty dictionaries.
Lists, scalars, null, and empty dictionaries or lists fully replace earlier values.
Never merge list items.

Store templates under Template/.
Pass merged config, runtime arguments, target_family, and the current render item to each template.

Keep YAML simple and avoid duplicated shared definitions.

Treat ans as read-only validation data.
Never use ans as renderer input, template source, or output.

Write files only under --output.

For each ans/{workflow}/{target}/{env}, the matching command must reproduce the same file tree and contents.

Inspect the project, simplify the config, implement the renderer, and run validation.

Do not ask questions.
Use the smallest maintainable solution and do not hardcode current samples.
