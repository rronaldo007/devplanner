"""Generation orchestration: engine selection and the public entrypoints.

This module holds the implementation behind the :mod:`planner.generators`
package facade. Two engines are available:

* :mod:`planner.generators.templates` — pure Python, always works.
* :mod:`planner.generators.claude` — uses Anthropic's Claude API. Selected
  automatically when an API key is available (per-user key from
  ``UserProfile`` first, falling back to ``ANTHROPIC_API_KEY`` from the
  environment) and the ``anthropic`` package is installed.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import diagrams, templates

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Document, Project


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


def classify_document(
    project: "Project", *, title: str, body: str, force_engine: str | None = None
) -> dict:
    """Classify a custom document into one of the spec-pack categories.

    Uses Claude when available, falling back to deterministic keyword scoring
    (which also runs when Claude errors or returns an unknown slug). Returns
    ``{"category", "engine"}`` plus an optional ``_claude_error``.
    """

    from . import classify

    engine = _select_engine(project, force_engine)
    if engine == "claude":
        try:
            category = classify.classify_claude(
                title, body, api_key=_api_key_for(project)
            )
            return {"category": category, "engine": "claude"}
        except Exception as exc:
            return {
                "category": classify.classify_keyword(title, body),
                "engine": "keyword",
                "_claude_error": str(exc),
            }
    return {"category": classify.classify_keyword(title, body), "engine": "keyword"}


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
