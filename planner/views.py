"""Views for the planner app.

Three groups:

* Public: home, about, login, register, logout.
* Dashboard: projects list, project folder, interview, settings.
* Document: view, edit, regenerate, download, delete; "+ New document"
  flow for custom docs.

All dashboard / document views require login and scope queries to
``request.user``.
"""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import generators
from .forms import (
    CustomDocumentForm, DocumentEditForm, InterviewForm,
    RegisterForm, UserProfileForm,
)
from .models import Document, Project


# ===========================================================================
# Public
# ===========================================================================
def home(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("planner:dashboard"))
    return render(request, "planner/public/home.html")


def about(request):
    return render(request, "planner/public/about.html")


def register(request):
    if request.user.is_authenticated:
        return HttpResponseRedirect(reverse("planner:dashboard"))
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            auth_login(request, user)
            messages.success(request, "Welcome! Your account is ready.")
            return HttpResponseRedirect(reverse("planner:dashboard"))
    else:
        form = RegisterForm()
    return render(request, "planner/auth/register.html", {"form": form})


# ===========================================================================
# Dashboard
# ===========================================================================
@login_required
def dashboard(request):
    projects = request.user.projects.all()
    return render(
        request,
        "planner/dashboard/index.html",
        {
            "projects": projects,
            "project_count": projects.count(),
            "document_count": Document.objects.filter(project__owner=request.user).count(),
        },
    )


@login_required
def project_new(request):
    if request.method == "POST":
        form = InterviewForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()
            generators.sync_default_documents(project)
            messages.success(
                request,
                f"Project '{project.name}' created and {len(Document.DEFAULT_KINDS)} "
                f"documents generated.",
            )
            return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))
    else:
        initial = {"language": request.user.profile.default_language}
        form = InterviewForm(initial=initial)
    return render(
        request,
        "planner/dashboard/interview.html",
        {"form": form, "mode": "new"},
    )


@login_required
def project_edit(request, pk):
    project = _owned_project(request, pk)
    if request.method == "POST":
        form = InterviewForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, "Interview updated. Use 'Regenerate' on any document to refresh it.")
            return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))
    else:
        form = InterviewForm(instance=project)
    return render(
        request,
        "planner/dashboard/interview.html",
        {"form": form, "mode": "edit", "project": project},
    )


@login_required
def project_detail(request, pk):
    """Folder view: lists documents in the project."""

    project = _owned_project(request, pk)
    docs = list(project.documents.all())
    grouped = {
        "planning": [d for d in docs if d.kind in (
            Document.KIND_BUSINESS_PLAN,
            Document.KIND_SPECIFICATIONS,
            Document.KIND_USER_STORIES,
        )],
        "diagrams": [d for d in docs if d.kind in Document.DIAGRAM_KINDS],
        "custom": [d for d in docs if d.kind == Document.KIND_CUSTOM],
    }
    return render(
        request,
        "planner/dashboard/project_detail.html",
        {"project": project, "groups": grouped, "doc_count": len(docs)},
    )


@require_http_methods(["POST"])
@login_required
def project_delete(request, pk):
    project = _owned_project(request, pk)
    name = project.name
    project.delete()
    messages.success(request, f"Project '{name}' deleted.")
    return HttpResponseRedirect(reverse("planner:dashboard"))


# ===========================================================================
# Documents
# ===========================================================================
@login_required
def document_detail(request, pk, doc_pk):
    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    return render(
        request,
        "planner/dashboard/document_detail.html",
        {"project": project, "document": document},
    )


@login_required
def document_edit(request, pk, doc_pk):
    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    if request.method == "POST":
        form = DocumentEditForm(request.POST, instance=document)
        if form.is_valid():
            doc = form.save(commit=False)
            doc.is_generated = False  # hand-edited from now on
            doc.save()
            messages.success(request, "Document saved.")
            return HttpResponseRedirect(
                reverse("planner:document_detail", args=[project.pk, doc.pk])
            )
    else:
        form = DocumentEditForm(instance=document)
    return render(
        request,
        "planner/dashboard/document_edit.html",
        {"project": project, "document": document, "form": form},
    )


@require_http_methods(["POST"])
@login_required
def document_regenerate(request, pk, doc_pk):
    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    document.body = generators.regenerate(document)
    document.is_generated = True
    document.save()
    messages.success(request, f"'{document.title}' regenerated.")
    return HttpResponseRedirect(
        reverse("planner:document_detail", args=[project.pk, document.pk])
    )


@require_http_methods(["POST"])
@login_required
def document_delete(request, pk, doc_pk):
    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    if document.kind in Document.DEFAULT_KINDS:
        messages.error(request, "Default documents can't be deleted, only regenerated.")
        return HttpResponseRedirect(
            reverse("planner:document_detail", args=[project.pk, document.pk])
        )
    title = document.title
    document.delete()
    messages.success(request, f"'{title}' deleted.")
    return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))


@login_required
def document_new(request, pk):
    project = _owned_project(request, pk)
    if request.method == "POST":
        form = CustomDocumentForm(request.POST)
        if form.is_valid():
            title = form.cleaned_data["title"]
            prompt = form.cleaned_data["prompt"]
            result = generators.generate_custom(project, title, prompt)
            document = Document.objects.create(
                project=project,
                kind=Document.KIND_CUSTOM,
                title=title,
                body=result["body"],
                prompt=prompt,
                is_generated=bool(prompt),
            )
            if result.get("_claude_error"):
                messages.warning(
                    request,
                    f"Claude failed, created a starter instead: {result['_claude_error']}",
                )
            else:
                messages.success(request, f"'{title}' created via {result['engine']}.")
            return HttpResponseRedirect(
                reverse("planner:document_detail", args=[project.pk, document.pk])
            )
    else:
        form = CustomDocumentForm()
    return render(
        request,
        "planner/dashboard/document_new.html",
        {"project": project, "form": form},
    )


@require_http_methods(["GET"])
@login_required
def document_download(request, pk, doc_pk):
    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    response = HttpResponse(document.body, content_type="text/markdown; charset=utf-8")
    filename = f"{project.pk}_{document.kind}_{document.pk}.md"
    if request.GET.get("download") == "1":
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ===========================================================================
# Settings
# ===========================================================================
@login_required
def settings_view(request):
    profile = request.user.profile
    if request.method == "POST":
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return HttpResponseRedirect(reverse("planner:settings"))
    else:
        form = UserProfileForm(instance=profile)
    return render(
        request,
        "planner/dashboard/settings.html",
        {"form": form, "profile": profile},
    )


# ===========================================================================
# Helpers
# ===========================================================================
def _owned_project(request, pk) -> Project:
    """Fetch a project ensuring the current user owns it (404 otherwise)."""

    return get_object_or_404(Project, pk=pk, owner=request.user)
