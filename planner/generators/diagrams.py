"""Mermaid diagrams derived from a Project's structured fields.

The diagrams are produced deterministically from the data (no LLM), so the
syntax is always valid Mermaid and matches what the user actually answered.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Project


_SAFE = re.compile(r"[^A-Za-z0-9]+")


def _id(text: str, prefix: str = "n") -> str:
    """Turn an arbitrary string into a safe Mermaid node id."""

    slug = _SAFE.sub("_", (text or "").strip()).strip("_")
    return f"{prefix}_{slug or 'x'}"


def _q(text: str) -> str:
    """Escape a label for inclusion inside a Mermaid bracketed label."""

    return (text or "").replace('"', "'").replace("\n", " ").strip() or "(unnamed)"


# ---------------------------------------------------------------------------
# Use case
# ---------------------------------------------------------------------------
def use_case(project: "Project") -> str:
    """Actors -> features, rendered as a Mermaid flowchart (LR)."""

    actors = [p.get("name") or p.get("role") or "User" for p in (project.personas or [])]
    if not actors:
        actors = ["User"]

    features = list(project.features or []) or ["Use the system"]
    lines = ["flowchart LR"]
    system_id = "system"
    lines.append(f'  subgraph S["{_q(project.name)}"]')
    for feat in features:
        lines.append(f'    {_id(feat, "uc")}(["{_q(feat)}"])')
    lines.append("  end")
    for actor in actors:
        aid = _id(actor, "actor")
        lines.append(f'  {aid}(("{_q(actor)}"))')
        for feat in features:
            lines.append(f'  {aid} --> {_id(feat, "uc")}')
    # Reference system_id once to make linter happy without warning users.
    del system_id
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ERD
# ---------------------------------------------------------------------------
def erd(project: "Project") -> str:
    """Entity-relationship diagram using Mermaid's erDiagram.

    Relationships are inferred when a field name on entity A equals (case
    insensitively) the name of another entity B — that's modeled as
    ``A }o--|| B``.
    """

    entities = project.entities or []
    if not entities:
        return 'erDiagram\n  Project {\n    string name\n  }'

    by_name = {e["name"].lower(): e for e in entities if e.get("name")}
    lines = ["erDiagram"]
    relations: list[str] = []
    for ent in entities:
        name = ent.get("name") or "Entity"
        safe_name = _SAFE.sub("_", name) or "Entity"
        fields = ent.get("fields") or []
        lines.append(f"  {safe_name} {{")
        if not fields:
            lines.append("    string id")
        for field in fields:
            ftype = "string"
            fname = _SAFE.sub("_", field) or "field"
            target = by_name.get(field.lower())
            if target:
                ftype = _SAFE.sub("_", target["name"])
                relations.append(
                    f"  {safe_name} }}o--|| {ftype} : {fname}"
                )
            lines.append(f"    {ftype} {fname}")
        lines.append("  }")
    lines.extend(relations)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Flow / user journey
# ---------------------------------------------------------------------------
def flow(project: "Project") -> str:
    """High-level user journey: discover -> sign up -> core features -> outcome."""

    features = list(project.features or [])
    metric = (project.success_metrics or "Value delivered").splitlines()[0]
    lines = ["flowchart TD"]
    lines.append(f'  A(["Discover {_q(project.name)}"])')
    lines.append('  B(["Sign up / onboard"])')
    lines.append("  A --> B")
    prev = "B"
    for idx, feat in enumerate(features[:5], start=1):
        node = f"F{idx}"
        lines.append(f'  {node}(["{_q(feat)}"])')
        lines.append(f"  {prev} --> {node}")
        prev = node
    lines.append(f'  Z(["{_q(metric)}"])')
    lines.append(f"  {prev} --> Z")
    return "\n".join(lines)
