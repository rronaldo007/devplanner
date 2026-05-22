# Conventions

Follow these when editing DevPlanner.

## Code
- Match the surrounding code's style, comment density, and naming. Prefer
  fat-model / thin-view; avoid N+1 queries.
- Generators: keep `generators/__init__.py` a thin facade over `engine.py`.
  Diagrams stay **deterministic** (no LLM). LLM paths (`claude.py`, `chat.py`)
  must degrade gracefully when `anthropic` or an API key is missing.
- Views: scope every project/document/chat query to `request.user`
  (`_owned_project`). POST endpoints are CSRF-protected; JSON endpoints read the
  `X-CSRFToken` header.

## AI chat
- Persist transcripts as `ChatMessage` (never session-only). Separate `intake`
  vs `assistant` phases.
- Assistant edits are **propose-then-confirm**: write to `Document`/`Project`
  only when the user applies a proposal. Validate field changes against the
  allowlist (`chat.coerce_field`).
- Never request or log the user's API key. Keys come from `UserProfile` then the
  `ANTHROPIC_API_KEY` env var.

## Migrations & tests
- Any model change needs a migration. The user applies migrations via their own
  refresh script — don't run `migrate` for them; just tell them.
- Run tests with **`.venv/bin/python manage.py test planner`** (the `.venv` has
  `anthropic`; tests stub it, so no network/key is needed). Keep the suite green.
