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


def _claude_available(project: "Project") -> bool:
    if not _api_key_for(project):
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


def _profile_of(project: "Project"):
    user = getattr(project, "owner", None)
    return getattr(user, "profile", None) if user is not None else None


def _preferred_provider(project: "Project") -> str:
    """The owner's preferred generation backend ('claude' or 'oss')."""

    profile = _profile_of(project)
    return getattr(profile, "ai_provider", "claude") or "claude"


def _oss_kwargs(project: "Project") -> dict:
    """OSS call config with the owner's chosen model (falling back to env)."""

    from . import oss

    cfg = dict(oss.config())
    profile = _profile_of(project)
    user_model = (getattr(profile, "oss_model", "") or "").strip() if profile else ""
    if user_model:
        cfg["model"] = user_model
    return cfg


def _oss_generation_ready(project: "Project") -> bool:
    """OSS can generate for this project: an endpoint + a resolved model."""

    cfg = _oss_kwargs(project)
    return bool(cfg["base_url"] and cfg["model"])


def _ai_tiers(project: "Project", force: str | None = None) -> list[str]:
    """Ordered AI engines to try before the deterministic fallback.

    Order respects the owner's preference: if they chose ``oss`` (to save Claude
    tokens), generate locally first, then fall back to Claude, then templates.
    Otherwise Claude first. ``force`` pins a single engine; ``force="templates"``
    skips AI entirely.
    """

    if force == "templates":
        return []
    if force in ("claude", "oss"):
        return [force]

    claude_ok = _claude_available(project)
    oss_ok = _oss_generation_ready(project)
    tiers: list[str] = []
    if _preferred_provider(project) == "oss" and oss_ok:
        tiers.append("oss")
    if claude_ok:
        tiers.append("claude")
    if oss_ok and "oss" not in tiers:
        tiers.append("oss")
    return tiers


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_all(project: "Project", *, force_engine: str | None = None) -> dict:
    """Generate every default document + diagram for ``project``.

    Returns a dict with the six well-known keys plus ``engine`` (the
    generator that produced the prose docs) and optional ``_claude_error``.
    """

    docs = None
    engine = None
    ai_error = ""
    for tier in _ai_tiers(project, force_engine):
        try:
            if tier == "claude":
                from . import claude

                docs = claude.generate_documents(project, api_key=_api_key_for(project))
            else:  # oss
                from . import oss

                docs = oss.generate_documents(project, **_oss_kwargs(project))
            engine = tier
            break
        except Exception as exc:
            ai_error = str(exc)
    if docs is None:
        docs = templates.generate_documents(project)
        engine = "templates"

    return {
        "engine": engine,
        "business_plan": docs.get("business_plan", ""),
        "specifications": docs.get("specifications", ""),
        "user_stories": docs.get("user_stories", ""),
        "use_case_diagram": diagrams.use_case(project),
        "erd_diagram": diagrams.erd(project),
        "flow_diagram": diagrams.flow(project),
        # Surface the AI error only when we fully degraded to templates (this
        # drives the "AI paused" banner). If OSS rescued a failed Claude call,
        # AI succeeded — no banner.
        "_claude_error": ai_error if engine == "templates" else "",
    }


def generate_custom(project: "Project", title: str, prompt: str) -> dict:
    """Generate a single custom document.

    Tries Claude, then the OSS engine (Ollama / OpenAI-compatible), then a
    simple template that just records the prompt so the user can write the
    doc themselves.
    """

    ai_error = ""
    for tier in _ai_tiers(project):
        try:
            if tier == "claude":
                from . import claude

                body = claude.generate_custom(
                    project, title=title, prompt=prompt, api_key=_api_key_for(project)
                )
            else:  # oss
                from . import oss

                body = oss.generate_custom(
                    project, title=title, prompt=prompt, **_oss_kwargs(project)
                )
            return {"engine": tier, "body": body}
        except Exception as exc:
            ai_error = str(exc)
    result = {
        "engine": "templates",
        "body": templates.custom_stub(project, title, prompt),
    }
    if ai_error:
        result["_claude_error"] = ai_error
    return result


def classify_document(
    project: "Project", *, title: str, body: str, force_engine: str | None = None
) -> dict:
    """Classify a custom document into one of the spec-pack categories.

    Tries Claude, then the OSS engine, then deterministic keyword scoring
    (which also runs when a model errors or returns an unknown slug). Returns
    ``{"category", "engine"}`` plus an optional ``_claude_error``.
    """

    from . import classify

    ai_error = ""
    for tier in _ai_tiers(project, force_engine):
        try:
            if tier == "claude":
                category = classify.classify_claude(
                    title, body, api_key=_api_key_for(project)
                )
            else:  # oss
                from . import oss

                category = oss.classify(title, body, **_oss_kwargs(project))
            return {"category": category, "engine": tier}
        except Exception as exc:
            ai_error = str(exc)
    result = {"category": classify.classify_keyword(title, body), "engine": "keyword"}
    if ai_error:
        result["_claude_error"] = ai_error
    return result


def regenerate(document: "Document", *, force_engine: str | None = None) -> dict:
    """Refresh ``document.body`` from its parent project.

    Returns ``{"body", "_claude_error"}`` (does NOT save the model). Diagrams
    are deterministic, so their ``_claude_error`` is always empty.
    """

    project = document.project
    if document.kind == "use_case_diagram":
        return {"body": diagrams.use_case(project), "_claude_error": ""}
    if document.kind == "erd_diagram":
        return {"body": diagrams.erd(project), "_claude_error": ""}
    if document.kind == "flow_diagram":
        return {"body": diagrams.flow(project), "_claude_error": ""}
    if document.kind == "custom":
        result = generate_custom(project, document.title, document.prompt or "")
        return {"body": result["body"], "_claude_error": result.get("_claude_error", "")}
    # Default planning docs.
    out = generate_all(project, force_engine=force_engine)
    return {"body": out.get(document.kind, ""), "_claude_error": out.get("_claude_error", "")}


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
