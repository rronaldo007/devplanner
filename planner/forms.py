"""Forms for the planner app."""

from __future__ import annotations

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from .models import Document, Project, UserProfile


User = get_user_model()


# ===========================================================================
# Auth
# ===========================================================================
class RegisterForm(UserCreationForm):
    """Sign-up form: username + email + password."""

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "email")


# ===========================================================================
# User settings
# ===========================================================================
class UserProfileForm(forms.ModelForm):
    """Editable bits of :class:`UserProfile`."""

    class Meta:
        model = UserProfile
        fields = ("anthropic_api_key", "default_language")
        widgets = {
            "anthropic_api_key": forms.PasswordInput(
                attrs={"placeholder": "sk-ant-..."}, render_value=True,
            ),
        }


# ===========================================================================
# Interview
# ===========================================================================
class InterviewForm(forms.ModelForm):
    """Multi-section interview captured in a single form submission."""

    features = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "placeholder": "One feature per line"}),
        help_text="Must-have features. One per line.",
    )
    nice_to_have = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "One feature per line"}),
        help_text="Nice-to-have features. One per line.",
    )
    out_of_scope = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "One item per line"}),
        help_text="Things explicitly NOT in this version. One per line.",
    )
    personas = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "Name | Role | Goal\nAlice | Freelance dev | Quickly draft project briefs",
        }),
        help_text="One persona per line. Format: Name | Role | Goal",
    )
    entities = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 8,
            "placeholder": (
                "Project\n  name\n  owner\n  status\n\n"
                "Document\n  type\n  content\n  project"
            ),
        }),
        help_text=(
            "One entity per block. First line is the entity name, subsequent "
            "indented lines are fields. Separate entities with a blank line."
        ),
    )

    fieldsets = [
        ("Identity", ["name", "tagline", "language"]),
        ("Problem & Solution", ["problem", "solution", "differentiation", "competitors"]),
        ("Audience", ["target_users", "personas"]),
        ("Scope", ["features", "nice_to_have", "out_of_scope"]),
        ("Business", ["business_model", "success_metrics"]),
        ("Technical", ["stack", "integrations", "hosting", "entities"]),
        ("Constraints & Risks", ["timeline", "budget", "risks"]),
    ]

    class Meta:
        model = Project
        fields = [
            "name", "tagline", "language",
            "problem", "solution", "differentiation", "competitors",
            "target_users", "personas",
            "features", "nice_to_have", "out_of_scope",
            "business_model", "success_metrics",
            "stack", "integrations", "hosting", "entities",
            "timeline", "budget", "risks",
        ]
        widgets = {
            "problem": forms.Textarea(attrs={"rows": 3}),
            "solution": forms.Textarea(attrs={"rows": 3}),
            "differentiation": forms.Textarea(attrs={"rows": 2}),
            "competitors": forms.Textarea(attrs={"rows": 2}),
            "target_users": forms.Textarea(attrs={"rows": 2}),
            "business_model": forms.Textarea(attrs={"rows": 2}),
            "success_metrics": forms.Textarea(attrs={"rows": 2}),
            "integrations": forms.Textarea(attrs={"rows": 2}),
            "risks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["features"].initial = "\n".join(self.instance.features or [])
            self.fields["nice_to_have"].initial = "\n".join(self.instance.nice_to_have or [])
            self.fields["out_of_scope"].initial = "\n".join(self.instance.out_of_scope or [])
            self.fields["personas"].initial = "\n".join(
                f"{p.get('name', '')} | {p.get('role', '')} | {p.get('goal', '')}"
                for p in (self.instance.personas or [])
            )
            self.fields["entities"].initial = _entities_to_text(self.instance.entities or [])

    def clean_features(self):
        return _lines(self.cleaned_data.get("features", ""))

    def clean_nice_to_have(self):
        return _lines(self.cleaned_data.get("nice_to_have", ""))

    def clean_out_of_scope(self):
        return _lines(self.cleaned_data.get("out_of_scope", ""))

    def clean_personas(self):
        raw = self.cleaned_data.get("personas", "") or ""
        out: list[dict[str, str]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|")]
            while len(parts) < 3:
                parts.append("")
            out.append({"name": parts[0], "role": parts[1], "goal": parts[2]})
        return out

    def clean_entities(self):
        return _parse_entities(self.cleaned_data.get("entities", "") or "")


# ===========================================================================
# Documents
# ===========================================================================
class CustomDocumentForm(forms.Form):
    """Form for the 'Add document' flow.

    Users supply a title and (optionally) an instruction prompt. If Claude is
    available the body is generated; otherwise a stub is created and they
    can write it themselves.
    """

    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Technical Architecture"}),
    )
    prompt = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": (
                "What should this document contain? Leave blank to write it yourself."
            ),
        }),
        help_text="Used as instructions for Claude. Optional.",
    )


class DocumentEditForm(forms.ModelForm):
    """Inline editor for a document body."""

    class Meta:
        model = Document
        fields = ("title", "body")
        widgets = {
            "body": forms.Textarea(attrs={"rows": 20, "class": "font-mono"}),
        }


# ===========================================================================
# Helpers
# ===========================================================================
def _lines(text: str) -> list[str]:
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


def _parse_entities(text: str) -> list[dict]:
    blocks: list[list[str]] = [[]]
    for line in (text or "").splitlines():
        if not line.strip():
            if blocks[-1]:
                blocks.append([])
            continue
        blocks[-1].append(line)
    entities: list[dict] = []
    for block in blocks:
        if not block:
            continue
        header = block[0].strip()
        if not header:
            continue
        fields = []
        for raw in block[1:]:
            field = raw.strip().lstrip("-").strip()
            if field:
                fields.append(field)
        entities.append({"name": header, "fields": fields})
    return entities


def _entities_to_text(entities: list[dict]) -> str:
    parts = []
    for ent in entities:
        block = [ent.get("name", "")]
        for field in ent.get("fields", []):
            block.append(f"  {field}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)
