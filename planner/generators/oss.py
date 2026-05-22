"""OpenAI-compatible generator (Ollama, OpenAI, or any compatible host).

This is the cheap/free tier of the fallback chain: when Claude is unavailable
(no key, or out of credits) the engine falls back here before degrading to
templates. It speaks the OpenAI Chat Completions API, so it works against:

* **Ollama** — local *or* a remote host (e.g. a "shadow PC"); set
  ``OSS_BASE_URL`` to ``http://<host>:11434/v1`` and ``OSS_API_KEY`` to any
  non-empty placeholder.
* **OpenAI** — ``OSS_BASE_URL=https://api.openai.com/v1`` with a real key.
* Any other OpenAI-compatible provider (Groq, Together, OpenRouter, ...).

Prompts are shared with :mod:`planner.generators.claude` so the two engines
stay single-sourced.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from . import classify as _classify
from .claude import (
    _split_markers,
    custom_prompt,
    documents_prompt,
    finalize_custom_body,
)

if TYPE_CHECKING:  # pragma: no cover
    from planner.models import Project

# Output ceiling for prose docs; classification stays tiny.
MAX_TOKENS = int(os.environ.get("OSS_MAX_TOKENS", "8000"))
CLASSIFY_MAX_TOKENS = int(os.environ.get("OSS_CLASSIFY_MAX_TOKENS", "16"))


def _base_url() -> str:
    """Resolve the OSS endpoint: OSS_BASE_URL, else derive from Ollama's OLLAMA_HOST.

    Many setups already export ``OLLAMA_HOST=http://host:11434`` (Ollama's own
    var). We reuse it — appending the OpenAI-compatible ``/v1`` path — so the
    OSS engine works without a second env var.
    """

    base = os.environ.get("OSS_BASE_URL", "").strip()
    if base:
        return base
    ollama_host = os.environ.get("OLLAMA_HOST", "").strip()
    if ollama_host:
        return ollama_host.rstrip("/") + "/v1"
    return ""


def config() -> dict[str, str]:
    """Read the OSS endpoint config from the environment (live, for testability)."""

    return {
        "base_url": _base_url(),
        "model": os.environ.get("OSS_MODEL", "").strip(),
        # Ollama ignores the key but the SDK requires a non-empty value.
        "api_key": os.environ.get("OSS_API_KEY", "").strip() or "ollama",
    }


def has_endpoint() -> bool:
    """True when an OSS endpoint is reachable-in-principle (base_url resolved).

    Enough to *list* models and to run a call where the model is supplied by the
    caller (e.g. a per-conversation choice). Does not require OSS_MODEL.
    """

    return bool(config()["base_url"])


def is_configured() -> bool:
    """True when OSS can run with no per-call model (base_url + default model).

    Used by the document-generation fallback chain, where the model comes from
    OSS_MODEL rather than per-conversation.
    """

    cfg = config()
    return bool(cfg["base_url"] and cfg["model"])


def list_models(timeout: float = 4.0) -> list[str]:
    """Live list of model ids from the configured OSS endpoint.

    Returns ``[]`` on any failure (endpoint down/misconfigured) so callers can
    degrade gracefully to a static list.
    """

    cfg = config()
    if not cfg["base_url"]:
        return []
    try:
        from openai import OpenAI

        client = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"], timeout=timeout)
        return sorted(m.id for m in client.models.list().data)
    except Exception:
        return []


def _client(base_url: str, api_key: str):
    from openai import OpenAI

    return OpenAI(base_url=base_url, api_key=api_key)


def _complete(system: str, user_msg: str, *, max_tokens: int,
              base_url: str, model: str, api_key: str) -> str:
    client = _client(base_url, api_key)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )
    return (response.choices[0].message.content or "").strip()


def generate_documents(
    project: "Project", *, base_url: str, model: str, api_key: str
) -> dict[str, str]:
    """Business plan + specifications + user stories via an OSS model."""

    system, user_msg = documents_prompt(project)
    text = _complete(
        system, user_msg, max_tokens=MAX_TOKENS,
        base_url=base_url, model=model, api_key=api_key,
    )
    return _split_markers(text)


def generate_custom(
    project: "Project", *, title: str, prompt: str,
    base_url: str, model: str, api_key: str,
) -> str:
    """One custom document body via an OSS model."""

    system, user_msg = custom_prompt(project, title, prompt)
    body = _complete(
        system, user_msg, max_tokens=MAX_TOKENS,
        base_url=base_url, model=model, api_key=api_key,
    )
    return finalize_custom_body(body, title)


def classify(
    title: str, body: str, *, base_url: str, model: str, api_key: str
) -> str:
    """Return a category slug via an OSS model. Raises on an unknown slug."""

    system, user_msg = _classify.classify_prompt(title, body)
    raw = _complete(
        system, user_msg, max_tokens=CLASSIFY_MAX_TOKENS,
        base_url=base_url, model=model, api_key=api_key,
    )
    return _classify.normalize_slug(raw)
