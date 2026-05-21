"""Admin, themed with django-unfold.

All model admins extend ``unfold.admin.ModelAdmin`` so the whole site uses the
Unfold UI. The built-in auth User/Group admins are re-registered on top of
Unfold's base for a cohesive look.
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.models import Group
from unfold.admin import ModelAdmin, TabularInline

from .models import ChatMessage, Document, Project, UserProfile

User = get_user_model()


# --- Re-skin the built-in auth admins with Unfold ------------------------
admin.site.unregister(User)
admin.site.unregister(Group)


@admin.register(User)
class UserAdmin(DjangoUserAdmin, ModelAdmin):
    pass


@admin.register(Group)
class GroupAdmin(DjangoGroupAdmin, ModelAdmin):
    pass


# --- Planner models ------------------------------------------------------
class DocumentInline(TabularInline):
    model = Document
    fields = ("title", "kind", "is_generated", "updated_at")
    readonly_fields = ("updated_at",)
    extra = 0
    show_change_link = True
    tab = True


@admin.register(UserProfile)
class UserProfileAdmin(ModelAdmin):
    list_display = ("user", "default_language", "has_api_key", "updated_at")
    search_fields = ("user__username", "user__email")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(boolean=True, description="API key")
    def has_api_key(self, obj):
        return bool(obj.anthropic_api_key)


@admin.register(Project)
class ProjectAdmin(ModelAdmin):
    list_display = ("name", "owner", "language", "is_draft", "doc_count", "updated_at")
    list_filter = ("language", "is_draft")
    list_filter_submit = True
    search_fields = ("name", "tagline", "owner__username")
    list_select_related = ("owner",)
    readonly_fields = ("created_at", "updated_at")
    inlines = (DocumentInline,)
    fieldsets = (
        ("Identity", {
            "classes": ["tab"],
            "fields": ("owner", "name", "tagline", "language", "is_draft"),
        }),
        ("Problem & Solution", {
            "classes": ["tab"],
            "fields": ("problem", "solution", "differentiation", "competitors"),
        }),
        ("Audience", {
            "classes": ["tab"],
            "fields": ("target_users", "personas"),
        }),
        ("Scope", {
            "classes": ["tab"],
            "fields": ("features", "nice_to_have", "out_of_scope"),
        }),
        ("Business", {
            "classes": ["tab"],
            "fields": ("business_model", "success_metrics"),
        }),
        ("Technical", {
            "classes": ["tab"],
            "fields": ("stack", "integrations", "hosting", "entities"),
        }),
        ("Constraints & Risks", {
            "classes": ["tab"],
            "fields": ("timeline", "budget", "risks"),
        }),
        ("Meta", {
            "classes": ["tab"],
            "fields": ("created_at", "updated_at"),
        }),
    )

    @admin.display(description="Docs")
    def doc_count(self, obj):
        return obj.documents.count()


@admin.register(Document)
class DocumentAdmin(ModelAdmin):
    list_display = ("title", "project", "kind", "is_generated", "updated_at")
    list_filter = ("kind", "is_generated")
    list_filter_submit = True
    search_fields = ("title", "project__name")
    list_select_related = ("project",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ChatMessage)
class ChatMessageAdmin(ModelAdmin):
    list_display = (
        "project", "phase", "role", "short_content", "proposal_status", "created_at",
    )
    list_filter = ("phase", "role", "proposal_status")
    list_filter_submit = True
    search_fields = ("project__name", "content")
    list_select_related = ("project",)
    readonly_fields = ("created_at",)

    @admin.display(description="Content")
    def short_content(self, obj):
        text = " ".join((obj.content or "").split())
        return (text[:80] + "…") if len(text) > 80 else text
