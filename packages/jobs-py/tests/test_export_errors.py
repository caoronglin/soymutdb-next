"""Public error messages are a fixed vocabulary, not trimmed diagnostics."""

import pytest

from soymutdb_jobs.export_errors import EXPORT_FAILED_MESSAGE, public_export_error


@pytest.mark.parametrize("message", [
    "SELECT internal_id FROM mutants", "token=private-secret", "/private/file",
    "\x00\x07\x1b", "x" * 10000, "   ",
])
def test_diagnostics_are_never_echoed(message):
    assert public_export_error(message) == EXPORT_FAILED_MESSAGE


@pytest.mark.parametrize("message", [None, ""])
def test_absent_error_stays_absent(message):
    assert public_export_error(message) is None
