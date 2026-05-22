"""Conversational project intake backed by Claude.

Instead of the one-shot :class:`~planner.forms.InterviewForm`, this drives a
chat: Claude interviews the user one question at a time and, once it has
enough to fill a project brief, emits a JSON block that we parse into
``Project`` field values.

The web layer persists the running transcript as ``ChatMessage`` rows (one per
turn, so chats survive across sessions and are resumable) and calls
:func:`next_turn` on every user message.
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from .claude import DEFAULT_MODEL, _extract_text  # single model source + block joiner

if TYPE_CHECKING:  # pragma: no cover
    from django.contrib.auth.models import AbstractBaseUser


# Intake turns are short Q&A, so they get their own (smaller) budget, separate
# from ANTHROPIC_MAX_TOKENS which sizes the long document-generation calls.
INTAKE_MAX_TOKENS = int(os.environ.get("ANTHROPIC_INTAKE_MAX_TOKENS", "2000"))

READY_MARKER = "===PROJECT_READY==="
PROPOSAL_MARKER = "===PROPOSAL==="

# The assistant may rewrite several whole document bodies in one turn, so it
# needs far more room than the intake chat's short turns. The response is
# streamed (see assistant_turn), so a large budget is safe. 64k is the max
# output for the default model (Sonnet 4.6); bump this if you switch to an
# Opus model (128k). No prefill continuation: 4.x models reject assistant
# prefill, so the turn must complete in one streamed response.
ASSISTANT_MAX_TOKENS = int(os.environ.get("ANTHROPIC_ASSISTANT_MAX_TOKENS", "64000"))
# OSS/Ollama models have far smaller context windows than Claude, so the
# assistant turn gets a conservative budget on that path.
OSS_ASSISTANT_MAX_TOKENS = int(os.environ.get("OSS_ASSISTANT_MAX_TOKENS", "4096"))

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
        "max_tokens": INTAKE_MAX_TOKENS,
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


def assistant_available(user: "AbstractBaseUser") -> bool:
    """The project assistant can run if Claude is available OR an OSS endpoint exists.

    OSS only needs an endpoint here (not a default model) — the model is chosen
    per conversation.
    """

    if is_available(user):
        return True
    from . import oss

    return oss.has_endpoint()


def available_models() -> dict:
    """Models for the per-conversation AI-options dropdown.

    ``{"claude": [...], "oss": [...]}`` — Claude is a static list; OSS is
    live-queried from the configured endpoint (empty if it's down).
    """

    from . import claude, oss

    return {"claude": list(claude.KNOWN_MODELS), "oss": oss.list_models()}


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

    kwargs["personas"] = _personas(fields.get("personas"))
    kwargs["entities"] = _entities(fields.get("entities"))

    # ``name`` is required by the model; give it a placeholder if missing.
    if not kwargs.get("name"):
        kwargs["name"] = "Untitled project"

    return kwargs


_STRUCT_FIELDS = {"personas", "entities"}
ALLOWED_FIELDS = _TEXT_FIELDS | _LIST_FIELDS | _STRUCT_FIELDS


def coerce_field(field: str, value) -> tuple[bool, object]:
    """Validate and normalise a single project-field change.

    Returns ``(ok, coerced_value)``; ``ok`` is False for unknown fields.
    """

    if field not in ALLOWED_FIELDS:
        return False, None
    if field in _TEXT_FIELDS:
        return True, (value.strip() if isinstance(value, str) else str(value).strip())
    if field in _LIST_FIELDS:
        return True, _string_list(value)
    if field == "personas":
        return True, _personas(value)
    if field == "entities":
        return True, _entities(value)
    return False, None


def _personas(value) -> list[dict]:
    return [
        {
            "name": str(p.get("name", "")).strip(),
            "role": str(p.get("role", "")).strip(),
            "goal": str(p.get("goal", "")).strip(),
        }
        for p in (value or [])
        if isinstance(p, dict) and any(p.values())
    ]


def _entities(value) -> list[dict]:
    return [
        {
            "name": str(e.get("name", "")).strip(),
            "fields": _string_list(e.get("fields")),
        }
        for e in (value or [])
        if isinstance(e, dict) and e.get("name")
    ]


def _string_list(value) -> list[str]:
    """Normalise a brief value into a clean list of non-empty strings."""

    if isinstance(value, str):
        items = value.splitlines()
    elif isinstance(value, (list, tuple)):
        items = value
    else:
        return []
    return [str(item).strip() for item in items if str(item).strip()]


# ===========================================================================
# Project assistant (post-creation chat that can edit info and documents)
# ===========================================================================
def assistant_opening_message(language: str = "en") -> str:
    if language == "fr":
        return (
            "J'ai chargé tout votre projet et ses documents. Que souhaitez-vous "
            "modifier, compléter ou améliorer ?"
        )
    return (
        "I've loaded your whole project and its documents. What would you like "
        "to change, finish or improve?"
    )


def build_project_context(project) -> str:
    """A text snapshot of the project: all interview fields + every document.

    Fed to the assistant each turn so it answers and edits with full context.
    """

    from .claude import _project_to_json

    parts = [
        "# PROJECT FIELDS (JSON)",
        "```json",
        _project_to_json(project),
        "```",
        "",
        "# DOCUMENTS",
    ]
    docs = list(project.documents.all())
    if not docs:
        parts.append("(no documents yet)")
    for d in docs:
        parts.append(
            f"\n## document_id={d.pk} · kind={d.kind} · title={d.title!r}"
        )
        parts.append(d.body or "(empty)")
    return "\n".join(parts)


def _assistant_system_prompt(language_name: str, *, web_search: bool = False) -> str:
    search_rule = (
        "- You may search the web to check general facts (competitors, market "
        "data, common stacks). Never search for the user's private details.\n"
        if web_search
        else ""
    )
    return (
        "You are DevPlanner's project assistant. The user already has a project "
        "and its planning documents, given to you as context. Help them improve "
        "it: answer questions, finish incomplete documents, rewrite or extend "
        "any document, and update project fields.\n"
        f"Converse in {language_name}.\n\n"
        "Rules:\n"
        "- Be concrete and concise; ask a clarifying question if the request is "
        "ambiguous.\n"
        + search_rule
        + "- When the user wants a concrete change, don't just describe it — "
        "PROPOSE it. Write a short conversational reply, then on a NEW line "
        f"output the marker {PROPOSAL_MARKER} followed by a single JSON object "
        "and nothing after it:\n"
        '  {"summary": "...", "changes": [ ... ]}\n'
        "Each change is one of:\n"
        '  - Document: {"type":"document","document_id":<int, omit to create '
        'new>,"kind":"<kind>","title":"...","body":"<COMPLETE new markdown '
        'body>","note":"what changed"}\n'
        '  - Field: {"type":"field","field":"<name>","value":<string or '
        'array>,"note":"..."}\n'
        "Always give the full new document body, never a diff. To edit an "
        "existing document include its document_id; to add one omit it and use "
        'kind "custom".\n'
        "Valid fields: name, tagline, problem, solution, differentiation, "
        "competitors, target_users, business_model, success_metrics, stack, "
        "integrations, hosting, timeline, budget, risks (strings); features, "
        "nice_to_have, out_of_scope (string arrays); personas (array of "
        '{name,role,goal}); entities (array of {name,fields:[...]}).\n'
        "- Diagrams (use case, ERD, user flow) are generated automatically and "
        "deterministically from project fields. NEVER write or edit a diagram "
        "document body or any Mermaid yourself. To change a diagram, propose a "
        "FIELD change to its source data: use case = personas + features; ERD = "
        "entities; user flow = features + success_metrics + name. The diagram "
        "documents are regenerated for you.\n"
        "- IMPORTANT: never reply with only an acknowledgement like \"I'll "
        "rewrite the documents now\" and then stop. In the SAME message, after "
        "your short reply, include the complete proposal with the full document "
        "bodies. Do not defer the work to a later turn.\n"
        "Only emit the marker when you have a concrete change to propose; "
        "otherwise reply normally without it."
    )


def assistant_turn(
    history: list[dict], context: str, *, api_key: str | None = None,
    language: str = "en", provider: str = "claude", model: str | None = None,
) -> dict:
    """One project-assistant turn.

    Routes to Claude (default) or an OpenAI-compatible OSS endpoint
    (Ollama/OpenAI) per ``provider``; ``model`` overrides the backend default.
    Returns ``{"reply", "proposals", "summary"}``. ``proposals`` is a list of
    change dicts the user must confirm before they're applied (empty if the
    assistant only chatted).
    """

    language_name = "French" if language == "fr" else "English"
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    while messages and messages[0]["role"] != "user":
        messages.pop(0)

    if provider == "oss":
        return _assistant_turn_oss(messages, context, language, language_name, model)

    import anthropic

    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    tools = _build_tools()
    # The system prompt + full project context is large and stable across the
    # turns of one assistant conversation, so cache it (cache_control) to cut
    # cost and latency on follow-up turns. Volatile content (the conversation
    # messages) stays after it, preserving the cached prefix.
    system = [
        {
            "type": "text",
            "text": (
                _assistant_system_prompt(language_name, web_search=bool(tools))
                + "\n\n# CURRENT PROJECT CONTEXT\n"
                + context
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    create_kwargs = {
        "model": model or DEFAULT_MODEL,
        "max_tokens": ASSISTANT_MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    if tools:
        create_kwargs["tools"] = tools

    # Stream the response: a multi-document rewrite can use a large max_tokens,
    # and streaming avoids the SDK's non-streaming timeout guard on big outputs.
    # opus-4-7 does not support assistant-message prefill, so the old
    # continue-on-max_tokens prefill loop is gone — one generous, streamed
    # response replaces it. The conversation always ends on a user message.
    with client.messages.stream(**create_kwargs) as stream:
        response = stream.get_final_message()
    text = _extract_text(response)
    truncated = getattr(response, "stop_reason", None) == "max_tokens"
    return _finish_assistant_turn(text, language, truncated)


def _assistant_turn_oss(
    messages: list[dict], context: str, language: str, language_name: str,
    model: str | None,
) -> dict:
    """Assistant turn via an OpenAI-compatible OSS endpoint (Ollama/OpenAI).

    No tools and no prompt caching (not supported there), and a smaller token
    budget. Proposals are best-effort: smaller models are less reliable at the
    strict ``===PROPOSAL===`` JSON, but if one is emitted it parses the same way.
    """

    from openai import OpenAI

    from . import oss

    cfg = oss.config()
    system_text = (
        _assistant_system_prompt(language_name, web_search=False)
        + _OSS_PROPOSAL_EXAMPLE
        + "\n\n# CURRENT PROJECT CONTEXT\n"
        + context
    )
    client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
    response = client.chat.completions.create(
        model=model or cfg["model"],
        max_tokens=OSS_ASSISTANT_MAX_TOKENS,
        messages=[{"role": "system", "content": system_text}] + messages,
    )
    choice = response.choices[0]
    text = (choice.message.content or "").strip()
    truncated = getattr(choice, "finish_reason", None) == "length"
    # Lenient parsing: smaller models often drop the marker or wrap the JSON in
    # a code fence — accept those rather than losing the change.
    return _finish_assistant_turn(text, language, truncated, lenient=True)


# Concrete example shown only to OSS models (which follow the format less
# reliably than Claude). Demonstrates the exact marker + envelope.
_OSS_PROPOSAL_EXAMPLE = (
    "\n\n# EXAMPLE of a proposal turn (follow this format EXACTLY)\n"
    "User: Add a custom doc called \"Security Plan\".\n"
    "Assistant:\n"
    "I've drafted a Security Plan.\n"
    + PROPOSAL_MARKER + "\n"
    '{"summary": "Add a Security Plan document", "changes": [{"type": "document", '
    '"kind": "custom", "title": "Security Plan", "body": "# Security Plan\\n\\n'
    '## Authentication\\n- ...\\n"}]}'
)


def _finish_assistant_turn(
    text: str, language: str, truncated: bool, *, lenient: bool = False,
) -> dict:
    """Shared post-processing for a raw assistant response (both backends).

    ``lenient`` (OSS path) accepts a proposal that omits the marker / wraps the
    JSON in a code fence, and strips that blob out of the shown reply.
    """

    proposals, summary = _parse_proposal(text, lenient=lenient)
    reply = text
    if PROPOSAL_MARKER in text:
        reply = text.split(PROPOSAL_MARKER, 1)[0].strip()
    elif lenient and proposals:
        # No marker, but we extracted a JSON proposal — strip it from the reply.
        reply = _strip_json_blob(text).strip()
    if proposals and not reply:
        reply = summary or "Here's what I'd change — review and apply below."
    # If we ran out of room before a valid proposal closed, say so rather than
    # silently dropping the half-written changes.
    if truncated and not proposals:
        note = (
            " (La réponse était trop longue ; demandez-moi de ne modifier qu'un "
            "document à la fois.)"
            if language == "fr"
            else " (That response was too long to finish — ask me to change one "
            "document at a time.)"
        )
        reply = (reply or "").rstrip() + note
    return {"reply": reply, "proposals": proposals or [], "summary": summary}


def _parse_proposal(text: str, *, lenient: bool = False) -> tuple[list | None, str]:
    """Extract ``(changes, summary)`` from a proposal.

    Strict (default): requires the ``===PROPOSAL===`` marker. ``lenient`` (OSS
    path) additionally accepts an unmarked proposal — a fenced/bare JSON object
    that is either the ``{"summary","changes":[...]}`` envelope or a single
    bare change dict — since small models often drop the marker.
    """

    if PROPOSAL_MARKER in text:
        after = text.split(PROPOSAL_MARKER, 1)[1].strip()
        result = _changes_from(_loads_json_blob(after))
        if result is not None or not lenient:
            return result if result is not None else (None, "")
    elif not lenient:
        return None, ""
    # Lenient fallback: scan the whole reply for a JSON proposal.
    return _changes_from(_loads_json_blob(text)) or (None, "")


def _loads_json_blob(text: str):
    """Parse the first JSON object in ``text`` — a ```` ```json ```` fence if
    present, else the outermost ``{...}``. Returns the parsed value or ``None``."""

    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidate = fence.group(1) if fence else None
    if candidate is None:
        start, end = text.find("{"), text.rfind("}")
        candidate = text[start : end + 1] if start != -1 and end > start else None
    if not candidate:
        return None
    try:
        return json.loads(candidate)
    except (ValueError, TypeError):
        return None


def _changes_from(data) -> tuple[list, str] | None:
    """Build ``(changes, summary)`` from a parsed envelope or bare change dict."""

    if not isinstance(data, dict):
        return None
    if isinstance(data.get("changes"), list):
        raw, summary = data["changes"], str(data.get("summary", ""))
    elif data.get("type") in ("document", "field"):
        raw, summary = [data], ""  # a single bare change
    else:
        return None
    changes = [
        _normalize_change(c) for c in raw
        if isinstance(c, dict) and c.get("type") in ("document", "field")
    ]
    return (changes, summary) if changes else None


def _normalize_change(change: dict) -> dict:
    """Coerce a document change toward a valid kind (new/unknown kind → custom)."""

    if change.get("type") != "document":
        return change
    from planner.models import Document

    valid_kinds = {k for k, _ in Document.KIND_CHOICES}
    if change.get("kind") not in valid_kinds:
        change = {**change, "kind": Document.KIND_CUSTOM}
    return change


def _strip_json_blob(text: str) -> str:
    """Remove a fenced/bare JSON object from a reply (lenient OSS path)."""

    stripped = re.sub(r"```(?:json)?\s*\{.*\}\s*```", "", text, flags=re.DOTALL)
    if stripped != text:
        return stripped
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[:start] + text[end + 1 :]
    return text
