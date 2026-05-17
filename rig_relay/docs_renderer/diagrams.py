"""Schema-driven diagram rendering for static documentation site.

Supports: flow, state_machine, timeline, matrix, dependency_graph.
Unsupported kinds render placeholder cards.
"""

from __future__ import annotations

from collections.abc import Callable
import html as _html
import json

from rig_relay.docs_renderer.data_sources import load_source
from rig_relay.docs_renderer.paths import REPO_ROOT

_STATUS_COLORS: dict[str, str] = {
    "active": "#2563eb",
    "completed": "#059669",
    "pending": "#6b7280",
    "error": "#dc2626",
    "inactive": "#d1d5db",
}

_ARROW_MARKER = (
    '<marker id="arrowhead" markerWidth="10" markerHeight="7" '
    'refX="10" refY="3.5" orient="auto">'
    '<polygon points="0 0, 10 3.5, 0 7" fill="#6b7280"/></marker>'
)


def _load_diagram_spec(path: str) -> dict:
    file_path = (REPO_ROOT / path).resolve()
    if not str(file_path).startswith(str(REPO_ROOT.resolve())):
        raise ValueError(f"Path outside repo: {path}")
    if not file_path.is_file():
        raise FileNotFoundError(f"Diagram spec not found: {path}")
    return json.loads(file_path.read_text(encoding="utf-8"))


def render_diagram_ref(block: dict) -> str:
    diagram_id = block.get("diagram_id", "")
    path = block.get("path", "")
    caption = _html.escape(str(block.get("caption", "")))
    fb = _html.escape(str(block.get("fallback_text", "Diagram: " + diagram_id)))
    bid = _html.escape(str(block.get("block_id", "")), quote=True)

    if not path:
        return (
            f'<figure id="{bid}" class="diagram diagram-missing" role="figure">'
            f"<figcaption>{caption}</figcaption>"
            f'<p class="diagram-fallback">{fb}</p>'
            f'<p class="diagram-error">Missing diagram path</p></figure>'
        )
    try:
        spec = _load_diagram_spec(path)
    except (FileNotFoundError, ValueError) as e:
        return (
            f'<figure id="{bid}" class="diagram diagram-missing" role="figure">'
            f"<figcaption>{caption}</figcaption>"
            f'<p class="diagram-fallback">{fb}</p>'
            f'<p class="diagram-error">Diagram not found: {_html.escape(str(e))}</p>'
            f"</figure>"
        )

    kind = spec.get("kind", "unknown")
    renderer = _DIAGRAM_RENDERERS.get(kind)
    if renderer is None:
        return _placeholder(spec, bid, caption, fb)

    try:
        source_data = spec.get("source_data")
        data = load_source(source_data, spec)
        svg = renderer(spec, data)
    except Exception as e:
        return (
            f'<figure id="{bid}" class="diagram diagram-error" role="figure">'
            f"<figcaption>{caption}</figcaption>"
            f'<p class="diagram-fallback">{fb}</p>'
            f'<p class="diagram-error">Render error: {_html.escape(str(e))}</p>'
            f"</figure>"
        )

    long_desc = spec.get("accessibility", {}).get("long_description", "")
    parts = [
        f'<figure id="{bid}" class="diagram diagram-{kind}" role="figure">',
        svg,
        f"<figcaption>{caption or _html.escape(spec.get('title', ''))}</figcaption>",
    ]
    if long_desc:
        parts.append(
            "<details><summary>Description</summary>"
            f"<p>{_html.escape(long_desc)}</p></details>"
        )
    if fb:
        parts.append(f'<p class="diagram-fallback">{fb}</p>')
    parts.append("</figure>")
    return "\n".join(parts)


def _placeholder(spec: dict, bid: str, caption: str, fb: str) -> str:
    kind = spec.get("kind", "unknown")
    title = _html.escape(spec.get("title", kind))
    return (
        f'<figure id="{bid}" class="diagram diagram-unsupported" role="figure">'
        f'<div class="diagram-placeholder"><span class="diagram-icon">📊</span>'
        f"<h4>{title}</h4>"
        f"<p>Unsupported diagram kind: <code>{_html.escape(kind)}</code></p>"
        "</div>"
        f"<figcaption>{caption or title}</figcaption>"
        + (f'<p class="diagram-fallback">{fb}</p>' if fb else "")
        + "</figure>"
    )


# ── Shared helpers ────────────────────────────────────────────


def _dash_attr(style: str) -> str:
    d = {"dashed": "8,4", "dotted": "2,4"}.get(style, "")
    return f' stroke-dasharray="{d}"' if d else ""


def _svg_wrap(title: str, desc: str, svg_w: int, svg_h: int, body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w} {svg_h}" '
        f'width="100%" role="img" aria-label="{title}">'
        f"<title>{title}</title><desc>{desc}</desc>"
        f"<defs>{_ARROW_MARKER}</defs>"
        f'<rect width="100%" height="100%" fill="#f9fafb" rx="8"/>'
        f"\n{body}\n</svg>"
    )


# ── Flow diagram ──────────────────────────────────────────────


def _render_flow_svg(spec: dict, data: object) -> str:
    nodes: list[dict] = spec.get("nodes", [])
    edges: list[dict] = spec.get("edges", [])
    title = _html.escape(spec.get("title", "Flow Diagram"))
    nc = len(nodes)
    horiz = spec.get("layout", {}).get("orientation") == "horizontal"
    if horiz:
        svg_w, svg_h = max(400, nc * 160 + 80), 200
        nw, nh, cy = 130, 50, svg_h // 2
        positions, ns = _nodes_h(nodes, nw, nh, cy)
        es = _edges_h(edges, positions, nw)
    else:
        svg_w, svg_h = 600, max(200, nc * 100 + 80)
        cx = svg_w // 2
        nw, nh = 200, 50
        positions, ns = _nodes_v(nodes, nw, nh, cx)
        es = _edges_v(edges, positions, nh)
    return _svg_wrap(title, f"Flow diagram with {nc} nodes", svg_w, svg_h, ns + es)


def _nodes_v(nodes: list[dict], w: int, h: int, cx: int) -> tuple[dict, str]:
    positions: dict[str, tuple[int, int]] = {}
    sg = ""
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = _html.escape(node.get("label", nid))
        fill = _STATUS_COLORS.get(node.get("status", "pending"), "#6b7280")
        y = 60 + i * 100
        positions[nid] = (cx, y)
        sg += (
            f'  <g class="diagram-node" data-node-id="{nid}">'
            f'<rect x="{cx - w // 2}" y="{y - h // 2}" width="{w}" height="{h}" '
            f'rx="8" fill="{fill}" stroke="#1e3a5f" stroke-width="2"/>'
            f'<text x="{cx}" y="{y + 5}" text-anchor="middle" fill="white" '
            f'font-size="14" font-family="system-ui, sans-serif">{label}</text></g>\n'
        )
    return positions, sg


def _nodes_h(nodes: list[dict], w: int, h: int, cy: int) -> tuple[dict, str]:
    positions: dict[str, tuple[int, int]] = {}
    sg = ""
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = _html.escape(node.get("label", nid))
        fill = _STATUS_COLORS.get(node.get("status", "pending"), "#6b7280")
        x = 60 + i * 160
        positions[nid] = (x, cy)
        sg += (
            f'  <g class="diagram-node" data-node-id="{nid}">'
            f'<rect x="{x - w // 2}" y="{cy - h // 2}" width="{w}" height="{h}" '
            f'rx="8" fill="{fill}" stroke="#1e3a5f" stroke-width="2"/>'
            f'<text x="{x}" y="{cy + 5}" text-anchor="middle" fill="white" '
            f'font-size="12" font-family="system-ui, sans-serif">{label}</text></g>\n'
        )
    return positions, sg


def _edges_v(edges: list[dict], positions: dict, node_h: int) -> str:
    sg = ""
    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        y1 += node_h // 2
        y2 -= node_h // 2
        D = _dash_attr(edge.get("style", "solid"))
        sg += f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#6b7280" stroke-width="2"{D} marker-end="url(#arrowhead)"/>\n'
        if edge.get("label"):
            el = _html.escape(str(edge["label"]))
            mid = (y1 + y2) // 2
            sg += f'  <text x="{x1 + 20}" y="{mid - 5}" fill="#374151" font-size="11" font-family="system-ui, sans-serif">{el}</text>\n'
    return sg


def _edges_h(edges: list[dict], positions: dict, node_w: int) -> str:
    sg = ""
    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        x1 += node_w // 2
        x2 -= node_w // 2
        D = _dash_attr(edge.get("style", "solid"))
        sg += f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#6b7280" stroke-width="2"{D} marker-end="url(#arrowhead)"/>\n'
        if edge.get("label"):
            el = _html.escape(str(edge["label"]))
            sg += f'  <text x="{(x1 + x2) // 2}" y="{y1 - 10}" text-anchor="middle" fill="#374151" font-size="11" font-family="system-ui, sans-serif">{el}</text>\n'
    return sg


# ── State machine ─────────────────────────────────────────────


def _render_state_machine_svg(spec: dict, data: object) -> str:  # noqa: PLR0914
    nodes: list[dict] = spec.get("nodes", [])
    edges: list[dict] = spec.get("edges", [])
    title = _html.escape(spec.get("title", "State Machine"))
    nc = len(nodes)
    cols = min(4, max(2, int(nc**0.5 + 0.5)))
    rows = max(1, (nc + cols - 1) // cols)
    svg_w = cols * 200 + 40
    svg_h = rows * 120 + 40
    positions: dict[str, tuple[int, int]] = {}
    ns = ""
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = _html.escape(node.get("label", nid))
        fill = _STATUS_COLORS.get(node.get("status", "pending"), "#6b7280")
        col = i % cols
        row = i // cols
        cx = 120 + col * 200
        cy = 80 + row * 120
        positions[nid] = (cx, cy)
        ns += (
            f'  <g class="diagram-node" data-node-id="{nid}">'
            f'<rect x="{cx - 70}" y="{cy - 25}" width="140" height="50" rx="25" '
            f'fill="{fill}" stroke="#1e3a5f" stroke-width="2"/>'
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" fill="white" '
            f'font-size="13" font-family="system-ui, sans-serif">{label}</text></g>\n'
        )
    es = ""
    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        curve = _path_between(x1, y1, x2, y2)
        es += f'  <path d="{curve}" fill="none" stroke="#6b7280" stroke-width="2" marker-end="url(#arrowhead)"/>\n'
        if edge.get("label"):
            el = _html.escape(str(edge["label"]))
            mx, my = (x1 + x2) // 2, (y1 + y2) // 2 - 12
            es += f'  <text x="{mx}" y="{my}" text-anchor="middle" fill="#374151" font-size="11" font-family="system-ui, sans-serif">{el}</text>\n'
    return _svg_wrap(title, f"State machine with {nc} states", svg_w, svg_h, ns + es)


def _path_between(x1: int, y1: int, x2: int, y2: int) -> str:
    if y1 == y2:
        mid = (x1 + x2) // 2
        return f"M {x1} {y1} L {mid} {y1} L {mid} {y2} L {x2} {y2}"
    if x1 == x2:
        mid = (y1 + y2) // 2
        return f"M {x1} {y1} L {x1} {mid} L {x2} {mid} L {x2} {y2}"
    return f"M {x1} {y1} C {x1} {(y1 + y2) // 2}, {x2} {(y1 + y2) // 2}, {x2} {y2}"


# ── Timeline ──────────────────────────────────────────────────


def _render_timeline_svg(spec: dict, data: object) -> str:
    nodes: list[dict] = spec.get("nodes", [])
    title = _html.escape(spec.get("title", "Timeline"))
    nc = len(nodes)
    sp = 160
    svg_w = max(400, nc * sp + 80)
    svg_h = 200
    lane_y = svg_h // 2
    ns = ""
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = _html.escape(node.get("label", nid))
        fill = _STATUS_COLORS.get(node.get("status", "pending"), "#6b7280")
        cx = 60 + i * sp
        ns += (
            f'  <circle cx="{cx}" cy="{lane_y}" r="10" fill="{fill}" '
            f'stroke="#1e3a5f" stroke-width="2"/>\n'
        )
        ns += (
            f'  <text x="{cx}" y="{lane_y - 20}" text-anchor="middle" fill="#1e3a5f" '
            f'font-size="12" font-weight="600" font-family="system-ui, sans-serif">{label}</text>\n'
        )
        desc = node.get("description", "")
        if desc:
            ns += (
                f'  <text x="{cx}" y="{lane_y + 30}" text-anchor="middle" '
                f'fill="#6b7280" font-size="10" font-family="system-ui, sans-serif">'
                f"{_html.escape(desc[:40])}</text>\n"
            )
    ns += (
        f'  <line x1="40" y1="{lane_y}" x2="{svg_w - 20}" y2="{lane_y}" '
        f'stroke="#d1d5db" stroke-width="3"/>\n'
    )
    return _svg_wrap(title, f"Timeline with {nc} events", svg_w, svg_h, ns)


# ── Matrix ────────────────────────────────────────────────────


def _render_matrix_svg(spec: dict, data: object) -> str:
    rows_data: list[dict] = spec.get("rows", [])
    columns: list[str] = spec.get("columns", [])
    if not rows_data and isinstance(data, list):
        rows_data = data  # type: ignore[assignment]
    if not columns and rows_data:
        columns = list(rows_data[0].keys()) if rows_data else []
    title = _html.escape(spec.get("title", "Matrix"))
    cc = len(columns)
    rc = len(rows_data)
    cw, ch = 120, 36
    svg_w = max(300, cc * cw + 60)
    svg_h = (rc + 1) * ch + 40

    hdr = ""
    for ci, col in enumerate(columns):
        x = 30 + ci * cw
        hdr += (
            f'  <rect x="{x}" y="20" width="{cw}" height="{ch}" fill="#1e3a5f" stroke="#111827" stroke-width="1"/>'
            f'<text x="{x + cw // 2}" y="{20 + ch // 2 + 5}" text-anchor="middle" '
            f'fill="white" font-size="13" font-family="system-ui, sans-serif">{_html.escape(col)}</text>\n'
        )
    body = ""
    for ri, row in enumerate(rows_data):
        for ci, col in enumerate(columns):
            x = 30 + ci * cw
            y = 20 + (ri + 1) * ch
            val = _html.escape(str(row.get(col, "")))
            bg = "#ffffff" if ri % 2 == 0 else "#f3f4f6"
            body += (
                f'  <rect x="{x}" y="{y}" width="{cw}" height="{ch}" fill="{bg}" stroke="#d1d5db" stroke-width="1"/>'
                f'<text x="{x + cw // 2}" y="{y + ch // 2 + 5}" text-anchor="middle" '
                f'fill="#111827" font-size="12" font-family="system-ui, sans-serif">{val}</text>\n'
            )
    return _svg_wrap(
        title, f"Matrix with {rc} rows and {cc} columns", svg_w, svg_h, hdr + body
    )


# ── Dependency graph ──────────────────────────────────────────


def _render_dependency_graph_svg(spec: dict, data: object) -> str:  # noqa: PLR0914
    nodes: list[dict] = spec.get("nodes", [])
    edges: list[dict] = spec.get("edges", [])
    title = _html.escape(spec.get("title", "Dependency Graph"))
    nc = len(nodes)
    layer_sz = 3
    nw, nh = 150, 40
    svg_w = layer_sz * (nw + 40) + 40
    svg_h = max(200, ((nc + layer_sz - 1) // layer_sz) * (nh + 30) + 40)
    positions: dict[str, tuple[int, int]] = {}
    ns = ""
    for i, node in enumerate(nodes):
        nid = node.get("id", "")
        label = _html.escape(node.get("label", nid))
        fill = _STATUS_COLORS.get(node.get("status", "pending"), "#6b7280")
        col = i % layer_sz
        row = i // layer_sz
        cx = 40 + col * (nw + 40) + nw // 2
        cy = 40 + row * (nh + 30) + nh // 2
        positions[nid] = (cx, cy)
        ns += (
            f'  <g class="diagram-node" data-node-id="{nid}">'
            f'<rect x="{cx - nw // 2}" y="{cy - nh // 2}" width="{nw}" height="{nh}" '
            f'rx="6" fill="{fill}" stroke="#1e3a5f" stroke-width="2"/>'
            f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" fill="white" '
            f'font-size="12" font-family="system-ui, sans-serif">{label}</text></g>\n'
        )
    es = ""
    for edge in edges:
        src, dst = edge["from"], edge["to"]
        if src not in positions or dst not in positions:
            continue
        x1, y1 = positions[src]
        x2, y2 = positions[dst]
        y1 += nh // 2
        y2 -= nh // 2
        D = _dash_attr(edge.get("style", "solid"))
        es += f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#6b7280" stroke-width="2"{D} marker-end="url(#arrowhead)"/>\n'
    return _svg_wrap(title, f"Dependency graph with {nc} nodes", svg_w, svg_h, ns + es)


# ── Dispatch ──────────────────────────────────────────────────

_DIAGRAM_RENDERERS: dict[str, Callable[[dict, object], str]] = {
    "flow": _render_flow_svg,
    "state_machine": _render_state_machine_svg,
    "timeline": _render_timeline_svg,
    "matrix": _render_matrix_svg,
    "dependency_graph": _render_dependency_graph_svg,
    "risk_map": _render_matrix_svg,
    "architecture_map": _render_flow_svg,
}
