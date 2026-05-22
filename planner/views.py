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

import json

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from . import generators
from .generators import chat, errors
from .forms import (
    CustomDocumentForm, DocumentEditForm, InterviewForm,
    NoteForm, RegisterForm, UserProfileForm,
)
from .models import ChatMessage, Conversation, Document, Note, Project


# ===========================================================================
# AI status banner (see planner/context_processors.ai_status)
# ===========================================================================
def _record_ai_status(request, category: str) -> None:
    """Remember a banner-worthy AI failure (credits / auth) for this session.

    Saved explicitly (like ``login()`` does) so it persists even from the JSON
    POST endpoints regardless of middleware save behaviour.
    """

    if errors.is_persistent(category):
        request.session["ai_status"] = category
        request.session.save()


def _clear_ai_status(request) -> None:
    """Clear the AI failure flag after a successful AI call."""

    if request.session.get("ai_status"):
        del request.session["ai_status"]
        request.session.save()


def _sync_ai_status(request, claude_error: str) -> None:
    """Record a banner-worthy failure when AI degraded, else clear the flag.

    ``claude_error`` is the ``_claude_error`` field returned by the generators
    (non-empty only when generation fell all the way back to templates).
    """

    if claude_error:
        category, _ = errors.classify(claude_error)
        _record_ai_status(request, category)
    else:
        _clear_ai_status(request)


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
            # Multiple auth backends are configured (username/email + default),
            # so name the one to log in with explicitly.
            auth_login(
                request, user,
                backend="planner.auth_backends.EmailOrUsernameModelBackend",
            )
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
    projects = request.user.projects.filter(is_draft=False)
    drafts = request.user.projects.filter(is_draft=True)
    return render(
        request,
        "planner/dashboard/index.html",
        {
            "projects": projects,
            "drafts": drafts,
            "project_count": projects.count(),
            "document_count": Document.objects.filter(
                project__owner=request.user, project__is_draft=False
            ).count(),
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
            output = generators.sync_default_documents(project)
            _sync_ai_status(request, output.get("_claude_error", ""))
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
def project_new_chat(request):
    """Start a conversational project intake.

    Creates a *draft* project immediately and seeds the transcript with the
    assistant's opening question, then redirects to that project's chat so
    the conversation is persisted from the very first turn. Falls back to the
    classic interview form when no Anthropic key is configured.
    """

    if not chat.is_available(request.user):
        messages.info(
            request,
            "Chat intake needs an Anthropic API key — add one in Settings to "
            "use it. For now, here's the classic interview form.",
        )
        return HttpResponseRedirect(reverse("planner:project_new"))

    # Resume an existing untouched draft rather than piling up duplicates:
    # a draft with no user turns yet is effectively a fresh chat.
    for draft in request.user.projects.filter(is_draft=True).order_by("-id"):
        if not draft.chat_messages.filter(role=ChatMessage.ROLE_USER).exists():
            return HttpResponseRedirect(reverse("planner:project_chat", args=[draft.pk]))

    language = request.user.profile.default_language
    project = Project.objects.create(
        owner=request.user,
        name="Untitled project",
        language=language,
        is_draft=True,
    )
    ChatMessage.objects.create(
        project=project,
        role=ChatMessage.ROLE_ASSISTANT,
        content=chat.opening_message(language),
    )
    return HttpResponseRedirect(reverse("planner:project_chat", args=[project.pk]))


@login_required
def project_chat(request, pk):
    """Render the chat page for a draft project, resuming its transcript."""

    project = _owned_project(request, pk)
    if not project.is_draft:
        # Already finalised — nothing left to chat about.
        return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))
    return render(
        request,
        "planner/dashboard/chat.html",
        {
            "project": project,
            "chat_messages": project.chat_messages.filter(
                phase=ChatMessage.PHASE_INTAKE
            ),
        },
    )


@require_http_methods(["POST"])
@login_required
def project_chat_rename(request, pk):
    """Rename a draft project from the chat (JSON in, JSON out)."""

    project = _owned_project(request, pk)
    try:
        payload = json.loads(request.body or "{}")
        title = (payload.get("title") or "").strip()
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad_request"}, status=400)
    if not title:
        return JsonResponse({"error": "empty_title"}, status=400)

    project.name = title[:120]
    project.save(update_fields=["name"])
    return JsonResponse({"name": project.name})


@require_http_methods(["POST"])
@login_required
def project_chat_message(request, pk):
    """Handle one chat turn for a draft project (JSON in, JSON out).

    Every turn is persisted as a :class:`ChatMessage`. On the turn where
    Claude signals the brief is complete, the draft is finalised: its fields
    are filled in, documents are generated, and ``is_draft`` is cleared.
    """

    project = _owned_project(request, pk)
    if not project.is_draft:
        return JsonResponse({"error": "already_finalised"}, status=409)
    if not chat.is_available(request.user):
        return JsonResponse({"error": "chat_unavailable"}, status=409)

    try:
        payload = json.loads(request.body or "{}")
        message = (payload.get("message") or "").strip()
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad_request"}, status=400)
    if not message:
        return JsonResponse({"error": "empty_message"}, status=400)

    # Persist the user's turn, then build the history Claude sees.
    ChatMessage.objects.create(
        project=project, role=ChatMessage.ROLE_USER, content=message,
    )
    # Give the draft a readable title from the first thing the user says.
    if project.name in ("", "Untitled project"):
        project.name = chat.derive_title(message)
        project.save(update_fields=["name"])
    history = [
        {"role": m.role, "content": m.content}
        for m in project.chat_messages.filter(phase=ChatMessage.PHASE_INTAKE)
    ]

    language = project.language
    try:
        result = chat.next_turn(
            history,
            api_key=chat.api_key_for_user(request.user),
            language=language,
        )
    except Exception as exc:  # pragma: no cover - network/runtime safety net
        # The user's message is already saved; they can retry without retyping.
        category, detail = errors.classify(exc)
        _record_ai_status(request, category)
        return JsonResponse({"error": category, "detail": detail}, status=502)

    _clear_ai_status(request)
    ChatMessage.objects.create(
        project=project, role=ChatMessage.ROLE_ASSISTANT, content=result["reply"],
    )

    if not result["done"]:
        return JsonResponse({"reply": result["reply"], "done": False})

    # Brief complete — fill in the draft and generate its documents.
    kwargs = chat.build_project_kwargs(result["fields"])
    for field, value in kwargs.items():
        setattr(project, field, value)
    project.is_draft = False
    project.save()
    output = generators.sync_default_documents(project)
    _sync_ai_status(request, output.get("_claude_error", ""))

    messages.success(
        request,
        f"Project '{project.name}' created from chat and "
        f"{len(Document.DEFAULT_KINDS)} documents generated.",
    )
    return JsonResponse({
        "reply": result["reply"],
        "done": True,
        "redirect_url": reverse("planner:project_detail", args=[project.pk]),
    })


# ===========================================================================
# Project assistant (post-creation chat that edits info + documents)
# ===========================================================================
def _assistant_redirect(project, conversation=None):
    url = reverse("planner:project_assistant", args=[project.pk])
    if conversation is not None:
        url = f"{url}?c={conversation.pk}"
    return HttpResponseRedirect(url)


def _active_conversation(project, request) -> Conversation:
    """Resolve the conversation to show: ``?c=<id>``, else most recent, else new."""

    cid = request.GET.get("c")
    conv = None
    if cid:
        conv = project.conversations.filter(pk=cid).first()
    if conv is None:
        conv = project.conversations.first()  # ordered by -updated_at
    if conv is None:
        conv = project.conversations.create(title="General")
    return conv


@login_required
def project_assistant(request, pk):
    """Chat with an assistant that knows the whole project and its documents.

    Assistant chat is organised into named conversations (threads). The active
    one is chosen via ``?c=<id>`` (default: most recent).
    """

    project = _owned_project(request, pk)
    if project.is_draft:
        return HttpResponseRedirect(reverse("planner:project_chat", args=[project.pk]))
    if not chat.is_available(request.user):
        messages.info(
            request,
            "The project assistant needs an Anthropic API key — add one in Settings.",
        )
        return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))

    conversation = _active_conversation(project, request)
    if not conversation.messages.exists():
        ChatMessage.objects.create(
            project=project,
            conversation=conversation,
            phase=ChatMessage.PHASE_ASSISTANT,
            role=ChatMessage.ROLE_ASSISTANT,
            content=chat.assistant_opening_message(project.language),
        )
    return render(
        request,
        "planner/dashboard/assistant.html",
        {
            "project": project,
            "conversations": project.conversations.all(),
            "active_conversation": conversation,
            "chat_messages": conversation.messages.all(),
        },
    )


@require_http_methods(["POST"])
@login_required
def conversation_new(request, pk):
    project = _owned_project(request, pk)
    conversation = project.conversations.create(title=Conversation.DEFAULT_TITLE)
    return _assistant_redirect(project, conversation)


@require_http_methods(["POST"])
@login_required
def conversation_rename(request, pk, conv_pk):
    project = _owned_project(request, pk)
    conversation = get_object_or_404(Conversation, pk=conv_pk, project=project)
    title = (request.POST.get("title") or "").strip()
    if title:
        conversation.title = title[:200]
        conversation.save(update_fields=["title", "updated_at"])
    return _assistant_redirect(project, conversation)


@require_http_methods(["POST"])
@login_required
def conversation_delete(request, pk, conv_pk):
    project = _owned_project(request, pk)
    conversation = get_object_or_404(Conversation, pk=conv_pk, project=project)
    conversation.delete()
    messages.success(request, "Conversation deleted.")
    return _assistant_redirect(project)


@require_http_methods(["POST"])
@login_required
def project_assistant_message(request, pk):
    """One project-assistant turn (JSON in, JSON out).

    The reply may carry ``proposals`` — pending changes the user confirms via
    :func:`project_assistant_apply`.
    """

    project = _owned_project(request, pk)
    if project.is_draft:
        return JsonResponse({"error": "draft"}, status=409)
    if not chat.is_available(request.user):
        return JsonResponse({"error": "chat_unavailable"}, status=409)

    try:
        payload = json.loads(request.body or "{}")
        message = (payload.get("message") or "").strip()
        conversation_id = payload.get("conversation_id")
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad_request"}, status=400)
    if not message:
        return JsonResponse({"error": "empty_message"}, status=400)

    conversation = project.conversations.filter(pk=conversation_id).first()
    if conversation is None:
        return JsonResponse({"error": "no_conversation"}, status=404)

    ChatMessage.objects.create(
        project=project, conversation=conversation,
        phase=ChatMessage.PHASE_ASSISTANT,
        role=ChatMessage.ROLE_USER, content=message,
    )
    # Name an untitled thread from its first user message (e.g. "diagrams").
    if conversation.title == Conversation.DEFAULT_TITLE:
        conversation.title = chat.derive_title(message)
    history = [
        {"role": m.role, "content": m.content}
        for m in conversation.messages.all()
    ]
    context = chat.build_project_context(project)
    try:
        result = chat.assistant_turn(
            history, context,
            api_key=chat.api_key_for_user(request.user),
            language=project.language,
        )
    except Exception as exc:  # pragma: no cover - network/runtime safety net
        category, detail = errors.classify(exc)
        _record_ai_status(request, category)
        return JsonResponse({"error": category, "detail": detail}, status=502)

    _clear_ai_status(request)
    proposals = result["proposals"]
    msg = ChatMessage.objects.create(
        project=project, conversation=conversation,
        phase=ChatMessage.PHASE_ASSISTANT,
        role=ChatMessage.ROLE_ASSISTANT, content=result["reply"],
        proposals=proposals,
        proposal_status=(
            ChatMessage.PROPOSAL_PENDING if proposals else ChatMessage.PROPOSAL_NONE
        ),
    )
    # Persist any new auto-title and bump updated_at (floats to top of list).
    conversation.save(update_fields=["title", "updated_at"])
    return JsonResponse({
        "reply": result["reply"],
        "message_id": msg.pk,
        "has_proposal": bool(proposals),
        "proposals": _proposals_summary(proposals),
        "conversation_title": conversation.title,
    })


@require_http_methods(["POST"])
@login_required
def project_assistant_apply(request, pk):
    """Apply or discard the pending proposal on an assistant message."""

    project = _owned_project(request, pk)
    try:
        payload = json.loads(request.body or "{}")
        message_id = payload.get("message_id")
        action = payload.get("action")
    except (ValueError, TypeError):
        return JsonResponse({"error": "bad_request"}, status=400)

    msg = get_object_or_404(
        ChatMessage, pk=message_id, project=project,
        phase=ChatMessage.PHASE_ASSISTANT,
    )
    if msg.proposal_status != ChatMessage.PROPOSAL_PENDING:
        return JsonResponse({"error": "not_pending"}, status=409)

    if action == "discard":
        msg.proposal_status = ChatMessage.PROPOSAL_DISCARDED
        msg.save(update_fields=["proposal_status"])
        return JsonResponse({"status": "discarded"})
    if action != "apply":
        return JsonResponse({"error": "bad_action"}, status=400)

    applied = _apply_changes(project, msg.proposals)
    msg.proposal_status = ChatMessage.PROPOSAL_APPLIED
    msg.save(update_fields=["proposal_status"])
    return JsonResponse({"status": "applied", "applied": applied})


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
    if project.is_draft:
        # Unfinished chat — resume it instead of showing an empty folder.
        return HttpResponseRedirect(reverse("planner:project_chat", args=[project.pk]))
    docs = list(project.documents.all())
    # Group by category, preserving the display order from CATEGORY_CHOICES.
    by_category = {value: [] for value, _ in Document.CATEGORY_CHOICES}
    for d in docs:
        by_category.setdefault(d.category, []).append(d)
    category_groups = [
        {"label": label, "docs": by_category.get(value, [])}
        for value, label in Document.CATEGORY_CHOICES
        if by_category.get(value)
    ]
    has_custom = any(d.kind == Document.KIND_CUSTOM for d in docs)
    has_unclassified = any(
        d.kind == Document.KIND_CUSTOM and d.category == Document.CATEGORY_OTHER
        for d in docs
    )
    return render(
        request,
        "planner/dashboard/project_detail.html",
        {
            "project": project,
            "category_groups": category_groups,
            "doc_count": len(docs),
            "has_custom": has_custom,
            "has_unclassified": has_unclassified,
        },
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
    result = generators.regenerate(document)
    document.body = result["body"]
    document.is_generated = True
    document.save()
    _sync_ai_status(request, result.get("_claude_error", ""))
    if result.get("_claude_error"):
        messages.warning(request, f"'{document.title}' regenerated from a template — AI is unavailable.")
    else:
        messages.success(request, f"'{document.title}' regenerated.")
    return HttpResponseRedirect(
        reverse("planner:document_detail", args=[project.pk, document.pk])
    )


@require_http_methods(["POST"])
@login_required
def document_reclassify(request, pk, doc_pk):
    """Re-run AI classification on a single custom document."""

    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    if document.kind != Document.KIND_CUSTOM:
        messages.error(
            request, "Only custom documents can be reclassified; built-in "
            "documents have a fixed category."
        )
        return HttpResponseRedirect(
            reverse("planner:document_detail", args=[project.pk, document.pk])
        )
    result = generators.classify_document(
        project, title=document.title, body=document.body
    )
    document.category = result["category"]
    document.save(update_fields=["category"])
    if result.get("_claude_error"):
        err_cat, detail = errors.classify(result["_claude_error"])
        _record_ai_status(request, err_cat)
    else:
        _clear_ai_status(request)
    messages.success(
        request,
        f"Classified as “{document.get_category_display()}” via {result['engine']}.",
    )
    return HttpResponseRedirect(
        reverse("planner:document_detail", args=[project.pk, document.pk])
    )


@require_http_methods(["POST"])
@login_required
def project_classify_all(request, pk):
    """Classify every uncategorized (Other) custom document in one pass."""

    project = _owned_project(request, pk)
    pending = project.documents.filter(
        kind=Document.KIND_CUSTOM, category=Document.CATEGORY_OTHER
    )
    moved = 0
    last_error = ""
    for document in pending:
        result = generators.classify_document(
            project, title=document.title, body=document.body
        )
        if result.get("_claude_error"):
            last_error = result["_claude_error"]
        if result["category"] != document.category:
            document.category = result["category"]
            document.save(update_fields=["category"])
            moved += 1
    if last_error:
        err_cat, _ = errors.classify(last_error)
        _record_ai_status(request, err_cat)
    else:
        _clear_ai_status(request)
    if moved:
        messages.success(request, f"Classified {moved} document(s) into categories.")
    else:
        messages.info(request, "No uncategorized custom documents to classify.")
    return HttpResponseRedirect(reverse("planner:project_detail", args=[project.pk]))


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
            # Auto-classify the new custom doc into a spec-pack category
            # (Claude when available, keyword fallback otherwise).
            classified = generators.classify_document(
                project, title=title, body=result["body"]
            )
            document = Document.objects.create(
                project=project,
                kind=Document.KIND_CUSTOM,
                category=classified["category"],
                title=title,
                body=result["body"],
                prompt=prompt,
                is_generated=bool(prompt),
            )
            if result.get("_claude_error"):
                category, detail = errors.classify(result["_claude_error"])
                _record_ai_status(request, category)
                messages.warning(
                    request,
                    f"Created a starter document instead — {detail}",
                )
            else:
                _clear_ai_status(request)
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


@require_http_methods(["GET"])
@login_required
def document_drawio(request, pk, doc_pk):
    """Download a diagram document as an editable draw.io (.drawio) file.

    Generated deterministically from the project's fields (same source as the
    stored Mermaid), so it always reflects the current answers.
    """

    from .generators import drawio

    project = _owned_project(request, pk)
    document = get_object_or_404(Document, pk=doc_pk, project=project)
    xml = drawio.for_kind(document.kind, project)
    if xml is None:
        raise Http404("This document is not a diagram.")
    response = HttpResponse(xml, content_type="application/xml; charset=utf-8")
    filename = f"{project.pk}_{document.kind}_{document.pk}.drawio"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ===========================================================================
# Notes
# ===========================================================================
@login_required
def project_notes(request, pk):
    project = _owned_project(request, pk)
    if request.method == "POST":
        form = NoteForm(request.POST)
        if form.is_valid():
            note = form.save(commit=False)
            note.project = project
            note.save()
            messages.success(request, "Note added.")
            return HttpResponseRedirect(reverse("planner:project_notes", args=[project.pk]))
    else:
        form = NoteForm()
    return render(
        request,
        "planner/dashboard/notes.html",
        {"project": project, "form": form, "notes": project.notes.all()},
    )


@login_required
def note_edit(request, pk, note_pk):
    project = _owned_project(request, pk)
    note = get_object_or_404(Note, pk=note_pk, project=project)
    if request.method == "POST":
        form = NoteForm(request.POST, instance=note)
        if form.is_valid():
            form.save()
            messages.success(request, "Note updated.")
            return HttpResponseRedirect(reverse("planner:project_notes", args=[project.pk]))
    else:
        form = NoteForm(instance=note)
    return render(
        request,
        "planner/dashboard/note_edit.html",
        {"project": project, "form": form, "note": note},
    )


@require_http_methods(["POST"])
@login_required
def note_delete(request, pk, note_pk):
    project = _owned_project(request, pk)
    note = get_object_or_404(Note, pk=note_pk, project=project)
    note.delete()
    messages.success(request, "Note deleted.")
    return HttpResponseRedirect(reverse("planner:project_notes", args=[project.pk]))


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


# --- Project assistant proposals -------------------------------------------
_VALID_DOC_KINDS = dict(Document.KIND_CHOICES)

# Project fields that deterministically feed each diagram (mirrors the field
# reads in planner/generators/diagrams.py). When the assistant changes one of
# these, the affected diagram documents are regenerated from the new fields —
# diagrams are never hand-written.
_DIAGRAM_FIELD_MAP = {
    "personas": (Document.KIND_USE_CASE_DIAGRAM,),
    "features": (Document.KIND_USE_CASE_DIAGRAM, Document.KIND_FLOW_DIAGRAM),
    "entities": (Document.KIND_ERD_DIAGRAM,),
    "success_metrics": (Document.KIND_FLOW_DIAGRAM,),
    "name": (Document.KIND_USE_CASE_DIAGRAM, Document.KIND_FLOW_DIAGRAM),
}


def _regenerate_diagrams(project: Project, kinds) -> list[str]:
    """Refresh existing diagram docs whose source fields changed.

    Diagrams are a deterministic projection of project fields, so we rebuild
    them via :func:`generators.regenerate` rather than store hand-written
    bodies. Only regenerates diagram docs that exist (drafts may not have any).
    """

    lines: list[str] = []
    for doc in project.documents.filter(kind__in=set(kinds)):
        doc.body = generators.regenerate(doc)["body"]
        doc.is_generated = True
        doc.save(update_fields=["body", "is_generated", "updated_at"])
        lines.append(f"Regenerated diagram “{doc.title}”")
    return lines


def _proposals_summary(proposals: list) -> list[dict]:
    """Short, display-friendly description of each proposed change."""

    out = []
    for change in proposals:
        if change.get("type") == "document":
            label = "Document · " + (change.get("title") or change.get("kind") or "document")
        else:
            label = "Field · " + str(change.get("field", "?"))
        out.append({"label": label, "note": change.get("note", "")})
    return out


def _apply_changes(project: Project, proposals: list) -> list[str]:
    """Apply each proposed change; return human-readable lines of what changed.

    Field changes that feed diagrams trigger a single deterministic
    regeneration of the affected diagram documents at the end. The whole batch
    is atomic so field saves and diagram rebuilds commit together.
    """

    applied: list[str] = []
    dirty_diagram_kinds: set[str] = set()
    with transaction.atomic():
        for change in proposals:
            ctype = change.get("type")
            if ctype == "document":
                line = _apply_document_change(project, change)
            elif ctype == "field":
                line, field = _apply_field_change(project, change)
                if line and field in _DIAGRAM_FIELD_MAP:
                    dirty_diagram_kinds.update(_DIAGRAM_FIELD_MAP[field])
            else:
                line = None
            if line:
                applied.append(line)
        applied.extend(_regenerate_diagrams(project, dirty_diagram_kinds))
    return applied


def _apply_document_change(project: Project, change: dict) -> str | None:
    body = change.get("body")
    if not isinstance(body, str):
        return None

    doc = None
    doc_id = change.get("document_id")
    if doc_id:
        doc = Document.objects.filter(pk=doc_id, project=project).first()

    kind = change.get("kind")

    # Diagrams are a deterministic projection of project fields — never store a
    # hand-written diagram body. Discard the proposed body and regenerate from
    # the current fields instead (no-op for a draft without the diagram doc).
    target_kind = doc.kind if doc is not None else kind
    if target_kind in Document.DIAGRAM_KINDS:
        if doc is None:
            doc = Document.objects.filter(project=project, kind=target_kind).first()
        if doc is None:
            return None
        doc.body = generators.regenerate(doc)["body"]
        doc.is_generated = True
        doc.save(update_fields=["body", "is_generated", "updated_at"])
        return f"Regenerated diagram “{doc.title}” from project fields"

    if doc is None and kind in Document.DEFAULT_KINDS:
        # Default kinds are unique per project — update in place if present.
        doc = Document.objects.filter(project=project, kind=kind).first()

    if doc is None:
        doc = Document(
            project=project,
            kind=kind if kind in _VALID_DOC_KINDS else Document.KIND_CUSTOM,
        )

    title = (change.get("title") or "").strip()
    if title:
        doc.title = title
    elif not doc.title:
        doc.title = (kind or "Document").replace("_", " ").title()
    doc.body = body
    doc.is_generated = False  # assistant-edited; treat as hand-authored
    doc.save()
    return f"Updated document “{doc.title}”"


def _apply_field_change(project: Project, change: dict) -> tuple[str | None, str | None]:
    """Apply one field change. Returns (human line, field name) — the field
    name lets the caller know which diagrams to regenerate."""

    field = change.get("field")
    ok, value = chat.coerce_field(field, change.get("value"))
    if not ok:
        return None, None
    setattr(project, field, value)
    project.save()
    return f"Updated field “{field}”", field
