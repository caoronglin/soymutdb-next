"""Re-export of :class:`enum.StrEnum`.

This module used to carry a backport of ``StrEnum`` for Python < 3.11. That
branch is dead code: ``apps/api/pyproject.toml`` pins
``requires-python = ">=3.14"``, and CI pins ``python:3.14``. Ruff's UP036 flagged
the version guard for exactly this reason, and UP042 flagged the backport class
itself, which had to inherit ``str`` and ``enum.Enum`` to imitate the standard
one.

The import path is kept because eleven schema modules import ``StrEnum`` from
here, and deleting the module would churn every one of them for no behavioural
gain. A future pass may collapse those imports to ``from enum import StrEnum``
and remove this file; until then it is a single, honest alias.
"""
from __future__ import annotations

from enum import StrEnum

__all__ = ["StrEnum"]
