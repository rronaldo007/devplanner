# Session 01 — Chat intake + project assistant

**Date:** 2026-05-21
**Branch:** `feat/chat-project-intake`
**PR:** https://github.com/rronaldo007/devplanner/pull/2 → base `devin/1779352320-multi-user-dashboard`
**Status:** committed + pushed + PR open. **Migrations 0002 & 0003 must be applied** in any env (`migrate`).

---

## What we built this session

### 0. Refactor (warm-up)
- Split `planner/generators/__init__.py` into a thin re-export **facade** over new
  `planner/generators/engine.py` (engine selection + `generate_all`/`generate_custom`/
  `regenerate`/`sync_default_documents` live in engine.py now). Dropped dead `DOC_KEY_TO_KIND`.

### 1. Chat-based project intake — commit `8fe05cd`
- `planner/generators/chat.py`: Claude-driven interview. `next_turn(history)` asks one
  question at a time, emits `===PROJECT_READY===` + JSON brief; `build_project_kwargs`
  maps it to `Project` fields.
- **Draft created at chat start**; every turn persisted as `ChatMessage` (fixes "I started a
  chat and lost it" — it used to be session-only). Resumable.
- Drafts hidden from dashboard (`is_draft`); "Unfinished chats" resume area; new chat reuses
  an untouched draft instead of duplicating.
- Editable chat **title** (auto from first message; inline rename; manual title preserved).
- **Web search** via Anthropic server-side tool `web_search_20250305`, gated by
  `ANTHROPIC_WEB_SEARCH` (default on).
- No API key → falls back to the classic interview form.

### 2. Project assistant — commit `0629bc5`
- "🤖 Assistant" button on every finalised project (chat- or form-created).
- `chat.assistant_turn(history, context)`: full context = all project fields + **every
  document body**. Emits `===PROPOSAL===` JSON of changes.
- **Propose-then-confirm**: proposal cards with Apply/Discard; nothing saved until Apply.
  Apply updates docs by id / reuses default-kind docs / creates custom docs; field changes
  validated via `chat.coerce_field` allowlist.
- **Auto-continue on `max_tokens`** (prefill, up to `ANTHROPIC_ASSISTANT_CONTINUATIONS=3`) so
  multi-doc rewrites finish in one request and the loading state stays visible. Prompt forbids
  deferring work ("I'll do it now" + stop). Honest note if it still can't finish.
- `ChatMessage` gained `phase` (intake/assistant), `proposals`, `proposal_status`.

---

## Key files
- `planner/generators/chat.py` — intake + assistant logic, web search, parsing, coercion.
- `planner/generators/engine.py` / `__init__.py` — generator facade.
- `planner/generators/diagrams.py` — **deterministic Mermaid** diagrams (use_case/erd/flow) from project fields. (Relevant to the open draw.io question below.)
- `planner/views.py` — `project_new_chat`, `project_chat`, `project_chat_message`,
  `project_chat_rename`, `project_assistant`, `project_assistant_message`,
  `project_assistant_apply` + `_apply_changes`/`_apply_document_change`/`_apply_field_change`.
- `planner/models.py` — `Project.is_draft`; `ChatMessage` (+phase/proposals/proposal_status).
- Templates: `dashboard/chat.html`, `dashboard/assistant.html`, plus edits to
  `_base_dashboard.html`, `dashboard/index.html`, `dashboard/interview.html`, `project_detail.html`.
- `planner/tests.py` — 76 tests passing on `.venv` (which has `anthropic`).

## Env / config knobs
`ANTHROPIC_WEB_SEARCH`, `ANTHROPIC_WEB_SEARCH_MAX_USES`, `ANTHROPIC_ASSISTANT_MAX_TOKENS`
(8000), `ANTHROPIC_ASSISTANT_CONTINUATIONS` (3), `ANTHROPIC_MODEL`, `ANTHROPIC_MAX_TOKENS`.

## Gotchas
- **Two Pythons**: pyenv `python` lacks `anthropic` (one engine test "fails" there); the
  project's `.venv/bin/python` has it and runs all 76 green. Use `.venv` for tests.
- The user applies migrations via their own **refresh script**, not me running `migrate`.
- Anthropic API is **stateless** — chat history lives in the local SQLite DB, not at Anthropic.
  Don't ask for / accept the user's API key; it's already configured and working.
- Long multi-doc assistant rewrites hold one request open; fine on dev server, may need
  streaming/SSE behind a short-timeout proxy in prod.

---

## OPEN / NEXT — draw.io diagram generation (paused mid-decision)
User asked about generating **draw.io (diagrams.net)** versions of the 3 diagrams.
Feasible: `.drawio` = mxGraph XML, generatable deterministically from the same project data
used in `diagrams.py`. **Main wrinkle:** draw.io stores explicit x/y coords (no auto-layout
like Mermaid), so each diagram type needs a simple layout pass.

I offered 3 delivery options + 3 placement options (via AskUserQuestion) — **user paused to
clarify first and did NOT pick**. Pending decisions:
1. Approach: (a) generate native `.drawio` XML, (b) export existing Mermaid for draw.io import,
   or (c) first just render the stored Mermaid in-app (need to confirm whether the diagram docs
   currently render visually or show raw Mermaid text — NOT yet checked).
2. Placement: alongside Mermaid / new docs / replace Mermaid.
3. Deterministic (like current diagrams) vs AI-generated.

---

## `.claude/` scaffolding added this session (uncommitted)
- **`.claude/docs/`** — all project docs consolidated here (root `docs/` was removed):
  - `CHAT_AND_ASSISTANT.md` — full feature reference (chats, endpoints, env vars, model).
  - `architecture.md` — codebase map.
  - `conventions.md` — editing rules.
  - `README.md` — index.
- **`.claude/agents/`** — `django-reviewer.md` (review-only agent encoding project
  conventions) + `README.md` (agent file format).
- **`.claude/sessions/session_01.md`** — this file.
- Memory written to `~/.claude/projects/-home-ronaldo-my-projects-devplanner/memory/`:
  `drawio-diagrams-pending`, `dont-request-api-key`, `use-venv-not-pyenv` (+ `MEMORY.md`).

**Uncommitted:** `.claude/` (incl. these) and previously the removed root `docs/`. The
two feature commits (`8fe05cd`, `0629bc5`) are pushed in PR #2; the `.claude/` files are
NOT in any commit.

**Resume here:** ask the user what they wanted to clarify, then reframe those questions.
