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

import json
import os
import sys
import types
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import InterviewForm
from .generators import diagrams, drawio, templates as tmpl_gen
from .generators import (
    DEFAULT_TITLES,
    generate_all, generate_custom, sync_default_documents,
)
from .generators.engine import _api_key_for, _select_engine
from .models import ChatMessage, Document, Note, Project, UserProfile


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
        self.assertIn("Discover", m)


class DrawioTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.project = _make_project(self.user)

    def _parse(self, xml):
        """Assert the output is well-formed XML draw.io can open."""

        from xml.etree import ElementTree as ET

        root = ET.fromstring(xml)
        self.assertEqual(root.tag, "mxfile")
        return root

    def test_use_case_is_valid_xml_with_actors_and_features(self):
        xml = drawio.use_case(self.project)
        self._parse(xml)
        self.assertIn("Alice", xml)
        self.assertIn("Create board", xml)
        self.assertIn("umlActor", xml)

    def test_erd_is_valid_xml_with_entities_and_relationship(self):
        xml = drawio.erd(self.project)
        self._parse(xml)
        self.assertIn("Task", xml)
        self.assertIn("Board", xml)
        # Task.board references the Board entity -> a labeled relationship edge.
        self.assertIn('value="board"', xml)
        self.assertIn('edge="1"', xml)

    def test_flow_is_valid_xml_with_journey(self):
        xml = drawio.flow(self.project)
        self._parse(xml)
        self.assertIn("Discover", xml)
        self.assertIn("Sign up", xml)

    def test_for_kind_returns_none_for_non_diagram(self):
        self.assertIsNone(drawio.for_kind(Document.KIND_BUSINESS_PLAN, self.project))

    def test_labels_are_xml_escaped(self):
        project = _make_project(self.user, name='A & B "x" <y>', features=["F"])
        xml = drawio.use_case(project)
        self._parse(xml)  # raises if &, <, > or " are not escaped
        self.assertNotIn("A & B", xml)


class DrawioDownloadTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(username="mallory")
        self.client.force_login(self.user)

    def test_diagram_download_returns_drawio(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind=Document.KIND_ERD_DIAGRAM)
        resp = self.client.get(
            reverse("planner:document_drawio", args=[project.pk, doc.pk])
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/xml", resp["Content-Type"])
        self.assertIn(".drawio", resp["Content-Disposition"])
        self.assertIn(b"mxGraphModel", resp.content)

    def test_non_diagram_drawio_is_404(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind="business_plan")
        resp = self.client.get(
            reverse("planner:document_drawio", args=[project.pk, doc.pk])
        )
        self.assertEqual(resp.status_code, 404)

    def test_drawio_scoped_to_owner(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        doc = project.documents.get(kind=Document.KIND_ERD_DIAGRAM)
        self.client.force_login(self.other)
        resp = self.client.get(
            reverse("planner:document_drawio", args=[project.pk, doc.pk])
        )
        self.assertEqual(resp.status_code, 404)


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
            self.stop_reason = "end_turn"

    class _Stream:
        """Context manager mimicking client.messages.stream()."""

        def __init__(self, response):
            self._response = response

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return self._response

    class _Messages:
        def __init__(self, outer):
            self.outer = outer
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return _Response(self.outer._response_text)

        def stream(self, **kwargs):
            self.calls.append(kwargs)
            return _Stream(_Response(self.outer._response_text))

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
class ProjectAssistantTests(TestCase):
    def setUp(self):
        self.user = _make_user(api_key="user-sk-test")
        self.project = _make_project(self.user)  # not a draft
        self.client.force_login(self.user)
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def _proposal_text(self, reply, changes, summary="ok"):
        return (
            reply + "\n" + chat_mod.PROPOSAL_MARKER + "\n"
            + json.dumps({"summary": summary, "changes": changes})
        )

    def _send(self, message):
        return self.client.post(
            reverse("planner:project_assistant_message", args=[self.project.pk]),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def _apply(self, message_id, action):
        return self.client.post(
            reverse("planner:project_assistant_apply", args=[self.project.pk]),
            data=json.dumps({"message_id": message_id, "action": action}),
            content_type="application/json",
        )

    def test_page_seeds_opening_message(self):
        _install_anthropic_stub("x")
        resp = self.client.get(reverse("planner:project_assistant", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.project.chat_messages.filter(phase=ChatMessage.PHASE_ASSISTANT).count(), 1
        )

    def test_draft_redirects_to_intake_chat(self):
        _install_anthropic_stub("x")
        draft = _make_project(self.user, name="Draft", is_draft=True)
        resp = self.client.get(reverse("planner:project_assistant", args=[draft.pk]))
        self.assertRedirects(resp, reverse("planner:project_chat", args=[draft.pk]))

    def test_without_key_redirects_to_detail(self):
        nokey = _make_user(username="nokey", api_key="")
        project = _make_project(nokey)
        self.client.force_login(nokey)
        _install_anthropic_stub("x")  # installed, but user has no key
        resp = self.client.get(reverse("planner:project_assistant", args=[project.pk]))
        self.assertRedirects(resp, reverse("planner:project_detail", args=[project.pk]))

    def test_plain_reply_has_no_proposal(self):
        _install_anthropic_stub("Your stack looks solid.")
        resp = self._send("is my stack ok?")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["has_proposal"])

    def test_field_proposal_apply_updates_project(self):
        text = self._proposal_text(
            "I'll update the stack.",
            [{"type": "field", "field": "stack", "value": "Django 6 + HTMX", "note": "modernised"}],
        )
        _install_anthropic_stub(text)
        resp = self._send("use htmx")
        body = resp.json()
        self.assertTrue(body["has_proposal"])
        self.assertEqual(self._apply(body["message_id"], "apply").json()["status"], "applied")
        self.project.refresh_from_db()
        self.assertEqual(self.project.stack, "Django 6 + HTMX")

    def test_document_proposal_updates_existing_document(self):
        doc = Document.objects.create(
            project=self.project, kind=Document.KIND_USER_STORIES,
            title="User Stories", body="old", is_generated=True,
        )
        text = self._proposal_text(
            "Finishing the user stories.",
            [{"type": "document", "document_id": doc.pk, "title": "User Stories",
              "body": "# User Stories\n\nUS-1 ...", "note": "completed"}],
        )
        _install_anthropic_stub(text)
        body = self._send("finish the user stories").json()
        self._apply(body["message_id"], "apply")
        doc.refresh_from_db()
        self.assertIn("US-1", doc.body)
        self.assertFalse(doc.is_generated)

    def test_document_proposal_creates_new_custom_doc(self):
        text = self._proposal_text(
            "Adding an architecture doc.",
            [{"type": "document", "kind": "custom", "title": "Architecture",
              "body": "# Architecture\n\n...", "note": "new"}],
        )
        _install_anthropic_stub(text)
        body = self._send("add an architecture doc").json()
        self._apply(body["message_id"], "apply")
        self.assertTrue(
            self.project.documents.filter(kind=Document.KIND_CUSTOM, title="Architecture").exists()
        )

    def test_discard_makes_no_changes(self):
        text = self._proposal_text(
            "I'll change the stack.",
            [{"type": "field", "field": "stack", "value": "SHOULD NOT APPLY"}],
        )
        _install_anthropic_stub(text)
        body = self._send("change stack").json()
        self.assertEqual(self._apply(body["message_id"], "discard").json()["status"], "discarded")
        self.project.refresh_from_db()
        self.assertNotEqual(self.project.stack, "SHOULD NOT APPLY")

    def test_cannot_apply_twice(self):
        text = self._proposal_text(
            "ok", [{"type": "field", "field": "budget", "value": "10k"}]
        )
        _install_anthropic_stub(text)
        body = self._send("set budget").json()
        self._apply(body["message_id"], "apply")
        self.assertEqual(self._apply(body["message_id"], "apply").status_code, 409)

    # --- Diagrams are a deterministic projection of fields ------------------
    def test_field_change_regenerates_affected_diagrams(self):
        sync_default_documents(self.project)
        text = self._proposal_text(
            "Adding a feature.",
            [{"type": "field", "field": "features",
              "value": ["Create board", "Burndown chart"], "note": "added chart"}],
        )
        _install_anthropic_stub(text)
        body = self._send("add burndown chart").json()
        applied = self._apply(body["message_id"], "apply").json()
        self.assertEqual(applied["status"], "applied")

        self.project.refresh_from_db()
        uc = self.project.documents.get(kind=Document.KIND_USE_CASE_DIAGRAM)
        fl = self.project.documents.get(kind=Document.KIND_FLOW_DIAGRAM)
        # features feeds both use case and flow — both rebuilt deterministically.
        self.assertEqual(uc.body, diagrams.use_case(self.project))
        self.assertEqual(fl.body, diagrams.flow(self.project))
        self.assertIn("Burndown chart", uc.body)
        self.assertTrue(uc.is_generated)
        self.assertTrue(any("Regenerated diagram" in line for line in applied["applied"]))

    def test_entities_change_regenerates_only_erd(self):
        sync_default_documents(self.project)
        uc_before = self.project.documents.get(kind=Document.KIND_USE_CASE_DIAGRAM).body
        fl_before = self.project.documents.get(kind=Document.KIND_FLOW_DIAGRAM).body
        text = self._proposal_text(
            "Adding an entity.",
            [{"type": "field", "field": "entities",
              "value": [{"name": "User", "fields": ["email"]},
                        {"name": "Invoice", "fields": ["amount", "user"]}],
              "note": "added invoice"}],
        )
        _install_anthropic_stub(text)
        body = self._send("add invoice entity").json()
        self._apply(body["message_id"], "apply")

        self.project.refresh_from_db()
        erd = self.project.documents.get(kind=Document.KIND_ERD_DIAGRAM)
        self.assertEqual(erd.body, diagrams.erd(self.project))
        self.assertIn("Invoice", erd.body)
        # use case / flow do not depend on entities — left untouched.
        self.assertEqual(
            self.project.documents.get(kind=Document.KIND_USE_CASE_DIAGRAM).body, uc_before
        )
        self.assertEqual(
            self.project.documents.get(kind=Document.KIND_FLOW_DIAGRAM).body, fl_before
        )

    def test_handwritten_diagram_body_is_rejected(self):
        sync_default_documents(self.project)
        erd = self.project.documents.get(kind=Document.KIND_ERD_DIAGRAM)
        text = self._proposal_text(
            "Rewriting the ERD.",
            [{"type": "document", "document_id": erd.pk, "kind": "erd_diagram",
              "body": "erDiagram\n  GARBAGE", "note": "hack"}],
        )
        _install_anthropic_stub(text)
        body = self._send("rewrite erd").json()
        applied = self._apply(body["message_id"], "apply").json()

        erd.refresh_from_db()
        self.project.refresh_from_db()
        self.assertNotIn("GARBAGE", erd.body)
        self.assertEqual(erd.body, diagrams.erd(self.project))
        self.assertTrue(erd.is_generated)
        self.assertTrue(
            any("Regenerated diagram" in line for line in applied["applied"])
        )

    def test_non_diagram_field_change_leaves_diagrams_untouched(self):
        sync_default_documents(self.project)
        erd_before = self.project.documents.get(kind=Document.KIND_ERD_DIAGRAM).body
        text = self._proposal_text(
            "Updating stack.",
            [{"type": "field", "field": "stack", "value": "Go + Postgres"}],
        )
        _install_anthropic_stub(text)
        body = self._send("use go").json()
        applied = self._apply(body["message_id"], "apply").json()

        self.project.refresh_from_db()
        self.assertEqual(
            self.project.documents.get(kind=Document.KIND_ERD_DIAGRAM).body, erd_before
        )
        self.assertFalse(
            any("Regenerated diagram" in line for line in applied["applied"])
        )


class ChatAssistantStreamingTests(TestCase):
    """assistant_turn streams a single response (no assistant-message prefill).

    opus-4-7 rejects assistant-message prefill, so the assistant must produce
    the whole proposal in one streamed response and never end the conversation
    on an assistant turn.
    """

    def setUp(self):
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def _install(self, text, stop_reason="end_turn"):
        calls = []

        class _Block:
            def __init__(self, t):
                self.text = t

        class _Resp:
            def __init__(self, t, sr):
                self.content = [_Block(t)]
                self.stop_reason = sr

        class _Stream:
            def __init__(self, resp):
                self._resp = resp

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_final_message(self):
                return self._resp

        class _Messages:
            def create(self, **kwargs):
                calls.append(kwargs)
                return _Resp(text, stop_reason)

            def stream(self, **kwargs):
                calls.append(kwargs)
                return _Stream(_Resp(text, stop_reason))

        class _Anthropic:
            def __init__(self, *a, **k):
                self.messages = _Messages()

        module = types.ModuleType("anthropic")
        module.Anthropic = _Anthropic
        sys.modules["anthropic"] = module
        self.calls = calls

    def test_single_streamed_response_parses_proposal(self):
        text = (
            "Working on it.\n" + chat_mod.PROPOSAL_MARKER
            + '\n{"summary":"s","changes":[{"type":"field","field":"stack",'
            '"value":"Django 6"}]}'
        )
        self._install(text)
        res = chat_mod.assistant_turn(
            [{"role": "user", "content": "go"}], "ctx", api_key="x"
        )
        self.assertEqual(res["proposals"][0]["value"], "Django 6")
        self.assertEqual(res["reply"], "Working on it.")

    def test_truncation_note_when_max_tokens(self):
        self._install("partial, no marker", "max_tokens")
        res = chat_mod.assistant_turn(
            [{"role": "user", "content": "go"}], "ctx", api_key="x", language="en"
        )
        self.assertEqual(res["proposals"], [])
        self.assertIn("too long", res["reply"])

    def test_conversation_never_ends_on_assistant_message(self):
        # The regression guard: opus-4-7 400s if the messages end with an
        # assistant turn (prefill). Even with prior assistant turns in history,
        # the request must end on the user's message.
        self._install("ok")
        chat_mod.assistant_turn(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "earlier reply"},
                {"role": "user", "content": "go"},
            ],
            "ctx",
            api_key="x",
        )
        sent = self.calls[-1]["messages"]
        self.assertEqual(sent[-1]["role"], "user")

    def test_system_context_is_cached(self):
        # The large system+context block carries a cache_control breakpoint.
        self._install("ok")
        chat_mod.assistant_turn(
            [{"role": "user", "content": "go"}], "project context", api_key="x"
        )
        system = self.calls[-1]["system"]
        self.assertEqual(system[0]["cache_control"], {"type": "ephemeral"})
        self.assertIn("project context", system[0]["text"])


class DefaultTitlesTests(TestCase):
    def test_default_titles_cover_all_kinds(self):
        for kind in Document.DEFAULT_KINDS:
            self.assertIn(kind, DEFAULT_TITLES)
            en, fr = DEFAULT_TITLES[kind]
            self.assertTrue(en)
            self.assertTrue(fr)


# ===========================================================================
# Chat intake
# ===========================================================================
from .generators import chat as chat_mod  # noqa: E402


_READY_BRIEF = {
    "name": "Acme Tasks",
    "problem": "Teams lose track of todos.",
    "solution": "A focused board.",
    "target_users": "Small eng teams.",
    "features": ["Create board", "Add task"],
    "personas": [{"name": "Alice", "role": "Lead", "goal": "see load"}],
    "entities": [{"name": "Task", "fields": ["title", "done"]}],
}


class ChatBriefParsingTests(TestCase):
    def test_parse_ready_extracts_json_after_marker(self):
        text = (
            "Great, I have what I need.\n"
            f"{chat_mod.READY_MARKER}\n"
            + json.dumps(_READY_BRIEF)
        )
        fields = chat_mod._parse_ready(text)
        self.assertEqual(fields["name"], "Acme Tasks")
        self.assertEqual(fields["features"], ["Create board", "Add task"])

    def test_parse_ready_handles_code_fence(self):
        text = (
            f"Done!\n{chat_mod.READY_MARKER}\n```json\n"
            + json.dumps(_READY_BRIEF)
            + "\n```"
        )
        self.assertIsNotNone(chat_mod._parse_ready(text))

    def test_parse_ready_none_without_marker(self):
        self.assertIsNone(chat_mod._parse_ready("Just a normal question?"))

    def test_build_project_kwargs_coerces_types(self):
        kwargs = chat_mod.build_project_kwargs({
            "name": "  Trimmed  ",
            "features": "one\ntwo\n\n",          # string -> list
            "nice_to_have": ["a", "", "b"],        # filters blanks
            "personas": [{"name": "A", "role": "R", "goal": "G"}, {}],
            "entities": [{"name": "E", "fields": ["f1", "f2"]}, {"fields": []}],
            "unknown_key": "ignored",
        })
        self.assertEqual(kwargs["name"], "Trimmed")
        self.assertEqual(kwargs["features"], ["one", "two"])
        self.assertEqual(kwargs["nice_to_have"], ["a", "b"])
        self.assertEqual(len(kwargs["personas"]), 1)
        self.assertEqual(len(kwargs["entities"]), 1)
        self.assertNotIn("unknown_key", kwargs)

    def test_build_project_kwargs_defaults_name(self):
        self.assertEqual(chat_mod.build_project_kwargs({})["name"], "Untitled project")

    def test_derive_title(self):
        self.assertEqual(chat_mod.derive_title("  a   task  app "), "a task app")
        self.assertEqual(chat_mod.derive_title(""), "Untitled project")
        long = chat_mod.derive_title("x" * 90)
        self.assertTrue(long.endswith("…"))
        self.assertLessEqual(len(long), 61)

    def test_parse_proposal(self):
        changes = [{"type": "field", "field": "stack", "value": "Django"}]
        text = "Sure.\n" + chat_mod.PROPOSAL_MARKER + "\n" + json.dumps(
            {"summary": "s", "changes": changes}
        )
        parsed, summary = chat_mod._parse_proposal(text)
        self.assertEqual(summary, "s")
        self.assertEqual(parsed[0]["field"], "stack")

    def test_parse_proposal_none_without_marker(self):
        parsed, summary = chat_mod._parse_proposal("just a reply")
        self.assertIsNone(parsed)

    def test_coerce_field(self):
        self.assertEqual(chat_mod.coerce_field("stack", "  Django  "), (True, "Django"))
        self.assertEqual(chat_mod.coerce_field("features", "a\nb"), (True, ["a", "b"]))
        ok, _ = chat_mod.coerce_field("not_a_field", "x")
        self.assertFalse(ok)


class ChatWebSearchTests(TestCase):
    def setUp(self):
        self._orig_flag = chat_mod.WEB_SEARCH_ENABLED
        self._orig_mod = sys.modules.get("anthropic")

    def tearDown(self):
        chat_mod.WEB_SEARCH_ENABLED = self._orig_flag
        if self._orig_mod is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig_mod

    def test_tools_built_when_enabled(self):
        chat_mod.WEB_SEARCH_ENABLED = True
        tools = chat_mod._build_tools()
        self.assertEqual(tools[0]["type"], "web_search_20250305")

    def test_no_tools_when_disabled(self):
        chat_mod.WEB_SEARCH_ENABLED = False
        self.assertEqual(chat_mod._build_tools(), [])

    def _capturing_anthropic(self, captured):
        """Install a stub that records the create() kwargs."""

        class _Block:
            text = "What's the idea?"

        class _Resp:
            content = [_Block()]

        class _Messages:
            def create(self, **kwargs):
                captured.update(kwargs)
                return _Resp()

        class _Anthropic:
            def __init__(self, *a, **k):
                self.messages = _Messages()

        module = types.ModuleType("anthropic")
        module.Anthropic = _Anthropic
        sys.modules["anthropic"] = module

    def test_next_turn_forwards_web_search_tool(self):
        chat_mod.WEB_SEARCH_ENABLED = True
        captured = {}
        self._capturing_anthropic(captured)
        chat_mod.next_turn([{"role": "user", "content": "a task app"}], api_key="x")
        self.assertIn("tools", captured)
        self.assertEqual(captured["tools"][0]["type"], "web_search_20250305")

    def test_next_turn_omits_tools_when_disabled(self):
        chat_mod.WEB_SEARCH_ENABLED = False
        captured = {}
        self._capturing_anthropic(captured)
        chat_mod.next_turn([{"role": "user", "content": "a task app"}], api_key="x")
        self.assertNotIn("tools", captured)


class ChatAvailabilityTests(TestCase):
    def setUp(self):
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def test_unavailable_without_key(self):
        user = _make_user(api_key="")
        _install_anthropic_stub("x")
        self.assertFalse(chat_mod.is_available(user))

    def test_available_with_key_and_package(self):
        user = _make_user(api_key="user-sk-test")
        _install_anthropic_stub("x")
        self.assertTrue(chat_mod.is_available(user))


class ChatViewTests(TestCase):
    def setUp(self):
        self.user = _make_user(api_key="user-sk-test")
        self.client.force_login(self.user)
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def _start_chat(self):
        """GET the entry point (creates a draft) and return that draft."""

        resp = self.client.get(reverse("planner:project_new_chat"))
        project = Project.objects.filter(owner=self.user, is_draft=True).latest("id")
        self.assertRedirects(resp, reverse("planner:project_chat", args=[project.pk]))
        return project

    def _post(self, pk, message):
        return self.client.post(
            reverse("planner:project_chat_message", args=[pk]),
            data=json.dumps({"message": message}),
            content_type="application/json",
        )

    def test_chat_page_without_key_redirects_to_form(self):
        nokey = _make_user(username="nokey", api_key="")
        self.client.force_login(nokey)
        resp = self.client.get(reverse("planner:project_new_chat"))
        self.assertRedirects(resp, reverse("planner:project_new"))
        self.assertFalse(Project.objects.filter(owner=nokey).exists())

    def test_starting_chat_creates_draft_with_opening(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        self.assertTrue(project.is_draft)
        opening = project.chat_messages.get()
        self.assertEqual(opening.role, "assistant")

    def test_chat_page_renders_saved_history(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        ChatMessage.objects.create(project=project, role="user", content="hello there")
        resp = self.client.get(reverse("planner:project_chat", args=[project.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hello there")

    def test_message_in_progress_persists_turns(self):
        _install_anthropic_stub("What problem does it solve?")
        project = self._start_chat()
        resp = self._post(project.pk, "A task app")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertFalse(body["done"])
        self.assertIn("problem", body["reply"])
        # opening + user turn + assistant reply
        self.assertEqual(project.chat_messages.count(), 3)

    def test_message_ready_finalises_draft(self):
        ready = f"All set!\n{chat_mod.READY_MARKER}\n" + json.dumps(_READY_BRIEF)
        _install_anthropic_stub(ready)
        project = self._start_chat()
        resp = self._post(project.pk, "that's enough")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["done"])
        project.refresh_from_db()
        self.assertFalse(project.is_draft)
        self.assertEqual(project.name, "Acme Tasks")
        self.assertEqual(project.documents.count(), 6)
        self.assertEqual(body["redirect_url"], reverse("planner:project_detail", args=[project.pk]))

    def test_message_to_finalised_project_rejected(self):
        ready = f"done\n{chat_mod.READY_MARKER}\n" + json.dumps(_READY_BRIEF)
        _install_anthropic_stub(ready)
        project = self._start_chat()
        self._post(project.pk, "that's enough")  # finalises it
        resp = self._post(project.pk, "another message")
        self.assertEqual(resp.status_code, 409)

    def test_empty_message_rejected(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        resp = self._post(project.pk, "   ")
        self.assertEqual(resp.status_code, 400)

    def test_first_message_sets_draft_title(self):
        _install_anthropic_stub("And what problem does it solve?")
        project = self._start_chat()
        self.assertEqual(project.name, "Untitled project")
        self._post(project.pk, "A budgeting app for couples")
        project.refresh_from_db()
        self.assertEqual(project.name, "A budgeting app for couples")

    def test_new_chat_reuses_untouched_draft(self):
        _install_anthropic_stub("x")
        p1 = self._start_chat()
        resp = self.client.get(reverse("planner:project_new_chat"))
        self.assertRedirects(resp, reverse("planner:project_chat", args=[p1.pk]))
        self.assertEqual(Project.objects.filter(owner=self.user, is_draft=True).count(), 1)

    def _rename(self, pk, title):
        return self.client.post(
            reverse("planner:project_chat_rename", args=[pk]),
            data=json.dumps({"title": title}),
            content_type="application/json",
        )

    def test_rename_draft(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        resp = self._rename(project.pk, "My cool app")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "My cool app")
        project.refresh_from_db()
        self.assertEqual(project.name, "My cool app")

    def test_rename_empty_rejected(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        self.assertEqual(self._rename(project.pk, "   ").status_code, 400)

    def test_manual_title_survives_first_message(self):
        _install_anthropic_stub("Tell me more.")
        project = self._start_chat()
        self._rename(project.pk, "Renamed by hand")
        self._post(project.pk, "a budgeting app")  # would auto-title if untouched
        project.refresh_from_db()
        self.assertEqual(project.name, "Renamed by hand")

    def test_new_chat_after_messaging_starts_a_separate_draft(self):
        _install_anthropic_stub("Tell me more.")
        p1 = self._start_chat()
        self._post(p1.pk, "first idea")  # p1 now has a user turn
        resp = self.client.get(reverse("planner:project_new_chat"))
        p2 = Project.objects.filter(owner=self.user, is_draft=True).exclude(pk=p1.pk).get()
        self.assertRedirects(resp, reverse("planner:project_chat", args=[p2.pk]))

    def test_draft_hidden_from_dashboard_and_resumable(self):
        _install_anthropic_stub("x")
        project = self._start_chat()
        resp = self.client.get(reverse("planner:dashboard"))
        self.assertEqual(resp.context["projects"].count(), 0)
        self.assertIn(project, list(resp.context["drafts"]))
        # Visiting the finished-folder URL of a draft resumes the chat.
        detail = self.client.get(reverse("planner:project_detail", args=[project.pk]))
        self.assertRedirects(detail, reverse("planner:project_chat", args=[project.pk]))


# ===========================================================================
# Notes
# ===========================================================================
class NotesTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.other = _make_user(username="mallory")
        self.project = _make_project(self.user)
        self.client.force_login(self.user)

    def test_notes_page_loads(self):
        resp = self.client.get(reverse("planner:project_notes", args=[self.project.pk]))
        self.assertEqual(resp.status_code, 200)

    def test_create_note(self):
        resp = self.client.post(
            reverse("planner:project_notes", args=[self.project.pk]),
            data={"title": "Idea", "body": "Use websockets"},
        )
        self.assertRedirects(resp, reverse("planner:project_notes", args=[self.project.pk]))
        note = self.project.notes.get()
        self.assertEqual(note.title, "Idea")
        self.assertEqual(note.body, "Use websockets")

    def test_empty_note_rejected(self):
        resp = self.client.post(
            reverse("planner:project_notes", args=[self.project.pk]),
            data={"title": "", "body": "   "},
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertEqual(self.project.notes.count(), 0)

    def test_edit_note(self):
        note = Note.objects.create(project=self.project, title="A", body="x")
        resp = self.client.post(
            reverse("planner:note_edit", args=[self.project.pk, note.pk]),
            data={"title": "B", "body": "y"},
        )
        self.assertRedirects(resp, reverse("planner:project_notes", args=[self.project.pk]))
        note.refresh_from_db()
        self.assertEqual(note.title, "B")
        self.assertEqual(note.body, "y")

    def test_delete_note(self):
        note = Note.objects.create(project=self.project, body="bye")
        resp = self.client.post(reverse("planner:note_delete", args=[self.project.pk, note.pk]))
        self.assertRedirects(resp, reverse("planner:project_notes", args=[self.project.pk]))
        self.assertFalse(Note.objects.filter(pk=note.pk).exists())

    def test_notes_scoped_to_owner(self):
        note = Note.objects.create(project=self.project, body="secret")
        self.client.force_login(self.other)
        # Cannot view another user's project notes...
        self.assertEqual(
            self.client.get(reverse("planner:project_notes", args=[self.project.pk])).status_code,
            404,
        )
        # ...nor edit/delete a specific note.
        self.assertEqual(
            self.client.post(
                reverse("planner:note_edit", args=[self.project.pk, note.pk]),
                data={"title": "hax", "body": "z"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                reverse("planner:note_delete", args=[self.project.pk, note.pk])
            ).status_code,
            404,
        )
        self.assertTrue(Note.objects.filter(pk=note.pk).exists())

    def test_note_deleted_with_project(self):
        Note.objects.create(project=self.project, body="x")
        pk = self.project.pk
        self.project.delete()
        self.assertFalse(Note.objects.filter(project_id=pk).exists())


# ===========================================================================
# Admin (django-unfold)
# ===========================================================================
class AdminSmokeTests(TestCase):
    """The Unfold-themed admin loads (validates UNFOLD nav links + ModelAdmins)."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="root", password="hunter2hunter2", email="root@example.com"
        )
        self.client.force_login(self.admin)

    def test_admin_index_loads(self):
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)

    def test_planner_changelists_load(self):
        for model in ("project", "document", "chatmessage", "userprofile", "note"):
            url = reverse(f"admin:planner_{model}_changelist")
            self.assertEqual(self.client.get(url).status_code, 200, model)

    def test_project_change_form_loads(self):
        owner = _make_user(username="owner")
        project = _make_project(owner)
        url = reverse("admin:planner_project_change", args=[project.pk])
        self.assertEqual(self.client.get(url).status_code, 200)


# ===========================================================================
# Graceful AI-failure UX
# ===========================================================================
from .generators import errors as ai_errors  # noqa: E402


def _install_anthropic_credit_error():
    """Stub anthropic so any API call raises an out-of-credits style 400."""

    _MSG = "Error code: 400 - Your credit balance is too low to access the Anthropic API."

    class _Messages:
        def create(self, **kwargs):
            raise RuntimeError(_MSG)

        def stream(self, **kwargs):
            raise RuntimeError(_MSG)

    class _Anthropic:
        def __init__(self, *a, **k):
            self.messages = _Messages()

    module = types.ModuleType("anthropic")
    module.Anthropic = _Anthropic
    sys.modules["anthropic"] = module
    return module


class ErrorClassifierTests(TestCase):
    def test_string_categories(self):
        self.assertEqual(ai_errors.category_of("your credit balance is too low"), "credits")
        self.assertEqual(ai_errors.category_of("insufficient credit"), "credits")
        self.assertEqual(ai_errors.category_of("a billing problem"), "credits")
        self.assertEqual(ai_errors.category_of("invalid x-api-key"), "auth")
        self.assertEqual(ai_errors.category_of("authentication_error"), "auth")
        self.assertEqual(ai_errors.category_of("rate limit exceeded"), "rate_limit")
        self.assertEqual(ai_errors.category_of("the service is overloaded"), "overloaded")
        self.assertEqual(ai_errors.category_of("some random boom"), "generic")

    def test_typed_status_code(self):
        class E(Exception):
            status_code = 429
        self.assertEqual(ai_errors.category_of(E("nope")), "rate_limit")

    def test_credits_wins_over_400_status(self):
        class E(Exception):
            status_code = 400
        self.assertEqual(ai_errors.category_of(E("credit balance too low")), "credits")

    def test_friendly_messages_leak_nothing(self):
        for category, msg in ai_errors.FRIENDLY.items():
            self.assertTrue(msg, category)
            low = msg.lower()
            self.assertNotIn("x-api-key", low)
            self.assertNotIn("error code", low)


class ChatErrorUXTests(TestCase):
    def setUp(self):
        self.user = _make_user(api_key="user-sk-test")
        self.client.force_login(self.user)
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def test_intake_credit_error_is_friendly(self):
        _install_anthropic_credit_error()
        self.client.get(reverse("planner:project_new_chat"))
        draft = Project.objects.filter(owner=self.user, is_draft=True).latest("id")
        resp = self.client.post(
            reverse("planner:project_chat_message", args=[draft.pk]),
            data=json.dumps({"message": "hi"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)
        data = resp.json()
        self.assertEqual(data["error"], "credits")
        self.assertNotIn("credit balance", data["detail"].lower())
        self.assertEqual(self.client.session.get("ai_status"), "credits")

    def test_assistant_credit_error_then_success_clears_flag(self):
        project = _make_project(self.user)
        _install_anthropic_credit_error()
        resp = self.client.post(
            reverse("planner:project_assistant_message", args=[project.pk]),
            data=json.dumps({"message": "go"}), content_type="application/json",
        )
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], "credits")
        self.assertEqual(self.client.session.get("ai_status"), "credits")

        _install_anthropic_stub("All good, nothing to change.")
        ok = self.client.post(
            reverse("planner:project_assistant_message", args=[project.pk]),
            data=json.dumps({"message": "thanks"}), content_type="application/json",
        )
        self.assertEqual(ok.status_code, 200)
        self.assertIsNone(self.client.session.get("ai_status"))


class DocumentNewErrorUXTests(TestCase):
    def setUp(self):
        self.user = _make_user(api_key="user-sk-test")
        self.client.force_login(self.user)
        self._orig = sys.modules.get("anthropic")

    def tearDown(self):
        if self._orig is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = self._orig

    def test_document_new_credit_error_is_friendly(self):
        project = _make_project(self.user)
        _install_anthropic_credit_error()
        resp = self.client.post(
            reverse("planner:document_new", args=[project.pk]),
            data={"title": "Architecture", "prompt": "describe the system"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        rendered = " ".join(str(m) for m in resp.context["messages"]).lower()
        self.assertIn("out of credits", rendered)
        self.assertNotIn("credit balance", rendered)
        self.assertEqual(self.client.session.get("ai_status"), "credits")


class AiBannerTests(TestCase):
    def test_no_key_shows_template_mode_banner(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            user = _make_user(username="nokey", api_key="")
            self.client.force_login(user)
            resp = self.client.get(reverse("planner:dashboard"))
            self.assertContains(resp, 'id="ai-banner"')
            self.assertContains(resp, "template mode")

    def test_credits_flag_shows_banner(self):
        user = _make_user(username="withkey", api_key="k")
        self.client.force_login(user)
        session = self.client.session
        session["ai_status"] = "credits"
        session.save()
        resp = self.client.get(reverse("planner:dashboard"))
        self.assertContains(resp, 'id="ai-banner"')
        self.assertContains(resp, "out of credits")

    def test_key_and_no_flag_shows_no_banner(self):
        user = _make_user(username="clean", api_key="k")
        self.client.force_login(user)
        resp = self.client.get(reverse("planner:dashboard"))
        self.assertNotContains(resp, 'id="ai-banner"')


# ===========================================================================
# Document categories
# ===========================================================================
class DocumentCategoryTests(TestCase):
    def setUp(self):
        self.user = _make_user()
        self.client.force_login(self.user)

    def test_category_for_kind_mapping(self):
        self.assertEqual(
            Document.category_for_kind(Document.KIND_BUSINESS_PLAN),
            Document.CATEGORY_BUSINESS,
        )
        self.assertEqual(
            Document.category_for_kind(Document.KIND_SPECIFICATIONS),
            Document.CATEGORY_SYSTEM_DESIGN,
        )
        self.assertEqual(
            Document.category_for_kind(Document.KIND_USE_CASE_DIAGRAM),
            Document.CATEGORY_SYSTEM_DESIGN,
        )
        self.assertEqual(
            Document.category_for_kind(Document.KIND_ERD_DIAGRAM),
            Document.CATEGORY_DATA_DESIGN,
        )
        self.assertEqual(
            Document.category_for_kind(Document.KIND_FLOW_DIAGRAM),
            Document.CATEGORY_APP_DESIGN,
        )
        self.assertEqual(
            Document.category_for_kind(Document.KIND_CUSTOM),
            Document.CATEGORY_OTHER,
        )

    def test_save_normalises_builtin_category(self):
        project = _make_project(self.user)
        # Even if the wrong category is passed, built-in kinds are normalised.
        doc = Document.objects.create(
            project=project, kind=Document.KIND_BUSINESS_PLAN, title="BP",
            category=Document.CATEGORY_OTHER,
        )
        self.assertEqual(doc.category, Document.CATEGORY_BUSINESS)

    def test_custom_category_preserved(self):
        project = _make_project(self.user)
        doc = Document.objects.create(
            project=project, kind=Document.KIND_CUSTOM, title="Arch",
            category=Document.CATEGORY_SYSTEM_DESIGN,
        )
        self.assertEqual(doc.category, Document.CATEGORY_SYSTEM_DESIGN)
        plain = Document.objects.create(
            project=project, kind=Document.KIND_CUSTOM, title="X",
        )
        self.assertEqual(plain.category, Document.CATEGORY_OTHER)

    def test_sync_default_documents_sets_categories(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        cats = {d.kind: d.category for d in project.documents.all()}
        self.assertEqual(cats[Document.KIND_BUSINESS_PLAN], Document.CATEGORY_BUSINESS)
        self.assertEqual(cats[Document.KIND_USE_CASE_DIAGRAM], Document.CATEGORY_SYSTEM_DESIGN)
        self.assertEqual(cats[Document.KIND_ERD_DIAGRAM], Document.CATEGORY_DATA_DESIGN)
        self.assertEqual(cats[Document.KIND_FLOW_DIAGRAM], Document.CATEGORY_APP_DESIGN)
        self.assertEqual(cats[Document.KIND_USER_STORIES], Document.CATEGORY_APP_DESIGN)

    def test_project_detail_groups_by_category_in_order(self):
        project = _make_project(self.user)
        sync_default_documents(project)
        resp = self.client.get(reverse("planner:project_detail", args=[project.pk]))
        self.assertEqual(resp.status_code, 200)
        labels = [g["label"] for g in resp.context["category_groups"]]
        # Display order, empty categories (System Modeling, Other) omitted.
        self.assertEqual(labels, ["Business", "System Design", "Data Design", "App Design"])
        self.assertContains(resp, "System Design")
        self.assertContains(resp, "Data Design")


# ===========================================================================
# Password reset
# ===========================================================================
import re as _re  # noqa: E402
from django.core import mail  # noqa: E402


class PasswordResetTests(TestCase):
    def _user_with_email(self, username="resetme", email="reset@example.com"):
        user = _make_user(username=username)
        user.email = email
        user.save()
        return user

    def test_login_page_links_to_reset(self):
        resp = self.client.get(reverse("planner:login"))
        self.assertContains(resp, reverse("planner:password_reset"))

    def test_reset_request_sends_email(self):
        self._user_with_email()
        resp = self.client.post(
            reverse("planner:password_reset"), {"email": "reset@example.com"}
        )
        self.assertRedirects(resp, reverse("planner:password_reset_done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "Reset your DevPlanner password")
        self.assertIn("/reset/", mail.outbox[0].body)

    def test_full_reset_flow_lets_user_log_in(self):
        self._user_with_email()
        self.client.post(reverse("planner:password_reset"), {"email": "reset@example.com"})
        link = _re.search(r"/reset/[\w-]+/[\w-]+/", mail.outbox[0].body).group(0)

        # GET the token link → redirects to the session-based set-password form.
        resp = self.client.get(link)
        self.assertEqual(resp.status_code, 302)
        set_url = resp.url

        new_password = "n3w-Secur3-pass"
        resp = self.client.post(
            set_url,
            {"new_password1": new_password, "new_password2": new_password},
        )
        self.assertRedirects(resp, reverse("planner:password_reset_complete"))
        self.assertTrue(self.client.login(username="resetme", password=new_password))

    def test_unknown_email_still_succeeds_but_sends_nothing(self):
        resp = self.client.post(
            reverse("planner:password_reset"), {"email": "nobody@example.com"}
        )
        self.assertRedirects(resp, reverse("planner:password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)


class EmailOrUsernameLoginTests(TestCase):
    """Login accepts username or email via EmailOrUsernameModelBackend."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="alice", email="Alice@Example.com", password="Sup3rSecret!42",
        )
        self.url = reverse("planner:login")

    def _login(self, identifier, password="Sup3rSecret!42"):
        return self.client.post(
            self.url, {"username": identifier, "password": password},
        )

    def test_login_with_username(self):
        resp = self._login("alice")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_email(self):
        resp = self._login("Alice@Example.com")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_with_email_case_insensitive(self):
        resp = self._login("alice@example.com")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)

    def test_login_wrong_password_fails(self):
        resp = self._login("alice@example.com", password="nope")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_unknown_identifier_fails(self):
        resp = self._login("ghost@example.com")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_duplicate_email_is_ambiguous_and_rejected(self):
        # A second account sharing the email must not let either log in by email.
        User.objects.create_user(
            username="alice2", email="alice@example.com", password="Other!42pw",
        )
        resp = self._login("alice@example.com")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_field_relabelled(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, "Username or email")
