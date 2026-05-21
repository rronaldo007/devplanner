"""Tests for the planner app.

Focus on the parts that don't talk to the network: the form parsers, the
template-based document generator and the deterministic Mermaid diagrams.
The Claude engine is exercised behind a stub in :class:`ClaudeEngineTests`.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

from django.test import Client, TestCase
from django.urls import reverse

from .forms import InterviewForm
from .generators import diagrams, templates as tpl_gen
from .generators import generate
from .models import Project


def _sample_project(**overrides) -> Project:
    data = dict(
        name="Acme Tasks",
        tagline="Tiny todo manager for small teams",
        language="en",
        problem="Small teams lose track of todos across chat apps.",
        solution="A focused, shared task board with shortcuts.",
        differentiation="Faster keyboard UX than Trello.",
        competitors="Trello, Asana, Notion",
        target_users="Engineering teams of 2-10 people.",
        personas=[
            {"name": "Alice", "role": "Tech lead", "goal": "see team load at a glance"},
            {"name": "Bob", "role": "Engineer", "goal": "knock out tickets quickly"},
        ],
        features=["Create board", "Add task", "Assign task", "Mark done"],
        nice_to_have=["Slack integration"],
        out_of_scope=["Gantt charts"],
        business_model="Freemium: free for <5 users, $5/user/mo above.",
        success_metrics="100 active teams in 6 months.",
        stack="Django 6 + Postgres + HTMX",
        integrations="Slack, GitHub",
        hosting="Fly.io",
        entities=[
            {"name": "User", "fields": ["email", "name"]},
            {"name": "Board", "fields": ["name", "owner"]},
            {"name": "Task", "fields": ["title", "board", "assignee", "status"]},
        ],
        timeline="MVP in 8 weeks",
        budget="2 engineers part-time",
        risks="Slack API rate limits",
    )
    data.update(overrides)
    return Project.objects.create(**data)


class FormParserTests(TestCase):
    """The interview form turns textareas into structured JSON."""

    def test_features_split_by_line(self):
        form = InterviewForm(data=_form_data(features="a\nb\n  c  \n\nd"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["features"], ["a", "b", "c", "d"])

    def test_personas_pipe_format(self):
        form = InterviewForm(
            data=_form_data(personas="Alice | Lead | ship faster\nBob | Eng | finish tickets"),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["personas"],
            [
                {"name": "Alice", "role": "Lead", "goal": "ship faster"},
                {"name": "Bob", "role": "Eng", "goal": "finish tickets"},
            ],
        )

    def test_entities_indented_blocks(self):
        raw = "User\n  email\n  name\n\nTask\n  title\n  user"
        form = InterviewForm(data=_form_data(entities=raw))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["entities"],
            [
                {"name": "User", "fields": ["email", "name"]},
                {"name": "Task", "fields": ["title", "user"]},
            ],
        )

    def test_pre_fills_textareas_when_editing(self):
        project = _sample_project()
        form = InterviewForm(instance=project)
        self.assertIn("Create board", form.fields["features"].initial)
        self.assertIn("Alice | Tech lead", form.fields["personas"].initial)
        self.assertIn("Task", form.fields["entities"].initial)


class TemplateGeneratorTests(TestCase):
    def test_business_plan_includes_key_sections_english(self):
        project = _sample_project()
        doc = tpl_gen.business_plan(project)
        for section in (
            "Business Plan", "Executive Summary", "Problem", "Solution",
            "Target Audience", "Business Model", "Risks",
        ):
            self.assertIn(section, doc)
        self.assertIn("Acme Tasks", doc)
        self.assertIn("Alice", doc)

    def test_business_plan_localized_to_french(self):
        project = _sample_project(language="fr")
        doc = tpl_gen.business_plan(project)
        for section in ("Résumé exécutif", "Problème", "Solution", "Public cible"):
            self.assertIn(section, doc)

    def test_specifications_lists_features_and_entities(self):
        project = _sample_project()
        doc = tpl_gen.specifications(project)
        self.assertIn("FR-01", doc)
        self.assertIn("Create board", doc)
        self.assertIn("Task", doc)
        self.assertIn("assignee", doc)

    def test_user_stories_one_per_persona_per_feature(self):
        project = _sample_project()
        doc = tpl_gen.user_stories(project)
        story_count = doc.count("US-")
        expected = len(project.personas) * (len(project.features) + len(project.nice_to_have))
        self.assertEqual(story_count, expected)


class DiagramTests(TestCase):
    def test_use_case_mentions_actors_and_features(self):
        project = _sample_project()
        out = diagrams.use_case(project)
        self.assertTrue(out.startswith("flowchart"))
        self.assertIn("Create board", out)
        self.assertIn("Alice", out)

    def test_erd_emits_entities(self):
        project = _sample_project()
        out = diagrams.erd(project)
        self.assertTrue(out.startswith("erDiagram"))
        self.assertIn("User", out)
        self.assertIn("Task", out)

    def test_erd_with_no_entities_still_returns_valid_mermaid(self):
        project = _sample_project(entities=[])
        out = diagrams.erd(project)
        self.assertTrue(out.startswith("erDiagram"))

    def test_flow_diagram_chains_through_features(self):
        project = _sample_project()
        out = diagrams.flow(project)
        self.assertTrue(out.startswith("flowchart"))
        self.assertIn("Discover Acme Tasks", out)
        self.assertIn("Sign up", out)


class GenerateOrchestratorTests(TestCase):
    def test_falls_back_to_templates_without_api_key(self):
        project = _sample_project()
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            out = generate(project)
        self.assertEqual(out["engine"], "templates")
        self.assertIn("Business Plan", out["business_plan"])

    def test_force_engine_templates(self):
        project = _sample_project()
        out = generate(project, force_engine="templates")
        self.assertEqual(out["engine"], "templates")


class ClaudeEngineTests(TestCase):
    """Exercise the Claude branch with a stubbed ``anthropic`` package."""

    def test_uses_claude_when_module_and_key_available(self):
        project = _sample_project()
        stub = _build_anthropic_stub(
            "===BUSINESS_PLAN===\n# Business Plan — Acme Tasks\nfake bp\n"
            "===SPECIFICATIONS===\n# Cahier — Acme Tasks\nfake spec\n"
            "===USER_STORIES===\n# US — Acme Tasks\nUS-1 ...\n"
        )
        with mock.patch.dict(sys.modules, {"anthropic": stub}), \
             mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            out = generate(project)
        self.assertEqual(out["engine"], "claude")
        self.assertIn("fake bp", out["business_plan"])
        self.assertIn("fake spec", out["specifications"])
        self.assertIn("US-1", out["user_stories"])

    def test_falls_back_to_templates_on_error(self):
        project = _sample_project()
        stub = _build_anthropic_stub(None, raise_on_create=RuntimeError("boom"))
        with mock.patch.dict(sys.modules, {"anthropic": stub}), \
             mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test"}):
            out = generate(project)
        self.assertEqual(out["engine"], "templates")
        self.assertIn("boom", out["_claude_error"])


class ViewsTests(TestCase):
    def setUp(self):
        self.client = Client()

    def test_home_lists_projects(self):
        _sample_project(name="Project X")
        response = self.client.get(reverse("planner:home"))
        self.assertContains(response, "Project X")

    def test_new_project_submission_creates_and_redirects(self):
        response = self.client.post(
            reverse("planner:project_new"),
            data=_form_data(name="NewOne"),
        )
        self.assertEqual(response.status_code, 302)
        project = Project.objects.get(name="NewOne")
        self.assertIn(f"/projects/{project.pk}/", response.url)

    def test_detail_renders_documents_and_mermaid(self):
        project = _sample_project()
        response = self.client.get(reverse("planner:project_detail", args=[project.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Business Plan")
        self.assertContains(response, "class=\"mermaid\"")
        self.assertContains(response, "erDiagram")

    def test_download_endpoint_serves_markdown(self):
        project = _sample_project()
        url = reverse("planner:project_document", args=[project.pk, "business_plan"])
        response = self.client.get(url + "?download=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/markdown; charset=utf-8")
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(b"Business Plan", response.content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _form_data(**overrides) -> dict:
    base = {
        "name": "Acme",
        "tagline": "",
        "language": "en",
        "problem": "some problem",
        "solution": "some solution",
        "differentiation": "",
        "competitors": "",
        "target_users": "devs",
        "personas": "",
        "features": "",
        "nice_to_have": "",
        "out_of_scope": "",
        "business_model": "",
        "success_metrics": "",
        "stack": "",
        "integrations": "",
        "hosting": "",
        "entities": "",
        "timeline": "",
        "budget": "",
        "risks": "",
    }
    base.update(overrides)
    return base


def _build_anthropic_stub(reply_text: str | None, *, raise_on_create: Exception | None = None):
    """Return a fake `anthropic` module exposing the API we use."""

    module = types.ModuleType("anthropic")

    class _Block:
        def __init__(self, text):
            self.text = text

    class _Response:
        def __init__(self, text):
            self.content = [_Block(text)]

    class _Messages:
        def __init__(self):
            self.last_kwargs: dict | None = None

        def create(self, **kwargs):
            self.last_kwargs = kwargs
            if raise_on_create is not None:
                raise raise_on_create
            return _Response(reply_text or "")

    class _Anthropic:
        def __init__(self, *args, **kwargs):
            self.messages = _Messages()

    module.Anthropic = _Anthropic
    return module


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
