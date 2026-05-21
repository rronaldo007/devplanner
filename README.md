# DevPlanner

A multi-user Django dashboard that helps developers prepare a project before
writing a single line of code. Each user gets project **folders** that contain
generated documents:

- a **Business Plan**
- a **Cahier des Charges** (specifications)
- **User Stories**
- three **Mermaid diagrams**: use case, ERD, user flow
- any number of **custom documents** (architecture, README, deployment plan…)

Generation runs through one of two engines:

1. **Built-in templates** (no API key needed) — always available, deterministic.
2. **Claude (Anthropic)** — used automatically when a user has stored their
   `ANTHROPIC_API_KEY` in **Settings** (or the env var is set). Falls back to
   templates on any error.

The UI is rendered with Tailwind via the Play CDN — no build step.

## Features

- Multi-user authentication (register, login, logout).
- Per-user project folders, isolated by ownership.
- Six default documents auto-generated when a project is created.
- Add unlimited custom documents (with optional Claude prompt).
- Edit, regenerate, and download any document as Markdown.
- Per-user settings page for Claude API key and default language (EN/FR).

## Quick start

### With Docker (recommended)

```bash
cp .env.example .env          # then edit .env (at minimum set DJANGO_SECRET_KEY)
docker compose up --build
```

The web service runs on <http://127.0.0.1:8000/>. SQLite is persisted in
the `devplanner-data` named volume so signups and projects survive container
restarts.

To swap SQLite for Postgres, uncomment `DATABASE_URL` in your `.env` and run:

```bash
docker compose --profile postgres up --build
```

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000/>:

1. **Sign up** for an account (auto-login on success).
2. Click **+ New project** and answer the interview.
3. You land in the project folder with six documents generated.
4. Open any document to view, edit, regenerate, or download it.
5. Visit **Settings** to add your Claude API key for richer generation.

### Using Claude

You can provide an API key in one of two ways:

- Per-user, via the **Settings** page (preferred; stored on the user profile).
- Globally, via the `ANTHROPIC_API_KEY` environment variable.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
# optional: override the model (defaults to claude-opus-4-5)
export ANTHROPIC_MODEL=claude-opus-4-5
python manage.py runserver
```

## Interview structure

One page, seven sections:

1. **Identity** — name, tagline, output language (FR/EN)
2. **Problem & Solution** — problem, solution, differentiation, competitors
3. **Audience** — target users, personas (`Name | Role | Goal`, one per line)
4. **Scope** — features, nice-to-have, out-of-scope (one item per line)
5. **Business** — business model, success metrics
6. **Technical** — stack, integrations, hosting, entities (indented DSL)
7. **Constraints & Risks** — timeline, budget, risks

The entities textarea uses a simple indented DSL:

```
User
  email
  name

Task
  title
  user
```

Fields whose name matches another entity are inferred as relationships in
the ERD diagram.

## Project structure

```
devplanner/
├── devplanner/          # Django project (settings, urls)
└── planner/             # The single app
    ├── generators/      # templates.py, claude.py, diagrams.py, __init__.py
    ├── templates/planner/
    │   ├── public/      # home, about
    │   ├── auth/        # login, register
    │   └── dashboard/   # index, interview, project_detail, document_*, settings
    ├── templatetags/
    ├── models.py        # UserProfile, Project, Document
    ├── forms.py         # Register, UserProfile, Interview, CustomDocument, DocumentEdit
    ├── views.py         # 18 views (public, auth, dashboard, documents, settings)
    └── urls.py
```

## Tests

```bash
python manage.py test planner
```

36 tests cover form parsing, template generation, Mermaid diagrams,
orchestrator engine selection, Claude (with a stubbed `anthropic` module so
no network is needed), and the full HTTP flow including ownership isolation.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | dev-only insecure key | **Set in production.** Used for sessions, CSRF, password reset tokens. |
| `DJANGO_DEBUG` | `true` | Set to `false` in production. |
| `DJANGO_ALLOWED_HOSTS` | `*` when DEBUG, empty otherwise | Comma-separated list of allowed hostnames. |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | empty | Comma-separated origins (`https://devplanner.example.com`). |
| `DJANGO_SQLITE_PATH` | `db.sqlite3` | Where to store SQLite when no `DATABASE_URL` is set. |
| `DATABASE_URL` | empty | If set, used instead of SQLite (e.g. `postgres://user:pass@host:5432/db`). |
| `DJANGO_HSTS_SECONDS` | `0` | Enable HSTS in production by setting this to e.g. `31536000`. |
| `DJANGO_SECURE_COOKIES` | `true` when DEBUG=false | Set to `false` if you are not yet on HTTPS. |
| `ANTHROPIC_API_KEY` | empty | Global Claude key (per-user keys configured in Settings always win). |
| `ANTHROPIC_MODEL` | `claude-opus-4-5` | Override Claude model. |
| `ANTHROPIC_MAX_TOKENS` | `4000` | Max tokens per Claude response. |

## License

MIT.
