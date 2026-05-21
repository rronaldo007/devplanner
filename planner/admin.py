from django.contrib import admin

from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "language", "updated_at", "created_at")
    search_fields = ("name", "tagline", "problem", "solution")
    list_filter = ("language",)
