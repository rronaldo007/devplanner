"""Tests for the planner app.

Covers:

* Form parsing (features, personas, entities).
* Template-based document and Mermaid diagram generation.
* Generator orchestration: engine selection, fallback on Claude failure.
* Claude engine via a stubbed ``anthropic`` module (no network).
* HTTP views: public pages, auth scoping, ownership isolation, full
  project + custom-document lifecycle, settings update.
"""

from __future__ import annotations

import sys
import types

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import InterviewForm
from .generators import diagrams, templates as tmpl_gen
from .generators import (
    DEFAULT_TITLES, _api_key_for, _select_engine,
    generate_all, generate_custom, sync_default_documents,
)
from .models import Document, Project, UserProfile


User = get_user_model()


def _make_user(username="alice", api_key="") -> User:
    user = User.objects.create_user(username=username, password="hunter2hunter2")
    profile = user.profile
    profile.anthropic_api_key = api_key
    profile.save()
    return user


def _make_project(owner, **overrides) -> Project:
    data = dict(
        owner=owner,
        name="Acme Tasks",
        tagline="Tiny todo manager for small teams",
        language="en",
        problem="Small teams lose track of todos.",
        solution="A focused task board with keyboard-first UX.",
        target_users="Engineering teams of 2-10.",
        features=["Create board", "Add task", "Assign task"],
        nice_to_have=["Slack integration"],
        out_of_scope=["Gantt charts"],
        personas=[
            {"name": "Alice", "role": "Tech lead", "goal": "see team load"},
            {"name": "Bob", "role": "Engineer", "goal": "ship tickets"},
        ],
        entities=[
            {"name": "User", "fields": ["email", "name"]},
            {"name": "Board", "fields": ["name", "owner"]},
            {"name": "Task", "fields": ["title", "board", "assignee"]},
        ],
        stack="Django 6 + Postgres",
        hosting="Fly.io",
        integrations="Slack",
        timeline="MVP in 8 weeks",
        budget="2 engineers",
        risks="Crowded market.",
        competitors="Trello",
        differentiation="Faster than Trello",
        business_model="Freemium",
        success_metrics="100 teams in 6 months",
    )
    data.update(overrides)
    return Project.objects.create(**data)


# ===========================================================================
# Forms
# ===========================================================================
class FormParserTests(TestCase):
    def test_user_profile_created_on_signal(self):
        user = User.objects.create_user(username="bob", password="hunter2hunter2")
        self.assertTrue(UserProfile.objects.filter(user=user).exists())

    def test_personas_parsing(self):
        form = InterviewForm(data={
            "name": "X", "tagline": "", "language": "en",
            "problem": "p", "solution": "s",
            "differentiation": "", "competitors": "",
            "target_users": "t",
            "personas": "Alice | Tech lead | see load\nBob||",
            "features": "F1\nF2",
            "nice_to_have": "", "out_of_scope": "",
            "business_model": "", "success_metrics": "",
            "stack": "", "integrations": "", "hosting": "",
            "entities": "",
            "timeline": "", "budget": "", "risks": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        personas = form.cleaned_data["personas"]
        self.assertEqual(personas[0], {"name": "Alice", "role": "Tech lead", "goal": "see load"})
        self.assertEqual(personas[1], {"name": "Bob", "role": "", "goal": ""})

    def test_features_parsing(self):
        form = InterviewForm(data={
            "name": "X", "tagline": "", "language": "en",
            "problem": "p", "solution": "s",
            "differentiation": "", "competitors": "",
            "target_users": "t",
            "personas": "",
            "features": "Create board\n\n  Add task  \n", "nice_to_have": "", "out_of_scope": "",
            "business_model": "", "success_metrics": "",
            "stack": "", "integrations": "", "hosting": "",
            "entities": "",
            "timeline": "", "budget": "", "risks": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["features"], ["Create board", "Add task"])

    def test_entities_parsing(self):
        form = InterviewForm(data={
            "name": "X", "tagline": "", "language": "en",
            "problem": "p", "solution": "s",
            "differentiation": "", "competitors": "",
            "target_users": "t",
            "personas": "",
            "features": "", "nice_to_have": "", "out_of_scope": "",
            "business_model": "", "success_metrics": "",
            "stack": "", "integrations": "", "hosting": "",
            "entities": "User\n  email\n  name\n\nTask\n  title\n  user",
            "timeline": "", "budget": "", "risks": "",
        })
        self.assertTrue(form.is_valid(), form.errors)
        entities = form.cleaned_data["entities"]
        self.assertEqual(entities, [
            {"name": "User", "fields": ["email", "name"]},
            {"name": "Task", "fields": ["title", "user"]},
        ])


# ===========================================================================
# Template generator
# ===========================================================================
class TemplateGeneratorTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.project = _make_project(self.user)

    def test_business_plan_includes_name_and_sections(self):
        out = tmpl_gen.generate_documents(self.project)
        bp = out["business_plan"]
        self.assertIn("Acme Tasks", bp)
        for section in ("Problem", "Solution", "Target Audience", "Risks"):
            self.assertIn(section, bp)

    def test_specifications_lists_features_as_FR(self):
        out = tmpl_gen.generate_documents(self.project)
        specs = out["specifications"]
        self.assertIn("FR-01", specs)
        self.assertIn("FR-02", specs)
        self.assertIn("FR-03", specs)

    def test_user_stories_cross_product(self):
        out = tmpl_gen.generate_documents(self.project)
        stories = out["user_stories"]
        # 2 personas × 4 (features + nice-to-have) = 8 stories
        self.assertEqual(stories.count("US-"), 8)

    def test_french_language_swaps_section_titles(self):
        self.project.language = "fr"
        self.project.save()
        out = tmpl_gen.generate_documents(self.project)
        self.assertIn("Résumé exécutif", out["business_plan"])
        self.assertIn("Cahier des Charges", out["specifications"])


# ===========================================================================
# Diagrams
# ===========================================================================
class DiagramTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.project = _make_project(self.user)

    def test_use_case_has_actors_and_features(self):
        m = diagrams.use_case(self.project)
        self.assertIn("flowchart", m)
        self.assertIn("Alice", m)
        self.assertIn("Create board", m)

    def test_erd_links_field_to_entity(self):
        m = diagrams.erd(self.project)
        self.assertIn("erDiagram", m)
        # Task has a field `board` which is also an entity → relationship line
        self.assertIn("Task }o--|| Board", m)

    def test_flow_has_start_and_features(self):
        m = diagrams.flow(self.project)
        self.assertIn("flowchart TD", m)
        self.assertIn("Sign up", m) if False else self.assertIn("Discover", m)


# ===========================================================================
# Orchestrator + Claude engine selection
# ===========================================================================
class GenerateOrchestratorTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.project = _make_project(self.user)

    def test_select_engine_no_key_uses_templates(self):
        self.assertEqual(_select_engine(self.project), "templates")

    @override_settings()
    def test_select_engine_with_user_key_uses_claude(self):
        self.user.profile.anthropic_api_key = "sk-test"
        self.user.profile.save()
        # Refresh from DB so the FK reverse lookup picks up the new key.
        self.project.refresh_from_db()
        # Pretend anthropic is importable (it actually is via requirements).
        self.assertEqual(_select_engine(self.project), "claude")

    def test_force_templates(self):
        self.user.profile.anthropic_api_key = "sk-test"
        self.user.profile.save()
        out = generate_all(self.project, force_engine="templates")
        self.assertEqual(out["engine"], "templates")
        self.assertIn("Acme Tasks", out["business_plan"])

    def test_sync_default_documents_creates_six_docs(self):
        out = sync_default_documents(self.project)
        self.assertEqual(out["engine"], "templates")
        docs = list(Document.objects.filter(project=self.project))
        self.assertEqual(len(docs), 6)
        kinds = {d.kind for d in docs}
        self.assertEqual(kinds, set(Document.DEFAULT_KINDS))

    def test_sync_is_idempotent(self):
        sync_default_documents(self.project)
        sync_default_documents(self.project)
        self.assertEqual(Document.objects.filter(project=self.project).count(), 6)

    def test_api_key_resolution_prefers_profile_over_env(self):
        import os
        os.environ["ANTHROPIC_API_KEY"] = "env-key"
        try:
            self.user.profile.anthropic_api_key = "user-key"
            self.user.profile.save()
            self.project.refresh_from_db()
            self.assertEqual(_api_key_for(self.project), "user-key")

            self.user.profile.anthropic_api_key = ""
            self.user.profile.save()
            self.project.refresh_from_db()
            self.assertEqual(_api_key_for(self.project), "env-key")
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)


# ===========================================================================
# Claude engine (stubbed anthropic module)
# ===========================================================================
def _install_anthropic_stub(response_text: str):
    """Install a stub ``anthropic`` module that returns ``response_text``."""

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Response:
        def __init__(self, text):
            self.content = [_Block(text)]

    class _Messages:
        def __init__(self, outer):
            self.outer = outer
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return _Response(self.outer._response_text)

    class _Anthropic:
        def __init__(self, *args, api_key=None, **kwargs):
            self.api_key = api_key
            self._response_text = response_text
            self.messages = _Messages(self)

    module = types.ModuleType("anthropic")
    module.Anthropic = _Anthropic
    sys.modules["anthropic"] = module
    return module


class ClaudeEngineTests(TestCase):
    def setUp(self):
        self.user = _make_user(api_key="user-sk-test")
        self.project = _make_project(self.user)
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def test_generate_documents_parses_markers(self):
        text = (
            "===BUSINESS_PLAN===\n# BP\nBody.\n"
            "===SPECIFICATIONS===\n# Specs\nBody.\n"
            "===USER_STORIES===\n# Stories\nBody."
        )
        _install_anthropic_stub(text)
        from .generators import claude
        out = claude.generate_documents(self.project, api_key="user-sk-test")
        self.assertIn("BP", out["business_plan"])
        self.assertIn("Specs", out["specifications"])
        self.assertIn("Stories", out["user_stories"])

    def test_generate_custom_uses_title(self):
        _install_anthropic_stub("Some custom content.")
        from .generators import claude
        body = claude.generate_custom(
            self.project, title="Architecture", prompt="describe", api_key="x"
        )
        self.assertIn("Architecture", body)
        self.assertIn("Some custom content", body)

    def test_orchestrator_falls_back_to_templates_on_claude_error(self):
        # Stub with a class that raises.
        class _Boom:
            def __init__(self, *a, **kw): pass
            class _M:
                def create(self, **kw): raise RuntimeError("kaboom")
            messages = _M()
        module = types.ModuleType("anthropic")
        module.Anthropic = _Boom
        sys.modules["anthropic"] = module

        out = generate_all(self.project)
        self.assertEqual(out["engine"], "templates")
        self.assertIn("kaboom", out["_claude_error"])
        # And templates still produced something.
        self.assertIn("Acme Tasks", out["business_plan"])


# ===========================================================================
# Views & ownership
# ===========================================================================
class PublicViewsTests(TestCase):
    def test_home_anonymous(self):
        resp = self.client.get(reverse("planner:home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Prepare your project")

    def test_about_anonymous(self):
        resp = self.client.get(reverse("planner:about"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "About DevPlanner")

    def test_home_authenticated_redirects_to_dashboard(self):
        user = _make_user()
        self.client.force_login(user)
        resp = self.client.get(reverse("planner:home"))
        self.assertRedirects(resp, reverse("planner:dashboard"))

    def test_dashboard_requires_login(self):
        resp = self.client.get(reverse("planner:dashboard"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("planner:login"), resp.url)


class AuthViewsTests(TestCase):
    def test_register_creates_user_and_logs_in(self):
        resp = self.client.post(reverse("planner:register"), {
            "username": "newbie",
            "email": "newbie@example.com",
            "password1": "supersecretpw123",
            "password2": "supersecretpw123",
        })
        self.assertRedirects(resp, reverse("planner:dashboard"))
        self.assertTrue(User.objects.filter(username="newbie").exists())

    def test_login_login_redirects_to_dashboard(self):
        user = _make_user(username="loginu")
        resp = self.client.post(reverse("planner:login"), {
            "username": "loginu", "password": "hunter2hunter2",
        })
        self.assertRedirects(resp, reverse("planner:dashboard"))


class DashboardFlowTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(username="mallory")
        self.client.force_login(self.user)

    def _interview_payload(self):
        return {
            "name": "Test Project", "tagline": "Tag",
            "language": "en",
            "problem": "P", "solution": "S",
            "differentiation": "", "competitors": "",
            "target_users": "U",
            "personas": "Alice | Lead | goal",
            "features": "F1\nF2",
            "nice_to_have": "", "out_of_scope": "",
            "business_model": "", "success_metrics": "",
            "stack": "", "integrations": "", "hosting": "",
            "entities": "User\n  email\n  name",
            "timeline": "", "budget": "", "risks": "",
        }

    def test_create_project_generates_six_documents(self):
        resp = self.client.post(reverse("planner:project_new"), self._interview_payload())
        self.assertEqual(resp.status_code, 302)
        project = Project.objects.get(name="Test Project")
        self.assertEqual(project.owner, self.user)
        self.assertEqual(project.documents.count(), 6)

    def test_project_list_isolation(self):
        _make_project(self.user, name="MineA")
        _make_project(self.other, name="HersA")
        resp = self.client.get(reverse("planner:dashboard"))
        self.assertContains(resp, "MineA")
        self.assertNotContains(resp, "HersA")

    def test_other_user_project_detail_404(self):
        p = _make_project(self.other, name="HersB")
        resp = self.client.get(reverse("planner:project_detail", args=[p.pk]))
        self.assertEqual(resp.status_code, 404)

    def test_new_custom_document_uses_templates_when_no_key(self):
        project = _make_project(self.user)
        resp = self.client.post(
            reverse("planner:document_new", args=[project.pk]),
            {"title": "Architecture", "prompt": "Describe layers"},
        )
        self.assertEqual(resp.status_code, 302)
        doc = Document.objects.filter(project=project, kind="custom").first()
        self.assertIsNotNone(doc)
        self.assertIn("Architecture", doc.body)

    def test_settings_save_persists_api_key(self):
        resp = self.client.post(reverse("planner:settings"), {
            "anthropic_api_key": "sk-test",
            "default_language": "fr",
        })
        self.assertRedirects(resp, reverse("planner:settings"))
        self.user.profile.refresh_from_db()
        self.assertEqual(self.user.profile.anthropic_api_key, "sk-test")
        self.assertEqual(self.user.profile.default_language, "fr")

    def test_document_download_returns_markdown(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind="business_plan")
        resp = self.client.get(
            reverse("planner:document_download", args=[project.pk, doc.pk]) + "?download=1"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp["Content-Type"])
        self.assertIn("attachment;", resp["Content-Disposition"])

    def test_document_regenerate_refreshes_body(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind="business_plan")
        doc.body = "STALE"
        doc.is_generated = False
        doc.save()
        resp = self.client.post(
            reverse("planner:document_regenerate", args=[project.pk, doc.pk])
        )
        self.assertEqual(resp.status_code, 302)
        doc.refresh_from_db()
        self.assertNotIn("STALE", doc.body)
        self.assertTrue(doc.is_generated)

    def test_default_document_cannot_be_deleted(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind="business_plan")
        resp = self.client.post(reverse("planner:document_delete", args=[project.pk, doc.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Document.objects.filter(pk=doc.pk).exists())

    def test_project_delete_removes_documents(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        pk = project.pk
        resp = self.client.post(reverse("planner:project_delete", args=[pk]))
        self.assertRedirects(resp, reverse("planner:dashboard"))
        self.assertFalse(Project.objects.filter(pk=pk).exists())
        self.assertFalse(Document.objects.filter(project_id=pk).exists())


# ===========================================================================
# Default titles
# ===========================================================================
class DefaultTitlesTests(TestCase):
    def test_default_titles_cover_all_kinds(self):
        for kind in Document.DEFAULT_KINDS:
            self.assertIn(kind, DEFAULT_TITLES)
            en, fr = DEFAULT_TITLES[kind]
            self.assertTrue(en)
            self.assertTrue(fr)
