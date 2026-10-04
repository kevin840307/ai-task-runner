from __future__ import annotations

from pathlib import Path

from runner.workflow.registry import workflow_catalog


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "ui" / "studio-src" / "src" / "main.tsx").read_text(encoding="utf-8")


def test_react_workflow_editor_uses_runtime_catalog_for_stage_options():
    catalog = workflow_catalog()
    assert catalog["stage_types"]

    # The production React editor must source Stage types/options from the runtime catalog,
    # then render ordinary options through the generic Field component.
    assert 'catalog.stage_types[draft.type]?.options || []' in SOURCE
    assert 'Object.keys(catalog?.stage_types || {})' in SOURCE
    assert '<Field' in SOURCE
    assert 'key={option.name}' in SOURCE
    assert 'value={draft[option.name]}' in SOURCE
    special_catalog_fields = {"status", "targets", "max_failures"}
    observed = {
        option["name"]
        for stage in catalog["stage_types"].values()
        for option in stage["options"]
    }
    unknown_special = special_catalog_fields - observed
    # Some plugins/builds may omit one special field, but built-ins currently expose all three.
    assert not unknown_special, f"Expected built-in catalog fields disappeared: {sorted(unknown_special)}"

    # Fields filtered out of the generic parameter list must have an explicit UI owner.
    # Backend/model/session ownership is projected by catalog constraints rather than a frontend name list.
    assert 'executionTargetNames.has(o.name)' in SOURCE
    assert 'const executionTargetOptions = options.filter((o) => executionTargetNames.has(o.name))' in SOURCE
    assert 'const executionPair = executionConstraint?.paired_fields || []' in SOURCE
    assert 'value={String(draft.status || "")}' in SOURCE
    assert 'draft.type === "handoff"' in SOURCE and 'stage.targets || []' in SOURCE
    assert 'draft.max_failures' in SOURCE and 'max_failures' in SOURCE

    # Prompt is catalog-driven but intentionally gets a richer selector instead of a plain input.
    assert 'option.name === "prompt"' in SOURCE
    assert 'effectivePrompt(catalog, draft)' in SOURCE


def test_react_workflow_editor_covers_all_node_level_runtime_options():
    node_options = workflow_catalog()["node_options"]
    assert set(node_options) == {"label", "validator", "routes", "error_policy"}

    assert 'value={String(draft.label || "")}' in SOURCE
    assert 'value={String(draft.profile || "generic")}' in SOURCE
    assert 'value={draft.scope || ""}' not in SOURCE
    draft_model = (ROOT / "ui" / "studio-src" / "src" / "workflow-draft.ts").read_text(encoding="utf-8")
    assert 'const routes = (stage.routes || {}) as Record<string, string>' in draft_model
    assert 'stage.routes || {}' in draft_model
    assert 'draft.error_policy?.retries' in SOURCE

    # Graph result routes are semantic PASS/FAIL only. Handoff targets are a Stage-owned
    # dynamic edge list and technical ERROR remains StageExecutor policy, not a graph edge.
    draft = (ROOT / "ui" / "studio-src" / "src" / "workflow-draft.ts").read_text(encoding="utf-8")
    assert '!["pass", "fail", "handoff"].includes(status)' in draft
    assert 'delete routes[status]' in draft
    assert 'targets: (stage.targets || []).filter' in draft


def test_generic_field_renderer_supports_every_catalog_scalar_shape():
    catalog = workflow_catalog()
    option_types = {
        str(option.get("type", "")).lower()
        for stage in catalog["stage_types"].values()
        for option in stage["options"]
        if option["name"] not in {"targets"}
    }

    # Object-valued runtime controls are owned explicitly at node/routing level. Ordinary
    # catalog fields must remain representable by the generic enum/bool/number/list/text UI.
    unsupported = {
        value for value in option_types
        if value and not (
            value in {"string", "str", "bool", "boolean", "optional_boolean", "enum"}
            or "int" in value
            or "float" in value
            or "list" in value
            or "optional" in value
            or "literal" in value
            or "union" in value
            or "callable" in value
        )
    }
    assert not unsupported, f"React generic Field needs a renderer for catalog types: {sorted(unsupported)}"

    assert 'type === "optional_boolean"' in SOURCE
    assert 'type === "bool" || type === "boolean"' in SOURCE
    assert 'type.includes("int")' in SOURCE
    assert 'type.includes("float")' in SOURCE
    assert 'type.includes("list")' in SOURCE
    assert 'option.values?.length || type === "enum"' in SOURCE


def test_ai_stage_profile_catalog_is_extensible():
    catalog = workflow_catalog()
    base = catalog["stage_types"]["base"]
    profile = next(option for option in base["options"] if option["name"] == "profile")
    assert profile["type"] == "enum"
    assert profile["values"] == ["generic", "execute", "review"]
    mode = next(option for option in base["options"] if option["name"] == "mode")
    assert mode["type"] == "enum"
    assert mode["values"] == ["readonly", "write"]
    assert "scope" not in catalog["node_options"]
    assert "task" not in catalog["stage_types"]
    assert "review" not in catalog["stage_types"]
