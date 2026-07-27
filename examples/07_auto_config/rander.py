#!/usr/bin/env python3
"""Generic Jinja2-based config renderer for auto-config workflows."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import jinja2
import yaml


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Render config templates for auto-config workflows"
    )
    parser.add_argument(
        "--workflow",
        required=True,
        help="Workflow name (e.g., WORKFLOW-A)",
    )
    parser.add_argument(
        "--fab",
        required=True,
        help="Target/FAB ID (e.g., FAB29-FZ1)",
    )
    parser.add_argument(
        "--env",
        required=True,
        help="Environment name",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output directory path",
    )
    return parser.parse_args()


def get_target_family(fab: str) -> str:
    """Extract target family from FAB ID (part before first dash)."""
    return fab.split("-", 1)[0]


def load_yaml_file(path: Path) -> Any:
    """Load and parse a YAML file, returning None if file doesn't exist or is empty."""
    if not path.exists():
        return None
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return yaml.safe_load(content)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries, with override taking precedence.

    Later values that are lists, empty dicts, empty lists, or null/None
    are explicit replacements that overwrite earlier values.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Both are dicts - deep merge
            result[key] = deep_merge(result[key], value)
        else:
            # Explicit replacement: lists, empty dicts, empty lists, or null/None
            # replace the earlier value instead of merging
            result[key] = value
    return result


def deep_merge_with_empty_dict_handling(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge two dictionaries with special handling for empty dicts.

    Empty dicts in override should replace the base value completely.
    This is used to ensure empty dicts are preserved in the output.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Check if override value is empty dict - explicit replacement
            if not value:
                result[key] = value
            else:
                # Both are non-empty dicts - deep merge
                result[key] = deep_merge(result[key], value)
        else:
            # Explicit replacement: lists, empty dicts, empty lists, or null/None
            result[key] = value
    return result


def merge_configs(
    global_config: Dict[str, Any],
    workflow_config: Dict[str, Any],
    target_family_config: Dict[str, Any],
    workflow_target_config: Dict[str, Any],
    env_config: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge configs in the specified order. Later files override earlier ones."""
    merged = global_config.copy()
    merged = deep_merge_with_empty_dict_handling(merged, workflow_config)
    merged = deep_merge_with_empty_dict_handling(merged, target_family_config)
    merged = deep_merge_with_empty_dict_handling(merged, workflow_target_config)
    merged = deep_merge_with_empty_dict_handling(merged, env_config)
    return merged


def find_template_file(
    output_type: str,
    template_dir: Path,
    template_map: List[Dict[str, Any]],
) -> Optional[Path]:
    """Find the appropriate template file based on output type and template map."""
    if not template_map:
        # Default to YAML template
        yaml_template = template_dir / "output.yaml.j2"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.yaml.jinja"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.yaml.jinja2"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.yml.j2"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.yml.jinja"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.yml.jinja2"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.xml.j2"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.xml.jinja"
        if yaml_template.exists():
            return yaml_template
        yaml_template = template_dir / "output.xml.jinja2"
        if yaml_template.exists():
            return yaml_template
        return None

    for template_entry in template_map:
        if isinstance(template_entry, dict) and "output_type" in template_entry:
            if template_entry["output_type"] == output_type:
                if "template" in template_entry:
                    template_path = template_dir / template_entry["template"]
                    if template_path.exists():
                        return template_path
                if "templates" in template_entry:
                    for template in template_entry["templates"]:
                        template_path = template_dir / template
                        if template_path.exists():
                            return template_path
    return None


def convert_hyphenated_keys_to_underscore(data: Any) -> Any:
    """Recursively convert hyphenated keys to underscore-separated."""
    if isinstance(data, dict):
        return {
            hyphen_to_underscore(key): convert_hyphenated_keys_to_underscore(value)
            for key, value in data.items()
        }
    elif isinstance(data, list):
        return [convert_hyphenated_keys_to_underscore(item) for item in data]
    else:
        return data


def hyphen_to_underscore(key: str) -> str:
    """Convert a hyphenated key to underscore-separated."""
    return key.replace("-", "_")


def get_app_output_file_name(file_type: str, merged_config: Dict[str, Any], p: str | None = None) -> str:
    """Get the output file name for an app config from the config."""
    app_output_files = merged_config.get("app_output_files", {})
    if file_type in app_output_files:
        file_name = app_output_files[file_type]
        # Replace {p} placeholder with actual p value if provided
        if p and "{p}" in file_name:
            file_name = file_name.replace("{p}", p)
        return file_name
    # Default fallback - use generic name
    return "application.yaml"


def render_template(
    template_path: Path,
    context: Dict[str, Any],
) -> str:
    """Render a Jinja2 template with the given context."""
    template_content = template_path.read_text(encoding="utf-8")
    template = jinja2.Template(template_content)
    # Convert hyphenated keys to underscore-separated for template access
    converted_context = convert_hyphenated_keys_to_underscore(context)
    return template.render(**converted_context)


def render_yaml_template(
    template_path: Path,
    context: Dict[str, Any],
) -> str:
    """Render a Jinja2 template that generates YAML with proper formatting."""
    template_content = template_path.read_text(encoding="utf-8")
    template = jinja2.Template(template_content)
    # Convert hyphenated keys to underscore-separated for template access
    converted_context = convert_hyphenated_keys_to_underscore(context)
    rendered = template.render(**converted_context)
    # Parse the rendered template as Python dict and convert to proper YAML
    parsed = yaml.safe_load(rendered)
    return yaml.safe_dump(parsed, sort_keys=False, allow_unicode=True)


def create_output_structure(
    output_root: Path,
    workflow: str,
    target: str,
    env: str,
) -> Path:
    """Create the output directory structure."""
    output_dir = output_root / workflow / target / env
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def run_renderer(
    project_root: Path,
    output_root: Path,
    workflow: str,
    target: str,
    env: str,
) -> None:
    """Execute the rendering process for a given workflow/target/env combination."""
    # Load all config files
    global_config = load_yaml_file(project_root / "config" / "values.yaml") or {}

    workflow_config = load_yaml_file(
        project_root / "config" / workflow / "values.yaml"
    ) or {}

    target_family = get_target_family(target)
    target_family_config = load_yaml_file(
        project_root / "config" / "phases" / f"{target_family}.yaml"
    ) or {}
    target_family_config = target_family_config or load_yaml_file(
        project_root / "config" / "phase" / f"{target_family}.yaml"
    ) or {}

    workflow_target_config = load_yaml_file(
        project_root / "config" / workflow / target / "values.yaml"
    ) or {}

    env_config = load_yaml_file(
        project_root / "config" / workflow / f"{env}.yaml"
    ) or {}
    env_config = env_config or load_yaml_file(
        project_root / "config" / workflow / target / f"{env}.yaml"
    ) or {}

    # Merge configs
    merged_config = merge_configs(
        global_config,
        workflow_config,
        target_family_config,
        workflow_target_config,
        env_config,
    )

    # Prepare rendering context
    context = {
        "workflow": workflow,
        "target": target,
        "env": env,
        "target_family": target_family,
        "config": merged_config,
    }

    # Find and render templates
    template_dir = project_root / "Template"
    if not template_dir.exists():
        print(f"Warning: Template directory not found: {template_dir}", file=sys.stderr)
        return

    # Determine output type from config or use default
    output_type = "yaml"
    if "output_type" in merged_config:
        output_type = merged_config["output_type"]

    # Find template
    template_path = find_template_file(
        output_type,
        template_dir,
        merged_config.get("template_map", []),
    )

    if template_path is None:
        print(f"Warning: No template found for output type {output_type}", file=sys.stderr)
        return

    # Render template
    rendered_content = render_yaml_template(template_path, context)

    # Create output structure
    output_dir = create_output_structure(output_root, workflow, target, env)

    # Write rendered content
    output_file = output_dir / "values.yaml"
    output_file.write_text(rendered_content, encoding="utf-8")

    # Generate app-specific config files
    generate_app_configs(
        project_root,
        output_dir,
        workflow,
        target,
        env,
        merged_config,
    )

    # Generate flow-specific config files
    generate_flow_config(
        project_root,
        output_dir,
        workflow,
        target,
        env,
        merged_config,
    )


def generate_app_configs(
    project_root: Path,
    output_dir: Path,
    workflow: str,
    target: str,
    env: str,
    merged_config: Dict[str, Any],
) -> None:
    """Generate app-specific config files based on centralized app lists."""
    # Get all apps from centralized render matrix (flow_apps)
    flow_apps = merged_config.get("flow_apps", [])

    # Get special apps list from config (apps that use special config patterns)
    special_apps = merged_config.get("special_apps", [])

    for app_name in flow_apps:
        # Get app config from app-deploy (for backward compatibility)
        app_deploy = merged_config.get("app-deploy", {})
        app_config = app_deploy.get(app_name, {})

        if not app_config:
            continue

        # Determine output path based on app name
        output_path = output_dir / "config" / app_name
        output_path.mkdir(parents=True, exist_ok=True)

        # Determine app type based on config structure
        if isinstance(app_config, list):
            # List-based config (version-specific configs)
            generate_versioned_app_config(
                app_name,
                app_config,
                output_path,
                merged_config,
                env,
                workflow,
            )
        elif isinstance(app_config, dict):
            # Check if this is a special app with special config structure
            if app_name in special_apps:
                # Special app with special config structure
                generate_special_app_config(
                    app_name,
                    app_config,
                    output_path,
                    merged_config,
                    env,
                    workflow,
                )
            elif "log" in app_config:
                # App with log configuration
                generate_app_with_log(
                    app_name,
                    app_config,
                    output_path,
                    merged_config,
                )
            else:
                # Dict-based version config or simple app config
                # Check if it's a dict-based version config (has version-specific configs)
                # by checking if any value in the dict is a dict (version-specific config)
                has_version_config = any(
                    isinstance(value, dict) for value in app_config.values()
                )
                if has_version_config:
                    # Dict-based version config (e.g., app with version-specific configs)
                    generate_versioned_app_config(
                        app_name,
                        app_config,
                        output_path,
                        merged_config,
                        env,
                        workflow,
                    )
                else:
                    # Simple app config - generate application.yml
                    generate_simple_app_config(
                        app_name,
                        app_config,
                        output_path,
                        merged_config,
                        env,
                        workflow,
                    )


def generate_flow_config(
    project_root: Path,
    output_dir: Path,
    workflow: str,
    target: str,
    env: str,
    merged_config: Dict[str, Any],
) -> None:
    """Generate flow-specific config files based on centralized flow lists."""
    # Get special flows list from config (flows that use special config patterns)
    special_flows = merged_config.get("special_flows", [])

    # Only generate flow configs for flows in special_flows list
    for flow_name in special_flows:
        # Get flow config from flow-deploy (for backward compatibility)
        flow_deploy = merged_config.get("flow-deploy", {})
        flow_config = flow_deploy.get(flow_name, {})

        if not flow_config:
            continue

        # Determine output path based on flow name
        output_path = output_dir / "config" / flow_name
        output_path.mkdir(parents=True, exist_ok=True)

        # Determine flow type based on config structure
        if isinstance(flow_config, list):
            # List-based config (version-specific configs)
            generate_versioned_flow_config(
                flow_name,
                flow_config,
                output_path,
                merged_config,
                env,
                workflow,
            )
        elif isinstance(flow_config, dict):
            # Check if this is a special flow with special config structure
            if flow_name in special_flows:
                # Special flow with special config structure
                generate_special_flow_config(
                    flow_name,
                    flow_config,
                    output_path,
                    merged_config,
                    env,
                    workflow,
                )
            elif "log" in flow_config:
                # Flow with log configuration
                generate_flow_with_log(
                    flow_name,
                    flow_config,
                    output_path,
                    merged_config,
                    env,
                    workflow,
                    project_root,
                )
            else:
                # Simple flow config - generate flow.yml
                generate_simple_flow_config(
                    flow_name,
                    flow_config,
                    output_path,
                    merged_config,
                    env,
                    workflow,
                )


def generate_app_config(
    app_name: str,
    merged_config: Dict[str, Any],
) -> Dict[str, Any] | None:
    """Generate config data for a specific app."""
    # Get app-specific config from app-deploy only (flow-deploy is ignored for this renderer)
    app_deploy = merged_config.get("app-deploy", {})

    app_config = app_deploy.get(app_name, {})

    if not app_config:
        print(f"DEBUG: app_config is None for app_name={app_name}", file=__import__('sys').stderr)
        return None

    # Handle case where app_config is a list (version-specific configs)
    # Return the full list for proper handling in generate_versioned_app_config
    return app_config


def generate_special_app_config(
    app_name: str,
    app_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate special app config files for special config structure."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", [])
    if not versions:
        versions = merged_config.get("versions", [])

    # Get p_values from config
    p_values = merged_config.get("p_values", [])

    # Navigate to the p configs: app -> special -> p1, p2, p3
    fab_key = None
    for key in app_config:
        if key.startswith("FAB"):
            fab_key = key
            break

    if fab_key:
        fab_config = app_config.get(fab_key, {})
        p_configs = fab_config
    else:
        p_configs = app_config

    # Generate files for each p and each version
    for p in p_values:
        p_config = p_configs.get(p, [])
        if not p_config:
            continue

        # Generate files for each version
        for version in versions:
            # Find the version-specific data in p_config
            for item in p_config:
                if item.get("name") == version:
                    version_data = item.copy()
                    version_data["app"] = app_name
                    version_data["version"] = version
                    version_data["workflow"] = render_target_info.get("name", "")
                    version_data["target"] = render_target_info.get("target_family", "")
                    version_data["env"] = render_target_info.get("profiles", [env])[0]

                    version_yaml = yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True)
                    output_file_name = get_app_output_file_name("application-p", merged_config, p)
                    # Create parent directories before writing
                    (output_path / version).mkdir(parents=True, exist_ok=True)
                    (output_path / version / output_file_name).write_text(version_yaml, encoding="utf-8")
                    break


def generate_app_with_log(
    app_name: str,
    app_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
) -> None:
    """Generate app config files with log."""
    # Generate application config
    app_config_data = app_config.get("application", {})
    if app_config_data:
        app_config_data["app"] = app_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        app_config_data["workflow"] = render_target_info.get("name", "")
        app_config_data["target"] = render_target_info.get("target_family", "")
        app_config_data["env"] = render_target_info.get("profiles", [env])[0]
        app_config_data["version"] = render_target_info.get("versions", [env])[0]

        app_config_yaml = yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_app_output_file_name("application", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(app_config_yaml, encoding="utf-8")

    # Generate log config
    log_config = app_config.get("log", {})
    if log_config:
        log_config["app"] = app_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        log_config["workflow"] = render_target_info.get("name", "")
        log_config["target"] = render_target_info.get("target_family", "")
        log_config["env"] = render_target_info.get("profiles", [env])[0]
        log_config["version"] = render_target_info.get("versions", [env])[0]

        log_xml = render_template(
            project_root / "Template" / "output.xml.j2",
            {
                "app": app_name,
                "workflow": render_target_info.get("name", ""),
                "target": render_target_info.get("target_family", ""),
                "env": render_target_info.get("profiles", [env])[0],
                "version": render_target_info.get("versions", [env])[0],
                "log": log_config,
            },
        )
        output_file_name = get_app_output_file_name("log", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(log_xml, encoding="utf-8")


def generate_simple_app_config(
    app_name: str,
    app_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate simple app config file."""
    # Check if app_config has an "application" key
    app_config_data = app_config.get("application", {})
    if app_config_data:
        app_config_data["app"] = app_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        app_config_data["workflow"] = render_target_info.get("name", "")
        app_config_data["target"] = render_target_info.get("target_family", "")
        app_config_data["env"] = render_target_info.get("profiles", [env])[0]
        app_config_data["version"] = render_target_info.get("versions", [env])[0]

        app_config_yaml = yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_app_output_file_name("application", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(app_config_yaml, encoding="utf-8")
    else:
        # Simple app config without "application" key - just use the app_config as-is
        # Add app name and basic info
        app_config_data = app_config.copy()
        app_config_data["app"] = app_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        app_config_data["workflow"] = render_target_info.get("name", "")
        app_config_data["target"] = render_target_info.get("target_family", "")
        app_config_data["env"] = render_target_info.get("profiles", [env])[0]
        app_config_data["version"] = render_target_info.get("versions", [env])[0]

        app_config_yaml = yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_app_output_file_name("application", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(app_config_yaml, encoding="utf-8")


def generate_versioned_app_config(
    app_name: str,
    app_config: Any,
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate version-specific app config files."""
    # Get versions from config
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", [])
    if not versions:
        versions = merged_config.get("versions", [])

    # Get app-specific deployment config from merged_config directly
    app_deploy = merged_config.get("app-deploy", {})
    flow_deploy = merged_config.get("flow-deploy", {})

    # Determine which config to use based on app name
    # Get the list of special app names from config (apps that use special config patterns)
    special_apps = merged_config.get("special_apps", [])
    p_values = merged_config.get("p_values", [])
    
    # Check if this is a special app with special config structure
    is_special_app = app_name in special_apps
    if is_special_app:
        # Special apps use special config patterns
        # Structure: app -> special -> p1, p2, p3
        app_deploy_config = app_deploy.get(app_name, {})
        # Navigate to the p configs: app -> special -> p1, p2, p3
        fab_key = None
        for key in app_deploy_config:
            if key.startswith("FAB"):
                fab_key = key
                break
        if fab_key:
            fab_config = app_deploy_config.get(fab_key, {})
            p_configs = fab_config
        else:
            p_configs = app_deploy_config
    else:
        # Regular apps use version-specific config
        # Structure: app = [{'name': 'version1', 'resource': {...}}, {'name': 'version2', 'resource': {...}}]
        app_deploy_config = app_deploy.get(app_name, {})
        flow_deploy_config = flow_deploy.get(app_name, {})

    # Generate files for each version
    for version in versions:
        # Create version-specific output directory structure
        version_dir = output_path / version
        version_dir.mkdir(parents=True, exist_ok=True)
        
        # Determine if this is a special app (uses p1, p2, p3 pattern)
        if is_special_app:
            # Special app uses application-pX.yml for p1, p2, p3
            # The structure is: app -> special -> pX where X is p1/p2/p3
            # Each pX contains a list of versions
            # We need to generate files for each p and each version
            for p in p_values:
                p_config = p_configs.get(p, [])
                if p_config:
                    # Get version-specific data from p_config
                    # The structure is: p_config = [{'name': 'version1', ...}, {'name': 'version2', ...}]
                    for item in p_config:
                        if item.get("name") == version:
                            version_data = item.copy()
                            version_data["app"] = app_name
                            version_data["version"] = version
                            version_data["workflow"] = render_target_info.get("name", "")
                            version_data["target"] = render_target_info.get("target_family", "")
                            version_data["env"] = render_target_info.get("profiles", [env])[0]

                            version_yaml = yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True)
                            output_file_name = get_app_output_file_name("application-p", merged_config, p)
                            (version_dir / output_file_name).write_text(version_yaml, encoding="utf-8")
                            break
        else:
            # Regular app uses application config with version-specific configs as a list
            if isinstance(app_deploy_config, list):
                # Find the config for the current version
                for item in app_deploy_config:
                    if item.get("name") == version:
                        app_config_data = item.get("resource", {})
                        if app_config_data:
                            app_config_data["app"] = app_name
                            app_config_data["version"] = version
                            app_config_data["workflow"] = render_target_info.get("name", "")
                            app_config_data["target"] = render_target_info.get("target_family", "")
                            app_config_data["env"] = render_target_info.get("profiles", [env])[0]

                            app_config_yaml = yaml.safe_dump(app_config_data, sort_keys=False, allow_unicode=True)
                            output_file_name = get_app_output_file_name("application", merged_config)
                            (version_dir / output_file_name).write_text(app_config_yaml, encoding="utf-8")
                        break
            elif isinstance(app_deploy_config, dict):
                # Fallback for dict-based version configs
                # For dict-based version configs, we need to generate application-pX.yml files
                # for each p value, not just application.yml for each version
                for p in p_values:
                    p_config = p_configs.get(p, [])
                    if p_config:
                        # Get version-specific data from p_config
                        # The structure is: p_config = [{'name': 'version1', ...}, {'name': 'version2', ...}]
                        for item in p_config:
                            if item.get("name") == version:
                                version_data = item.copy()
                                version_data["app"] = app_name
                                version_data["version"] = version
                                version_data["workflow"] = render_target_info.get("name", "")
                                version_data["target"] = render_target_info.get("target_family", "")
                                version_data["env"] = render_target_info.get("profiles", [env])[0]

                                version_yaml = yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True)
                                output_file_name = get_app_output_file_name("application-p", merged_config, p)
                                (version_dir / output_file_name).write_text(version_yaml, encoding="utf-8")
                                break


def generate_versioned_flow_config(
    flow_name: str,
    flow_config: Any,
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate version-specific flow config files."""
    # Get versions from config
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", [])
    if not versions:
        versions = merged_config.get("versions", [])

    # Get flow-specific deployment config from merged_config directly
    flow_deploy = merged_config.get("flow-deploy", {})

    # Generate files for each version
    for version in versions:
        # Create version-specific output directory structure
        version_dir = output_path / version
        version_dir.mkdir(parents=True, exist_ok=True)

        # Find the config for the current version
        if isinstance(flow_config, list):
            # Find the config for the current version
            for item in flow_config:
                if item.get("name") == version:
                    flow_config_data = item.get("resource", {})
                    if flow_config_data:
                        flow_config_data["flow"] = flow_name
                        flow_config_data["version"] = version
                        flow_config_data["workflow"] = render_target_info.get("name", "")
                        flow_config_data["target"] = render_target_info.get("target_family", "")
                        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]

                        flow_config_yaml = yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True)
                        output_file_name = get_flow_output_file_name("flow", merged_config)
                        (version_dir / output_file_name).write_text(flow_config_yaml, encoding="utf-8")
                    break
        elif isinstance(flow_config, dict):
            # Fallback for dict-based version configs
            flow_config_data = flow_config.get(version, {})
            if flow_config_data:
                flow_config_data["flow"] = flow_name
                flow_config_data["version"] = version
                flow_config_data["workflow"] = render_target_info.get("name", "")
                flow_config_data["target"] = render_target_info.get("target_family", "")
                flow_config_data["env"] = render_target_info.get("profiles", [env])[0]

                flow_config_yaml = yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True)
                output_file_name = get_flow_output_file_name("flow", merged_config)
                (version_dir / output_file_name).write_text(flow_config_yaml, encoding="utf-8")


def generate_special_flow_config(
    flow_name: str,
    flow_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate special flow config files for special config structure."""
    render_targets = merged_config.get("render_targets", {})
    render_target_info = render_targets.get(workflow, {})
    versions = render_target_info.get("versions", [])
    if not versions:
        versions = merged_config.get("versions", [])

    # Get p_values from config
    p_values = merged_config.get("p_values", [])

    # Navigate to the p configs: flow -> special -> p1, p2, p3
    fab_key = None
    for key in flow_config:
        if key.startswith("FAB"):
            fab_key = key
            break

    if fab_key:
        fab_config = flow_config.get(fab_key, {})
        p_configs = fab_config
    else:
        p_configs = flow_config

    # Generate files for each p and each version
    for p in p_values:
        p_config = p_configs.get(p, [])
        if not p_config:
            continue

        # Generate files for each version
        for version in versions:
            # Find the version-specific data in p_config
            for item in p_config:
                if item.get("name") == version:
                    version_data = item.copy()
                    version_data["flow"] = flow_name
                    version_data["version"] = version
                    version_data["workflow"] = render_target_info.get("name", "")
                    version_data["target"] = render_target_info.get("target_family", "")
                    version_data["env"] = render_target_info.get("profiles", [env])[0]

                    version_yaml = yaml.safe_dump(version_data, sort_keys=False, allow_unicode=True)
                    output_file_name = get_flow_output_file_name("flow-p", merged_config, p)
                    # Create parent directories before writing
                    (output_path / version).mkdir(parents=True, exist_ok=True)
                    (output_path / version / output_file_name).write_text(version_yaml, encoding="utf-8")
                    break


def generate_flow_with_log(
    flow_name: str,
    flow_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
    project_root: Path,
) -> None:
    """Generate flow config files with log."""
    # Generate flow config
    flow_config_data = flow_config.get("flow", {})
    if flow_config_data:
        flow_config_data["flow"] = flow_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]

        flow_config_yaml = yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_flow_output_file_name("flow", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(flow_config_yaml, encoding="utf-8")

    # Generate log config
    log_config = flow_config.get("log", {})
    if log_config:
        log_config["flow"] = flow_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        log_config["workflow"] = render_target_info.get("name", "")
        log_config["target"] = render_target_info.get("target_family", "")
        log_config["env"] = render_target_info.get("profiles", [env])[0]
        log_config["version"] = render_target_info.get("versions", [env])[0]

        log_xml = render_template(
            project_root / "Template" / "output.xml.j2",
            {
                "flow": flow_name,
                "workflow": render_target_info.get("name", ""),
                "target": render_target_info.get("target_family", ""),
                "env": render_target_info.get("profiles", [env])[0],
                "version": render_target_info.get("versions", [env])[0],
                "log": log_config,
            },
        )
        output_file_name = get_flow_output_file_name("log", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(log_xml, encoding="utf-8")


def generate_simple_flow_config(
    flow_name: str,
    flow_config: Dict[str, Any],
    output_path: Path,
    merged_config: Dict[str, Any],
    env: str,
    workflow: str,
) -> None:
    """Generate simple flow config file."""
    # Check if flow_config has a "flow" key
    flow_config_data = flow_config.get("flow", {})
    if flow_config_data:
        flow_config_data["flow"] = flow_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]

        flow_config_yaml = yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_flow_output_file_name("flow", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(flow_config_yaml, encoding="utf-8")
    else:
        # Simple flow config without "flow" key - just use the flow_config as-is
        # Add flow name and basic info
        flow_config_data = flow_config.copy()
        flow_config_data["flow"] = flow_name
        render_targets = merged_config.get("render_targets", {})
        render_target_info = render_targets.get(workflow, {})
        flow_config_data["workflow"] = render_target_info.get("name", "")
        flow_config_data["target"] = render_target_info.get("target_family", "")
        flow_config_data["env"] = render_target_info.get("profiles", [env])[0]
        flow_config_data["version"] = render_target_info.get("versions", [env])[0]

        flow_config_yaml = yaml.safe_dump(flow_config_data, sort_keys=False, allow_unicode=True)
        output_file_name = get_flow_output_file_name("flow", merged_config)
        # Create parent directories before writing
        output_path.mkdir(parents=True, exist_ok=True)
        (output_path / output_file_name).write_text(flow_config_yaml, encoding="utf-8")


def get_flow_output_file_name(file_type: str, merged_config: Dict[str, Any], p: str = "") -> str:
    """Get the output file name for a flow config."""
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
