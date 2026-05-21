"""Views for the planner app."""

from __future__ import annotations

from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import generators
from .forms import InterviewForm
from .models import Project


DOC_LABELS = {
    "business_plan": ("Business Plan", "business_plan.md"),
    "specifications": ("Cahier des Charges", "cahier_des_charges.md"),
    "user_stories": ("User Stories", "user_stories.md"),
}


def home(request):
    projects = Project.objects.all()
    return render(request, "planner/home.html", {"projects": projects})


def project_new(request):
    if request.method == "POST":
        form = InterviewForm(request.POST)
        if form.is_valid():
            project = form.save()
            return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))
    else:
        form = InterviewForm()
    return render(
        request,
        "planner/interview.html",
        {"form": form, "mode": "new"},
    )


def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == "POST":
        form = InterviewForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))
    else:
        form = InterviewForm(instance=project)
    return render(
        request,
        "planner/interview.html",
        {"form": form, "mode": "edit", "project": project},
    )


def project_detail(request, pk):
    project = get_object_or_404(Project, pk=pk)
    force = request.GET.get("engine")  # optional override: ?engine=templates|claude
    output = generators.generate(project, force_engine=force)
    return render(
        request,
        "planner/project_detail.html",
        {
            "project": project,
            "output": output,
            "doc_labels": DOC_LABELS,
        },
    )


@require_http_methods(["GET"])
def project_document(request, pk, doc):
    if doc not in DOC_LABELS:
        return HttpResponse(status=404)
    project = get_object_or_404(Project, pk=pk)
    output = generators.generate(project)
    body = output.get(doc) or ""
    _, filename = DOC_LABELS[doc]
    download = request.GET.get("download") == "1"
    response = HttpResponse(body, content_type="text/markdown; charset=utf-8")
    if download:
        response["Content-Disposition"] = (
            f'attachment; filename="{project.pk}_{filename}"'
        )
    return response


@require_http_methods(["POST"])
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    project.delete()
    return HttpResponseRedirect(reverse("planner:home"))
