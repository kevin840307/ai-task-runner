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
        Pair("#newTaskModal .task-input-grid", ".task-workspace-input-grid", ("grid-template-columns", "gap", "align-items", "margin-top")),
        Pair(".source-card", ".task-workspace-source-card", ("border", "border-radius", "background", "overflow")),
        Pair(".source-head", ".task-workspace-source-head", ("padding", "border-bottom", "background", "margin-bottom")),
        Pair(".source-body", ".task-workspace-source-body", ("padding", "gap")),
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
            "#newTaskModal .task-primary-source .source-tabs button",
            ".task-workspace-task-primary-source .task-workspace-source-tabs button",
            ("width", "min-width", "height", "padding", "white-space", "overflow", "text-overflow"),
        ),
        Pair("#newTaskModal .task-primary-source .task-source-mode-panel>textarea", ".task-workspace-task-primary-source .task-workspace-source-mode-panel>textarea", ("min-height",)),
        Pair("#newTaskModal .task-ai-source .task-source-mode-panel>textarea", ".task-workspace-task-ai-source .task-workspace-source-mode-panel>textarea", ("min-height",)),
        Pair(".workspace-option", ".task-workspace-workspace-option", ("min-height", "padding", "border-radius", "background")),
        Pair(".drawer", ".task-workspace-shell", ("transform", "transition")),
        Pair(".overlay.open .drawer", ".task-workspace-overlay.open .task-workspace-shell", ("transform",)),
    ),
)

TASK_LIST = PanelSpec(
    "ui/static/css/task-workspace.css",
    (
        Pair(".plan-page-body", ".task-workspace-list-page", ("grid-template-columns", "gap", "padding")),
        Pair(".plan-main", ".task-workspace-list-main", ("padding", "border-radius")),
        Pair(".plan-side", ".task-workspace-list-side", ("display", "gap", "align-content")),
        Pair(".plan-side-card", ".task-workspace-list-side-card", ("padding", "border-radius", "background")),
        Pair(".plan-add-task-footer", ".task-workspace-add-task-footer", ("width", "min-height", "gap", "margin-top", "border-radius", "font-size")),
        Pair(".plan-row-compact[draggable=\"true\"]", ".task-workspace-list-row[draggable=\"true\"]", ("cursor",)),
        Pair(".draft-plan-row", ".task-workspace-list-row[draggable=\"true\"]", ("transition",)),
        Pair(".plan-row-compact.dragging", ".task-workspace-list-row.dragging", ("opacity",)),
        Pair(".plan-row-compact.drag-over", ".task-workspace-list-row.drag-over", ("outline", "outline-offset")),
        Pair(".plan-row-head>.drag-grip", ".task-workspace-drag-grip", ("width", "height", "font-size")),
        Pair(".plan-workspace-chip", ".task-workspace-list-chip", ("font-size", "font-weight")),
        Pair(".plan-page-body", ".task-workspace-list-page", ("grid-template-columns",), feature_media="max-width:960px", production_media="max-width:960px"),
        Pair(".plan-side", ".task-workspace-list-side", ("grid-template-columns",), feature_media="max-width:960px", production_media="max-width:960px"),
    ),
)

BOARD = PanelSpec(
    "ui/static/css/tasks-board.css",
    (
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
