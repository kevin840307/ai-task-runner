#!/usr/bin/env python3
"""Generic Jinja2-based config renderer for auto-config workflows."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import jinja2
import yaml


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Render config templates for auto-config workflows")
    parser.add_argument("--workflow", required=True, help="Workflow name")
    parser.add_argument("--fab", required=True, help="Target/FAB ID")
    parser.add_argument("--env", required=True, help="Environment name")
    parser.add_argument("--output", required=True, help="Output directory path")
    return parser.parse_args()


def get_target_family(fab: str) -> str:
    """Extract target family from FAB ID."""
    return fab.split("-", 1)[0]


def load_yaml_file(path: Path) -> Any:
    """Load YAML file, returning None if missing or empty."""
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    return yaml.safe_load(content) if content else None


def deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries. Later values override earlier ones."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def find_template(template_dir: Path, output_type: str, template_map: list) -> Path:
    """Find template file based on output type and template map."""
    if not template_map:
        for ext in ["output.yaml.j2", "output.yaml.jinja", "output.xml.j2", "output.yml.j2"]:
            t = template_dir / ext
            if t.exists():
                return t
        return template_dir / "output.yaml.j2"
    for entry in template_map:
        if isinstance(entry, dict) and "output_type" in entry and entry["output_type"] == output_type:
            if "template" in entry:
                t = template_dir / entry["template"]
                if t.exists():
                    return t
            if "templates" in entry:
                for tpl in entry["templates"]:
                    t = template_dir / tpl
                    if t.exists():
                        return t
    return template_dir / "output.yaml.j2"


def convert_hyphens_to_underscores(data: Any) -> Any:
    """Recursively convert hyphenated keys to underscores."""
    if isinstance(data, dict):
        return {hyphen_to_underscore(k): convert_hyphens_to_underscores(v) for k, v in data.items()}
    if isinstance(data, list):
        return [convert_hyphens_to_underscores(item) for item in data]
    return data


def hyphen_to_underscore(key: str) -> str:
    """Convert hyphenated key to underscore-separated."""
    return key.replace("-", "_")


def render_template(template_path: Path, context: dict) -> str:
    """Render a Jinja2 template with context."""
    template_content = template_path.read_text(encoding="utf-8")
    template = jinja2.Template(template_content)
    converted_context = convert_hyphens_to_underscores(context)
    return template.render(**converted_context)


def render_yaml_template(template_path: Path, context: dict) -> str:
    """Render template and output as formatted YAML."""
    rendered = render_template(template_path, context)
    return yaml.safe_dump(yaml.safe_load(rendered), sort_keys=False, allow_unicode=True)


def create_output_structure(output_root: Path, workflow: str, target: str, env: str) -> Path:
    """Create output directory structure."""
    output_dir = output_root / workflow / target / env
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_renderer(project_root: Path, output_root: Path, workflow: str, target: str, env: str) -> None:
    """Execute rendering for a workflow/target/env combination."""
    global_config = load_yaml_file(project_root / "config" / "values.yaml") or {}
    workflow_config = load_yaml_file(project_root / "config" / workflow / "values.yaml") or {}
    target_family = get_target_family(target)
    target_family_config = load_yaml_file(project_root / "config" / "phases" / f"{target_family}.yaml") or {}
    target_family_config = target_family_config or load_yaml_file(project_root / "config" / "phase" / f"{target_family}.yaml") or {}
    workflow_target_config = load_yaml_file(project_root / "config" / workflow / target / "values.yaml") or {}
    env_config = load_yaml_file(project_root / "config" / workflow / f"{env}.yaml") or {}
    env_config = env_config or load_yaml_file(project_root / "config" / workflow / target / f"{env}.yaml") or {}
    shared_app_deploy = load_yaml_file(project_root / "config" / "shared" / "app-deploy.yaml") or {}
    shared_flow_deploy = load_yaml_file(project_root / "config" / "shared" / "flow-deploy.yaml") or {}
    shared_gateway = load_yaml_file(project_root / "config" / "shared" / "gateway.yaml") or {}
    shared_namespace = load_yaml_file(project_root / "config" / "shared" / "namespace.yaml") or {}

    # Merge all shared configs together first
    shared_configs = deep_merge(shared_app_deploy, deep_merge(shared_flow_deploy, deep_merge(shared_gateway, shared_namespace)))

    merged_config = deep_merge(
        global_config,
        deep_merge(
            workflow_config,
            deep_merge(
                target_family_config,
                deep_merge(
                    workflow_target_config,
                    deep_merge(env_config, shared_configs)
                )
            )
        )
    )

    context = {"workflow": workflow, "target": target, "env": env, "target_family": target_family, "config": merged_config}

    template_dir = project_root / "Template"
    output_type = merged_config.get("output_type", "yaml")
    template_path = find_template(template_dir, output_type, merged_config.get("template_map", []))

    if template_path is None:
        print(f"Warning: No template found for output type {output_type}", file=sys.stderr)
        return

    rendered_content = render_yaml_template(template_path, context)
    output_dir = create_output_structure(output_root, workflow, target, env)
    (output_dir / "values.yaml").write_text(rendered_content, encoding="utf-8")

    generate_app_configs(project_root, output_dir, workflow, target, env, merged_config)
    generate_flow_configs(project_root, output_dir, workflow, target, env, merged_config)


def generate_app_configs(project_root: Path, output_dir: Path, workflow: str, target: str, env: str, merged_config: dict) -> None:
    """Generate app-specific config files."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])
    app_deploy = merged_config.get("app-deploy") or {}
    special_apps = merged_config.get("special_apps", [])
    p_values = merged_config.get("p_values", [])
    app_output_files = merged_config.get("app_output_files", {})

    for app_name in merged_config.get("apps", []):
        app_config = app_deploy.get(app_name, {})
        output_path = output_dir / "config" / app_name
        output_path.mkdir(parents=True, exist_ok=True)

        if isinstance(app_config, list):
            generate_versioned_app_config(app_name, app_config, output_path, merged_config, env, workflow)
        elif isinstance(app_config, dict):
            if app_name in special_apps:
                generate_special_app_config(app_name, app_config, output_path, merged_config, env, workflow)
            elif "log" in app_config:
                generate_app_with_log(app_name, app_config, output_path, merged_config, env, workflow, project_root)
            else:
                generate_simple_app_config(app_name, app_config, output_path, merged_config, env, workflow)
        else:
            file_name = get_app_output_file_name("application", merged_config)
            (output_path / file_name).write_text("", encoding="utf-8")


def generate_versioned_app_config(app_name: str, app_config: Any, output_path: Path, merged_config: dict, env: str, workflow: str) -> None:
    """Generate version-specific app config files for list-based app configs."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])
    special_apps = merged_config.get("special_apps", [])
    p_values = merged_config.get("p_values", [])
    app_output_files = merged_config.get("app_output_files", {})

    is_special_app = app_name in special_apps

    for version in versions:
        version_dir = output_path / version
        version_dir.mkdir(parents=True, exist_ok=True)

        if is_special_app:
            fab_key = next((k for k in app_config if k.startswith("FAB")), None)
            p_configs = app_config.get(fab_key, app_config) if fab_key else app_config

            for p in p_values:
                p_config = p_configs.get(p, [])
                for item in p_config:
                    if item.get("name") == version:
                        version_data = item.copy()
                        version_data["app"] = app_name
                        version_data["version"] = version
                        version_data["workflow"] = render_target_info.get("name", "")
                        version_data["target"] = render_target_info.get("target_family", "")
                        version_data["env"] = render_target_info.get("profiles", [env])[0]
                        file_name = get_app_output_file_name("application-p", merged_config, p)
                        (version_dir / file_name).write_text(yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
                        break
        else:
            # For non-special apps with list config, generate files for each item
            for item in app_config:
                version_data = item.copy()
                version_data["app"] = app_name
                version_data["version"] = version
                version_data["workflow"] = render_target_info.get("name", "")
                version_data["target"] = render_target_info.get("target_family", "")
                version_data["env"] = render_target_info.get("profiles", [env])[0]
                file_name = get_app_output_file_name("application", merged_config)
                (version_dir / file_name).write_text(yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_special_app_config(app_name: str, app_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str) -> None:
    """Generate special app config files."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])
    p_values = merged_config.get("p_values", [])
    fab_key = next((k for k in app_config if k.startswith("FAB")), None)
    
    # If app_config has a FAB key, use the config under that key for each p value
    # Otherwise, use the entire app_config as the config for all p values
    if fab_key:
        p_configs = app_config.get(fab_key, {})
    else:
        p_configs = app_config

    for p in p_values:
        # If p_configs is a dict, get the config for this p value
        # If p_configs is a list, use the entire list
        if isinstance(p_configs, dict):
            p_config = p_configs.get(p, [])
        else:
            p_config = p_configs

        for version in versions:
            for item in p_config:
                if item.get("name") == version:
                    version_data = item.copy()
                    version_data["app"] = app_name
                    version_data["version"] = version
                    version_data["workflow"] = render_target_info.get("name", "")
                    version_data["target"] = render_target_info.get("target_family", "")
                    version_data["env"] = render_target_info.get("profiles", [env])[0]
                    file_name = get_app_output_file_name("application-p", merged_config, p)
                    version_dir = output_path / version
                    version_dir.mkdir(parents=True, exist_ok=True)
                    (version_dir / file_name).write_text(yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
                    break


def generate_app_with_log(app_name: str, app_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str, project_root: Path) -> None:
    """Generate app config files with log."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    app_config_data = app_config.get("application", {})
    if app_config_data:
        app_config_data["app"] = app_name
        app_config_data["workflow"] = render_target_info.get("name", "")
        app_config_data["target"] = render_target_info.get("target_family", "")
        app_config_data["env"] = render_target_info.get("profiles", [env])[0]
        app_config_data["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_app_output_file_name("application", merged_config)
        (output_path / file_name).write_text(yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    log_config = app_config.get("log", {})
    if log_config:
        log_config["app"] = app_name
        log_config["workflow"] = render_target_info.get("name", "")
        log_config["target"] = render_target_info.get("target_family", "")
        log_config["env"] = render_target_info.get("profiles", [env])[0]
        log_config["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_app_output_file_name("log", merged_config)
        context = {"app": app_name, "log": log_config, "config": merged_config}
        (output_path / file_name).write_text(render_template(project_root / "Template" / "output.xml.j2", context), encoding="utf-8")


def generate_simple_app_config(app_name: str, app_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str) -> None:
    """Generate simple app config file."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    app_config_data = app_config.copy()
    app_config_data["app"] = app_name
    app_config_data["workflow"] = render_target_info.get("name", "")
    app_config_data["target"] = render_target_info.get("target_family", "")
    app_config_data["env"] = render_target_info.get("profiles", [env])[0]
    app_config_data["version"] = render_target_info.get("versions", [env])[0]
    file_name = get_app_output_file_name("application", merged_config)
    (output_path / file_name).write_text(yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_flow_configs(project_root: Path, output_dir: Path, workflow: str, target: str, env: str, merged_config: dict) -> None:
    """Generate flow-specific config files."""
    special_flows = merged_config.get("special_flows", [])
    flow_deploy = merged_config.get("flow-deploy") or {}
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    for flow_name in special_flows:
        flow_config = flow_deploy.get(flow_name, {})
        if not flow_config:
            continue
        output_path = output_dir / "config" / flow_name
        output_path.mkdir(parents=True, exist_ok=True)

        if isinstance(flow_config, list):
            generate_versioned_flow_config(flow_name, flow_config, output_path, merged_config, env, workflow)
        elif isinstance(flow_config, dict):
            fab_key = next((k for k in flow_config if k.startswith("FAB")), None)
            p_configs = flow_config.get(fab_key, flow_config) if fab_key else flow_config
            generate_special_flow_config(flow_name, flow_config, output_path, merged_config, env, workflow, p_configs)


def generate_versioned_flow_config(flow_name: str, flow_config: Any, output_path: Path, merged_config: dict, env: str, workflow: str) -> None:
    """Generate version-specific flow config files."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    for version in versions:
        version_dir = output_path / version
        version_dir.mkdir(parents=True, exist_ok=True)

        if isinstance(flow_config, list):
            for item in flow_config:
                if item.get("name") == version:
                    flow_config_data = item.get("resource", {})
                    if flow_config_data:
                        flow_config_data["flow"] = flow_name
                        flow_config_data["version"] = version
                        flow_config_data["workflow"] = render_target_info.get("name", "")
                        flow_config_data["target"] = render_target_info.get("target_family", "")
                        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
                        file_name = get_flow_output_file_name("flow", merged_config)
                        (version_dir / file_name).write_text(yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
                    break
        elif isinstance(flow_config, dict):
            flow_config_data = flow_config.get(version, {})
            if flow_config_data:
                flow_config_data["flow"] = flow_name
                flow_config_data["version"] = version
                flow_config_data["workflow"] = render_target_info.get("name", "")
                flow_config_data["target"] = render_target_info.get("target_family", "")
                flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
                file_name = get_flow_output_file_name("flow", merged_config)
                (version_dir / file_name).write_text(yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def generate_special_flow_config(flow_name: str, flow_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str, p_configs: dict) -> None:
    """Generate special flow config files."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])
    p_values = merged_config.get("p_values", [])

    for p in p_values:
        p_config = p_configs.get(p, [])
        for version in versions:
            for item in p_config:
                if item.get("name") == version:
                    version_data = item.copy()
                    version_data["flow"] = flow_name
                    version_data["version"] = version
                    version_data["workflow"] = render_target_info.get("name", "")
                    version_data["target"] = render_target_info.get("target_family", "")
                    version_data["env"] = render_target_info.get("profiles", [env])[0]
                    file_name = get_flow_output_file_name("flow-p", merged_config, p)
                    (output_path / version / file_name).write_text(yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
                    break


def generate_flow_with_log(flow_name: str, flow_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str, project_root: Path) -> None:
    """Generate flow config files with log."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    flow_config_data = flow_config.get("flow", {})
    if flow_config_data:
        flow_config_data["flow"] = flow_name
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_flow_output_file_name("flow", merged_config)
        (output_path / file_name).write_text(yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")

    log_config = flow_config.get("log", {})
    if log_config:
        log_config["flow"] = flow_name
        log_config["workflow"] = render_target_info.get("name", "")
        log_config["target"] = render_target_info.get("target_family", "")
        log_config["env"] = render_target_info.get("profiles", [env])[0]
        log_config["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_flow_output_file_name("log", merged_config)
        context = {"flow": flow_name, "log": log_config, "config": merged_config}
        (output_path / file_name).write_text(render_template(project_root / "Template" / "output.xml.j2", context), encoding="utf-8")


def generate_simple_flow_config(flow_name: str, flow_config: dict, output_path: Path, merged_config: dict, env: str, workflow: str) -> None:
    """Generate simple flow config file."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", []) or merged_config.get("versions", [])

    flow_config_data = flow_config.get("flow", {})
    if flow_config_data:
        flow_config_data["flow"] = flow_name
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_flow_output_file_name("flow", merged_config)
        (output_path / file_name).write_text(yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    else:
        flow_config_data = flow_config.copy()
        flow_config_data["flow"] = flow_name
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]
        file_name = get_flow_output_file_name("flow", merged_config)
        (output_path / file_name).write_text(yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def get_app_output_file_name(file_type: str, merged_config: dict, p: str = "") -> str:
    """Get output file name for app config."""
    app_output_files = merged_config.get("app_output_files", {})
    if file_type in app_output_files:
        file_name = app_output_files[file_type]
        if p and "{p}" in file_name:
            file_name = file_name.replace("{p}", p)
        return file_name
    return "application.yaml"


def get_flow_output_file_name(file_type: str, merged_config: dict, p: str = "") -> str:
    """Get output file name for flow config."""
    template_map = merged_config.get("template_map", [])
    for template in template_map:
        if file_type in template:
            return file_type + ".yml"
    return file_type + ".yml"


def main() -> int:
    """Main entry point."""
    args = parse_args()
    project_root = Path(".").resolve()
    output_root = Path(args.output).resolve()
    run_renderer(project_root, output_root, args.workflow, args.fab, args.env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
