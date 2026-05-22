"""draw.io (diagrams.net) versions of the project diagrams.

Like :mod:`planner.generators.diagrams` (Mermaid), these are produced
deterministically from a ``Project``'s structured fields — no LLM — so the
output is always valid and matches what the user answered. The difference is
the target format: native mxGraph XML with explicit geometry, which draw.io
opens as fully editable shapes (boxes, actors, arrows) rather than a text
block.

draw.io has no auto-layout, so each diagram type runs a tiny layout pass that
assigns x/y coordinates on a simple grid.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Project


def _esc(text: str) -> str:
    """Escape a label for an XML attribute, keeping newlines as line breaks.

    ``&#10;`` renders as a line break inside a draw.io cell value (the cells use
    ``whiteSpace=wrap;html=1``), which is what stacks the ERD entity fields.
    """

    s = (text or "").strip() or "(unnamed)"
    return escape(s, {'"': "&quot;", "\n": "&#10;"})


def _vertex(cid: str, value: str, style: str, x: int, y: int, w: int, h: int) -> str:
    return (
        f'        <mxCell id="{cid}" value="{_esc(value)}" style="{style}" '
        f'vertex="1" parent="1">\n'
        f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/>\n'
        f"        </mxCell>"
    )


def _edge(cid: str, source: str, target: str, value: str = "") -> str:
    style = "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=classic;"
    return (
        f'        <mxCell id="{cid}" value="{_esc(value) if value else ""}" '
        f'style="{style}" edge="1" parent="1" source="{source}" target="{target}">\n'
        f'          <mxGeometry relative="1" as="geometry"/>\n'
        f"        </mxCell>"
    )


def _document(name: str, cells: list[str]) -> str:
    """Wrap cells in the mxfile/diagram/mxGraphModel envelope draw.io expects."""

    body = "\n".join(cells)
    return (
        '<mxfile host="DevPlanner">\n'
        f'  <diagram name="{_esc(name)}">\n'
        '    <mxGraphModel dx="900" dy="600" grid="1" gridSize="10" '
        'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" '
        'pageScale="1" pageWidth="850" pageHeight="1100" math="0" shadow="0">\n'
        "      <root>\n"
        '        <mxCell id="0"/>\n'
        '        <mxCell id="1" parent="0"/>\n'
        f"{body}\n"
        "      </root>\n"
        "    </mxGraphModel>\n"
        "  </diagram>\n"
        "</mxfile>\n"
    )


# ---------------------------------------------------------------------------
# Use case: actors (left column) -> use-case ellipses (right, inside a system)
# ---------------------------------------------------------------------------
def use_case(project: "Project") -> str:
    actors = [p.get("name") or p.get("role") or "User" for p in (project.personas or [])]
    if not actors:
        actors = ["User"]
    features = list(project.features or []) or ["Use the system"]

    cells: list[str] = []

    # System backdrop sized to contain the use-case column.
    sys_h = max(len(features) * 90 + 20, 100)
    cells.append(_vertex(
        "system", project.name or "System",
        "rounded=0;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;"
        "verticalAlign=top;fontStyle=1;",
        300, 20, 240, sys_h,
    ))

    uc_ids: list[str] = []
    for j, feat in enumerate(features):
        cid = f"uc{j}"
        uc_ids.append(cid)
        cells.append(_vertex(
            cid, feat,
            "ellipse;whiteSpace=wrap;html=1;fillColor=#dae8fc;strokeColor=#6c8ebf;",
            320, 40 + j * 90, 200, 60,
        ))

    eid = 0
    for i, actor in enumerate(actors):
        aid = f"actor{i}"
        cells.append(_vertex(
            aid, actor, "shape=umlActor;verticalLabelPosition=bottom;html=1;"
            "verticalAlign=top;outlineConnect=0;",
            40, 50 + i * 110, 50, 80,
        ))
        for uc in uc_ids:
            cells.append(_edge(f"e{eid}", aid, uc))
            eid += 1

    return _document("Use Case", cells)


# ---------------------------------------------------------------------------
# ERD: entity boxes on a grid; inferred relationships as labeled edges
# ---------------------------------------------------------------------------
def erd(project: "Project") -> str:
    entities = project.entities or []
    if not entities:
        entities = [{"name": "Project", "fields": ["name"]}]

    by_name = {e["name"].lower(): e for e in entities if e.get("name")}
    id_of = {}
    cells: list[str] = []

    cols = 3
    col_w, row_h = 230, 200
    for idx, ent in enumerate(entities):
        name = ent.get("name") or "Entity"
        fields = ent.get("fields") or ["id"]
        cid = f"ent{idx}"
        id_of[name.lower()] = cid
        # Title + fields stacked in one editable box (newline-separated label).
        label = name + "\n" + "\n".join(str(f) for f in fields)
        box_h = 30 + len(fields) * 18
        col, row = idx % cols, idx // cols
        cells.append(_vertex(
            cid, label,
            "rounded=0;whiteSpace=wrap;html=1;align=left;verticalAlign=top;"
            "spacingLeft=8;spacingTop=4;fillColor=#d5e8d4;strokeColor=#82b366;",
            40 + col * col_w, 40 + row * row_h, 180, box_h,
        ))

    eid = 0
    for idx, ent in enumerate(entities):
        fields = ent.get("fields") or []
        for field in fields:
            target = by_name.get(str(field).lower())
            if target and target["name"].lower() in id_of:
                cells.append(_edge(
                    f"r{eid}", f"ent{idx}", id_of[target["name"].lower()], str(field),
                ))
                eid += 1

    return _document("ERD", cells)


# ---------------------------------------------------------------------------
# Flow: vertical journey discover -> sign up -> features -> outcome
# ---------------------------------------------------------------------------
def flow(project: "Project") -> str:
    features = list(project.features or [])[:5]
    metric = (project.success_metrics or "Value delivered").splitlines()[0]

    steps = [f"Discover {project.name}", "Sign up / onboard", *features, metric]
    cells: list[str] = []
    node_ids: list[str] = []
    for i, step in enumerate(steps):
        cid = f"s{i}"
        node_ids.append(cid)
        cells.append(_vertex(
            cid, step,
            "rounded=1;whiteSpace=wrap;html=1;fillColor=#ffe6cc;strokeColor=#d79b00;",
            300, 40 + i * 100, 200, 50,
        ))
    for i in range(len(node_ids) - 1):
        cells.append(_edge(f"e{i}", node_ids[i], node_ids[i + 1]))

    return _document("User Flow", cells)


# Map diagram document kinds to their generator.
def for_kind(kind: str, project: "Project") -> str | None:
    """Return .drawio XML for a diagram ``kind``, or ``None`` if not a diagram."""

    from planner.models import Document

    fn = {
        Document.KIND_USE_CASE_DIAGRAM: use_case,
        Document.KIND_ERD_DIAGRAM: erd,
        Document.KIND_FLOW_DIAGRAM: flow,
    }.get(kind)
    return fn(project) if fn else None
