"""Python version compatibility shims.

Provides ``StrEnum`` for Python < 3.11 so that the codebase can be imported
in CI/dev environments that haven't upgraded yet.  On Python 3.11+ (and the
project's target 3.14) this is just ``enum.StrEnum``.
"""
from __future__ import annotations

import sys
import enum

if sys.version_info >= (3, 11):
    StrEnum = enum.StrEnum
else:
    # Fallback for Python 3.10 and earlier.
    class StrEnum(str, enum.Enum):
        """Backport of :class:`enum.StrEnum` for Python < 3.11."""

        @staticmethod
        def _generate_next_value_(name, start, count, last_values):  # noqa: D401
            return name.lower()

        def __str__(self) -> str:
            return self.value


__all__ = ["StrEnum"]
