#!/usr/bin/env python3
"""Content-key contract: portal content readers and the registry must match.

The portal's backend-editable copy runs through
``useSiteContent().get("<key>", <fallback>)``. Both directions are drift:

* a key that is read but not registered can never be stored or overridden, so
  the read silently falls back to i18n forever and the Admin console has no
  field for it;
* a registered key with no reader is an admin-editable setting that does
  nothing.

Literal ``get("<key>")`` calls are read directly. The portal also iterates two
static lists and interpolates the entry into the key — home tool cards
(``tool.${tool.key}.label|desc|image``) and the help FAQ
(``help.faq${i + 1}.q|a``) — and resolves navigation labels through
``labelKey`` values consumed by the header. Those families are expanded from
their source lists, so a new tool card or FAQ entry without a matching
registration still fails the gate.

An unrecognised dynamic template fails closed: the guard refuses to guess, so
a new interpolation style cannot silently escape the contract.

Usage:
    python3 scripts/check_content_key_contract.py            # gate
    python3 scripts/check_content_key_contract.py --report   # print drift, exit 0
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "apps/api/app/core/settings_registry.py"
PORTAL_ROOT = REPO_ROOT / "apps/web/src"

# The portal helper is invoked bare: `get("key", fallback)`. Property access
# (`di.get("api")`, `map.get("x")`) is not part of the content contract.
GET_CALL = re.compile(r'(?<![.\w])get\(\s*["\']([A-Za-z][A-Za-z0-9_.]*)["\']')
GET_TEMPLATE = re.compile(r"(?<![.\w])get\(\s*`([^`]*)`")
PLACEHOLDER = re.compile(r"\$\{([^}]*)\}")
CONTENT_DEFINITION = re.compile(r'_definition\(\s*"content"\s*,\s*"([^"]+)"')
# `labelKey: "nav.search"` values are resolved through `get(labelKey, ...)`.
# Only files that actually pass a labelKey identifier to get() count their
# labelKey constants as content consumers; elsewhere labelKey is i18n-only.
LABEL_KEY = re.compile(r'labelKey:\s*"([A-Za-z][A-Za-z0-9_.]*)"')
LABEL_KEY_CONSUMER = re.compile(r"(?<![.\w])get\(\s*[\w.]*\blabelKey\b")
SKIP_PARTS = {".umi", ".umi-production", ".umi-test", "node_modules", "dist"}
SKIP_SUFFIXES = (".test.ts", ".test.tsx", ".spec.ts", ".spec.tsx")

_HOME_TOOLS = "components/home/antd-home.tsx"
_HELP_PAGE = "routes/help.tsx"
_TOOL_ARRAY = re.compile(r"const TOOL_ENTRIES[^=]*=\s*\[(.*?)\n\];", re.DOTALL)
_TOOL_KEY = re.compile(r'\{\s*key:\s*"([a-z][a-z0-9_]*)"[^}]*labelKey:')
_FAQ_ARRAY = re.compile(r"const FAQS[^=]*=\s*\[(.*?)\n\];", re.DOTALL)
_FAQ_ENTRY = re.compile(r'\{\s*q:\s*"')


class UnmodelledDynamicRead(ValueError):
    """A dynamic get() the guard cannot resolve from a static source list."""


def registered_content_keys(registry_text: str) -> set[str]:
    return set(CONTENT_DEFINITION.findall(registry_text))


def _iter_sources(portal_root: Path):
    for path in sorted(portal_root.rglob("*")):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name.endswith(SKIP_SUFFIXES):
            continue
        yield path, path.read_text(encoding="utf-8", errors="ignore")


def _source_label(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return path.name


def _tool_keys(text: str) -> list[str]:
    array = _TOOL_ARRAY.search(text)
    if array is None:
        raise UnmodelledDynamicRead(
            f"{_HOME_TOOLS} no longer declares TOOL_ENTRIES; update the guard"
        )
    keys = _TOOL_KEY.findall(array.group(1))
    if not keys:
        raise UnmodelledDynamicRead(
            f"{_HOME_TOOLS} declares no tool keys; update the guard"
        )
    return keys


def _faq_indices(text: str) -> list[str]:
    array = _FAQ_ARRAY.search(text)
    if array is None:
        raise UnmodelledDynamicRead(
            f"{_HELP_PAGE} no longer declares FAQS; update the guard"
        )
    count = len(_FAQ_ENTRY.findall(array.group(1)))
    if count == 0:
        raise UnmodelledDynamicRead(f"{_HELP_PAGE} declares no FAQ entries")
    return [str(index) for index in range(1, count + 1)]


# Interpolated expression -> (source file relative to the portal root, extractor).
_DYNAMIC_EXPRESSIONS = {
    "tool.key": (_HOME_TOOLS, _tool_keys),
    "i + 1": (_HELP_PAGE, _faq_indices),
}


def _dynamic_values(expr: str, portal_root: Path, cache: dict[str, list[str]]) -> list[str]:
    if expr in cache:
        return cache[expr]
    spec = _DYNAMIC_EXPRESSIONS.get(expr)
    if spec is None:
        raise UnmodelledDynamicRead(
            f"cannot resolve dynamic content key expression '${{{expr}}}'; "
            "add its source list to the guard"
        )
    relative, extractor = spec
    source = portal_root / relative
    if not source.is_file():
        raise UnmodelledDynamicRead(f"dynamic key source is missing: {relative}")
    cache[expr] = extractor(source.read_text(encoding="utf-8", errors="ignore"))
    return cache[expr]


def _expand_template(
    template: str, portal_root: Path, cache: dict[str, list[str]]
) -> list[str]:
    parts = PLACEHOLDER.split(template)
    if len(parts) == 1:
        return [template]
    if len(parts) != 3:
        raise UnmodelledDynamicRead(
            f"cannot resolve content key template `{template}` with multiple placeholders"
        )
    prefix, expr, suffix = parts
    return [
        f"{prefix}{value}{suffix}"
        for value in _dynamic_values(" ".join(expr.split()), portal_root, cache)
    ]


def portal_get_keys(portal_root: Path) -> dict[str, str]:
    """Map each consumed content key to the first source file that reads it."""
    found: dict[str, str] = {}
    cache: dict[str, list[str]] = {}
    for path, text in _iter_sources(portal_root):
        label = _source_label(path)
        for match in GET_CALL.finditer(text):
            found.setdefault(match.group(1), label)
        for template in GET_TEMPLATE.findall(text):
            for key in _expand_template(template, portal_root, cache):
                found.setdefault(key, label)
        if LABEL_KEY_CONSUMER.search(text):
            for key in LABEL_KEY.findall(text):
                found.setdefault(key, label)
    return found


def drift(registered: set[str], consumed: dict[str, str]) -> tuple[list[str], list[str]]:
    unregistered = sorted(set(consumed) - registered)
    unread = sorted(registered - set(consumed))
    return unregistered, unread


def _report(registered: set[str], consumed: dict[str, str], unregistered: list[str], unread: list[str]) -> None:
    print(f"registered content keys: {len(registered)}")
    print(f"portal content consumers: {len(consumed)}")
    print(f"consumed but unregistered ({len(unregistered)}):")
    for key in unregistered:
        print(f"  {key} <- {consumed[key]}")
    print(f"registered but no consumer ({len(unread)}):")
    for key in unread:
        print(f"  {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        action="store_true",
        help="print both drift directions (informational) and always exit 0",
    )
    args = parser.parse_args(argv)

    registered = registered_content_keys(REGISTRY.read_text(encoding="utf-8"))
    try:
        consumed = portal_get_keys(PORTAL_ROOT)
    except UnmodelledDynamicRead as exc:
        print(f"content-key contract failed: {exc}", file=sys.stderr)
        return 0 if args.report else 1
    unregistered, unread = drift(registered, consumed)

    if args.report:
        _report(registered, consumed, unregistered, unread)
        return 0

    if unregistered:
        print(
            "content-key contract failed: the portal reads keys that are not "
            "registered in apps/api/app/core/settings_registry.py, so they can "
            "never be stored or overridden:",
            file=sys.stderr,
        )
        for key in unregistered:
            print(f"  {key} <- {consumed[key]}", file=sys.stderr)
        return 1

    if unread:
        print(
            "content-key contract failed: registered content keys have no portal "
            "consumer, so the Admin console exposes fields that do nothing:",
            file=sys.stderr,
        )
        for key in unread:
            print(f"  {key}", file=sys.stderr)
        return 1

    print(
        f"content-key contract OK ({len(consumed)} portal content consumers, "
        f"{len(registered)} registered content keys)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())