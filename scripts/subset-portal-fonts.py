#!/usr/bin/env python3
"""Subset the self-hosted HarmonyOS Sans SC woff2 files for the admin app.

The admin console and the standalone genome browser self-host HarmonyOS Sans SC
(three full ~4.3 MB woff2 files each, under ``apps/<app>/public/fonts/harmonyos/``). Only a small slice of the CJK repertoire
is ever rendered, so the script rewrites those files with a reproducible
character set, split per weight into a small ``-latin`` face (ASCII + Western
symbols, preloaded) and a ``-cjk`` face (hanzi and CJK/fullwidth punctuation,
fetched only when CJK glyphs render).  This script rewrites all six files in place with a reproducible character
set (the woff2 bytes themselves can vary slightly between fontTools runs):

* every character that appears in the i18n locale JSON bundles,
* every character that appears in ``apps/*/src/**/*.{ts,tsx}`` (deliberately
  conservative: comments and test fixtures are included),
* all GB2312 level-1 + level-2 hanzi (6763 characters), and
* printable ASCII (U+0020..U+007E).

Rare hanzi outside that set fall back to the system font stack declared next to
the ``@font-face`` rules, so coverage degrades gracefully instead of rendering
tofu.  The manifest written beside the fonts lets the pytest guard validate
coverage and budgets without importing fontTools.

Requirements
------------
fontTools *and* brotli are required (``--flavor=woff2`` needs brotli).  The
API/worker virtualenvs ship fontTools but not brotli, so run this with an
interpreter that has both, e.g.::

    python -m pip install --user fonttools brotli
    python scripts/subset-portal-fonts.py

Usage
-----
    python scripts/subset-portal-fonts.py              # regenerate fonts + manifests
    python scripts/subset-portal-fonts.py --check      # verify, never write
    python scripts/subset-portal-fonts.py --dry-run    # show the plan, never write

The first regeneration caches the pristine full fonts under
``.cache/font-subset-sources/`` (git-ignored) so later runs can add new UI
characters without losing glyphs that a previous subset dropped.  If that cache
is gone and the tracked files already contain subsets, restore the originals
from git history (see ``docs/dev/font-subsetting.md``) or pass ``--source-dir``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

LOCALE_ROOT = REPO_ROOT / "packages" / "i18n-core" / "src" / "locales"
APP_SOURCE_DIRS = (
    REPO_ROOT / "apps" / "web" / "src",
    REPO_ROOT / "apps" / "admin" / "src",
)
# The public portal deliberately uses the system CJK stack (no HarmonyOS
# @font-face and no font preload); the admin console and the standalone genome
# browser self-host the subset. Both serve it from their own origin root, so
# their CSS can use root-absolute `/fonts/harmonyos/...` URLs and the build
# copies each file exactly once (no hashed-webpack duplicate).
APP_FONT_DIRS = {
    "admin": REPO_ROOT / "apps" / "admin" / "public" / "fonts" / "harmonyos",
    "jbrowse": REPO_ROOT / "apps" / "jbrowse" / "public" / "fonts" / "harmonyos",
}
FONT_FILES = (
    (400, "HarmonyOS-Sans-SC-Regular.woff2"),
    (500, "HarmonyOS-Sans-SC-Medium.woff2"),
    (700, "HarmonyOS-Sans-SC-Bold.woff2"),
)
MANIFEST_NAME = "subset-manifest.json"
SCHEMA_VERSION = 1

SOURCE_CACHE_DIR = REPO_ROOT / ".cache" / "font-subset-sources"
STAGING_DIR = REPO_ROOT / ".cache" / "font-subset-staging"

# Guard budgets (mirrored in scripts/test_portal_font_subset.py).  A full font is
# ~4.3 MB, so either check catches a full-font recommit.
#
# Each weight is split into two files by unicode-range: the "latin" file holds
# ASCII + Western punctuation/symbols (a few KB, preloaded), the "cjk" file holds
# hanzi and CJK/fullwidth punctuation (only fetched when the page renders CJK).
MAX_LATIN_FILE_BYTES = 262_144  # 256 KiB
MAX_CJK_FILE_BYTES = 1_258_291  # 1.2 MiB
MAX_APP_BYTES = 3_145_728  # 3.0 MiB
FONT_ROLES = ("latin", "cjk")
ROLE_BUDGET_BYTES = {"latin": MAX_LATIN_FILE_BYTES, "cjk": MAX_CJK_FILE_BYTES}

ASCII_PRINTABLE = range(0x20, 0x7F)
CJK_RANGES = (
    (0x2E80, 0x2EFF),  # CJK Radicals Supplement
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0xF900, 0xFAFF),  # CJK Compatibility Ideographs
    (0xFE30, 0xFE4F),  # CJK Compatibility Forms
    (0xFF00, 0xFFEF),  # Halfwidth and Fullwidth Forms
)

# A pristine source has the full Han repertoire and is multi-megabyte; a subset
# produced by this script has ~7k cmap entries after later UI additions.
FULL_FONT_MIN_CMAP = 20_000
FULL_FONT_MIN_BYTES = 2_000_000


# ---------------------------------------------------------------------------
# Charset
# ---------------------------------------------------------------------------


def _normalise(text: str) -> set[str]:
    """Every character in ``text``.

    Newlines and tabs are dropped: they are never rendered glyphs and cannot be
    mapped by a font, so keeping them only forces a "missing codepoint" entry
    into every manifest.
    """
    return {char for char in text if char != "\n" and char != "\t"}


def _walk_json_strings(node: object) -> set[str]:
    chars: set[str] = set()
    if isinstance(node, dict):
        for value in node.values():
            chars |= _walk_json_strings(value)
    elif isinstance(node, list):
        for value in node:
            chars |= _walk_json_strings(value)
    elif isinstance(node, str):
        chars |= _normalise(node)
    return chars


def _gb2312_level_1_2() -> set[str]:
    chars: set[str] = set()
    for high in range(0xB0, 0xF8):
        for low in range(0xA1, 0xFF):
            try:
                chars.add(bytes((high, low)).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return chars


def _iter_app_sources() -> list[Path]:
    files: list[Path] = []
    for root in APP_SOURCE_DIRS:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in {".ts", ".tsx"}:
                continue
            # Skip generated / cache directories such as apps/web/src/.umi*.
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            files.append(path)
    return sorted(files)


def collect_charset() -> tuple[set[str], dict[str, object]]:
    """Return the target character set and a deterministic provenance block."""
    locale_sources: dict[str, int] = {}
    locale_chars: set[str] = set()
    for path in sorted(LOCALE_ROOT.rglob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        chars = _walk_json_strings(data)
        locale_sources[path.relative_to(REPO_ROOT).as_posix()] = len(chars)
        locale_chars |= chars

    app_sources: dict[str, int] = {}
    app_chars: set[str] = set()
    app_chars_by_root: dict[str, set[str]] = {}
    for path in _iter_app_sources():
        chars = _normalise(path.read_text(encoding="utf-8", errors="replace"))
        app_chars |= chars
        try:
            root = path.relative_to(REPO_ROOT).parts[:3]
        except ValueError:
            continue
        app_chars_by_root.setdefault("/".join(root), set()).update(chars)
    for root, chars in sorted(app_chars_by_root.items()):
        app_sources[root] = len(chars)

    gb2312_chars = _gb2312_level_1_2()
    ascii_chars = {chr(codepoint) for codepoint in ASCII_PRINTABLE}

    charset = locale_chars | app_chars | gb2312_chars | ascii_chars
    sources = {
        "locale_json": dict(sorted(locale_sources.items())),
        "app_typescript": dict(sorted(app_sources.items())),
        "gb2312_level_1_2": len(gb2312_chars),
        "ascii_printable": len(ascii_chars),
        "note": "counts are per-source distinct characters and overlap; they are not additive",
    }
    return charset, sources


def codepoints(charset: set[str]) -> list[int]:
    return sorted(ord(char) for char in charset)


def codepoints_to_ranges(codepoints_list: list[int]) -> list[str]:
    """Encode codepoints as lowercase hex ``start-end`` (or ``point``) strings.

    One string per range keeps the checked-in manifest reviewable (~50 KB) instead
    of pretty-printing thousands of ``[start, end]`` arrays (~166 KB).
    """
    ranges: list[list[int]] = []
    for codepoint in codepoints_list:
        if ranges and codepoint == ranges[-1][1] + 1:
            ranges[-1][1] = codepoint
        else:
            ranges.append([codepoint, codepoint])
    return [
        f"{start:x}-{end:x}" if start != end else f"{start:x}"
        for start, end in ranges
    ]


def ranges_to_codepoints(ranges: object) -> set[int]:
    result: set[int] = set()
    if not isinstance(ranges, list):
        raise ValueError("charset.ranges must be a list")
    previous_end = -1
    for entry in ranges:
        if not isinstance(entry, str):
            raise ValueError(f"invalid range entry: {entry!r}")
        token = entry.strip().lower()
        try:
            if "-" in token:
                start_text, end_text = token.split("-", 1)
                start, end = int(start_text, 16), int(end_text, 16)
            else:
                start = end = int(token, 16)
        except ValueError as exc:
            raise ValueError(f"invalid range entry: {entry!r}") from exc
        if start < 0 or end < start:
            raise ValueError(f"invalid range entry: {entry!r}")
        if start <= previous_end:
            raise ValueError(f"ranges are not sorted and disjoint at {entry!r}")
        previous_end = end
        result.update(range(start, end + 1))
    return result


def charset_digest(codepoints_list: list[int]) -> str:
    payload = ",".join(str(codepoint) for codepoint in codepoints_list).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def is_cjk(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in CJK_RANGES)


def required_cjk(charset: set[str]) -> set[int]:
    return {ord(char) for char in charset if is_cjk(ord(char))}


def split_charset(charset: set[str]) -> dict[str, set[str]]:
    """Partition the target charset into the latin/ui and CJK files."""
    latin = {char for char in charset if not is_cjk(ord(char))}
    cjk = {char for char in charset if is_cjk(ord(char))}
    return {"latin": latin, "cjk": cjk}


def role_filename(filename: str, role: str) -> str:
    stem = filename[: -len(".woff2")] if filename.endswith(".woff2") else filename
    return f"{stem}-{role}.woff2"


# ---------------------------------------------------------------------------
# Font tools
# ---------------------------------------------------------------------------


def _try_import_fonttools():
    """Return ``(subset, TTFont)`` when fontTools + brotli are importable, else None."""
    try:
        import brotli  # noqa: F401  (required by fontTools for woff2)
    except ImportError:
        return None
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    return subset, TTFont


def _import_fonttools():
    """Import fontTools + brotli, or exit with an actionable message."""
    imported = _try_import_fonttools()
    if imported is not None:
        return imported
    try:
        import brotli  # noqa: F401
    except ImportError:
        sys.exit(
            "error: brotli is required to write woff2 fonts but is not installed for "
            f"{sys.executable}.\n"
            "       Install it (python -m pip install --user brotli fonttools) or run this "
            "script with an interpreter that has both, then retry.\n"
            "       The API/worker virtualenvs ship fontTools but NOT brotli, so they cannot "
            "regenerate these files."
        )
    sys.exit(
        "error: fontTools is required to subset fonts but is not installed for "
        f"{sys.executable}.\n"
        "       Install it (python -m pip install --user fonttools brotli) and retry."
    )


def _cmap_codepoints(TTFont, path: Path) -> set[int]:
    font = TTFont(path, lazy=True)
    try:
        return set(font.getBestCmap())
    finally:
        font.close()


def _font_probe(TTFont, path: Path) -> tuple[int, int]:
    font = TTFont(path, lazy=True)
    try:
        return len(font.getBestCmap()), path.stat().st_size
    finally:
        font.close()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_source(app: str, filename: str, source_dir: Path | None, TTFont) -> Path:
    """Return the pristine full font for ``app``, caching it on first use."""
    target = APP_FONT_DIRS[app] / filename
    cache = SOURCE_CACHE_DIR / app / filename

    if cache.is_file():
        cmap_count, size = _font_probe(TTFont, cache)
        if cmap_count < FULL_FONT_MIN_CMAP or size < FULL_FONT_MIN_BYTES:
            sys.exit(
                f"error: cached source {cache.relative_to(REPO_ROOT)} does not look like a "
                f"full font (cmap={cmap_count}, bytes={size}).\n"
                "       Delete that file and restore the original from git history, then retry."
            )
        return cache

    if source_dir is not None:
        chosen = source_dir / filename
        if not chosen.is_file():
            sys.exit(
                f"error: --source-dir was given but {chosen} does not exist.\n"
                f"       It must contain {', '.join(name for _, name in FONT_FILES)}."
            )
    else:
        if not target.is_file():
            sys.exit(f"error: missing font {target.relative_to(REPO_ROOT)}.")
        cmap_count, size = _font_probe(TTFont, target)
        if cmap_count < FULL_FONT_MIN_CMAP or size < FULL_FONT_MIN_BYTES:
            sys.exit(
                f"error: no pristine full font for {target.relative_to(REPO_ROOT)} "
                f"(cmap={cmap_count}, bytes={size}) and no cached source.\n"
                "       The tracked file already looks like a subset, so re-subsetting it "
                "would drop glyphs added since the last run.\n"
                "       Restore the original from git history into "
                f"{SOURCE_CACHE_DIR.relative_to(REPO_ROOT)}/{app}/, or pass "
                "--source-dir DIR with the three full fonts.\n"
                "       Example:\n"
                f"         git show <full-font-commit>:apps/web/public/fonts/harmonyos/{filename} "
                f"> {SOURCE_CACHE_DIR.relative_to(REPO_ROOT)}/web/{filename}"
            )
        chosen = target

    cache.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(chosen, cache)
    cmap_count, size = _font_probe(TTFont, cache)
    if cmap_count < FULL_FONT_MIN_CMAP or size < FULL_FONT_MIN_BYTES:
        cache.unlink(missing_ok=True)
        sys.exit(
            f"error: {chosen} is not a full HarmonyOS Sans SC font "
            f"(cmap={cmap_count}, bytes={size}); refusing to cache it as a source."
        )
    print(f"cached full source {chosen.relative_to(REPO_ROOT)} -> {cache.relative_to(REPO_ROOT)}")
    return cache


def _subset(source: Path, destination: Path, charset_text: str) -> None:
    subset, TTFont = _import_fonttools()
    font = TTFont(source)
    try:
        options = subset.Options()
        options.flavor = "woff2"
        # Pin the prototype's behaviour instead of inheriting a fontTools default
        # that can change between releases.
        options.layout_features = ["*"]
        subsetter = subset.Subsetter(options=options)
        subsetter.populate(text=charset_text)
        subsetter.subset(font)
        destination.parent.mkdir(parents=True, exist_ok=True)
        font.save(destination)
    finally:
        font.close()


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def build_manifest(
    app: str,
    charset_list: list[int],
    sources: dict[str, object],
    files: list[dict[str, object]],
) -> dict[str, object]:
    total = sum(int(entry["bytes"]) for entry in files)
    latin_count = sum(1 for codepoint in charset_list if not is_cjk(codepoint))
    return {
        "schema_version": SCHEMA_VERSION,
        "app": app,
        "font_dir": APP_FONT_DIRS[app].relative_to(REPO_ROOT).as_posix(),
        "charset": {
            "codepoint_count": len(charset_list),
            "charset_sha256": charset_digest(charset_list),
            "ranges": codepoints_to_ranges(charset_list),
            "parts": {"latin": latin_count, "cjk": len(charset_list) - latin_count},
            "sources": sources,
        },
        "files": files,
        "totals": {"bytes": total},
        "budgets": {
            "max_latin_file_bytes": MAX_LATIN_FILE_BYTES,
            "max_cjk_file_bytes": MAX_CJK_FILE_BYTES,
            "max_app_bytes": MAX_APP_BYTES,
        },
    }


def write_json_atomic(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.chmod(handle.name, 0o644)
        os.replace(handle.name, path)
    except BaseException:
        Path(handle.name).unlink(missing_ok=True)
        raise


def _load_manifest(app: str) -> dict[str, object]:
    path = APP_FONT_DIRS[app] / MANIFEST_NAME
    if not path.is_file():
        sys.exit(
            f"error: {path.relative_to(REPO_ROOT)} is missing.\n"
            "       Run: python scripts/subset-portal-fonts.py"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.exit(
            f"error: {path.relative_to(REPO_ROOT)} is not valid JSON: {exc}.\n"
            "       Run: python scripts/subset-portal-fonts.py"
        )


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def describe_charset(charset: set[str]) -> None:
    cjk = required_cjk(charset)
    print(f"charset: {len(charset)} characters ({len(cjk)} CJK, GB2312 level 1+2 included)")


def command_check(charset: set[str]) -> int:
    expected = codepoints(charset)
    expected_digest = charset_digest(expected)
    parts = split_charset(charset)
    expected_role_codepoints = {
        role: {ord(char) for char in chars} for role, chars in parts.items()
    }
    problems: list[str] = []

    imported = _try_import_fonttools()
    verify_cmap = imported is not None
    TTFont = imported[1] if imported is not None else None
    role_index = {role: index for index, role in enumerate(FONT_ROLES)}
    expected_files = len(FONT_FILES) * len(FONT_ROLES)

    for app in APP_FONT_DIRS:
        manifest = _load_manifest(app)
        try:
            covered = ranges_to_codepoints(manifest["charset"]["ranges"])  # type: ignore[index]
        except (KeyError, TypeError, ValueError) as exc:
            problems.append(f"{app}: malformed manifest charset ranges ({exc})")
            continue

        missing = sorted(set(expected) - covered)
        if missing:
            sample = ", ".join(f"U+{codepoint:04X} {chr(codepoint)!r}" for codepoint in missing[:8])
            problems.append(
                f"{app}: manifest is stale; {len(missing)} character(s) used by the locale/UI "
                f"sources are not covered ({sample}). Run: python scripts/subset-portal-fonts.py"
            )
        if int(manifest["charset"]["codepoint_count"]) != len(expected):  # type: ignore[index]
            problems.append(f"{app}: charset.codepoint_count does not match the sources")
        if manifest["charset"]["charset_sha256"] != expected_digest:  # type: ignore[index]
            problems.append(
                f"{app}: charset.charset_sha256 does not match the sources. "
                "Run: python scripts/subset-portal-fonts.py"
            )
        parts_manifest = manifest["charset"].get("parts")  # type: ignore[union-attr]
        expected_parts = {
            role: len(chars) for role, chars in parts.items()
        }
        if parts_manifest != expected_parts:
            problems.append(
                f"{app}: charset.parts {parts_manifest!r} != expected {expected_parts!r}; "
                "Run: python scripts/subset-portal-fonts.py"
            )

        entries = manifest.get("files")
        if not isinstance(entries, list) or len(entries) != expected_files:
            problems.append(f"{app}: manifest must list exactly {expected_files} font files")
            continue

        weights = sorted(int(entry.get("weight", -1)) for entry in entries)
        expected_weights = sorted(
            weight for weight, _ in FONT_FILES for _ in FONT_ROLES
        )
        if weights != expected_weights:
            problems.append(
                f"{app}: manifest weights {weights} do not match {expected_weights}"
            )
        seen_roles: dict[int, set[str]] = {}
        for entry in entries:
            seen_roles.setdefault(int(entry.get("weight", -1)), set()).add(
                str(entry.get("role", ""))
            )
        for weight, seen in seen_roles.items():
            if seen != set(FONT_ROLES):
                problems.append(
                    f"{app}: weight {weight} must have role files {sorted(FONT_ROLES)}, "
                    f"manifest has {sorted(seen)}"
                )

        for entry in entries:
            filename = str(entry.get("file", ""))
            role = str(entry.get("role", ""))
            target = APP_FONT_DIRS[app] / filename
            if role not in FONT_ROLES:
                problems.append(f"{app}: {filename} has unknown role {role!r}")
                continue
            if not target.is_file():
                problems.append(f"{app}: missing font file {target.relative_to(REPO_ROOT)}")
                continue
            actual_bytes = target.stat().st_size
            if actual_bytes != int(entry.get("bytes", -1)):
                problems.append(
                    f"{app}: {filename} is {actual_bytes} bytes but the manifest says "
                    f"{entry.get('bytes')}. Run: python scripts/subset-portal-fonts.py"
                )
            budget = ROLE_BUDGET_BYTES[role]
            if actual_bytes > budget:
                problems.append(
                    f"{app}: {filename} is {actual_bytes} bytes (> {budget} for role {role}); "
                    "a full font was probably committed. Run: python scripts/subset-portal-fonts.py"
                )
            if _file_sha256(target) != entry.get("sha256"):
                problems.append(
                    f"{app}: {filename} sha256 does not match the manifest. "
                    "Run: python scripts/subset-portal-fonts.py"
                )
            if verify_cmap:
                actual_cmap = _cmap_codepoints(TTFont, target)
                declared_missing = {
                    int(codepoint) for codepoint in entry.get("missing_codepoints", [])
                }
                role_missing = sorted(
                    expected_role_codepoints[role] - actual_cmap - declared_missing
                )
                if role_missing:
                    sample = ", ".join(
                        f"U+{codepoint:04X} {chr(codepoint)!r}"
                        for codepoint in role_missing[:8]
                    )
                    problems.append(
                        f"{app}: {filename} lacks {len(role_missing)} required {role} "
                        f"character(s) ({sample}). Run: python scripts/subset-portal-fonts.py"
                    )

        total = sum(int(entry.get("bytes", 0)) for entry in entries)
        if total != int(manifest.get("totals", {}).get("bytes", -1)):  # type: ignore[union-attr]
            problems.append(f"{app}: totals.bytes does not equal the sum of file sizes")
        if total > MAX_APP_BYTES:
            problems.append(f"{app}: app font payload is {total} bytes (> {MAX_APP_BYTES})")

    if problems:
        print("font subset check FAILED:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    suffix = "" if verify_cmap else " (cmap verification skipped: fontTools/brotli unavailable)"
    print("font subset check OK" + suffix)
    return 0


def command_dry_run(charset: set[str]) -> int:
    print("\nplanned targets (no files will be written):")
    for app, font_dir in APP_FONT_DIRS.items():
        print(f"  [{app}] {font_dir.relative_to(REPO_ROOT)}")
        for weight, filename in FONT_FILES:
            for role in FONT_ROLES:
                output = role_filename(filename, role)
                target = font_dir / output
                current = target.stat().st_size if target.is_file() else -1
                state = "missing" if current < 0 else f"{current} B"
                print(f"    {weight:>3} {role:<5}  {output:<40} current={state}")
    print(
        "\nper-file budgets: "
        f"latin {MAX_LATIN_FILE_BYTES} B, cjk {MAX_CJK_FILE_BYTES} B; "
        f"per-app budget: {MAX_APP_BYTES} B; "
        f"source cache: {SOURCE_CACHE_DIR.relative_to(REPO_ROOT)}/"
    )
    return 0


def command_regenerate(
    charset: set[str], sources: dict[str, object], source_dir: Path | None
) -> int:
    _, TTFont = _import_fonttools()
    charset_list = codepoints(charset)
    parts = split_charset(charset)
    part_text = {
        role: "".join(sorted(chars, key=ord)) for role, chars in parts.items()
    }
    part_codepoints = {
        role: {ord(char) for char in chars} for role, chars in parts.items()
    }

    # app, weight, role, output filename, pristine source, staged file
    staging_jobs: list[tuple[str, int, str, str, Path, Path]] = []
    for app in APP_FONT_DIRS:
        for weight, filename in FONT_FILES:
            source = _ensure_source(app, filename, source_dir, TTFont)
            for role in FONT_ROLES:
                output = role_filename(filename, role)
                staged = STAGING_DIR / app / output
                print(f"subsetting {app}/{output} ...", flush=True)
                _subset(source, staged, part_text[role])
                cmap = _cmap_codepoints(TTFont, staged)
                missing = sorted(part_codepoints[role] - cmap)
                # The source font may legitimately lack a non-CJK symbol (e.g. the
                # keyboard glyphs U+2318/U+21B5). The browser then falls back to
                # the system stack; record those codepoints in the manifest instead
                # of failing. CJK coverage is non-negotiable: missing hanzi would
                # render as tofu, not fallback, because the CJK face matches.
                if missing and role == "cjk":
                    sample = ", ".join(
                        f"U+{codepoint:04X} {chr(codepoint)!r}" for codepoint in missing[:8]
                    )
                    sys.exit(
                        f"error: subset {app}/{output} lost {len(missing)} required CJK "
                        f"character(s) ({sample}); refusing to install it."
                    )
                staging_jobs.append((app, weight, role, output, source, staged))

    # Every subset succeeded: install atomically, then write the manifests.
    installed: dict[str, list[dict[str, object]]] = {app: [] for app in APP_FONT_DIRS}
    for app, weight, role, filename, source, staged in staging_jobs:
        target = APP_FONT_DIRS[app] / filename
        temp = target.with_name(f".{filename}.tmp-{os.getpid()}")
        try:
            shutil.copyfile(staged, temp)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        cmap = _cmap_codepoints(TTFont, target)
        installed[app].append(
            {
                "weight": weight,
                "role": role,
                "file": filename,
                "bytes": target.stat().st_size,
                "sha256": _file_sha256(target),
                "codepoint_count": len(cmap),
                # Role-scoped: the latin file legitimately lacks CJK glyphs and
                # vice versa, so only codepoints this role must cover count.
                "missing_codepoints": sorted(part_codepoints[role] - cmap),
                "source_bytes": source.stat().st_size,
                "source_sha256": _file_sha256(source),
            }
        )

    role_index = {role: index for index, role in enumerate(FONT_ROLES)}
    for app, entries in installed.items():
        entries.sort(key=lambda entry: (int(entry["weight"]), role_index[str(entry["role"])]))
        manifest = build_manifest(app, charset_list, sources, entries)
        write_json_atomic(APP_FONT_DIRS[app] / MANIFEST_NAME, manifest)

    print("\nwritten:")
    for app, entries in installed.items():
        total = sum(int(entry["bytes"]) for entry in entries)
        for entry in entries:
            print(
                f"  {app:<5} {entry['weight']:>3} {entry['role']:<5}  {entry['bytes']:>9} B  "
                f"({int(entry['source_bytes']) - int(entry['bytes'])} B saved)  {entry['file']}"
            )
        print(f"  {app:<5} total {total:>9} B  ({MANIFEST_NAME})")
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subset the HarmonyOS Sans SC woff2 files used by the admin console (latin + CJK per weight).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Character set: locale JSON strings + apps/*/src/**/*.{ts,tsx} text + "
            "GB2312 level 1+2 + printable ASCII.\n"
            "Requires fontTools and brotli (for woff2 output).\n\n"
            "Examples:\n"
            "  python scripts/subset-portal-fonts.py\n"
            "  python scripts/subset-portal-fonts.py --check\n"
            "  python scripts/subset-portal-fonts.py --dry-run\n"
            "  python scripts/subset-portal-fonts.py --source-dir /path/to/full/fonts\n"
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help=(
            "verify the tracked fonts and manifests without writing "
            "(fontTools is not required; cmap verification is skipped without it)"
        ),
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="print the target character set and file plan without writing anything",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        metavar="DIR",
        help=(
            "directory containing the three pristine full woff2 files "
            "(default: the first run caches the currently tracked full fonts under .cache/)"
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    charset, sources = collect_charset()
    describe_charset(charset)

    if args.check:
        return command_check(charset)
    if args.dry_run:
        return command_dry_run(charset)
    return command_regenerate(charset, sources, args.source_dir)


if __name__ == "__main__":
    raise SystemExit(main())
