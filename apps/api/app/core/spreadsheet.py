"""Neutralise spreadsheet formula injection in exported cells.

Excel, LibreOffice and Google Sheets evaluate a cell whose text starts with
``=``, ``+``, ``-`` or ``@``. A value that an untrusted party can influence --
an audit log's ``resource_id`` carries the caller's raw search query -- is
therefore executable content once an administrator opens the export.

The defensive move is a leading apostrophe, which every one of those tools
treats as "this is text". It changes the displayed value only by suppressing
the formula, and it is what ``import_inspection_service`` already does for its
own preview cells; this module is the shared home so the two paths cannot drift.
"""

from __future__ import annotations

#: Characters a spreadsheet treats as the start of a formula.
_FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@")


def neutralize_spreadsheet_cell(value: str) -> str:
    """Return *value*, prefixed with an apostrophe if it would be a formula.

    Typed ``str -> str`` on purpose: only text can carry a formula, and every
    caller already coerces its column to a string (``log.resource_id or ""``),
    so a generic signature would buy nothing and would make each writer
    re-narrow the value before handing it to a cell. Leading whitespace is
    significant -- a cell beginning with spaces then ``=`` is still evaluated --
    so the check looks at the lstripped text while the original is preserved.
    """
    if not isinstance(value, str) or not value:
        return value
    if value.lstrip().startswith(_FORMULA_PREFIXES):
        # ``str`` in, ``str`` out: the apostrophe is the whole change.
        return "'" + value
    return value


__all__ = ["neutralize_spreadsheet_cell"]
