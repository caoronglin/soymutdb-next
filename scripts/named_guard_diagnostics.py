"""Render a non-empty failure cause for the contracts layer's stdlib runners.

Several guards run their own ``test_*`` functions in a loop (no pytest), catch
``AssertionError`` and print one ``FAIL:`` line per case. Two shapes of
assertion produce an *empty* cause:

* ``assert failures(...) == []`` -- the failure list is never attached to the
  exception, so ``str(exc)`` is ``''``;
* a bare setup assertion (``assert a in generated``, ``assert count == 1``)
  whose precondition stops holding because the committed bytes drifted.

``AssertionError`` is truthy even with an empty message, so the usual
``f"...: {exc or 'assertion failed'}"`` fallback is dead code: the operator
sees ``FAIL: test_name:`` and nothing after the colon. A red gate that cannot
say what stopped holding is the twin of a green gate with no output.

``describe_assertion`` is the shared last line of defence: it returns the
assertion's own message when present, otherwise names the file, line and source
text of the failing precondition. Callers with a ``failures()``-style list
should still attach it as the assert message (``assert not found, found``) --
that names the *contract* drift, while this helper names the *precondition*.

Stdlib only. Imported as a flat sibling module (``scripts/`` has no
``__init__.py``): direct execution puts the script's directory on ``sys.path``,
and pytest's default prepend import mode does the same for these modules.
"""
from __future__ import annotations

import inspect
import traceback
from collections.abc import Callable


def describe_assertion(exc: BaseException, check: Callable[[], object]) -> str:
    """Return a non-empty cause for a failed check."""
    message = str(exc).strip()
    if message:
        return message
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        frame = frames[-1]
        location = f"{frame.filename.rsplit('/', 1)[-1]}:{frame.lineno}"
        source = (frame.line or "").strip()
        if source:
            return f"assertion failed at {location}: {source}"
        return f"assertion failed at {location}"
    try:
        source_file = inspect.getsourcefile(check)
        location = f"{source_file}:{inspect.getsourcelines(check)[1]}"
    except (OSError, TypeError):
        location = getattr(check, "__name__", "check")
    return f"assertion failed in {location} (no message)"
