"""Source-level regression tests for the actual admin guard entry point."""
from pathlib import Path

import pytest

from scripts import check_admin_content_architecture as guard

THEME_SOURCE = (guard.ADMIN_SRC / "lib/antd-theme.ts").read_text(encoding="utf-8")
MOTION_READ = """
const MOTION_STORAGE_KEY = "soymutdb-animation-prefs";
export function readMotionPreference() {
  if (typeof localStorage === "undefined") return "auto";
  try {
    return parseMotionPreference(localStorage.getItem(MOTION_STORAGE_KEY));
  } catch {
    // A malformed preference is equivalent to auto.
  }
  return "auto";
}
"""


@pytest.fixture
def source_tree(tmp_path, monkeypatch):
    src = tmp_path / "apps/admin/src"
    src.mkdir(parents=True)
    monkeypatch.setattr(guard, "ROOT", tmp_path)
    monkeypatch.setattr(guard, "ADMIN_SRC", src)
    return src


def put(src: Path, name: str, text: str) -> None:
    target = src / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_empty_scan_fails(source_tree, capsys):
    assert guard.main() == 1
    assert "scan is empty" in capsys.readouterr().err


@pytest.mark.parametrize("directory", [".umi", ".umi-production", ".umi-test", "dist", "build", "coverage", "node_modules"])
def test_generated_files_are_excluded(source_tree, directory):
    put(source_tree, "page.tsx", "export const Page = () => <main />;")
    put(source_tree, f"{directory}/nested/generated.tsx", "fetch('/probe');")
    assert len(guard.sources()) == 1
    assert guard.main() == 0


def test_new_and_modified_tsx_are_scanned(source_tree):
    put(source_tree, "new-page.tsx", "export const Page = () => <main />;")
    assert guard.main() == 0
    put(source_tree, "new-page.tsx", "fetch('/probe');")
    assert guard.main() == 1
    put(source_tree, "second-page.tsx", "sessionStorage.setItem('preferences', value);")
    assert len(guard.sources()) == 2
    assert guard.main() == 1


def test_audited_hex_theme_operations_pass(source_tree):
    put(source_tree, "lib/theme.ts", THEME_SOURCE)
    assert guard.main() == 0


@pytest.mark.parametrize("old,new", [
    ('"soymutdb-admin-primary-color"', '"preferences"'),
    ('/^#[0-9a-f]{6}$/i', '/.*/'),
    ('localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, normalized)',
     'localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, value)'),
    ('localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, normalized)',
     'localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, "eyJhbGciOiJIUzI1NiJ9.payload.signature")'),
    ('stored && isValidAdminPrimaryColor(stored)', 'stored'),
])
def test_changed_key_or_unvalidated_theme_values_fail(source_tree, old, new):
    assert old in THEME_SOURCE
    put(source_tree, "lib/theme.ts", THEME_SOURCE.replace(old, new))
    assert guard.main() == 1


@pytest.mark.parametrize("extra", [
    'const preference = "eyJhbGciOiJIUzI1NiJ9.payload.signature"; localStorage.setItem("color", preference);',
    'localStorage.setItem(ADMIN_PRIMARY_COLOR_STORAGE_KEY, credential);',
    'sessionStorage.setItem("layout", response.access_token);',
    'fetch("/api/v1/auth/me");',
])
def test_disguised_token_and_fetch_in_theme_file_still_fail(source_tree, extra):
    put(source_tree, "lib/theme.ts", THEME_SOURCE + "\n" + extra)
    assert guard.main() == 1


def test_theme_guard_removal_flips_actual_entry(source_tree):
    put(source_tree, "lib/theme.ts", THEME_SOURCE)
    assert guard.main() == 0
    mutant = THEME_SOURCE.replace('!isValidAdminPrimaryColor(value) || ', '')
    put(source_tree, "lib/theme.ts", mutant)
    assert guard.main() == 1
    put(source_tree, "lib/theme.ts", THEME_SOURCE)
    assert guard.main() == 0


@pytest.mark.parametrize("directory", ["App.tsx"])
def test_validator_wrapped_motion_preference_read_passes(source_tree, directory):
    put(source_tree, directory, MOTION_READ)
    assert guard.main() == 0


def test_motion_preference_read_by_key_literal_passes(source_tree):
    put(source_tree, "App.tsx", 'const p = parseMotionPreference(localStorage.getItem("soymutdb-animation-prefs"));')
    assert guard.main() == 0


@pytest.mark.parametrize("line", [
    'localStorage.setItem("soymutdb-animation-prefs", response.access_token);',
    'localStorage.setItem(MOTION_KEY, credential);',
    'const token = localStorage.getItem("soymutdb-animation-prefs");',
    'localStorage.getItem("preferences");',
    'localStorage.setItem(someComputedKey, value);',
    'sessionStorage.setItem("motion", preference);',
])
def test_unvalidated_or_disguised_storage_still_fails(source_tree, line):
    put(source_tree, "App.tsx", MOTION_READ + "\n" + line)
    assert guard.main() == 1


def test_removing_the_parser_wrapper_flips_the_motion_allowance(source_tree):
    put(source_tree, "App.tsx", MOTION_READ)
    assert guard.main() == 0
    put(source_tree, "App.tsx", MOTION_READ.replace("parseMotionPreference(localStorage.getItem(MOTION_STORAGE_KEY))",
                                                    "localStorage.getItem(MOTION_STORAGE_KEY)"))
    assert guard.main() == 1
    put(source_tree, "App.tsx", MOTION_READ)
    assert guard.main() == 0
