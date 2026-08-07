"""Worker environment access with canonical ``SOYMUTDB_`` names."""

from __future__ import annotations

import os
from typing import TypeVar

_T = TypeVar("_T")


def get_setting(name: str, default: _T) -> str | _T:
    """Read a canonical variable, with a legacy fallback for production."""
    return os.getenv(f"SOYMUTDB_{name}", os.getenv(name, default))


__all__ = ["get_setting"]
