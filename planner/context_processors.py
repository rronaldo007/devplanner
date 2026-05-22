"""Template context processors for the planner app."""

from __future__ import annotations

from .generators import chat, errors


def ai_status(request):
    """Expose an ``ai_banner`` dict to dashboard templates when AI is unusable.

    The banner shows when the signed-in user has no Anthropic API key (the app
    runs in template mode), or when a recent AI call failed for a persistent
    reason (out of credits / invalid key — stored in the session by the chat
    views and cleared on the next successful call).
    """

    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}

    key_set = bool(chat.api_key_for_user(user))
    session_status = request.session.get("ai_status")

    if not key_set:
        return {"ai_banner": {
            "category": errors.AUTH,
            "message": (
                "No Anthropic API key is set — DevPlanner is running in template "
                "mode. Add a key in Settings to enable AI generation and chat."
            ),
        }}
    if session_status in (errors.CREDITS, errors.AUTH):
        return {"ai_banner": {
            "category": session_status,
            "message": errors.FRIENDLY[session_status],
        }}
    return {"ai_banner": None}
