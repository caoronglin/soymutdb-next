"""Python-side access to the compiled Rust bio-core wheel.

The wheel is a private compiled extension, not an optional convenience:
when it is missing, every sequence tool must fail closed with a structured
503 instead of returning a silently-empty or Python-faked result.

The Python layer remains the sole owner of authorization, release/assembly
resolution, request-size limits and error shaping.  Rust receives only
validated bytes/strings.
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from typing import Any

from ..core.exceptions import ServiceUnavailableError, ValidationError

_MODULE_NAME = "soymutdb_bio_core"


def _engine_setting() -> str:
    from ..core.config import get_settings

    return get_settings().bio_engine


@dataclass(frozen=True)
class BioCoreStatus:
    available: bool
    engine: str | None
    engine_version: str | None
    reason: str | None = None


def _load() -> Any:
    if importlib.util.find_spec(_MODULE_NAME) is None:
        return None
    try:
        return importlib.import_module(_MODULE_NAME)
    except ImportError:
        return None


_UNSET = object()
_module: Any = _UNSET


def status() -> BioCoreStatus:
    """Report engine availability without importing at module import time."""
    global _module
    if _engine_setting() == "python":
        return BioCoreStatus(
            available=False,
            engine=None,
            engine_version=None,
            reason=(
                "SOYMUTDB_BIO_ENGINE=python has no equivalent implementation; "
                "no silent fallback"
            ),
        )
    if _module is _UNSET:
        _module = _load()
    if _module is None:
        return BioCoreStatus(
            available=False,
            engine=None,
            engine_version=None,
            reason="compiled bio-core wheel is not installed",
        )
    cap = _module.capabilities()
    return BioCoreStatus(
        available=True,
        engine=cap["engine"],
        engine_version=cap["engine_version"],
    )


def require() -> Any:
    """Return the extension, or raise a structured 503 (never a fake result)."""
    st = status()
    if not st.available:
        raise ServiceUnavailableError(
            "sequence engine unavailable",
            details={"reason": st.reason},
        )
    return _module


def translate_error(exc: Exception) -> Exception:
    """Map a BioCoreException to the repository's unified error envelope.

    ``BioCoreException.args[0]`` is a stable machine-readable code; the second
    element is a human message that never contains sequence content or paths.
    """
    code = "validation_error"
    message = "invalid sequence tool request"
    args = getattr(exc, "args", ())
    if args and isinstance(args[0], str):
        code = args[0]
    if len(args) > 1 and isinstance(args[1], str):
        message = args[1]
    if code in {"SEQUENCE_TOO_LONG", "BUDGET_EXCEEDED"}:
        return ValidationError(message, details={"code": code})
    return ValidationError(message, details={"code": code})
