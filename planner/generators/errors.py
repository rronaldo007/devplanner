"""Classify Claude/API failures into friendly, non-leaky user messages.

Pure Python (no Django imports) so it's usable from views, the engine, and unit
tests. Works on an exception object OR a string (e.g. the engine's stored
``_claude_error``). It never returns raw provider text — the messages here are
safe to show to end users.
"""

from __future__ import annotations

CREDITS = "credits"
AUTH = "auth"
RATE_LIMIT = "rate_limit"
OVERLOADED = "overloaded"
GENERIC = "generic"

# Categories that should raise a persistent banner (the API is unusable until
# the account/key is fixed), vs. transient ones the user can just retry.
_PERSISTENT = {CREDITS, AUTH}

FRIENDLY = {
    CREDITS: (
        "AI features are paused — the Anthropic account is out of credits. "
        "Add credit in the Anthropic console (or update your API key in "
        "Settings). Everything else keeps working: templates, the interview "
        "form, diagrams and notes."
    ),
    AUTH: (
        "AI features are unavailable — the Anthropic API key is missing or "
        "invalid. Check your key in Settings."
    ),
    RATE_LIMIT: (
        "The AI is busy right now (rate limit). Please wait a moment and try "
        "again."
    ),
    OVERLOADED: (
        "The AI service is temporarily overloaded. Please try again in a few "
        "seconds."
    ),
    GENERIC: (
        "Something went wrong reaching the AI. Please try again — your work is "
        "saved."
    ),
}


def _category_from_status(status) -> str | None:
    if status == 429:
        return RATE_LIMIT
    if status == 529:
        return OVERLOADED
    if status in (401, 403):
        return AUTH
    return None


def _category_from_type(type_str: str) -> str | None:
    mapping = {
        "authentication_error": AUTH,
        "permission_error": AUTH,
        "rate_limit_error": RATE_LIMIT,
        "overloaded_error": OVERLOADED,
    }
    return mapping.get(type_str)


def _category_from_text(text: str) -> str:
    t = text.lower()
    # Credits first: the real out-of-credits error is HTTP 400, so we can't
    # rely on status code for it.
    if "credit balance" in t or "out of credit" in t or "billing" in t or (
        "insufficient" in t and "credit" in t
    ):
        return CREDITS
    if (
        "authentication" in t
        or "invalid x-api-key" in t
        or "invalid api key" in t
        or "unauthorized" in t
        or "401" in t
        or "403" in t
    ):
        return AUTH
    if "rate limit" in t or "rate_limit" in t or "too many requests" in t or "429" in t:
        return RATE_LIMIT
    if "overloaded" in t or "529" in t:
        return OVERLOADED
    return GENERIC


def category_of(exc_or_text) -> str:
    """Best-effort category for an exception or error string."""

    # Typed/structured signals (defensive — the test stub raises plain
    # exceptions with none of these attributes, so this no-ops there).
    if not isinstance(exc_or_text, str):
        status = getattr(exc_or_text, "status_code", None)
        if status is None:
            status = getattr(getattr(exc_or_text, "response", None), "status_code", None)
        # A 400 may still be a credits error — let the text check decide that;
        # only trust status for the unambiguous codes.
        by_status = _category_from_status(status)
        type_str = getattr(exc_or_text, "type", None)
        by_type = _category_from_type(type_str) if isinstance(type_str, str) else None
        # Text check can override (e.g. credits hidden in a 400 message).
        by_text = _category_from_text(str(exc_or_text))
        if by_text == CREDITS:
            return CREDITS
        return by_type or by_status or by_text

    return _category_from_text(exc_or_text)


def classify(exc_or_text) -> tuple[str, str]:
    """Return ``(category, friendly_message)``."""

    category = category_of(exc_or_text)
    return category, FRIENDLY.get(category, FRIENDLY[GENERIC])


def friendly_message(exc_or_text) -> str:
    return classify(exc_or_text)[1]


def is_persistent(category: str) -> bool:
    return category in _PERSISTENT
