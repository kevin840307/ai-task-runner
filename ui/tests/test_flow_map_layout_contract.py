from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "static"


def test_workflow_flow_header_keeps_actions_on_one_row_and_visual_panel_has_no_phantom_gap():
    flow_css = (ROOT / "css" / "workflow-flow-map.css").read_text(encoding="utf-8")
    css = "".join(flow_css.split())
    assert ".workflow-page.designer-panel-actions{display:flex!important;flex-flow:rownowrap!important" in css
    assert ".workflow-page.designer-panel-actionsbutton{flex:00auto" in css
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" not in css
    assert ".workflow-page.studio-workflow-editor:has(>.validation-output[hidden]){grid-template-rows:autominmax(0,1fr)!important" in css
    assert "height:auto!important;align-self:stretch" in css


def test_dense_flow_map_defaults_to_core_view_with_all_routes_toggle():
    flow_js = (ROOT / "js" / "workflow-flow-map.js").read_text(encoding="utf-8")
    assert 'const dense = allNodes.length > 20 || allEdges.length > 28' in flow_js
    assert 'effectiveMode === "core"' in flow_js
    assert "Show all routes" in flow_js
    assert "Simplify routes" in flow_js
    assert "flow-map-density-toggle" in flow_js
