"""Document generation for a :class:`planner.models.Project`.

The implementation lives in submodules; this package re-exports the public
entrypoints:

* :func:`generate_all` — produce the six built-in documents (three planning
  docs + three Mermaid diagrams) for a project.
* :func:`generate_custom` — produce a single custom document from a
  user-supplied prompt using the project as context.
* :func:`regenerate` — refresh the body of an existing :class:`Document`.
* :func:`sync_default_documents` — persist / refresh all default docs as
  ``Document`` rows on a project.

Engine selection (templates vs. Claude) is handled in
:mod:`planner.generators.engine`.
"""

from __future__ import annotations

from .engine import (
    DEFAULT_TITLES,
    generate_all,
    generate_custom,
    regenerate,
    sync_default_documents,
)

__all__ = [
    "DEFAULT_TITLES",
    "generate_all",
    "generate_custom",
    "regenerate",
    "sync_default_documents",
]
