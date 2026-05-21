from django.contrib import admin

from .models import Document, Project, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "default_language", "has_api_key", "updated_at")
    search_fields = ("user__username", "user__email")

    @admin.display(boolean=True, description="API key")
    def has_api_key(self, obj):
        return bool(obj.anthropic_api_key)


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "language", "created_at", "updated_at")
    list_filter = ("language", "owner")
    search_fields = ("name", "tagline", "owner__username")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("title", "project", "kind", "is_generated", "updated_at")
    list_filter = ("kind", "is_generated")
    search_fields = ("title", "project__name")
