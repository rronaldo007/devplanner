from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from . import views
from .forms import EmailOrUsernameLoginForm

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
            authentication_form=EmailOrUsernameLoginForm,
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

    # --- Password reset (Django built-in views, app-styled templates) ---
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="planner/auth/password_reset_form.html",
            email_template_name="planner/auth/password_reset_email.html",
            subject_template_name="planner/auth/password_reset_subject.txt",
            success_url=reverse_lazy("planner:password_reset_done"),
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="planner/auth/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="planner/auth/password_reset_confirm.html",
            success_url=reverse_lazy("planner:password_reset_complete"),
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="planner/auth/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),

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
    path(
        "projects/<int:pk>/conversations/new/",
        views.conversation_new,
        name="conversation_new",
    ),
    path(
        "projects/<int:pk>/conversations/<int:conv_pk>/rename/",
        views.conversation_rename,
        name="conversation_rename",
    ),
    path(
        "projects/<int:pk>/conversations/<int:conv_pk>/delete/",
        views.conversation_delete,
        name="conversation_delete",
    ),
    path("projects/<int:pk>/edit/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),
    path(
        "projects/<int:pk>/classify-all/",
        views.project_classify_all,
        name="project_classify_all",
    ),

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
        "projects/<int:pk>/documents/<int:doc_pk>/reclassify/",
        views.document_reclassify,
        name="document_reclassify",
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
