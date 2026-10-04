#!/usr/bin/env python3
"""Guard the admin console's session and transport boundary.

The previous version of this check pinned the React admin's content-pages tab to
its query-key helpers. That tab is retired with the page builder (ADR-0009), and
the console is React, so the check now guards the two properties that outlive any
particular page:

1. **One transport.** Every request goes through `@soymutdb/api-client` (or this
   app's `lib/api.ts`, which wraps it). A view that calls `fetch` directly would
   skip the CSRF attachment, the refresh-on-401 coordination and the release
   header, and it would do so silently.
2. **One session store.** The access token lives in module memory. A view that
   reads or writes `localStorage`/`sessionStorage` for auth is reintroducing the
   persisted-token design the console deliberately does not use.

Both are decided by scanning source, so a new page cannot opt out by accident.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADMIN_SRC = ROOT / "apps" / "admin" / "src"

# A direct network call that bypasses the shared client. `adminApi` and the
# api-client functions are the only sanctioned entry points.
DIRECT_FETCH_RE = re.compile(r"\bfetch\s*\(")
STORAGE_RE = re.compile(r"\b(?:local|session)Storage\b")

# Comments are stripped before scanning: the header of `lib/auth.ts` explains why
# the token is *not* persisted, and a guard that flags the explanation of its own
# rule is a guard that gets weakened on the first false positive.
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_LINE_COMMENT_RE = re.compile(r"(?<!:)//[^\n]*")
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def strip_comments(text: str) -> str:
    text = _BLOCK_COMMENT_RE.sub("", text)
    text = _HTML_COMMENT_RE.sub("", text)
    return _LINE_COMMENT_RE.sub("", text)



GENERATED_DIRS = {"node_modules", "dist", "build", "coverage", "__pycache__"}
THEME_KEY = "soymutdb-admin-primary-color"

# Preference keys are presentation state, not credentials (motion preference and
# primary colour). They are allowed only through the validator that constrains
# their value, so a token cannot ride in under a declared key name: writing
#
#     localStorage.setItem("soymutdb-animation-prefs", response.access_token)
#
# has no parser wrapping it and stays a violation. Matching on the *variable
# name* alone would not survive a key called `preferences`.
PREFERENCE_KEYS = {
    "soymutdb-animation-prefs": "parseMotionPreference",
}
_STORAGE_GUARD_RE = re.compile(r"\btypeof\s+(?:local|session)Storage\s*===\s*(['\"])undefined\1")


def _mask(text: str, start: int, end: int, replacement: str) -> str:
    """Replace a span, keeping every later offset identical to the original."""
    span = end - start
    return text[:start] + replacement + " " * (span - len(replacement)) + text[end:]


def allow_validated_preference_reads(text: str) -> str:
    """Mask `localStorage.getItem(<declared key>)` wrapped by its parser.

    Offset-preserving: matches are collected first and replaced right to left.
    """
    for key, parser in PREFERENCE_KEYS.items():
        names = set(re.findall(r"\bconst\s+(\w+)\s*=\s*['\"]" + re.escape(key) + r"['\"]", text))
        args = "|".join([r"['\"]" + re.escape(key) + r"['\"]"]
                        + [r"\b" + re.escape(name) + r"\b" for name in sorted(names)])
        pattern = re.compile(
            r"\b" + re.escape(parser) + r"\s*\(\s*"
            r"(?:local|session)Storage\s*\.\s*(?:getItem|get)\s*\(\s*(?:" + args + r")\s*\)\s*\)"
        )
        for match in reversed(list(pattern.finditer(text))):
            text = _mask(text, match.start(), match.end(), "preferenceRead")
    for match in reversed(list(_STORAGE_GUARD_RE.finditer(text))):
        text = _mask(text, match.start(), match.end(), "storageGuard")
    return text


def allow_validated_theme_operations(text: str) -> str:
    """Mask only the audited theme operations, never their containing file.

    The narrow shapes prove the stored value passes the six-digit hex validator.
    Any added storage operation or changed validation falls back to a violation.
    This is a source-level contract, not a general TypeScript data-flow analyzer.
    """
    key = re.search(
        r'\bconst\s+ADMIN_PRIMARY_COLOR_STORAGE_KEY\s*=\s*(["\'])'
        + re.escape(THEME_KEY) + r'\1\s*;', text
    )
    validator = re.search(
        r'\bconst\s+HEX_COLOR_RE\s*=\s*/\^#\[0-9a-f\]\{6\}\$/i\s*;', text
    )
    compact = lambda value: re.sub(r"\s+", "", value)
    functions = {
        "isValidAdminPrimaryColor": 'return HEX_COLOR_RE.test(value);',
        "readAdminPrimaryColor": '''
            if (typeof localStorage === "undefined") return ANTD_PRIMARY_HEX;
            try {
                const stored = localStorage.getItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY);
                return stored && isValidAdminPrimaryColor(stored)
                    ? stored.toLowerCase() : ANTD_PRIMARY_HEX;
            } catch { return ANTD_PRIMARY_HEX; }
        ''',
        "saveAdminPrimaryColor": '''
            if (!isValidAdminPrimaryColor(value) || typeof localStorage === "undefined") return;
            const normalized = value.toLowerCase();
            try { localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, normalized); }
            catch { return; }
            window.dispatchEvent(new CustomEvent(ADMIN_PRIMARY_COLOR_EVENT, { detail: normalized }));
        ''',
    }
    matches = {}
    for name, body in functions.items():
        match = re.search(
            r"export\s+function\s+" + name
            + r"\([^\n]*\)\s*:\s*\w+\s*\{(?P<body>.*?)^\}", text, re.M | re.S
        )
        if match and compact(match.group("body")) == compact(body):
            matches[name] = match
    if not key or not validator or "isValidAdminPrimaryColor" not in matches:
        return text
    # Reverse offsets so masking one operation does not move another match.
    for name in ("saveAdminPrimaryColor", "readAdminPrimaryColor"):
        match = matches.get(name)
        if match:
            start, end = match.span("body")
            body = STORAGE_RE.sub("themeStorage", text[start:end])
            text = text[:start] + body + text[end:]
            # Keep length unchanged for the next match's offsets.
            if len(body) != end - start:
                raise AssertionError("theme mask must preserve source offsets")
    return text


def sources() -> list[Path]:
    return sorted(
        path
        for path in ADMIN_SRC.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and path.is_file()
        and not any(
            part in GENERATED_DIRS or part in {".umi", ".umi-production", ".umi-test"}
            for part in path.relative_to(ADMIN_SRC).parts[:-1]
        )
    )


def main() -> int:
    failures: list[str] = []

    paths = sources()
    if not paths:
        failures.append("admin source scan is empty: expected TS/TSX business sources")

    for path in paths:
        text = strip_comments(path.read_text(encoding="utf-8"))
        relative = path.relative_to(ROOT).as_posix()

        if DIRECT_FETCH_RE.search(text):
            failures.append(
                f"{relative}: calls fetch() directly — go through @soymutdb/api-client "
                "so CSRF, refresh-on-401 and the release header stay attached"
            )
        if STORAGE_RE.search(allow_validated_preference_reads(allow_validated_theme_operations(text))):
            failures.append(
                f"{relative}: touches web storage — the admin access token is "
                "module-memory only (see src/lib/auth.ts)"
            )

    if failures:
        print("Admin transport/session architecture check failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print(
        f"Admin transport/session architecture check passed "
        f"({len(paths)} source file(s))."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
