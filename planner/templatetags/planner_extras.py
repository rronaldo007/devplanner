"""Custom template filters used by planner templates."""

from django import template

register = template.Library()


@register.filter(name="dict_get")
def dict_get(d, key):
    """Look up ``key`` in dict-like ``d``; return empty string if missing."""

    try:
        return d.get(key, "")
    except AttributeError:
        return ""


@register.filter(name="getfield")
def getfield(form, name):
    """Return a bound field from ``form`` by ``name``.

    Used by the interview template to iterate over ``form.fieldsets`` (which
    lists field names) and render each field.
    """

    return form[name]


@register.filter(name="active_projects")
def active_projects(user):
    """Non-draft projects for ``user`` (drafts are hidden from listings)."""

    return user.projects.filter(is_draft=False)
