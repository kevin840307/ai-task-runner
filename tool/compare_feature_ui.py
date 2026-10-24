"""Compare production Task UI CSS against the accepted feature prototype.

The comparator is intentionally selector/property based instead of screenshot based so it is
stable in CI and points directly at the declaration that drifted.  It models semantic panel
ownership where production splits one prototype surface across multiple elements.
"""
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).replace(" !important", "!important")


@dataclass(frozen=True)
class Rule:
    media: str | None
    selectors: tuple[str, ...]
    declarations: dict[str, str]


@dataclass(frozen=True)
class Pair:
    feature_selector: str
    production_selector: str
    properties: tuple[str, ...]
    feature_media: str | None = None
    production_media: str | None = None


@dataclass(frozen=True)
class PanelSpec:
    production_path: str
    pairs: tuple[Pair, ...]


def _matching_brace(source: str, open_index: int) -> int:
    depth = 1
    quote: str | None = None
    index = open_index + 1
    while index < len(source):
        char = source[index]
        if quote:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    raise ValueError("unbalanced CSS braces")


def rules(source: str, *, media: str | None = None) -> list[Rule]:
    result: list[Rule] = []
    index = 0
    while index < len(source):
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            index = len(source) if end < 0 else end + 2
            continue
        if source[index].isspace():
            index += 1
            continue

        open_index = source.find("{", index)
        if open_index < 0:
            break
        semicolon = source.find(";", index, open_index)
        if semicolon >= 0:
            index = semicolon + 1
            continue

        header = source[index:open_index].strip()
        close_index = _matching_brace(source, open_index)
        body = source[open_index + 1 : close_index]

        if header.startswith("@media"):
            query = normalize(header[len("@media") :])
            result.extend(rules(body, media=query))
        elif not header.startswith("@"):
            declarations_map: dict[str, str] = {}
            for raw in body.split(";"):
                if ":" not in raw:
                    continue
                key, value = raw.split(":", 1)
                declarations_map[key.strip()] = normalize(value)
            selectors = tuple(normalize(part) for part in header.split(","))
            result.append(Rule(media=media, selectors=selectors, declarations=declarations_map))
        index = close_index + 1
    return result


def declarations(
    css: str,
    selector: str,
    *,
    media_contains: str | None = None,
) -> dict[str, str]:
    wanted = normalize(selector)
    result: dict[str, str] = {}
    found = False
    for rule in rules(css):
        if media_contains is None:
            if rule.media is not None:
                continue
        elif rule.media is None or normalize(media_contains) not in normalize(rule.media):
            continue
        if wanted not in rule.selectors:
            continue
        found = True
        result.update(rule.declarations)
    if not found:
        raise ValueError(f"selector not found ({media_contains or 'base'}): {selector}")
    return result


TASK_EDITOR = PanelSpec(
    "ui/static/css/task-workspace.css",
    (
        Pair("#newTaskModal>.modal-body", ".task-workspace-shell.task-editor-route .task-workspace-body", ("padding",)),
        Pair("#newTaskModal .task-basics", ".task-workspace-basics", ("grid-template-columns", "gap", "align-items")),
        Pair(".field", ".task-workspace-basics>.task-workspace-field", ("margin-top",)),
        Pair("#newTaskModal .task-basics label", ".task-workspace-basics .task-workspace-field>span", ("margin-bottom",)),
        Pair(".field label", ".task-workspace-basics .task-workspace-field>span", ("font-size", "font-weight", "text-transform", "letter-spacing")),
        Pair(".field input", ".task-workspace-basics .task-workspace-field input", ("padding",)),
        Pair(".field select", ".task-workspace-basics .task-workspace-field select", ("padding",)),
        Pair("#newTaskModal .task-input-grid", ".task-workspace-input-grid", ("grid-template-columns", "gap", "align-items", "margin-top")),
        Pair(".source-card", ".task-workspace-source-card", ("border", "border-radius", "background", "overflow")),
        Pair(".source-head", ".task-workspace-source-head", ("padding", "border-bottom", "background", "margin-bottom")),
        Pair(".source-body", ".task-workspace-source-body", ("padding", "gap")),
        Pair(
            ".source-note",
            ".task-workspace-shell.task-editor-route .task-workspace-source-note",
            ("border-radius", "background"),
        ),
        Pair(
            "#newTaskModal .source-note",
            ".task-workspace-shell.task-editor-route .task-workspace-source-note",
            ("padding", "font-size", "line-height"),
        ),
        Pair(
            ".file-upload-hint",
            ".task-workspace-file-upload-hint",
            ("display", "align-items", "gap", "min-width", "border", "border-radius", "background", "font-size"),
        ),
        Pair(
            "#newTaskModal .file-upload-hint",
            ".task-workspace-shell.task-editor-route .task-workspace-file-upload-hint",
            ("padding",),
        ),
        Pair(
            ".file-upload-hint strong",
            ".task-workspace-file-upload-hint strong",
            ("flex", "min-width", "overflow", "text-overflow", "white-space"),
        ),
        Pair(".file-upload-hint span", ".task-workspace-file-upload-hint span", ("color",)),
        Pair(
            "#newTaskModal .task-primary-source .source-tabs",
            ".task-workspace-task-primary-source .task-workspace-source-tabs",
            ("display", "grid-template-columns", "width", "min-width", "gap", "box-sizing", "height"),
        ),
        Pair(
            "#newTaskModal .task-ai-source .source-tabs",
            ".task-workspace-task-ai-source .task-workspace-source-tabs",
            ("display", "grid-template-columns", "width", "min-width", "gap", "box-sizing", "height"),
        ),
        Pair(
            "#newTaskModal .task-primary-source .source-head strong",
            ".task-workspace-task-primary-source .task-workspace-source-head strong",
            ("font-size",),
        ),
        Pair(
            "#newTaskModal .task-primary-source .source-head small",
            ".task-workspace-task-primary-source .task-workspace-source-head small",
            ("font-size",),
        ),
        Pair(
            "#newTaskModal .task-file-source .cap-chip",
            ".task-workspace-task-file-source .task-workspace-required-chip",
            ("font-size",),
        ),
        Pair("#newTaskModal .task-ai-source", ".task-workspace-task-ai-source", ("opacity",)),
        Pair(
            "#newTaskModal .task-editor-secondary",
            ".task-workspace-editor-secondary",
            ("margin-top", "padding"),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-selector-title",
            ".task-workspace-editor-secondary .task-workspace-workspace-head",
            ("margin-bottom",),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-options",
            ".task-workspace-editor-secondary .task-workspace-workspace-options",
            ("gap",),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-option",
            ".task-workspace-editor-secondary .task-workspace-workspace-option",
            ("min-height", "padding"),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-option small",
            ".task-workspace-editor-secondary .task-workspace-workspace-option small",
            ("margin-top", "font-size", "line-height"),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-option .workspace-status",
            ".task-workspace-editor-secondary .task-workspace-workspace-status",
            ("margin-top", "font-size"),
        ),
        Pair(
            "#newTaskModal .task-editor-secondary .workspace-preview",
            ".task-workspace-editor-secondary .task-workspace-workspace-preview",
            ("margin-top", "padding", "font-size", "line-height"),
        ),
        Pair(
            "#newTaskModal .task-primary-source .source-tabs button",
            ".task-workspace-task-primary-source .task-workspace-source-tabs button",
            ("width", "min-width", "height", "padding", "white-space", "overflow", "text-overflow"),
        ),
        Pair(
            "#newTaskModal .task-ai-source .source-tabs button",
            ".task-workspace-task-ai-source .task-workspace-source-tabs button",
            ("width", "min-width", "height", "padding", "white-space", "overflow", "text-overflow"),
        ),
        Pair(
            "#newTaskModal .task-source-mode-panel",
            ".task-workspace-source-mode-panel",
            ("width", "min-width", "box-sizing", "display", "flex-direction", "gap"),
        ),
        Pair("#newTaskModal .task-primary-source .task-source-mode-panel>textarea", ".task-workspace-task-primary-source .task-workspace-source-mode-panel>textarea", ("min-height",)),
        Pair("#newTaskModal .task-ai-source .task-source-mode-panel>textarea", ".task-workspace-task-ai-source .task-workspace-source-mode-panel>textarea", ("min-height",)),
        Pair(
            ".pathrow input",
            ".task-workspace-path-row input",
            ("width", "height", "padding", "border", "border-radius", "background", "color", "font-size"),
        ),
        Pair(
            "#newTaskModal .task-upload-btn",
            ".task-workspace-upload",
            ("border-color", "background", "color"),
        ),
        Pair(
            ".mini-btn",
            ".task-workspace-upload",
            ("height", "padding", "border-radius", "font-size", "font-weight"),
        ),
        Pair(".workspace-option", ".task-workspace-workspace-option", ("min-height", "padding", "border-radius", "background")),
        Pair(".overlay", ".task-workspace-overlay", ("position", "inset", "overflow", "background", "backdrop-filter")),
        Pair(
            ".drawer",
            ".task-workspace-shell",
            ("width", "max-width", "height", "min-width", "display", "border-left", "background", "box-shadow", "transform", "transition"),
        ),
        Pair(".drawer.workspace-route", ".task-workspace-shell.workspace-route", ("width", "max-width")),
        Pair(".drawerhead", ".task-workspace-head", ("padding", "border-bottom")),
        Pair(".drawerheadtop", ".task-workspace-head", ("display", "gap", "align-items")),
        Pair(".drawerhead h2", ".task-workspace-heading strong", ("font-size", "line-height", "white-space", "overflow", "text-overflow")),
        Pair(".drawer-back", ".task-workspace-back", ("width", "height", "border", "border-radius", "background", "font-size", "font-weight")),
        Pair(".drawerfoot", ".task-workspace-foot", ("display", "align-items", "justify-content", "flex-wrap", "gap", "height", "min-height", "max-height", "overflow", "padding", "border-top", "background")),
        Pair(".drawerfoot .btn", ".task-workspace-foot button", ("height", "min-height", "max-height", "padding-block", "line-height", "white-space")),
        Pair("#newTaskModal>.modal-foot", ".task-workspace-shell.task-editor-route .task-workspace-foot", ("padding",)),
        Pair(".overlay.open .drawer", ".task-workspace-overlay.open .task-workspace-shell", ("transform",)),
    ),
)

TASK_LIST = PanelSpec(
    "ui/static/css/task-workspace.css",
    (
        Pair(".plan-page-body", ".task-workspace-list-page", ("grid-template-columns", "gap", "padding")),
        Pair("#planModal .plan-page-body", ".task-workspace-list-page", ("min-height", "height", "overflow")),
        Pair(".plan-main", ".task-workspace-list-main", ("padding", "border-radius")),
        Pair("#planModal .plan-main", ".task-workspace-list-main", ("min-height", "overflow")),
        Pair(".plan-side", ".task-workspace-list-side", ("display", "gap", "align-content")),
        Pair("#planModal .plan-side", ".task-workspace-list-side", ("min-height", "overflow")),
        Pair(".plan-side-card", ".task-workspace-list-side-card", ("padding", "border-radius", "background")),
        Pair(
            ".plan-add-task-footer",
            ".task-workspace-add-task-footer",
            ("width", "min-height", "display", "align-items", "justify-content", "gap", "margin-top", "border", "border-radius", "background", "color", "font-size", "font-weight", "cursor"),
        ),
        Pair(".plan-row-compact[draggable=\"true\"]", ".task-workspace-list-row[draggable=\"true\"]", ("cursor",)),
        Pair(".draft-plan-row", ".task-workspace-list-row[draggable=\"true\"]", ("transition",)),
        Pair(".plan-row-compact.dragging", ".task-workspace-list-row.dragging", ("opacity",)),
        Pair(".plan-row-compact.drag-over", ".task-workspace-list-row.drag-over", ("outline", "outline-offset")),
        Pair(
            ".plan-row-head>.drag-grip",
            ".task-workspace-drag-grip",
            ("width", "height", "margin", "color", "font-size", "font-weight", "line-height", "cursor", "user-select"),
        ),
        Pair(
            ".plan-workspace-chip",
            ".task-workspace-list-chip",
            ("padding", "border-radius", "background", "color", "font-size", "font-weight"),
        ),
        Pair(
            ".plan-workspace-chip.worktree",
            ".task-workspace-list-chip.worktree",
            ("background", "color", "border", "font-weight", "letter-spacing"),
        ),
        Pair(".plan-row", ".task-workspace-list-row", ("border", "border-radius", "background", "overflow")),
        Pair(".plan-row-head", ".task-workspace-list-row", ("padding",)),
        Pair(".plan-row-compact .plan-row-head", ".task-workspace-list-row", ("min-height",)),
        Pair(
            ".plan-row-compact .plan-row-head",
            ".task-workspace-list-row:not(.task-workspace-info-row)",
            ("grid-template-columns", "column-gap", "align-items"),
        ),
        Pair(
            ".plan-row-num",
            ".task-workspace-list-number",
            ("width", "height", "margin", "display", "place-items", "line-height", "align-self"),
        ),
        Pair(".plan-intro", ".task-workspace-list-intro", ("display", "align-items", "justify-content", "gap", "margin-bottom")),
        Pair("#planModal .plan-intro", ".task-workspace-list-intro", ("padding-bottom", "border-bottom")),
        Pair(".plan-intro strong", ".task-workspace-list-intro strong", ("display", "font-size")),
        Pair(
            ".plan-intro span:not(.pill)",
            ".task-workspace-list-intro span:not(.task-workspace-list-state-pill)",
            ("display", "margin-top", "color", "font-size"),
        ),
        Pair(".plan-list", ".task-workspace-list", ("display", "gap")),
        Pair(".plan-row-copy strong", ".task-workspace-list-copy strong", ("font-size",)),
        Pair(
            ".plan-row-copy small",
            ".task-workspace-list-copy small",
            ("margin-top", "font-size", "white-space", "overflow", "text-overflow", "max-width"),
        ),
        Pair(".plan-row-actions", ".task-workspace-list-actions", ("display", "align-items", "gap")),
        Pair(
            ".plan-row-controls button",
            ".task-workspace-list-actions button",
            ("height", "min-width", "padding", "border", "border-radius", "background", "color", "font-size"),
        ),
        Pair(".plan-side-card h3", ".task-workspace-list-side-card h3", ("margin", "font-size", "text-transform", "letter-spacing")),
        Pair(".plan-side-card p", ".task-workspace-list-side-card p", ("margin", "font-size", "line-height")),
        Pair(".plan-side-kv", ".task-workspace-list-kv", ("display", "grid-template-columns", "gap", "font-size")),
        Pair(".empty-plan-cta", ".task-workspace-empty-list-cta", ("width", "display", "align-items", "gap", "padding", "border-radius", "text-align", "cursor")),
        Pair(".empty-plan-cta.large", ".task-workspace-empty-list-cta", ("min-height", "justify-content", "flex-direction")),
        Pair(".empty-plan-cta strong", ".task-workspace-empty-list-cta strong", ("font-size",)),
        Pair(".empty-plan-cta span", ".task-workspace-empty-list-cta span", ("font-size", "font-weight")),
        Pair(".plan-page-body", ".task-workspace-list-page", ("grid-template-columns",), feature_media="max-width:960px", production_media="max-width:960px"),
        Pair(".plan-side", ".task-workspace-list-side", ("grid-template-columns",), feature_media="max-width:960px", production_media="max-width:960px"),
        Pair(".plan-page-body", ".task-workspace-list-page", ("grid-template-columns",), feature_media="max-width:900px", production_media="max-width:900px"),
        Pair(".plan-side", ".task-workspace-list-side", ("display",), feature_media="max-width:900px", production_media="max-width:900px"),
        Pair("#planModal .plan-page-foot", ".task-workspace-foot", ("display", "justify-content", "gap", "padding", "border-top", "background")),
        Pair(
            ".task-context-menu",
            ".task-workspace-context-menu",
            ("position", "z-index", "width", "padding", "border", "border-radius", "background", "box-shadow"),
        ),
        Pair(".task-context-actions", ".task-workspace-context-actions", ("padding",)),
        Pair(
            ".task-context-menu button",
            ".task-workspace-context-menu button",
            ("display", "align-items", "justify-content", "width", "padding", "border", "border-radius", "background", "color", "font-size", "text-align", "cursor"),
        ),
        Pair(".task-context-menu button:disabled", ".task-workspace-context-menu button:disabled", ("opacity", "cursor")),
        Pair(".task-context-menu .danger-item", ".task-workspace-context-menu .danger-item", ("color",)),
        Pair(".task-context-menu kbd", ".task-workspace-context-menu kbd", ("font", "color")),
        Pair(".context-separator", ".task-workspace-context-separator", ("height", "margin", "background")),
    ),
)

BOARD = PanelSpec(
    "ui/static/css/tasks-board.css",
    (
        Pair(".tasks-project-trigger strong", ".tasks-project-trigger .stateful-content", ("max-width",)),
        Pair(".boardtools", ".tasks-board-toolbar", ("padding", "border-bottom", "background")),
        Pair(".search", ".tasks-board-search", ("width", "height", "padding", "border", "border-radius", "background", "color")),
        Pair(".toggle", ".tasks-view-toggle", ("padding", "border", "border-radius", "background")),
        Pair(".toggle button", ".tasks-view-toggle button", ("height", "padding", "border-radius", "background", "color", "font-size", "font-weight")),
        Pair(".board", ".tasks-board-columns", ("display", "grid-template-columns", "gap")),
        Pair(".board", ".tasks-board-content", ("overflow", "padding")),
        Pair(".col", ".tasks-board-column", ("min-width", "display", "flex-direction", "min-height", "border", "border-radius", "background")),
        Pair(".colhead", ".tasks-board-column-head", ("display", "align-items", "gap", "min-height", "padding", "border-bottom")),
        Pair(".dropzone", ".tasks-board-dropzone", ("min-height", "overflow", "padding", "display", "flex-direction", "gap")),
        Pair(".taskcard", ".tasks-board-card", ("padding", "border-radius", "cursor")),
        Pair(".taskcard:hover", ".tasks-board-card:hover", ("transform",)),
        Pair(".taskcard.dragging", ".tasks-board-card.dragging", ("opacity",)),
        Pair(".handle", ".tasks-board-card-handle", ("font-size", "letter-spacing", "user-select")),
        Pair(".tasktitle", ".tasks-board-card-title", ("font-size", "font-weight", "line-height")),
        Pair(".cardmeta", ".tasks-board-card-meta", ("display", "align-items", "gap", "flex-wrap")),
        Pair(".progress", ".tasks-board-progress", ("display", "align-items", "gap")),
        Pair(".bar", ".tasks-board-progress-bar", ("width", "height", "border-radius", "overflow")),
    ),
)

PANELS = {"task-editor": TASK_EDITOR, "task-list": TASK_LIST, "board": BOARD}


def compare_panel(panel: str, *, root: Path = ROOT) -> list[str]:
    spec = PANELS[panel]
    feature_css = (root / "feature" / "ui-prototype" / "styles.css").read_text(encoding="utf-8")
    production_css = (root / spec.production_path).read_text(encoding="utf-8")
    drift: list[str] = []
    for pair in spec.pairs:
        try:
            feature = declarations(feature_css, pair.feature_selector, media_contains=pair.feature_media)
            production = declarations(production_css, pair.production_selector, media_contains=pair.production_media)
        except ValueError as exc:
            drift.append(str(exc))
            continue
        for prop in pair.properties:
            expected = feature.get(prop)
            actual = production.get(prop)
            if expected != actual:
                drift.append(
                    f"{panel}: {pair.production_selector} {prop}={actual!r}; "
                    f"prototype {pair.feature_selector}={expected!r}"
                )
    return drift


def compare_panels(panels: Iterable[str], *, root: Path = ROOT) -> list[str]:
    return [item for panel in panels for item in compare_panel(panel, root=root)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", choices=(*PANELS, "all"), default="all")
    args = parser.parse_args()
    selected = PANELS if args.panel == "all" else (args.panel,)
    drift = compare_panels(selected)
    if drift:
        print("\n".join(drift))
        return 1
    print("Feature Task UI parity: OK (" + ", ".join(selected) + ")")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
