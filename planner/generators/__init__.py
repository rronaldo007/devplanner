"""Document generation for a :class:`planner.models.Project`.

Two engines are available:

* :mod:`planner.generators.templates` — pure Python, always works.
* :mod:`planner.generators.claude` — uses Anthropic's Claude API. Selected
  automatically when ``ANTHROPIC_API_KEY`` is set in the environment and the
  ``anthropic`` package is installed.

The public entrypoint :func:`generate` returns a dict::

    {
        "engine": "claude" | "templates",
        "business_plan": "...markdown...",
        "specifications": "...markdown...",   # "cahier des charges"
        "user_stories": "...markdown...",
        "use_case_diagram": "...mermaid...",
        "erd_diagram": "...mermaid...",
        "flow_diagram": "...mermaid...",
    }
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import diagrams, templates

if TYPE_CHECKING:  # pragma: no cover - import only for typing
    from planner.models import Project


DOCUMENT_KEYS = ("business_plan", "specifications", "user_stories")
DIAGRAM_KEYS = ("use_case_diagram", "erd_diagram", "flow_diagram")


def generate(project: "Project", *, force_engine: str | None = None) -> dict:
    """Generate every document + diagram for ``project``.

    Diagrams are always produced deterministically from the structured data
    (so they're guaranteed to be valid Mermaid). Prose documents come from
    Claude when available, otherwise from the template engine.
    """

    engine = force_engine or _select_engine()
    if engine == "claude":
        try:
            from . import claude  # local import: anthropic may be missing

            docs = claude.generate_documents(project)
        except Exception as exc:  # pragma: no cover - network / runtime safety net
            docs = templates.generate_documents(project)
            docs["_claude_error"] = str(exc)
            engine = "templates"
    else:
        docs = templates.generate_documents(project)

    return {
        "engine": engine,
        **docs,
        "use_case_diagram": diagrams.use_case(project),
        "erd_diagram": diagrams.erd(project),
        "flow_diagram": diagrams.flow(project),
    }


def _select_engine() -> str:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "templates"
    try:
        import anthropic  # noqa: F401
    except Exception:
        return "templates"
    return "claude"
