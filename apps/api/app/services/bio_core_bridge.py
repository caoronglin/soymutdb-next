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


#: Every code ``packages/bio-core/src/errors.rs`` raises, with the sentence that
#: file publishes for it.  ``scripts/check_bio_core_error_codes.py`` reads both
#: sources and fails the build when a code is missing, misspelled, or carries a
#: different sentence -- this table is a mirror, not a second truth.
KERNEL_ERROR_MESSAGES = {
    "EMPTY_SEQUENCE": "empty sequence",
    "INVALID_CHARACTER": "invalid character for the selected alphabet",
    "UNSUPPORTED_ALPHABET": "unsupported alphabet for this operation",
    "SEQUENCE_TOO_LONG": "sequence exceeds the configured size limit",
    "BUDGET_EXCEEDED": "input exceeds the configured budget",
    "INVALID_INTERVAL": "invalid coordinate: start must be >= 0 and stop must be > start",
    "COORDINATE_OVERFLOW": "integer overflow while computing coordinates",
    "UNSUPPORTED_PARAMETER": "unsupported parameter value",
    "UNKNOWN_GENETIC_CODE": "genetic code is not implemented",
    "INVALID_RECORD": "invalid FASTA/FASTQ record",
}

#: Status every kernel code is reported as.  A rejected input is a 422 whichever
#: code fired; the *code* is what tells the caller which input to change.
_FALLBACK_CODE = "validation_error"
_FALLBACK_MESSAGE = "invalid sequence tool request"


def translate_error(exc: Exception) -> Exception:
    """Map a kernel failure to the repository's unified error envelope.

    ``BioCoreException(args=(CODE, sentence))`` is the only trusted shape: the
    kernel raises exactly that (``bindings.rs`` ``raise()`` builds the pair, and
    the two direct constructions do too).  Anything else -- a ``TypeError`` from
    the FFI, a plain ``Exception("timeout")`` -- has no machine code, so it must
    not invent one: publishing ``details.code == "timeout"`` would hand clients a
    code the caller-facing vocabulary has never contained.

    The sentence comes from :data:`KERNEL_ERROR_MESSAGES`, i.e. from the same
    file that defines the codes.  The kernel's own second element is deliberately
    not forwarded: it is an implementation detail of the Rust error type, and
    unifying it here is what keeps one code = one sentence.
    """
    args = getattr(exc, "args", ())
    if (
        len(args) == 2
        and isinstance(args[0], str)
        and isinstance(args[1], str)
        and args[0] in KERNEL_ERROR_MESSAGES
    ):
        message = KERNEL_ERROR_MESSAGES[args[0]]
        return ValidationError(message, details={"code": args[0]})
    return ValidationError(_FALLBACK_MESSAGE, details={"code": _FALLBACK_CODE})


__all__ = [
    "KERNEL_ERROR_MESSAGES",
    "BioCoreStatus",
    "require",
    "status",
    "translate_error",
]
