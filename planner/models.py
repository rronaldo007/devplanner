from django.db import models


class Project(models.Model):
    """A project idea being prepared for development.

    Stores the answers to the interview as structured fields. List-like
    answers (features, personas, entities, ...) live in JSONField columns so
    the generators can iterate over them cleanly.
    """

    LANG_FR = "fr"
    LANG_EN = "en"
    LANG_CHOICES = [
        (LANG_FR, "Français"),
        (LANG_EN, "English"),
    ]

    # --- Identity -------------------------------------------------------
    name = models.CharField(max_length=120)
    tagline = models.CharField(max_length=240, blank=True)
    language = models.CharField(
        max_length=2, choices=LANG_CHOICES, default=LANG_EN,
        help_text="Language of the generated documents.",
    )

    # --- Problem / Solution --------------------------------------------
    problem = models.TextField(
        help_text="What pain point does this project solve?",
    )
    solution = models.TextField(
        help_text="In 2-3 sentences, how does the project solve it?",
    )
    differentiation = models.TextField(
        blank=True,
        help_text="What makes it different from existing alternatives?",
    )
    competitors = models.TextField(
        blank=True,
        help_text="Comma-separated list of known competitors.",
    )

    # --- Audience -------------------------------------------------------
    target_users = models.TextField(
        help_text="Who is this for? Describe the main audience.",
    )
    personas = models.JSONField(
        default=list, blank=True,
        help_text=(
            "List of personas as {name, role, goal}. The interview form "
            "splits this from a textarea."
        ),
    )

    # --- Scope ----------------------------------------------------------
    features = models.JSONField(
        default=list, blank=True,
        help_text="Must-have features (one per line in the form).",
    )
    nice_to_have = models.JSONField(
        default=list, blank=True,
        help_text="Nice-to-have features (one per line in the form).",
    )
    out_of_scope = models.JSONField(
        default=list, blank=True,
        help_text="Explicitly excluded features (one per line in the form).",
    )

    # --- Business -------------------------------------------------------
    business_model = models.TextField(
        blank=True,
        help_text="How does the project make money? (or 'open source')",
    )
    success_metrics = models.TextField(
        blank=True,
        help_text="What does success look like? Concrete KPIs.",
    )

    # --- Technical ------------------------------------------------------
    stack = models.CharField(
        max_length=240, blank=True,
        help_text="Preferred tech stack (e.g. Django + Postgres + React).",
    )
    integrations = models.TextField(
        blank=True,
        help_text="Comma-separated list of external services / APIs.",
    )
    hosting = models.CharField(
        max_length=120, blank=True,
        help_text="Where will it run? (e.g. AWS, Fly.io, on-prem)",
    )
    entities = models.JSONField(
        default=list, blank=True,
        help_text=(
            "Data model entities as {name, fields}. Used to draw the ERD."
        ),
    )

    # --- Constraints / Risks -------------------------------------------
    timeline = models.CharField(
        max_length=120, blank=True,
        help_text="Target delivery window (e.g. 'MVP in 6 weeks').",
    )
    budget = models.CharField(
        max_length=120, blank=True,
        help_text="Budget / team size.",
    )
    risks = models.TextField(
        blank=True,
        help_text="Known risks and dependencies.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return self.name
