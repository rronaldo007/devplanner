# DevPlanner — AI Chat & Project Assistant

Reference for the AI chat features: creating projects by conversation and the
ongoing project assistant that edits info and documents. Covers every option,
endpoint, and configuration knob.

Implementation lives in `planner/generators/chat.py` (logic), `planner/views.py`
(HTTP), `planner/urls.py` (routes), `planner/models.py` (storage), and the
`planner/templates/planner/dashboard/` templates.

---

## 1. Overview

There are **two** AI chats, both Claude-powered and both storing their transcript
in the database (`ChatMessage`):

| Chat | When | Purpose | Phase |
|------|------|---------|-------|
| **Intake** | Creating a project | Interview → fill the brief → generate the 6 default docs | `intake` |
| **Project assistant** | After a project exists | Answer questions, edit project info, finish/rewrite/create documents | `assistant` |

Both require an Anthropic API key (per-user in Settings, or the `ANTHROPIC_API_KEY`
env var) and the `anthropic` package installed. Without a key the intake chat
falls back to the classic interview form, and the assistant is unavailable.

---

## 2. Chat-based project intake

**Entry points:** "💬 Start with chat" on the dashboard, the sidebar "New project"
link, and a "Prefer a guided chat?" link on the interview form.

### Behaviour / options
- **Draft created immediately.** Starting a chat creates a draft `Project`
  (`is_draft=True`) and seeds the assistant's opening question. The transcript is
  saved per turn, so it survives reloads and can be resumed (it is no longer
  session-only).
- **Drafts are hidden** from the dashboard project grid, sidebar, and counts. They
  appear in an **"Unfinished chats"** section with **Resume** and **Discard**.
- **No duplicate drafts.** Starting a new chat reuses an existing *untouched* draft
  (one with no user messages) instead of creating another empty one. Once a draft
  has real messages, a new chat starts a separate draft.
- **Editable title.** The draft is auto-titled from your first message (cleaned,
  ≤60 chars). The title in the chat header is an inline input — rename on blur or
  Enter, Esc cancels. A manually set title is **not** overwritten by the auto-title.
- **Completion.** When Claude has enough, it emits a hidden `===PROJECT_READY===`
  marker + JSON brief. The draft's fields are filled, `is_draft` cleared, and the
  six default documents generated. You're redirected to the project.
- **Web search** (see §5) lets the interviewer look up general facts.
- **Fallback.** No API key → redirected to the classic interview form with a notice.

### Endpoints
| Route | Name | Method | Purpose |
|-------|------|--------|---------|
| `/projects/new/chat/` | `project_new_chat` | GET | Start/resume a draft chat |
| `/projects/<pk>/chat/` | `project_chat` | GET | Render a draft's chat (resumes transcript) |
| `/projects/<pk>/chat/message/` | `project_chat_message` | POST (JSON) | One turn; finalises on completion |
| `/projects/<pk>/chat/rename/` | `project_chat_rename` | POST (JSON) | Rename the draft |

---

## 3. Project assistant

**Entry point:** the **"🤖 Assistant"** button on a finalised project's page.
(A draft opens its intake chat instead; a project with no key redirects to the
project page with a notice.)

### What it knows
Every turn, the assistant receives **full context**: all project interview fields
(as JSON) **plus the complete body of every document** (with each document's id,
kind, and title). So it can answer accurately and finish/rewrite existing docs.

### What it can do — and how changes apply
The assistant can:
- **Edit project info** — any interview field (validated against an allowlist).
- **Rewrite or finish documents** — provides the complete new body.
- **Create new documents** — as custom docs.

**Propose-then-confirm.** When you ask for a change, the assistant replies and emits
a hidden `===PROPOSAL===` JSON. The UI shows a **proposal card** listing each change
with an **Apply** and **Discard** button. **Nothing is saved until you click Apply.**
- Apply → changes are written: documents updated by id, default-kind docs reused,
  or new custom docs created; field changes coerced and saved. The card shows
  "✓ Applied — …".
- Discard → nothing changes; card shows "Discarded".
- A proposal can't be applied twice (returns HTTP 409).

### Finishing long / multi-document rewrites
- The system prompt **forbids deferring work** ("I'll do it now" then stopping) — the
  full proposal must come in the same turn.
- The assistant turn is **streamed** with `ANTHROPIC_ASSISTANT_MAX_TOKENS`
  (default 128000 — opus-4-7's max output ceiling), so multi-document rewrites
  finish in one request. While this runs, the chat keeps showing its **"Thinking…"**
  loading state. (No prefill-continuation: opus-4-7 rejects assistant-message prefill.)
- If a turn still hits the token limit (`max_tokens`) without a complete proposal, the
  reply ends with an honest note ("That response was too long to finish — ask me to
  change one document at a time").

### Endpoints
| Route | Name | Method | Purpose |
|-------|------|--------|---------|
| `/projects/<pk>/assistant/` | `project_assistant` | GET | Render assistant chat (seeds opening) |
| `/projects/<pk>/assistant/message/` | `project_assistant_message` | POST (JSON) | One turn; returns reply + proposals |
| `/projects/<pk>/assistant/apply/` | `project_assistant_apply` | POST (JSON) | Apply or discard a pending proposal |

---

## 4. Documents & diagrams (context)

Each project has six default documents, created at finalisation:
- **Planning (Markdown):** Business Plan, Cahier des Charges (Specifications), User Stories.
- **Diagrams (Mermaid):** Use Case, ERD, User Flow — generated **deterministically**
  from project fields in `planner/generators/diagrams.py` (no LLM).

The assistant can edit any of these and add custom documents.
> Open item: generating **draw.io** versions of the diagrams is under discussion
> (see `.claude/sessions/session_01.md`).

---

## 5. Web search (intake + assistant)

Uses Anthropic's **server-side** web search tool (`web_search_20250305`) — searches
run on Anthropic's side and return text with citations; no search provider to wire.
Claude is told to search only for general facts (competitors, market data, common
stacks), never the user's private details.

- Default **on**. Disable with `ANTHROPIC_WEB_SEARCH=0`.
- Requires the feature to be enabled on your Anthropic account/plan; if not, turns
  may error — disable it then.

---

## 6. Configuration (environment variables)

| Variable | Default | Effect |
|----------|---------|--------|
| `ANTHROPIC_API_KEY` | — | Fallback key when a user has none in their profile |
| `ANTHROPIC_MODEL` | `claude-opus-4-7` | Model for all chat/generation calls (defined once in `generators/claude.py`) |
| `ANTHROPIC_INTAKE_MAX_TOKENS` | `2000` | Max tokens per intake turn (short Q&A) |
| `ANTHROPIC_MAX_TOKENS` | `16000` | Max tokens for document-generation responses (non-streaming; ~16k is the safe ceiling) |
| `ANTHROPIC_ASSISTANT_MAX_TOKENS` | `128000` | Max tokens per assistant turn (opus-4-7's output ceiling). The turn is streamed, so this is safe. |
| `ANTHROPIC_WEB_SEARCH` | `1` (on) | Enable server-side web search (`0`/`false`/`off` to disable) |
| `ANTHROPIC_WEB_SEARCH_MAX_USES` | `5` | Max searches per turn |

Per-user settings (Settings page): Anthropic API key, default language (en/fr).

---

## 7. Data model

- **`Project.is_draft`** — true while a chat-created project is unfinished; hides it
  from listings.
- **`ChatMessage`** — one chat turn, FK to `Project` (`related_name="chat_messages"`).
  Fields:
  - `phase` — `intake` or `assistant` (separates the two transcripts).
  - `role` — `user` or `assistant`.
  - `content` — the message text.
  - `proposals` (JSON) — proposed changes attached to an assistant turn.
  - `proposal_status` — ``""`` / `pending` / `applied` / `discarded`.

Migrations: **`0002`** (`is_draft` + `ChatMessage`), **`0003`** (`phase` / `proposals`
/ `proposal_status`). Run `migrate` after pulling.

---

## 8. Notes & limits

- **History is local.** Transcripts live in the app's database. The Anthropic API is
  stateless and stores nothing — there's no "fetch my history" from Anthropic.
- **Cost.** Assistant turns send all document bodies as context and can return up to
  8000 tokens — heavier than intake turns.
- **Long requests.** A multi-document rewrite holds one HTTP request open for the full
  generation. Fine on the dev server; behind a short-timeout proxy you'd want
  streaming/SSE.
- **Testing.** Run with `.venv/bin/python manage.py test planner` (the `.venv` has the
  `anthropic` package; tests stub it, so no network/key needed).
