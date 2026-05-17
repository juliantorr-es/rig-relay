"""Disclosure metadata and collapsible wrapping for documentation blocks."""

from __future__ import annotations

import html as _html


def build_disclosure(
    block: dict, doc_disc: dict | None
) -> tuple[bool, bool, bool, str, str]:
    disc = block.get("disclosure", {})
    ddoc = doc_disc or {}
    level = disc.get("level") or ddoc.get("default_level", "standard")
    collapsible: bool = disc.get("collapsible", False)
    collapsed: bool = disc.get("collapsed_by_default", False)
    visible: bool = disc.get("initially_visible", True)
    audience: list[str] = disc.get("audience", [])
    hint = disc.get("render_hint", {})
    variant = hint.get("variant", "plain")
    emphasis = hint.get("emphasis", "normal")

    if (
        level in {"detailed", "exhaustive"}
        and not disc.get("collapsible")
        and not disc.get("initially_visible")
    ):
        collapsible = True
        collapsed = True

    css_parts = [f"disclosure-{level}"]
    if variant != "plain":
        css_parts.append(f"render-variant-{variant}")
    if emphasis != "normal":
        css_parts.append(f"emphasis-{emphasis}")
    css_cls = " ".join(css_parts)

    data_attrs = f' data-disclosure-level="{level}"'
    if audience:
        data_attrs += ' data-disclosure-audience="' + " ".join(audience) + '"'
    if collapsible:
        data_attrs += ' data-collapsible="true"'
    if collapsed:
        data_attrs += ' data-collapsed-default="true"'
    return collapsible, collapsed, visible, css_cls, data_attrs


def wrap_collapsible(
    body: str,
    bid: str,
    css_cls: str,
    data_attrs: str,
    collapsible: bool,
    visible: bool,
    collapsed: bool,
    title: str,
    content: str,
) -> str:
    if not collapsible:
        return body + "\n"
    summary_text = _html.escape(title or content[:100])
    open_attr = " open" if visible and not collapsed else ""
    return (
        f'<details id="{bid}" class="disclosure-collapsible {css_cls}"'
        f"{data_attrs}{open_attr}>"
        f"<summary>{summary_text}</summary>"
        f"{body}"
        f"</details>\n"
    )
