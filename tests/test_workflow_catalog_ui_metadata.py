from runner.workflow.registry import workflow_catalog


def test_workflow_catalog_exposes_stage_presentation_metadata():
    catalog = workflow_catalog()
    stage_types = catalog["stage_types"]

    base = stage_types["base"]
    options = {item["name"]: item for item in base["options"]}
    assert options["prompt"]["section"] == "content"
    assert options["backend"]["section"] == "execution"
    assert options["parser"]["section"] == "result"
    assert options["ai_validator_yolo"]["section"] == "advanced" if "ai_validator_yolo" in options else True

    assert base["profiles"]["execute"]["test_examples"]["pass"]
    assert base["profiles"]["review"]["test_examples"]["fail"]
    assert stage_types["plan"]["test_examples"]["pass"]
    assert stage_types["handoff"]["test_examples"]["error"]


def test_unknown_plugin_fields_default_to_advanced_without_ui_branching():
    from dataclasses import dataclass, field
    from runner.workflow.registry import _field_info

    @dataclass
    class Example:
        custom: str = field(default="", metadata={"ui_section": "content"})
        future_toggle: bool = False

    fields = Example.__dataclass_fields__
    assert _field_info(fields["custom"])["section"] == "content"
    assert _field_info(fields["future_toggle"])["section"] == "advanced"
