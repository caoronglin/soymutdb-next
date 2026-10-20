"""Literal ``LIKE`` patterns for user-supplied search text.

A SQL ``LIKE`` pattern is a *program*, not a string: ``%`` matches any run of
characters and ``_`` matches exactly one. Splicing raw user text into a
pattern therefore hands the caller control over which rows the query matches.
A search for ``%`` becomes "match every row" and a search for ``_`` matches
any single character -- and because a pattern made only of wildcards carries
no trigram, the planner cannot use the trigram indexes either, so the
"search" also degrades into a full scan of the table.

``docs/dev/database-core-contract.md`` §6 item 6 requires a literal ``%`` / ``_``
fixture precisely so that user input can never become a LIKE wildcard program.
This module is the single place where user text is turned into a pattern, so
every search path can share one convention.

The convention matches the global-search path
(``app/services/search_service.py``): the backslash is the escape character,
it is doubled when it occurs literally, and the SQL side must be told about it
(``ilike(pattern, escape="\\")``). The module deliberately imports nothing
beyond the standard library, so the global-search path can adopt it later
without pulling in a dependency cycle.
"""

from __future__ import annotations

#: The character that escapes the next character in a ``LIKE`` pattern.
#:
#: It is the default escape character of PostgreSQL's ``LIKE``/``ILIKE``, and
#: it has to be passed to the SQL side as well (``escape=LIKE_ESCAPE_CHARACTER``)
#: for the escaping below to mean anything. Without that clause the backslashes
#: would be matched literally and the ``%`` would still be a wildcard.
LIKE_ESCAPE_CHARACTER = "\\"


def literal_like_fragment(value: str) -> str:
    """Escape ``%``, ``_`` and the escape character itself.

    The result is a *fragment*: it carries no wildcards of its own, so it can
    be embedded in a pattern (``f"%{fragment}%"``) without the caller's text
    turning into a wildcard program.

    The replacements are ordered so that each one only sees characters that
    are still to be processed: the backslash is doubled **first**, otherwise
    the backslashes introduced for ``%`` and ``_`` would be doubled again and
    the pattern would no longer describe the text the user typed.
    """
    return (
        value.replace(LIKE_ESCAPE_CHARACTER, LIKE_ESCAPE_CHARACTER * 2)
        .replace("%", f"{LIKE_ESCAPE_CHARACTER}%")
        .replace("_", f"{LIKE_ESCAPE_CHARACTER}_")
    )


def contains_pattern(value: str) -> str:
    """Build a literal substring pattern for ``value``.

    The pattern matches any row whose column contains ``value`` as a literal
    substring -- case-insensitively, because it is meant for ``ILIKE``.

    Example: ``contains_pattern("a%b")`` is ``"%a\\%b%"``, which matches
    ``"xa%by"`` and *not* ``"xayb"``.
    """
    return f"%{literal_like_fragment(value)}%"
