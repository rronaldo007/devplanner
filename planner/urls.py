from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "planner"

urlpatterns = [
    # --- Public ---------------------------------------------------------
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),

    # --- Auth -----------------------------------------------------------
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="planner/auth/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(http_method_names=["get", "post", "options"]),
        name="logout",
    ),
    path("register/", views.register, name="register"),

    # --- Dashboard ------------------------------------------------------
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("projects/new/", views.project_new, name="project_new"),
    path("projects/new/chat/", views.project_new_chat, name="project_new_chat"),
    path("projects/<int:pk>/", views.project_detail, name="project_detail"),
    path("projects/<int:pk>/chat/", views.project_chat, name="project_chat"),
    path(
        "projects/<int:pk>/chat/message/",
        views.project_chat_message,
        name="project_chat_message",
    ),
    path(
        "projects/<int:pk>/chat/rename/",
        views.project_chat_rename,
        name="project_chat_rename",
    ),
    path("projects/<int:pk>/assistant/", views.project_assistant, name="project_assistant"),
    path(
        "projects/<int:pk>/assistant/message/",
        views.project_assistant_message,
        name="project_assistant_message",
    ),
    path(
        "projects/<int:pk>/assistant/apply/",
        views.project_assistant_apply,
        name="project_assistant_apply",
    ),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),

    # --- Documents ------------------------------------------------------
    path("projects/<int:pk>/documents/new/", views.document_new, name="document_new"),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/",
        views.document_detail,
        name="document_detail",
    ),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/edit/",
        views.document_edit,
        name="document_edit",
    ),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/regenerate/",
        views.document_regenerate,
        name="document_regenerate",
    ),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/delete/",
        views.document_delete,
        name="document_delete",
    ),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/download/",
        views.document_download,
        name="document_download",
    ),
    path(
        "projects/<int:pk>/documents/<int:doc_pk>/drawio/",
        views.document_drawio,
        name="document_drawio",
    ),

    # --- Notes ----------------------------------------------------------
    path("projects/<int:pk>/notes/", views.project_notes, name="project_notes"),
    path(
        "projects/<int:pk>/notes/<int:note_pk>/edit/",
        views.note_edit,
        name="note_edit",
    ),
    path(
        "projects/<int:pk>/notes/<int:note_pk>/delete/",
        views.note_delete,
        name="note_delete",
    ),
]
