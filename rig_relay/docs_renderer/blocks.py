"""Block renderers for documentation page content."""

from __future__ import annotations

import html as _html

from rig_relay.docs_renderer.diagrams import render_diagram_ref
from rig_relay.docs_renderer.disclosure import build_disclosure, wrap_collapsible


def render_heading(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    hlevel = min(max(block.get("level", 2), 1), 6)
    return f'<h{hlevel} id="{bid}" class="{css_cls}"{data_attrs}>{content}</h{hlevel}>'


def render_paragraph(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    return f'<p id="{bid}" class="{css_cls}"{data_attrs}>{content}</p>'


def render_callout(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    severity = block.get("severity", "info")
    return (
        f'<div class="callout callout-{severity} {css_cls}" id="{bid}"{data_attrs}>\n'
        f"  {f'<strong>{title}</strong>' if title else ''}\n"
        f"  <p>{content}</p>\n"
        f"</div>"
    )


def render_list(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    tag = "ol" if block.get("ordered") else "ul"
    items = block.get("items", [])
    items_html = "\n".join(f"  <li>{_html.escape(str(i))}</li>" for i in items)
    return f'<{tag} id="{bid}" class="{css_cls}"{data_attrs}>\n{items_html}\n</{tag}>'


def render_table(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    columns = block.get("columns", [])
    rows = block.get("rows", [])
    head = (
        "<thead><tr>"
        + "".join(f"<th>{_html.escape(str(c))}</th>" for c in columns)
        + "</tr></thead>"
    )
    tbody = (
        "<tbody>\n"
        + "\n".join(
            "<tr>"
            + "".join(f"<td>{_html.escape(str(cell))}</td>" for cell in row)
            + "</tr>"
            for row in rows
        )
        + "\n</tbody>"
    )
    return (
        f'<table id="{bid}" class="{css_cls}"{data_attrs}>\n{head}\n{tbody}\n</table>'
    )


def render_code(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    language = block.get("language", "")
    lang_attr = f' class="language-{_html.escape(language)}"' if language else ""
    return f'<pre id="{bid}"><code{lang_attr}>{content}</code></pre>\n'


def render_json(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    return f'<pre id="{bid}"><code class="language-json">{content}</code></pre>\n'


def render_evidence(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    btype = block.get("type", "risk")
    return (
        f'<div class="{btype} {css_cls}" id="{bid}"{data_attrs}>\n'
        f"  {f'<h4>{title}</h4>' if title else ''}\n"
        f"  <p>{content}</p>\n"
        f"</div>"
    )


def render_link(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    href = _html.escape(str(block.get("href", "")), quote=True)
    return f'<p id="{bid}" class="{css_cls}"{data_attrs}><a href="{href}">{content}</a></p>'


def render_file_ref(
    block: dict, content: str, title: str, bid: str, css_cls: str, data_attrs: str
) -> str:
    path = _html.escape(str(block.get("path", "")))
    return (
        f'<p class="file-ref {css_cls}" id="{bid}"{data_attrs}><code>{path}</code></p>'
    )


BLOCK_RENDERERS: dict[str, object] = {
    "heading": render_heading,
    "paragraph": render_paragraph,
    "callout": render_callout,
    "list": render_list,
    "table": render_table,
    "code": render_code,
    "json": render_json,
    "risk": render_evidence,
    "decision": render_evidence,
    "test_evidence": render_evidence,
    "link": render_link,
    "file_reference": render_file_ref,
}


def render_block(block: dict, doc_disc: dict | None = None) -> str:
    btype = block.get("type", "paragraph")

    if btype == "diagram_ref":
        return render_diagram_ref(block)

    if btype == "mermaid":
        code = _html.escape(str(block.get("content", "")))
        bid = _html.escape(str(block.get("block_id", "")), quote=True)
        return f'<div class="mermaid-block" id="{bid}"><pre><code class="language-mermaid">{code}</code></pre></div>'

    if btype == "schema_ref":
        ref = _html.escape(str(block.get("schema_ref", "")))
        bid = _html.escape(str(block.get("block_id", "")), quote=True)
        return f'<p id="{bid}" class="file-ref"><code>{ref}</code></p>'

    content = _html.escape(str(block.get("content", "")))
    title = _html.escape(str(block.get("title", "")))
    bid = _html.escape(str(block.get("block_id", "")), quote=True)

    collapsible, collapsed, visible, css_cls, data_attrs = build_disclosure(
        block, doc_disc
    )

    renderer = BLOCK_RENDERERS.get(btype)
    if renderer is None:
        body = f'<p id="{bid}" class="{css_cls}"{data_attrs}>{content}</p>'
    else:
        body = renderer(block, content, title, bid, css_cls, data_attrs)  # type: ignore[operator]

    if btype in {"code", "json"}:
        return body

    return wrap_collapsible(
        body, bid, css_cls, data_attrs, collapsible, visible, collapsed, title, content
    )
