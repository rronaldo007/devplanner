# Architecture map

DevPlanner is a single-app Django project: users create software-project "folders"
and generate planning documents (Business Plan, Cahier des Charges, User Stories) +
three Mermaid diagrams (Use Case, ERD, Flow), either via a one-shot interview form
or an AI chat. An AI assistant can then edit the project and its documents.

## Layout
```
devplanner/            # Django project (settings, urls, wsgi)
planner/               # the single app
├── models.py          # UserProfile, Project, Document, ChatMessage
├── forms.py           # RegisterForm, UserProfileForm, InterviewForm, ...
├── views.py           # public, dashboard, document, chat, assistant, settings
├── urls.py
├── templatetags/planner_extras.py   # dict_get, getfield, active_projects
├── generators/
│   ├── __init__.py    # thin facade re-exporting engine.*
│   ├── engine.py      # engine selection + generate_all/custom/regenerate/sync
│   ├── templates.py   # pure-Python doc generation (always works)
│   ├── claude.py      # Anthropic-backed doc generation (optional)
│   ├── diagrams.py    # deterministic Mermaid diagrams from project fields
│   └── chat.py        # intake chat + project assistant (Claude) + web search
└── templates/planner/ # base, dashboard/, auth/, public/
```

## Data model
- **UserProfile** (1–1 user): `anthropic_api_key`, `default_language`. Auto-created
  via `post_save` signal.
- **Project** (owned by user): interview fields (problem, solution, features[],
  personas[], entities[], stack, …) + `is_draft` (true for unfinished chat drafts).
- **Document** (FK project): `kind` (3 default planning + 3 diagram kinds + custom),
  `title`, `body`, `is_generated`, `prompt`. Diagrams store raw Mermaid.
- **ChatMessage** (FK project): `phase` (intake|assistant), `role`, `content`,
  `proposals` (JSON), `proposal_status` (pending|applied|discarded).

## Document generation
`engine.generate_all(project)` picks an engine: **claude** if a key is available and
`anthropic` is importable, else **templates** (pure Python). Diagrams are always
deterministic (`diagrams.py`). `sync_default_documents` writes the 6 default docs.

## AI chat flows (see CHAT_AND_ASSISTANT.md in this folder for full detail)
- **Intake** (`chat.next_turn`): draft Project created at start; turns saved as
  `ChatMessage(phase=intake)`; emits `===PROJECT_READY===` JSON → finalise + generate.
- **Assistant** (`chat.assistant_turn`): full context = project fields + all document
  bodies; emits `===PROPOSAL===` JSON; propose-then-confirm via the apply endpoint;
  auto-continues truncated turns (prefill) for long multi-doc rewrites.

## Key request paths
- Intake: `project_new_chat` → `project_chat` → `project_chat_message` (+rename).
- Assistant: `project_assistant` → `project_assistant_message` → `project_assistant_apply`.
- All scoped to `request.user` via `_owned_project`.

## Migrations of note
`0002` (Project.is_draft + ChatMessage), `0003` (ChatMessage.phase/proposals/
proposal_status). Apply with `migrate` (user runs their refresh script).
```
