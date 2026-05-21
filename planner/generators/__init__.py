"""Document generation for a :class:`planner.models.Project`.

Two engines are available:

* :mod:`planner.generators.templates` — pure Python, always works.
* :mod:`planner.generators.claude` — uses Anthropic's Claude API. Selected
  automatically when an API key is available (per-user key from
  ``UserProfile`` first, falling back to ``ANTHROPIC_API_KEY`` from the
  environment) and the ``anthropic`` package is installed.

Public entrypoints:

* :func:`generate_all` — produce the six built-in documents (three planning
  docs + three Mermaid diagrams) for a project.
* :func:`generate_custom` — produce a single custom document from a
  user-supplied prompt using the project as context.
* :func:`regenerate` — refresh the body of an existing :class:`Document`.
* :func:`sync_default_documents` — persist / refresh all default docs as
  ``Document`` rows on a project.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import diagrams, templates

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Document, Project


DOC_KEY_TO_KIND = {
    "business_plan": "business_plan",
    "specifications": "specifications",
    "user_stories": "user_stories",
}

DEFAULT_TITLES = {
    "business_plan": ("Business Plan", "Business Plan"),
    "specifications": ("Cahier des Charges", "Cahier des Charges"),
    "user_stories": ("User Stories", "User Stories"),
    "use_case_diagram": ("Use Case Diagram", "Diagramme de cas d'utilisation"),
    "erd_diagram": ("Entity-Relationship Diagram", "Modèle entité-association"),
    "flow_diagram": ("User Flow", "Parcours utilisateur"),
}


# ---------------------------------------------------------------------------
# Engine selection
# ---------------------------------------------------------------------------
def _api_key_for(project: "Project") -> str | None:
    """Resolve the API key: user's profile first, then env var."""

    user = getattr(project, "owner", None)
    if user is not None:
        profile = getattr(user, "profile", None)
        if profile and profile.anthropic_api_key:
            return profile.anthropic_api_key
    return os.environ.get("ANTHROPIC_API_KEY") or None


def _select_engine(project: "Project", force: str | None = None) -> str:
    if force in ("templates", "claude"):
        return force
    if not _api_key_for(project):
        return "templates"
    try:
        import anthropic  # noqa: F401
    except Exception:
        return "templates"
    return "claude"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_all(project: "Project", *, force_engine: str | None = None) -> dict:
    """Generate every default document + diagram for ``project``.

    Returns a dict with the six well-known keys plus ``engine`` (the
    generator that produced the prose docs) and optional ``_claude_error``.
    """

    engine = _select_engine(project, force_engine)
    if engine == "claude":
        try:
            from . import claude

            docs = claude.generate_documents(project, api_key=_api_key_for(project))
        except Exception as exc:  # pragma: no cover - safety net
            docs = templates.generate_documents(project)
            docs["_claude_error"] = str(exc)
            engine = "templates"
    else:
        docs = templates.generate_documents(project)

    return {
        "engine": engine,
        "business_plan": docs.get("business_plan", ""),
        "specifications": docs.get("specifications", ""),
        "user_stories": docs.get("user_stories", ""),
        "use_case_diagram": diagrams.use_case(project),
        "erd_diagram": diagrams.erd(project),
        "flow_diagram": diagrams.flow(project),
        "_claude_error": docs.get("_claude_error", ""),
    }


def generate_custom(project: "Project", title: str, prompt: str) -> dict:
    """Generate a single custom document.

    Uses Claude when available, otherwise falls back to a simple template
    that just records the prompt so the user can write the doc themselves.
    """

    engine = _select_engine(project)
    if engine == "claude":
        try:
            from . import claude

            body = claude.generate_custom(
                project, title=title, prompt=prompt, api_key=_api_key_for(project)
            )
            return {"engine": "claude", "body": body}
        except Exception as exc:  # pragma: no cover - safety net
            return {
                "engine": "templates",
                "body": templates.custom_stub(project, title, prompt),
                "_claude_error": str(exc),
            }
    return {
        "engine": "templates",
        "body": templates.custom_stub(project, title, prompt),
    }


def regenerate(document: "Document", *, force_engine: str | None = None) -> str:
    """Refresh ``document.body`` from its parent project.

    Returns the new body (does NOT save the model)."""

    project = document.project
    if document.kind == "use_case_diagram":
        return diagrams.use_case(project)
    if document.kind == "erd_diagram":
        return diagrams.erd(project)
    if document.kind == "flow_diagram":
        return diagrams.flow(project)
    if document.kind == "custom":
        result = generate_custom(project, document.title, document.prompt or "")
        return result["body"]
    # Default planning docs.
    out = generate_all(project, force_engine=force_engine)
    return out.get(document.kind, "")


def sync_default_documents(project: "Project", *, force_engine: str | None = None) -> dict:
    """Create or refresh the six default Document rows for ``project``.

    Returns the raw generator output (same shape as :func:`generate_all`).
    """

    # Local import to avoid a circular dependency at module load time.
    from planner.models import Document

    output = generate_all(project, force_engine=force_engine)
    titles = {k: v[0 if project.language == "en" else 1] for k, v in DEFAULT_TITLES.items()}

    for kind in Document.DEFAULT_KINDS:
        body = output.get(kind, "")
        Document.objects.update_or_create(
            project=project, kind=kind,
            defaults={
                "title": titles[kind],
                "body": body,
                "is_generated": True,
            },
        )
    return output
