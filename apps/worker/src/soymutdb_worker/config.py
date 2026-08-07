"""Worker environment access with canonical ``SOYMUTDB_`` names."""

from __future__ import annotations

import os


def get_setting[T](name: str, default: T) -> str | T:
    """Read a canonical variable, with a legacy fallback for production."""
    return os.getenv(f"SOYMUTDB_{name}", os.getenv(name, default))


__all__ = ["get_setting"]
