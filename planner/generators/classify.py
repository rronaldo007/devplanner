"""Classify a document into one of the project's spec-pack categories.

Mirrors the generator pattern in this package: a Claude-backed path with a
deterministic fallback. The fallback is keyword scoring, so classification
still works with no API key (and keeps cheap, high-volume work off Claude).

The category slugs are owned by :class:`planner.models.Document`; this module
references them through ``Document.CATEGORY_*`` (looked up lazily to avoid a
circular import at load time).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass

# Reuse the document generator's model id / token ceiling. Classification is a
# tiny task, so cap output hard regardless of the doc-generation ceiling.
from .claude import DEFAULT_MODEL  # noqa: E402

CLASSIFY_MAX_TOKENS = int(os.environ.get("ANTHROPIC_CLASSIFY_MAX_TOKENS", "16"))


def valid_categories() -> set[str]:
    """The set of acceptable category slugs (excluding the catch-all)."""

    from planner.models import Document

    return {value for value, _ in Document.CATEGORY_CHOICES}


# ---------------------------------------------------------------------------
# Deterministic fallback: keyword scoring
# ---------------------------------------------------------------------------
# Lower-cased keyword phrases per category. Title hits are weighted higher.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "business": (
        "business", "market", "revenue", "pricing", "monetization", "monetisation",
        "go-to-market", "gtm", "kpi", "competitor", "competition", "sales", "budget",
        "roi", "stakeholder", "value proposition", "customer acquisition", "growth",
    ),
    "system_design": (
        "architecture", "api", "endpoint", "deployment", "infrastructure", "infra",
        "scalability", "microservice", "system design", "integration", "service",
        "backend", "server", "queue", "cache", "load balanc", "sequence flow",
    ),
    "system_modeling": (
        "class diagram", "state machine", "state diagram", "domain model",
        "activity diagram", "bpmn", "c4", "uml", "component diagram",
        "sequence diagram", "behaviour model", "behavior model",
    ),
    "data_design": (
        "database", "schema", "erd", "entity-relationship", "entity relationship",
        "data model", "data dictionary", "migration", "sql", "index", "normalization",
        "normalisation", "foreign key", "relational",
    ),
    "app_design": (
        "ux", "ui", "user flow", "wireframe", "design system", "accessibility",
        "mockup", "navigation", "user story", "user journey", "prototype",
        "frontend", "screen", "look and feel", "interaction design",
    ),
}


def classify_keyword(title: str, body: str) -> str:
    """Score ``title``/``body`` against per-category keywords.

    Returns the best-matching category slug, or ``"other"`` when nothing
    matches. Title matches count triple to reflect their signal.
    """

    from planner.models import Document

    title_l = (title or "").lower()
    body_l = (body or "").lower()
    scores: dict[str, int] = {}
    for category, keywords in _KEYWORDS.items():
        score = 0
        for kw in keywords:
            score += title_l.count(kw) * 3
            score += body_l.count(kw)
        if score:
            scores[category] = score
    if not scores:
        return Document.CATEGORY_OTHER
    # Highest score wins; ties broken by CATEGORY_CHOICES display order.
    order = [value for value, _ in Document.CATEGORY_CHOICES]
    return max(scores, key=lambda c: (scores[c], -order.index(c)))


# ---------------------------------------------------------------------------
# Claude-backed classification
# ---------------------------------------------------------------------------
def classify_claude(title: str, body: str, *, api_key: str | None = None) -> str:
    """Ask Claude for the best category slug. Raises on an invalid response.

    Keeps the call tiny (short system prompt, truncated body, ~16 output
    tokens) so it stays cheap. The caller is expected to fall back to
    :func:`classify_keyword` on any exception.
    """

    import anthropic

    from planner.models import Document

    valid = valid_categories()
    choices = "\n".join(f"- {value}: {label}" for value, label in Document.CATEGORY_CHOICES)
    system = (
        "You classify a software project document into exactly one category. "
        "Reply with ONLY the category slug (e.g. 'data_design'), nothing else. "
        "Categories:\n" + choices + "\n"
        "Use 'other' only when none clearly fit."
    )
    # Body is truncated: the opening of a doc carries enough signal and keeps
    # input tokens (and cost) down.
    excerpt = (body or "")[:2000]
    user_msg = f"Title: {title}\n\nDocument (excerpt):\n{excerpt}"

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=CLASSIFY_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    slug = "".join(parts).strip().lower().strip(".'\" ")
    if slug not in valid:
        raise ValueError(f"Claude returned an unknown category: {slug!r}")
    return slug
