"""Guard the self-hosted HarmonyOS Sans SC subsets (admin + genome browser).

The admin console and the standalone genome browser ship, per weight, a small
``-latin`` woff2 (ASCII + Western symbols) and a ``-cjk`` woff2 (hanzi +
CJK/fullwidth punctuation, fetched only when CJK glyphs render), plus a
``subset-manifest.json``. The admin console preloads the latin Regular face; the
genome browser declares the faces without a preload. The public portal
deliberately uses the system CJK stack and must not re-introduce a HarmonyOS
``@font-face`` or a font preload.

What fails here, and why it matters:

* a manifest that is missing, stale, or internally inconsistent;
* a Chinese string added to a locale bundle (or to ``apps/*/src``) whose
  characters are not covered by the CJK subset -- regenerate the fonts;
* a font file replaced with the original full 4.3 MB file, or an app payload
  above 3.0 MiB -- that reintroduces the payload this work removed;
* the portal re-adding a font preload/@font-face for a font its CSS never uses.

The character set is read from the generator module itself, so the two cannot
drift; fontTools is optional (cmap checks are skipped without it, as on CI).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "subset-portal-fonts.py"


def _generator():
    spec = importlib.util.spec_from_file_location("subset_portal_fonts", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GEN = _generator()
MANIFEST_NAME = GEN.MANIFEST_NAME
SCHEMA_VERSION = GEN.SCHEMA_VERSION
REGENERATE = "run `python scripts/subset-portal-fonts.py` (requires fontTools + brotli)"

# Hard ceilings mirror the generator and the original subset work.
MAX_LATIN_FILE_BYTES = GEN.MAX_LATIN_FILE_BYTES
MAX_CJK_FILE_BYTES = GEN.MAX_CJK_FILE_BYTES
MAX_APP_BYTES = GEN.MAX_APP_BYTES


def _manifest_path(app: str) -> pathlib.Path:
    return GEN.APP_FONT_DIRS[app] / MANIFEST_NAME


def _load_manifest(app: str) -> dict:
    path = _manifest_path(app)
    assert path.is_file(), f"{path.relative_to(REPO_ROOT)} is missing; {REGENERATE}"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:  # pragma: no cover - corrupt file only
        raise AssertionError(
            f"{path.relative_to(REPO_ROOT)} is not valid JSON ({exc}); {REGENERATE}"
        ) from exc


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_charset() -> set[str]:
    charset, _sources = GEN.collect_charset()
    return charset


def _manifest_covered(manifest: dict) -> set[int]:
    return GEN.ranges_to_codepoints(manifest["charset"]["ranges"])


def test_only_admin_and_jbrowse_self_host_harmonyos() -> None:
    """The portal uses the system CJK stack; keep its bytes out of the artifact."""
    assert set(GEN.APP_FONT_DIRS) == {"admin", "jbrowse"}
    assert not (REPO_ROOT / "apps/web/public/fonts").exists(), (
        "apps/web/public/fonts is back; the portal CSS declares no HarmonyOS "
        "@font-face, so shipping these files only bloats the artifact"
    )
    web_css = (REPO_ROOT / "apps/web/src/index.css").read_text(encoding="utf-8")
    assert "@font-face" not in web_css, (
        "the portal CSS re-introduced @font-face; update docs/dev/font-subsetting.md "
        "and the generator/guard (admin vs portal font policy)"
    )
    web_config = (REPO_ROOT / "apps/web/config/config.ts").read_text(encoding="utf-8")
    assert "fonts/harmonyos" not in web_config, (
        "the portal config preloads a HarmonyOS font its CSS never uses"
    )


def test_admin_and_jbrowse_css_declare_split_faces_with_unicode_range() -> None:
    for app in GEN.APP_FONT_DIRS:
        css = (REPO_ROOT / "apps" / app / "src" / "index.css").read_text(encoding="utf-8")
        for _weight, filename in GEN.FONT_FILES:
            for role in GEN.FONT_ROLES:
                split = GEN.role_filename(filename, role)
                assert split in css, f"{app} CSS must declare {split}"
        assert len(re.findall(r"^\s*unicode-range:", css, re.M)) == (
            len(GEN.FONT_FILES) * len(GEN.FONT_ROLES)
        ), f"{app} CSS must give every split face a unicode-range"
    # The admin preload must be the small latin face, never the CJK file. The
    # genome browser declares the faces and relies on `font-display: swap`
    # instead of a preload.
    admin_config = (REPO_ROOT / "apps/admin/config/config.ts").read_text(encoding="utf-8")
    assert "HarmonyOS-Sans-SC-Regular-latin.woff2" in admin_config
    assert "HarmonyOS-Sans-SC-Regular-cjk.woff2" not in admin_config
    jbrowse_config = (REPO_ROOT / "apps/jbrowse/config/config.ts").read_text(encoding="utf-8")
    assert "fonts/harmonyos" not in jbrowse_config



def test_manifest_covers_the_collected_charset() -> None:
    expected = _expected_charset()
    expected_codepoints = {ord(char) for char in expected}
    expected_digest = GEN.charset_digest(GEN.codepoints(expected))
    parts = GEN.split_charset(expected)

    for app in GEN.APP_FONT_DIRS:
        manifest = _load_manifest(app)
        covered = _manifest_covered(manifest)

        assert manifest.get("schema_version") == SCHEMA_VERSION, (
            f"{app}: unsupported manifest schema {manifest.get('schema_version')!r}; {REGENERATE}"
        )
        assert manifest.get("app") == app
        assert manifest.get("font_dir") == GEN.APP_FONT_DIRS[app].relative_to(REPO_ROOT).as_posix()
        assert manifest["charset"].get("codepoint_count") == len(expected), (
            f"{app}: charset.codepoint_count is stale; {REGENERATE}"
        )
        assert manifest["charset"].get("charset_sha256") == expected_digest, (
            f"{app}: charset sha256 is stale; {REGENERATE}"
        )
        assert covered == expected_codepoints, (
            f"{app}: manifest ranges do not match the collected charset; {REGENERATE}"
        )
        assert manifest["charset"].get("parts") == {
            "latin": len(parts["latin"]),
            "cjk": len(parts["cjk"]),
        }, f"{app}: charset.parts is stale; {REGENERATE}"


def test_font_files_match_the_manifest_and_budgets() -> None:
    expected_roles = set(GEN.FONT_ROLES)
    for app in GEN.APP_FONT_DIRS:
        manifest = _load_manifest(app)
        font_dir = GEN.APP_FONT_DIRS[app]
        entries = manifest.get("files")
        assert isinstance(entries, list), f"{app}: manifest files must be a list; {REGENERATE}"
        assert len(entries) == len(GEN.FONT_FILES) * len(GEN.FONT_ROLES), (
            f"{app}: manifest must list {len(GEN.FONT_FILES) * len(GEN.FONT_ROLES)} files; "
            f"{REGENERATE}"
        )
        by_weight: dict[int, set[str]] = {}
        total = 0
        for entry in entries:
            weight = int(entry["weight"])
            role = str(entry["role"])
            filename = str(entry["file"])
            assert role in expected_roles, f"{app}: unknown role {role!r}"
            assert filename == GEN.role_filename(dict(GEN.FONT_FILES)[weight], role), (
                f"{app}: {filename} does not follow the <weight>-<role> naming; {REGENERATE}"
            )
            by_weight.setdefault(weight, set()).add(role)
            target = font_dir / filename
            assert target.is_file(), f"{app}: missing {target.relative_to(REPO_ROOT)}; {REGENERATE}"
            actual_bytes = target.stat().st_size
            total += actual_bytes
            budget = (
                MAX_LATIN_FILE_BYTES if role == "latin" else MAX_CJK_FILE_BYTES
            )
            assert actual_bytes <= budget, (
                f"{app}: {filename} is {actual_bytes} bytes, above the {budget}-byte "
                f"{role} budget; a full font was probably committed. {REGENERATE}"
            )
            assert actual_bytes == int(entry["bytes"]), (
                f"{app}: {filename} is {actual_bytes} bytes but the manifest says "
                f"{entry['bytes']}; {REGENERATE}"
            )
            assert entry.get("sha256") == _sha256(target), (
                f"{app}: {filename} sha256 does not match the manifest; {REGENERATE}"
            )
            assert int(entry.get("source_bytes", 0)) > actual_bytes
            missing = set(entry.get("missing_codepoints", []))
            assert isinstance(entry.get("missing_codepoints", []), list)
            if role == "cjk":
                assert not missing, (
                    f"{app}: {filename} reports missing CJK codepoints "
                    f"{sorted(missing)[:8]}; {REGENERATE}"
                )
        for weight, roles in by_weight.items():
            assert roles == expected_roles, (
                f"{app}: weight {weight} must have {sorted(expected_roles)}, has {sorted(roles)}"
            )
        assert manifest.get("totals", {}).get("bytes") == total
        assert total <= MAX_APP_BYTES, f"{app}: font payload {total} > {MAX_APP_BYTES}"
        budgets = manifest.get("budgets", {})
        assert budgets.get("max_latin_file_bytes", MAX_LATIN_FILE_BYTES + 1) <= MAX_LATIN_FILE_BYTES
        assert budgets.get("max_cjk_file_bytes", MAX_CJK_FILE_BYTES + 1) <= MAX_CJK_FILE_BYTES


def test_cmap_covers_required_characters_when_fonttools_is_available() -> None:
    imported = GEN._try_import_fonttools()
    if imported is None:
        return
    _subset, TTFont = imported
    expected = _expected_charset()
    parts = GEN.split_charset(expected)

    for app in GEN.APP_FONT_DIRS:
        manifest = _load_manifest(app)
        font_dir = GEN.APP_FONT_DIRS[app]
        for entry in manifest["files"]:
            role = str(entry["role"])
            target = font_dir / str(entry["file"])
            cmap = GEN._cmap_codepoints(TTFont, target)
            declared_missing = {int(codepoint) for codepoint in entry.get("missing_codepoints", [])}
            expected_codepoints = {ord(char) for char in parts[role]}
            lost = expected_codepoints - cmap - declared_missing
            assert not lost, (
                f"{app}/{entry['file']} lacks {len(lost)} required {role} character(s) "
                f"({sorted(lost)[:8]}); {REGENERATE}"
            )
