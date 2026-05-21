"""Models for the planner app.

Each ``Project`` is a *folder* owned by a ``User``. It holds the answers to
the project interview plus a collection of ``Document`` rows. Documents come
in fixed kinds (the three default planning docs and the three Mermaid
diagrams) plus a free-form ``custom`` kind so users can add their own files.

``UserProfile`` stores per-user settings (their own Anthropic API key and
their default output language).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


LANG_FR = "fr"
LANG_EN = "en"
LANG_CHOICES = [
    (LANG_FR, "Français"),
    (LANG_EN, "English"),
]


class UserProfile(models.Model):
    """Per-user settings: Claude API key + preferred output language."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    anthropic_api_key = models.CharField(
        max_length=200, blank=True,
        help_text="Your Anthropic API key. Used to call Claude for document generation.",
    )
    default_language = models.CharField(
        max_length=2, choices=LANG_CHOICES, default=LANG_EN,
        help_text="Default language for newly created projects.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"profile<{self.user}>"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    """Always have a profile for every user."""

    if created:
        UserProfile.objects.create(user=instance)
    else:
        UserProfile.objects.get_or_create(user=instance)


class Project(models.Model):
    """A project idea being prepared for development.

    The interview answers live directly on this model. Generated planning
    docs and diagrams are persisted as :class:`Document` rows so users can
    edit / add to them.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="projects",
    )

    # --- Identity -------------------------------------------------------
    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=240, blank=True)
    language = models.CharField(max_length=2, choices=LANG_CHOICES, default=LANG_EN)

    # --- Problem / Solution --------------------------------------------
    problem = models.TextField(help_text="What pain point does this project solve?")
    solution = models.TextField(help_text="In 2-3 sentences, how does the project solve it?")
    differentiation = models.TextField(blank=True)
    competitors = models.TextField(blank=True)

    # --- Audience -------------------------------------------------------
    target_users = models.TextField(help_text="Who is this for?")
    personas = models.JSONField(default=list, blank=True)

    # --- Scope ----------------------------------------------------------
    features = models.JSONField(default=list, blank=True)
    nice_to_have = models.JSONField(default=list, blank=True)
    out_of_scope = models.JSONField(default=list, blank=True)

    # --- Business -------------------------------------------------------
    business_model = models.TextField(blank=True)
    success_metrics = models.TextField(blank=True)

    # --- Technical ------------------------------------------------------
    stack = models.CharField(max_length=240, blank=True)
    integrations = models.TextField(blank=True)
    hosting = models.CharField(max_length=120, blank=True)
    entities = models.JSONField(default=list, blank=True)

    # --- Constraints / Risks -------------------------------------------
    timeline = models.CharField(max_length=120, blank=True)
    budget = models.CharField(max_length=120, blank=True)
    risks = models.TextField(blank=True)

    # A project created from a chat that hasn't been finalised yet. Drafts
    # are hidden from the dashboard until their documents are generated.
    is_draft = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name


class Document(models.Model):
    """A file living inside a project folder.

    A document can be either:
    * one of the six well-known kinds generated from the interview answers
      (business plan, cahier des charges, user stories, three diagrams), or
    * a free-form ``custom`` markdown file the user adds and edits.

    Documents of kind ``*_diagram`` store raw Mermaid syntax in ``body``;
    everything else stores Markdown.
    """

    KIND_BUSINESS_PLAN = "business_plan"
    KIND_SPECIFICATIONS = "specifications"
    KIND_USER_STORIES = "user_stories"
    KIND_USE_CASE_DIAGRAM = "use_case_diagram"
    KIND_ERD_DIAGRAM = "erd_diagram"
    KIND_FLOW_DIAGRAM = "flow_diagram"
    KIND_CUSTOM = "custom"

    KIND_CHOICES = [
        (KIND_BUSINESS_PLAN, "Business Plan"),
        (KIND_SPECIFICATIONS, "Cahier des Charges"),
        (KIND_USER_STORIES, "User Stories"),
        (KIND_USE_CASE_DIAGRAM, "Use Case Diagram"),
        (KIND_ERD_DIAGRAM, "Entity-Relationship Diagram"),
        (KIND_FLOW_DIAGRAM, "User Flow Diagram"),
        (KIND_CUSTOM, "Custom Document"),
    ]

    DEFAULT_KINDS = (
        KIND_BUSINESS_PLAN,
        KIND_SPECIFICATIONS,
        KIND_USER_STORIES,
        KIND_USE_CASE_DIAGRAM,
        KIND_ERD_DIAGRAM,
        KIND_FLOW_DIAGRAM,
    )
    DIAGRAM_KINDS = (
        KIND_USE_CASE_DIAGRAM,
        KIND_ERD_DIAGRAM,
        KIND_FLOW_DIAGRAM,
    )

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="documents",
    )
    kind = models.CharField(max_length=32, choices=KIND_CHOICES, default=KIND_CUSTOM)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_generated = models.BooleanField(
        default=False,
        help_text="True if this document was produced by the generators (vs hand-written).",
    )
    # The prompt the user gave when generating this custom doc, kept so we
    # can regenerate it later.
    prompt = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kind", "created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.get_kind_display()})"

    @property
    def is_diagram(self) -> bool:
        return self.kind in self.DIAGRAM_KINDS


class ChatMessage(models.Model):
    """One turn of the project-intake chat, persisted so the conversation
    survives reloads and can be resumed.

    Stored against the (draft) :class:`Project` the chat is building.
    """

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = [
        (ROLE_USER, "User"),
        (ROLE_ASSISTANT, "Assistant"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="chat_messages",
    )
    role = models.CharField(max_length=16, choices=ROLE_CHOICES)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.role}: {self.content[:40]}"
