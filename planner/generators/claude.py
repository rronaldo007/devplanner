"""Anthropic Claude-backed document generator.

Activated when ``ANTHROPIC_API_KEY`` is set and the ``anthropic`` package is
installed. Falls back to templates automatically if either is missing — that
fallback lives in :mod:`planner.generators`.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Project


# Single source of truth for the model id (chat.py imports this). Override per
# deployment with ANTHROPIC_MODEL, or per user via their saved API-key profile.
DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
# Document generation runs non-streaming, so keep this at the ~16k safe ceiling
# for non-streaming requests (larger values risk the SDK's HTTP-timeout guard).
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "16000"))


def generate_documents(project: "Project", *, api_key: str | None = None) -> dict[str, str]:
    """Generate business plan, specifications and user stories via Claude."""

    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    project_json = _project_to_json(project)
    language_name = "French" if project.language == "fr" else "English"

    system = (
        "You are a senior software product manager and tech lead. "
        "Given a developer's project brief (JSON), you produce crisp, "
        "actionable planning documents in clean GitHub-flavored Markdown. "
        f"All output MUST be written in {language_name}. "
        "Do not invent facts that are not implied by the input — if "
        "something is missing, mark it as 'TBD' or '—'. Do not wrap your "
        "answer in code fences. Return Markdown only, no preamble."
    )

    user_msg = (
        "Project brief (JSON):\n```json\n"
        + project_json
        + "\n```\n\n"
        + "Produce three documents, each prefixed by a marker line on its own:\n"
        "===BUSINESS_PLAN===\n"
        "  A business plan with sections: Executive Summary, Problem, "
        "Solution, Target Audience, Market & Competition, Business Model, "
        "Success Metrics, Milestones, Risks.\n"
        "===SPECIFICATIONS===\n"
        "  A specifications document (cahier des charges) with numbered "
        "sections: 1. Context, 2. Scope (In/Nice-to-have/Out), 3. Functional "
        "Requirements (numbered FR-01, FR-02, ...), 4. Non-Functional "
        "Requirements, 5. Technical Stack, 6. Data Model, 7. Deliverables, "
        "8. Planning & Constraints.\n"
        "===USER_STORIES===\n"
        "  A user stories document. Generate one story per persona/feature "
        "combination using the format: 'US-N — As a <role>, I want to "
        "<feature>, so that <benefit>.' Group by persona with H2 headers.\n"
        "\n"
        "Each document must start with a top-level '# Title — <project name>' heading. "
        f"Write everything in {language_name}."
    )

    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    text = _extract_text(response)
    return _split_markers(text)


def generate_custom(
    project: "Project", *, title: str, prompt: str, api_key: str | None = None
) -> str:
    """Generate one custom document body from a free-form prompt."""

    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    language_name = "French" if project.language == "fr" else "English"
    system = (
        "You are a senior software product manager and tech lead. Using the "
        "project brief (JSON) as context, write the requested document in "
        f"clean GitHub-flavored Markdown, in {language_name}. Do not invent "
        "facts that contradict the brief. Return Markdown only, no preamble."
    )
    user_msg = (
        "Project brief (JSON):\n```json\n"
        + _project_to_json(project)
        + "\n```\n\n"
        + f"Document title: {title}\n\n"
        + f"Instructions:\n{prompt or 'Write this document for the project.'}"
    )
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )
    body = _extract_text(response)
    if not body.lstrip().startswith("#"):
        body = f"# {title}\n\n{body}"
    return body.strip() + "\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _project_to_json(project: "Project") -> str:
    payload = {
        "name": project.name,
        "tagline": project.tagline,
        "language": project.language,
        "problem": project.problem,
        "solution": project.solution,
        "differentiation": project.differentiation,
        "competitors": project.competitors,
        "target_users": project.target_users,
        "personas": project.personas,
        "features": project.features,
        "nice_to_have": project.nice_to_have,
        "out_of_scope": project.out_of_scope,
        "business_model": project.business_model,
        "success_metrics": project.success_metrics,
        "stack": project.stack,
        "integrations": project.integrations,
        "hosting": project.hosting,
        "entities": project.entities,
        "timeline": project.timeline,
        "budget": project.budget,
        "risks": project.risks,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _extract_text(response) -> str:
    """Join the text blocks from an Anthropic Messages response."""

    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


_MARKERS = {
    "business_plan": "===BUSINESS_PLAN===",
    "specifications": "===SPECIFICATIONS===",
    "user_stories": "===USER_STORIES===",
}


def _split_markers(text: str) -> dict[str, str]:
    """Split Claude's output on the section markers."""

    # Build a regex that captures each section between markers.
    pattern = (
        r"===BUSINESS_PLAN===\s*(?P<business_plan>.*?)\s*"
        r"===SPECIFICATIONS===\s*(?P<specifications>.*?)\s*"
        r"===USER_STORIES===\s*(?P<user_stories>.*)\Z"
    )
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        # Fall back: whole text in business_plan, the rest empty.
        return {
            "business_plan": text or "",
            "specifications": "",
            "user_stories": "",
        }
    return {key: match.group(key).strip() + "\n" for key in _MARKERS}
