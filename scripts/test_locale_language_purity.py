"""Locale language purity: a Chinese UI shows Chinese, an English UI shows English.

The console had labels hardcoded as ``"中文 / English"`` pairs and English
sentences sitting in the Chinese bundle, so neither locale ever matched the
active language. These tests fail on either shape.

What is deliberately exempt: terms that are spelled the same in both languages
(``Indel``, ``Tm``, ``Slug``, ``Markdown``, ``Release id``, ``Variant ID``),
brand fragments, identifier examples, and any value that legitimately mixes a
Chinese sentence with an embedded product name. Only a value that is *entirely*
one script when it should be the other is a finding.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from named_guard_diagnostics import describe_assertion

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
LOCALES = REPO_ROOT / "packages" / "i18n-core" / "src" / "locales"

CJK = re.compile(r"[一-鿿]")
LATIN_SENTENCE = re.compile(r"[A-Za-z]{3,}(?:[ ][A-Za-z]{2,})+")

# Values that must not be rewritten: technical terms, brands, and identifier
# examples that read identically in both languages.
EXEMPT = {
    "brand.mut",
    "brand.soy",
    "variants.indel",
    "variants.indel_count",
    "search.primer.tm",
    "admin.analyticsSettings.cloudflareBadge",
    "admin.importCreate.releaseId",
    "admin.news.form.slug",
    "admin.editor.tabMarkdown",
    "admin.tableViews.column.variant_id",
    "admin.tableViews.column.gene_id",
    "tools.seqfetch.genesPlaceholderExample",
    # Brand eyebrow, rendered in English in both bundles by design.
    "home.databaseEyebrow",
    # Vendor product name, identical in both bundles by design.
    "admin.analyticsSettings.badgeCloudflare",
    # Upstream tool names (the NCBI search engine and DIAMOND). A BLAST user
    # searches for "NCBI BLAST+" and "DIAMOND", not for a translation, and
    # neither key exists under `blastPublic`: that namespace carries
    # `blastPublic.engine`, not per-engine labels.
    "blastSearch.engineNcbi",
    "blastSearch.engineDiamond",
}


# The portal merges three module-level bundles over the shared catalogs with
# `addResourceBundle(..., deep: true)` in `apps/web/src/lib/i18n.ts`. A key that
# lives only in one of them is visible in the running UI, so a guard that reads
# `common.json` alone reports correct copy as missing (87 `tools.sequence.*`
# keys did exactly that) and would also miss a real defect parked in a runtime
# bundle. Read the same merge the app performs.
PORTAL_RESOURCES = REPO_ROOT / "apps" / "web" / "src" / "lib" / "i18n-resources.ts"
RUNTIME_BUNDLES = ("EXTRA_RESOURCES", "TOOLS_RESOURCES", "HOME_RESOURCES")


def _object_literal(source: str, name: str) -> str:
    """Return the brace-balanced body of `export const <name>: ... = {...}`."""
    marker = f"export const {name}:"
    start = source.find(marker)
    if start < 0:
        raise AssertionError(f"{name} is missing from {PORTAL_RESOURCES.name}")
    start = source.index("= {", start) + 2
    depth = 0
    for index in range(start, len(source)):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"{name} object literal is unbalanced")


def _flatten(node: dict, prefix: str = "") -> dict:
    flat: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten(value, path))
        else:
            flat[path] = value
    return flat


# `key: value` / `key: {...}` — an unquoted object key as TypeScript writes it.
BARE_KEY = re.compile(r"([{,]\s*)([A-Za-z_$][\w$]*)(\s*:)")


def _json_compatible(body: str, name: str) -> str:
    """Quote bare object keys and drop trailing commas, leaving values alone.

    The bundles are plain data, but they are TypeScript, not JSON. Anything this
    cannot make parseable is reported instead of silently skipped.
    """
    text = BARE_KEY.sub(r'\1"\2"\3', body)
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    for token in ("`", "=>", " ?? ", "?.", " + "):
        if token in text:  # pragma: no cover - shape guard
            raise AssertionError(
                f"{name} in {PORTAL_RESOURCES.name} contains {token!r}; this guard "
                "reads plain object literals, so it needs a real parser now"
            )
    return text


def _runtime_bundles() -> dict[str, dict[str, str]]:
    """Parse the portal's runtime bundles out of the TypeScript module.

    They are plain data, so they are read without a TypeScript parser or a
    `node_modules` checkout -- which matters, because this layer must run on a
    clean tree that has not been installed.
    """
    source = PORTAL_RESOURCES.read_text(encoding="utf-8")
    merged: dict[str, dict[str, str]] = {}
    for name in RUNTIME_BUNDLES:
        body = _json_compatible(_object_literal(source, name), name)
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as error:  # pragma: no cover - shape guard
            raise AssertionError(
                f"{name} in {PORTAL_RESOURCES.name} is no longer JSON-compatible "
                f"({error}); this guard parses it directly"
            ) from error
        for locale, bundle in parsed.items():
            merged.setdefault(locale, {}).update(_flatten(bundle))
    return merged


def _load(locale: str) -> dict:
    """The catalog the UI actually renders: shared bundle + runtime overlay."""
    path = LOCALES / locale / "common.json"
    shared = _flatten(json.loads(path.read_text(encoding="utf-8")))
    shared.update(_runtime_bundles().get(locale, {}))
    return shared


def test_english_bundle_has_no_chinese() -> None:
    """An English UI must not leak Chinese, except CJK text that is data."""
    offenders = [
        (path, value)
        for path, value in _load("en").items()
        if CJK.search(value) and path not in EXEMPT
    ]
    assert offenders == [], "Chinese text in the English bundle: " + repr(offenders[:8])


def test_chinese_bundle_has_no_english_sentences() -> None:
    """A Chinese UI must not show English prose.

    Scoped to sentences rather than any Latin run: ``Indel``, ``Slug`` and
    ``Glyma.01G000100`` are correct in a Chinese sentence.
    """
    offenders = [
        (path, value)
        for path, value in _load("zh").items()
        if not CJK.search(value)
        and LATIN_SENTENCE.search(value)
        and path not in EXEMPT
    ]
    assert offenders == [], "English prose in the Chinese bundle: " + repr(offenders[:8])


def test_both_locales_define_the_same_keys() -> None:
    """A key present in one locale and absent in the other silently falls back."""
    zh = _load("zh")
    en = _load("en")
    missing_in_en = sorted(set(zh) - set(en))
    missing_in_zh = sorted(set(en) - set(zh))
    assert missing_in_en == [], f"present in zh, missing in en: {missing_in_en[:8]}"
    assert missing_in_zh == [], f"present in en, missing in zh: {missing_in_zh[:8]}"


def test_every_translated_key_exists_in_the_bundle() -> None:
    """A `t(key, { defaultValue })` whose key is absent renders the default.

    This is how the sign-in page stayed English inside a Chinese console: all 19
    `admin.login.*` keys and 9 `admin.shell.*` navigation keys existed only in
    source, never in a bundle, so every call silently fell back to its inline
    English `defaultValue`. Neither locale was "missing" the other, so the
    key-parity test above could not see it.
    """
    bundles = {locale: _load(locale) for locale in ("zh", "en")}
    roots = [REPO_ROOT / "apps" / "admin" / "src", REPO_ROOT / "apps" / "web" / "src"]
    # t("a.b.c", ...) and t("a.b.c", "text") — the defaultValue form.
    call = re.compile(r"""\bt\(\s*["']([a-zA-Z][a-zA-Z0-9]*(?:\.[a-zA-Z0-9_]+)+)["']""")
    offenders: dict[str, str] = {}
    for root in roots:
        for path in root.rglob("*.ts*"):
            text = path.read_text(encoding="utf-8")
            for match in call.finditer(text):
                key = match.group(1)
                if all(key in table for table in bundles.values()):
                    continue
                rel = str(path.relative_to(REPO_ROOT))
                offenders.setdefault(key, rel)
    assert offenders == {}, f"t() keys with no bundle entry: {offenders}"


def test_no_source_hardcodes_a_bilingual_label() -> None:
    """`"中文 / English"` in a component never follows the active locale.

    Walks the admin and portal source for a quoted string holding both scripts
    around a lone slash, which is the shape these defects took.
    """
    bilingual = re.compile(r"[一-鿿][^'\"\\]*\s+/\s+[A-Za-z][^'\"\\]*")
    roots = [
        REPO_ROOT / "apps" / "admin" / "src",
        REPO_ROOT / "apps" / "web" / "src",
    ]
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*.ts*"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("//", "*", "/*")):
                    continue
                if bilingual.search(line) and len(bilingual.search(line).group(0)) < 60:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}")
    assert offenders == [], "hardcoded bilingual labels: " + repr(offenders[:8])


if __name__ == "__main__":
    failures = 0
    for name, check in sorted(globals().items()):
        if name.startswith("test_") and callable(check):
            try:
                check()
                print(f"PASS {name}")
            except AssertionError as error:
                failures += 1
                print(f"FAIL {name}: {describe_assertion(error, check)}")
    sys.exit(1 if failures else 0)