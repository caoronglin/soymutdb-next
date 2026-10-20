#!/usr/bin/env python3
"""Guard: every `t("key", { ... })` interpolation supplies the placeholders.

Why this exists
---------------
A translation key can declare `{{name}}` placeholders, but i18next silently keeps
the raw `{{name}}` text when the call site passes a different option key. This is
not a type error and no other gate sees it: the page renders literal curly braces
("2 genes × {{conditions}} conditions.") and the accessible name degrades the
same way. That exact bug shipped in `apps/web/src/routes/tools/exppattern.tsx`
(`conds` vs `{{conditions}}`), found only when a new browser gate asserted the
rendered summary.

What is checked
---------------
For every literal-key `t("a.b.c", { ... })` call under `apps/*/src`:
  * the key (or its i18next plural variants `key_one`, `key_other`, ...) must
    exist in at least one locale catalog, else the call site is ignored (it is a
    backend/site-content key, not a UI catalog key);
  * every `{{placeholder}}` in the en/zh templates must appear as an option key
    in the object literal (`{ message }` shorthand counts);
  * `count` is exempt (i18next supplies it for pluralization) and calls with
    `defaultValue` are exempt (the call site owns its fallback text);
  * calls whose options spread (`{...vars}`) are skipped: the keys are not
    statically visible, and guessing would produce false failures.

Exit codes: 0 clean, 1 findings, 2 usage/config error. Run from anywhere.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCALES_DIR = REPO_ROOT / "packages" / "i18n-core" / "src" / "locales"
SOURCE_DIRS = (
    REPO_ROOT / "apps" / "web" / "src",
    REPO_ROOT / "apps" / "admin" / "src",
    REPO_ROOT / "apps" / "jbrowse" / "src",
)

CALL_RE = re.compile(r'\bt\(\s*"([^"]+)"\s*,\s*\{', re.S)
PLACEHOLDER_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
# object-literal members: `key: value` and ES6 shorthand `key`
SHORTHAND_RE = re.compile(r"(?:^|[,{\s])([A-Za-z_$][\w$]*)\s*(?=[,}]|$)", re.M)
KEYED_RE = re.compile(r"([A-Za-z_$][\w$]*)\s*:")

PLURAL_SUFFIXES = ("_zero", "_one", "_two", "_few", "_many", "_other")


def flatten(node: object, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    if isinstance(node, dict):
        for key, value in node.items():
            full = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(value, full))
    elif isinstance(node, str):
        out[prefix] = node
    return out


def load_catalogs(locales_dir: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (en, zh) flattened catalogs merged across every namespace file."""
    catalogs: dict[str, dict[str, str]] = {"en": {}, "zh": {}}
    for lang in ("en", "zh"):
        lang_dir = locales_dir / lang
        if not lang_dir.is_dir():
            raise SystemExit(f"missing locale directory: {lang_dir}")
        for path in sorted(lang_dir.glob("*.json")):
            try:
                catalogs[lang].update(flatten(json.loads(path.read_text(encoding="utf-8"))))
            except json.JSONDecodeError as exc:  # pragma: no cover - config error
                raise SystemExit(f"invalid locale JSON {path}: {exc}") from exc
    return catalogs["en"], catalogs["zh"]


def template_placeholders(catalogs: tuple[dict[str, str], dict[str, str]], key: str) -> set[str]:
    placeholders: set[str] = set()
    for catalog in catalogs:
        variants = [key] + [f"{key}{suffix}" for suffix in PLURAL_SUFFIXES]
        for variant in variants:
            template = catalog.get(variant)
            if isinstance(template, str):
                placeholders.update(PLACEHOLDER_RE.findall(template))
    return placeholders


def option_keys(body: str) -> set[str] | None:
    """Parse the keys of an object-literal body; None when it is dynamic."""
    if "..." in body:
        return None
    return set(KEYED_RE.findall(body)) | set(SHORTHAND_RE.findall(body))


def brace_body(text: str, start: int) -> str | None:
    """Return the contents of the object literal that opens at `start`."""
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    return None


def check_file(
    path: Path,
    catalogs: tuple[dict[str, str], dict[str, str]],
) -> list[tuple[str, int, str, list[str], list[str], list[str]]]:
    findings: list[tuple[str, int, str, list[str], list[str], list[str]]] = []
    text = path.read_text(encoding="utf-8", errors="ignore")
    for match in CALL_RE.finditer(text):
        key = match.group(1)
        placeholders = template_placeholders(catalogs, key)
        if not placeholders:
            continue  # unknown key or no interpolation: nothing to verify
        body = brace_body(text, match.end() - 1)
        if body is None:
            continue
        keys = option_keys(body)
        if keys is None:
            continue  # spread: statically unknowable
        allowed = set(keys) | {"count", "defaultValue"}
        missing = sorted(placeholders - allowed)
        if missing:
            line = text[: match.start()].count("\n") + 1
            try:
                rel = str(path.relative_to(REPO_ROOT))
            except ValueError:
                # Synthetic trees (the self-test) live outside the repository.
                rel = str(path)
            findings.append(
                (rel, line, key, sorted(placeholders), sorted(keys), missing)
            )
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--locales-dir",
        type=Path,
        default=LOCALES_DIR,
        help="override the locale catalog directory (used by the self-test)",
    )
    parser.add_argument(
        "--source",
        type=Path,
        action="append",
        default=None,
        help="override source directories (repeatable; used by the self-test)",
    )
    args = parser.parse_args(argv)

    catalogs = load_catalogs(args.locales_dir)
    sources = args.source if args.source is not None else list(SOURCE_DIRS)
    findings: list[tuple[str, int, str, list[str], list[str], list[str]]] = []
    for source in sources:
        if not source.is_dir():
            continue
        for path in sorted(source.rglob("*.ts")) + sorted(source.rglob("*.tsx")):
            if ".test." in path.name:
                continue
            findings.extend(check_file(path, catalogs))

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "file": file,
                        "line": line,
                        "key": key,
                        "placeholders": placeholders,
                        "options": options,
                        "missing": missing,
                    }
                    for file, line, key, placeholders, options, missing in findings
                ],
                indent=2,
            )
        )
    else:
        for file, line, key, placeholders, options, missing in findings:
            print(
                f"{file}:{line}: {key} declares {placeholders} but options "
                f"{options} miss {missing}"
            )
        print(f"i18n interpolation: {len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
