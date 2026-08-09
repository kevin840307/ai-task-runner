Build a generic Jinja2 config renderer for this project.

Create or update rander.py. It should only load YAML, merge values, render Jinja2 templates, create folders, and write files.

Example:
python rander.py --workflow WORKFLOW-A --fab FAB29-FZ1 --env PROD --output output

The example values are samples only. Never hardcode workflow, target, env, app, version, profile, template, filename, or answer-specific values in Python.

Treat --workflow, --fab, --env, and --output as runtime inputs. --fab is only a generic target id.

Keep Python generic and format-agnostic. All render combinations, templates, filenames, output paths, apps, services, versions, and profiles must come from YAML config.

Load available config layers in this order, with later values overriding earlier values:
config/values.yaml
config/{workflow}/values.yaml
config/phase/{target_family}.yaml or config/phases/{target_family}.yaml
config/{workflow}/{target}/values.yaml
config/{workflow}/{env}.yaml
config/{workflow}/{target}/{env}.yaml

target_family is the part before the first hyphen. Missing optional layers must be skipped.

Deep merge only when both values are non-empty dictionaries. Lists, empty dictionaries, empty lists, null, and scalars from a later layer replace the earlier value. Do not merge lists item by item.

Keep shared values centralized and YAML simple. Adding a new render target should not require changing rander.py.

Store Jinja2 templates under Template/. Templates must be dynamic and may generate any text format.

Pass merged config, runtime inputs, target_family, and the current render item to templates.

ans/ is read-only expected output. Never use ans/ as renderer input and never modify it. Write generated files only under --output.

For every ans/{workflow}/{target}/{env}, the matching command must generate exactly the same file tree and contents under output/{workflow}/{target}/{env}.

Keep rander.py under 500 lines and do not depend on other local Python files.

Do not add one-off logic only to pass the samples.
