"""Authentication backends for the planner app."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailOrUsernameModelBackend(ModelBackend):
    """Authenticate with either a username or an email address.

    Mirrors Django's :class:`ModelBackend` but, when the supplied identifier
    isn't a matching username, falls back to a case-insensitive email lookup.
    The password is always verified, and ``user_can_authenticate`` still gates
    inactive accounts.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(User.USERNAME_FIELD)
        if username is None or password is None:
            return None

        try:
            user = User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            # Not a username — try email. Ambiguous (duplicate) emails are
            # treated as a failed login rather than guessing an account.
            matches = list(User.objects.filter(email__iexact=username)[:2])
            if len(matches) != 1:
                # Run the default hasher once to keep timing consistent and
                # mitigate user enumeration via response time.
                User().set_password(password)
                return None
            user = matches[0]

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
