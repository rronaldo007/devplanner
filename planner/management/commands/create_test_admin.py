"""Create (or reset) a test admin superuser for the Unfold admin.

Idempotent: safe to run repeatedly (e.g. from the dev refresh script). Reads
credentials from the environment, falling back to dev-only defaults.

    python manage.py create_test_admin

Env overrides: DJANGO_ADMIN_USERNAME, DJANGO_ADMIN_EMAIL, DJANGO_ADMIN_PASSWORD.
"""

from __future__ import annotations

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Create or reset a test admin superuser (dev only)."

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_ADMIN_USERNAME", "admin")
        email = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@example.com")
        password = os.environ.get("DJANGO_ADMIN_PASSWORD", "admin12345")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={"email": email},
        )
        user.email = email
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        user.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} test admin '{username}' (password: {password}). "
                "Log in at /admin/."
            )
        )
