"""Django settings for devplanner.

Production-ready: anything sensitive or environment-specific is read from
environment variables. Sensible defaults keep the standard ``manage.py
runserver`` workflow working out of the box.
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.urls import reverse_lazy

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _env_bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str]) -> list[str]:
    v = os.environ.get(name)
    if not v:
        return default
    return [item.strip() for item in v.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Secure by default: a deploy that forgets to set these fails loudly or stays
# locked down, rather than silently running insecure. For local development,
# set DJANGO_DEBUG=1 (the dev scripts and .env.example already do).
DEBUG = _env_bool("DJANGO_DEBUG", False)

# SECRET_KEY must be provided in production. The insecure fallback is only
# allowed when DEBUG is on, so a misconfigured production deploy raises instead
# of running with this known, public key.
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "django-insecure-82f6)rk(xhz32uwnq9yj(3!#w#0z18jq9c+_vtfo7i20tn8eic"
    else:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Set DJANGO_DEBUG=1 for local development."
        )

# Never default to "*". Local development falls back to loopback hosts; any
# real deployment must list its hostnames in DJANGO_ALLOWED_HOSTS.
ALLOWED_HOSTS = _env_list(
    "DJANGO_ALLOWED_HOSTS",
    ["localhost", "127.0.0.1", "[::1]"] if DEBUG else [],
)

# Comma-separated list of trusted origins for CSRF (e.g. https://devplanner.example.com).
CSRF_TRUSTED_ORIGINS = _env_list("DJANGO_CSRF_TRUSTED_ORIGINS", [])


# ---------------------------------------------------------------------------
# Apps & middleware
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    # Unfold must come before django.contrib.admin to override its templates.
    "unfold",
    "unfold.contrib.filters",
    "unfold.contrib.forms",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "planner",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise serves static files in production without a separate proxy.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "devplanner.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "planner.context_processors.ai_status",
            ],
        },
    },
]

WSGI_APPLICATION = "devplanner.wsgi.application"


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
# DATABASE_URL takes precedence (e.g. postgres://user:pass@host:5432/db).
# Otherwise SQLite is used with the file path under DJANGO_SQLITE_PATH
# (defaults to db.sqlite3 in the project root).
_db_url = os.environ.get("DATABASE_URL", "").strip()
if _db_url:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(_db_url, conn_max_age=600)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get(
                "DJANGO_SQLITE_PATH", str(BASE_DIR / "db.sqlite3")
            ),
        }
    }


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ---------------------------------------------------------------------------
# Internationalization
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Compressed + hashed static files via WhiteNoise in production (requires
# `collectstatic`). In DEBUG, use plain storage so runserver/tests resolve
# static URLs (e.g. Unfold admin assets) without a built manifest.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
LOGIN_URL = "planner:login"
LOGIN_REDIRECT_URL = "planner:dashboard"
LOGOUT_REDIRECT_URL = "planner:home"


# ---------------------------------------------------------------------------
# Email (used by the password-reset flow)
# ---------------------------------------------------------------------------
# In DEBUG, print emails to the console (no SMTP needed for local dev). In
# production, configure SMTP via env. Reset links expire after this many
# seconds (Django default is 3 days).
if DEBUG:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = os.environ.get(
        "DJANGO_EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend"
    )
    EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
    EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = _env_bool("DJANGO_EMAIL_USE_TLS", True)

DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL", "DevPlanner <no-reply@devplanner.local>"
)
PASSWORD_RESET_TIMEOUT = int(os.environ.get("DJANGO_PASSWORD_RESET_TIMEOUT", str(60 * 60 * 24 * 3)))


# ---------------------------------------------------------------------------
# Production hardening (only when DEBUG is off)
# ---------------------------------------------------------------------------
if not DEBUG:
    SESSION_COOKIE_SECURE = _env_bool("DJANGO_SECURE_COOKIES", True)
    CSRF_COOKIE_SECURE = _env_bool("DJANGO_SECURE_COOKIES", True)
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_HSTS_SECONDS", "0"))
    if SECURE_HSTS_SECONDS:
        SECURE_HSTS_INCLUDE_SUBDOMAINS = True
        SECURE_HSTS_PRELOAD = True


# ---------------------------------------------------------------------------
# Admin theme (django-unfold)
# ---------------------------------------------------------------------------
# Indigo primary palette to match the app's dashboard accent (Tailwind indigo).
UNFOLD = {
    "SITE_TITLE": "DevPlanner Admin",
    "SITE_HEADER": "DevPlanner",
    "SITE_SUBHEADER": "Project planning workspace",
    "SITE_URL": "/",
    "SHOW_HISTORY": True,
    "SHOW_VIEW_ON_SITE": True,
    "THEME": None,  # let users toggle light / dark
    "BORDER_RADIUS": "8px",
    "COLORS": {
        "primary": {
            "50": "238 242 255",
            "100": "224 231 255",
            "200": "199 210 254",
            "300": "165 180 252",
            "400": "129 140 248",
            "500": "99 102 241",
            "600": "79 70 229",
            "700": "67 56 202",
            "800": "55 48 163",
            "900": "49 46 129",
            "950": "30 27 75",
        },
    },
    "SIDEBAR": {
        "show_search": True,
        "show_all_applications": True,
        "navigation": [
            {
                "title": "Planner",
                "separator": True,
                "collapsible": False,
                "items": [
                    {
                        "title": "Projects",
                        "icon": "folder",
                        "link": reverse_lazy("admin:planner_project_changelist"),
                    },
                    {
                        "title": "Documents",
                        "icon": "description",
                        "link": reverse_lazy("admin:planner_document_changelist"),
                    },
                    {
                        "title": "Chat messages",
                        "icon": "forum",
                        "link": reverse_lazy("admin:planner_chatmessage_changelist"),
                    },
                    {
                        "title": "User profiles",
                        "icon": "badge",
                        "link": reverse_lazy("admin:planner_userprofile_changelist"),
                    },
                ],
            },
            {
                "title": "Accounts",
                "separator": True,
                "collapsible": True,
                "items": [
                    {
                        "title": "Users",
                        "icon": "group",
                        "link": reverse_lazy("admin:auth_user_changelist"),
                    },
                    {
                        "title": "Groups",
                        "icon": "shield_person",
                        "link": reverse_lazy("admin:auth_group_changelist"),
                    },
                ],
            },
        ],
    },
}
