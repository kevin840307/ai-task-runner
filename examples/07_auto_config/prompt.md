Build a generic Jinja2-based config renderer for this project.

Create or update rander.py to load YAML config, deep merge values, render Jinja2 templates, create directories, and write output files.

Example command:
python rander.py --workflow WORKFLOW-A --fab FAB29-FZ1 --env PROD --output output

WORKFLOW-A, FAB29-FZ1, and PROD are examples only and must not be hardcoded.

Requirements:

1. Treat --workflow, --fab, --env, and --output as runtime inputs.

2. --fab is a generic target id, not necessarily a real FAB name.

3. rander.py may only load YAML, merge values, render templates, create folders, and write files.

4. Do not add app-specific, workflow-specific, target-specific, env-specific, format-specific, or ans-specific logic in Python.

5. Do not branch or loop on fixed app, workflow, target, env, version, profile, filename, or template names.

6. Apps, services, versions, profiles, templates, filenames, output paths, and render combinations must come from YAML config or one central render matrix.

7. Adding or removing render targets must not require changing rander.py.

8. Keep rander.py under 500 source lines.

9. rander.py must not import, call, or depend on other local Python files.

10. Python must remain format-agnostic. Templates may generate YAML, XML, INI, CFG, JSON, or text.

Load config in this order, with later files overriding earlier files:

config/values.yaml
config/{workflow}/values.yaml
config/phase/{target_family}.yaml or config/phases/{target_family}.yaml
config/{workflow}/{target}/values.yaml
config/{workflow}/{env}.yaml
config/{workflow}/{target}/{env}.yaml

target_family is the part before the first hyphen.
Example: FAB29-FZ1 becomes FAB29.

Skip missing optional config files.

Deep merge only when both old and new values are non-empty dictionaries.

A later list, empty dictionary, empty list, null, or scalar must fully replace the earlier value.

Do not merge lists item by item.

Use simple YAML and avoid duplicating shared apps, versions, profiles, template mappings, or output patterns.

Use one central render matrix to define templates, output paths, filenames, and render context.

Store Jinja2 templates under Template/.

Templates must contain dynamic placeholders and may use standard Jinja2 features.

Pass merged config, runtime arguments, target_family, and the current render item into the template context.

The ans directory is read-only validation data.

Do not create, modify, delete, move, copy, or use ans files as renderer inputs or templates.

Write generated files only under --output.

For every ans/{workflow}/{target}/{env}, running the matching command must create output/{workflow}/{target}/{env} with exactly the same file tree and contents.

Inspect the existing project, implement the renderer, simplify the config, and run validation tests.

Do not ask questions. Make reasonable assumptions from existing files.

Use the smallest, simplest, and most maintainable solution.

Do not add hardcoded logic only to pass current samples.
