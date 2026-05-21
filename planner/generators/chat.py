"""Conversational project intake backed by Claude.

Instead of the one-shot :class:`~planner.forms.InterviewForm`, this drives a
chat: Claude interviews the user one question at a time and, once it has
enough to fill a project brief, emits a JSON block that we parse into
``Project`` field values.

The web layer keeps the running transcript (a list of ``{"role", "content"}``
dicts) in the session and calls :func:`next_turn` on every user message.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from .claude import _extract_text  # reuse the response-block joiner

if TYPE_CHECKING:  # pragma: no cover
    from django.contrib.auth.models import AbstractBaseUser


DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-5")
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", "2000"))

READY_MARKER = "===PROJECT_READY==="

# Anthropic's server-side web search tool. When enabled, Claude can look facts
# up online (competitors, market data, common stacks) while interviewing the
# user. Disable with ANTHROPIC_WEB_SEARCH=0 if your account/plan lacks it.
WEB_SEARCH_ENABLED = (
    os.environ.get("ANTHROPIC_WEB_SEARCH", "1").strip().lower()
    not in ("0", "false", "no", "off", "")
)
WEB_SEARCH_MAX_USES = int(os.environ.get("ANTHROPIC_WEB_SEARCH_MAX_USES", "5"))

# The model fields the brief JSON may set. Anything else is ignored.
_TEXT_FIELDS = {
    "name", "tagline", "problem", "solution", "differentiation", "competitors",
    "target_users", "business_model", "success_metrics", "stack",
    "integrations", "hosting", "timeline", "budget", "risks",
}
_LIST_FIELDS = {"features", "nice_to_have", "out_of_scope"}


def _system_prompt(language_name: str, *, web_search: bool = False) -> str:
    search_rule = (
        "- You can search the web to check facts the user is unsure about — "
        "competitors, market size, common tech stacks, integration options. "
        "Use it sparingly, and never search for the user's private or "
        "project-specific details; ask them instead. Briefly mention when an "
        "answer came from a search.\n"
        if web_search
        else ""
    )
    return (
        "You are DevPlanner's intake assistant — a senior product manager who "
        "interviews a developer about a software project they want to build. "
        f"Converse in {language_name}.\n\n"
        "Your job is to gather, through a friendly back-and-forth, enough to "
        "fill a project brief: name, tagline, the problem, the solution, what "
        "makes it different, competitors, target users and personas, the "
        "must-have features, nice-to-haves, out-of-scope items, business "
        "model, success metrics, technical stack, integrations, hosting, the "
        "core data entities, timeline, budget and risks.\n\n"
        "Rules:\n"
        "- Ask ONE focused question at a time. Keep it short and concrete.\n"
        "- Build on previous answers; don't re-ask what you already know.\n"
        "- It's fine to infer reasonable defaults and confirm them rather than "
        "interrogate the user on every field.\n"
        "- The essentials are name, problem, solution and target users; the "
        "rest is best-effort.\n"
        + search_rule
        + "\n"
        "When you have enough (or the user asks to finish), first write a one "
        "or two sentence confirmation, then on a NEW line output the marker "
        f"{READY_MARKER} followed by a single JSON object — and nothing after "
        "it. Use these keys (omit unknowns rather than inventing facts):\n"
        '  "name", "tagline", "problem", "solution", "differentiation", '
        '"competitors", "target_users", "business_model", "success_metrics", '
        '"stack", "integrations", "hosting", "timeline", "budget", "risks" '
        "(all strings);\n"
        '  "features", "nice_to_have", "out_of_scope" (arrays of strings);\n'
        '  "personas" (array of {"name","role","goal"});\n'
        '  "entities" (array of {"name","fields":[strings]}).\n'
        "Do not emit the marker until you actually have the essentials."
    )


def _build_tools() -> list[dict]:
    """Anthropic server-side tools enabled for the intake chat.

    Currently just the web search tool, gated by ``WEB_SEARCH_ENABLED``.
    """

    if not WEB_SEARCH_ENABLED:
        return []
    return [
        {
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        }
    ]


def derive_title(text: str, *, limit: int = 60) -> str:
    """A short, human-readable chat title from a message (e.g. the first one)."""

    cleaned = " ".join((text or "").split())
    if not cleaned:
        return "Untitled project"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "…"


def opening_message(language: str = "en") -> str:
    """First assistant turn — no API call needed, so the page loads instantly."""

    if language == "fr":
        return (
            "Bonjour ! Je vais vous aider à cadrer votre projet en quelques "
            "questions. Pour commencer : quelle est l'idée, en une phrase ?"
        )
    return (
        "Hi! I'll help you scope your project with a few questions. "
        "To start: what's the idea, in one sentence?"
    )


def next_turn(
    history: list[dict], *, api_key: str | None = None, language: str = "en"
) -> dict:
    """Run one assistant turn against ``history``.

    ``history`` is the full transcript so far (user + assistant messages).
    Returns ``{"reply", "done", "fields"}``: when ``done`` is True the
    ``fields`` dict holds the parsed project brief.
    """

    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    language_name = "French" if language == "fr" else "English"

    # The Anthropic API requires the first message to be from the user; our
    # transcript opens with the assistant's greeting, so drop leading
    # assistant turns before sending.
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    tools = _build_tools()
    create_kwargs = {
        "model": DEFAULT_MODEL,
        "max_tokens": MAX_TOKENS,
        "system": _system_prompt(language_name, web_search=bool(tools)),
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    response = client.messages.create(**create_kwargs)
    text = _extract_text(response)

    fields = _parse_ready(text)
    if fields is not None:
        reply = text.split(READY_MARKER, 1)[0].strip()
        if not reply:
            reply = (
                "Parfait, je crée le projet maintenant…"
                if language == "fr"
                else "Great — creating your project now…"
            )
        return {"reply": reply, "done": True, "fields": fields}
    return {"reply": text, "done": False, "fields": None}


# ---------------------------------------------------------------------------
# Availability
# ---------------------------------------------------------------------------
def api_key_for_user(user: "AbstractBaseUser") -> str | None:
    """The user's own Anthropic key, falling back to the environment."""

    profile = getattr(user, "profile", None)
    if profile and profile.anthropic_api_key:
        return profile.anthropic_api_key
    return os.environ.get("ANTHROPIC_API_KEY") or None


def is_available(user: "AbstractBaseUser") -> bool:
    """True when chat intake can run: a key is set and ``anthropic`` is installed."""

    if not api_key_for_user(user):
        return False
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Brief parsing
# ---------------------------------------------------------------------------
def _parse_ready(text: str) -> dict | None:
    """Extract and parse the JSON brief after the ready marker, if present."""

    if READY_MARKER not in text:
        return None
    after = text.split(READY_MARKER, 1)[1].strip()
    if after.startswith("```"):
        after = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", after.strip())
    # Be tolerant of trailing prose: grab the outermost {...}.
    start = after.find("{")
    end = after.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        data = json.loads(after[start : end + 1])
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def build_project_kwargs(fields: dict) -> dict:
    """Coerce a raw brief dict into safe ``Project(**kwargs)`` values.

    Unknown keys are dropped; types are normalised to what the model expects.
    """

    kwargs: dict = {}

    for key in _TEXT_FIELDS:
        value = fields.get(key)
        if isinstance(value, str):
            kwargs[key] = value.strip()
        elif value not in (None, ""):
            kwargs[key] = str(value)

    for key in _LIST_FIELDS:
        kwargs[key] = _string_list(fields.get(key))

    kwargs["personas"] = [
        {
            "name": str(p.get("name", "")).strip(),
            "role": str(p.get("role", "")).strip(),
            "goal": str(p.get("goal", "")).strip(),
        }
        for p in fields.get("personas", [])
        if isinstance(p, dict) and any(p.values())
    ]

    kwargs["entities"] = [
        {
            "name": str(e.get("name", "")).strip(),
            "fields": _string_list(e.get("fields")),
        }
        for e in fields.get("entities", [])
        if isinstance(e, dict) and e.get("name")
    ]

    # ``name`` is required by the model; give it a placeholder if missing.
    if not kwargs.get("name"):
        kwargs["name"] = "Untitled project"

    return kwargs


def _string_list(value) -> list[str]:
    """Normalise a brief value into a clean list of non-empty strings."""

    if isinstance(value, str):
        items = value.splitlines()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]
