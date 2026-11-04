"""Regression tests for the api-client base-path guard.

PR #117 shipped ``BASE = "/api/v1/tools/sequence"`` while ``buildUrl`` already
prepends the base; all nine operations resolved to a doubled prefix. This test
pins the guard's behaviour against synthetic trees so weakening it turns red.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "check_api_client_base_path",
    Path(__file__).resolve().parent / "check_api_client_base_path.py",
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def clean_tree(tmp_path: Path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "tools.ts").write_text(
        'import { request } from "./client";\n'
        'const BASE = "/tools/sequence";\n'
        'export const get = () => request(`${BASE}/capabilities`, {});\n',
        encoding="utf-8",
    )
    return src


def test_clean_tree_passes(tmp_path: Path) -> None:
    assert guard.inspect(guard.collect(clean_tree(tmp_path))) == []


def test_doubled_base_constant_is_rejected(tmp_path: Path) -> None:
    src = clean_tree(tmp_path)
    (src / "tools.ts").write_text(
        'import { request } from "./client";\n'
        'const BASE = "/api/v1/tools/sequence";\n'
        'export const get = () => request(`${BASE}/capabilities`, {});\n',
        encoding="utf-8",
    )
    failures = guard.inspect(guard.collect(src))
    assert failures, "a doubled /api/v1 BASE must fail the guard"
    assert any("/api/v1" in f and "BASE" in f for f in failures)


def test_doubled_literal_is_rejected(tmp_path: Path) -> None:
    src = clean_tree(tmp_path)
    (src / "tools.ts").write_text(
        'import { request } from "./client";\n'
        'export const get = () => request("/api/v1/tools/sequence/stats", {});\n',
        encoding="utf-8",
    )
    failures = guard.inspect(guard.collect(src))
    assert any("request path" in f for f in failures)


def test_absolute_url_is_allowed(tmp_path: Path) -> None:
    src = clean_tree(tmp_path)
    (src / "tools.ts").write_text(
        'export const get = () => request("https://api.test/tools/x", {});\n',
        encoding="utf-8",
    )
    assert guard.inspect(guard.collect(src)) == []


def test_comments_and_test_files_are_ignored(tmp_path: Path) -> None:
    src = clean_tree(tmp_path)
    (src / "tools.ts").write_text(
        '// request("/api/v1/x", {});\n'
        'export const get = () => request("/tools/x", {});\n',
        encoding="utf-8",
    )
    (src / "tools.test.ts").write_text(
        'request("/api/v1/should-be-ignored", {});\n', encoding="utf-8"
    )
    assert guard.inspect(guard.collect(src)) == []


def test_self_test_stays_green() -> None:
    assert guard.self_test() == 0


def test_block_comments_do_not_shift_reported_line_numbers(tmp_path: Path) -> None:
    """A guard that tells you where to fix must point at the real line.

    ``strip_comments`` used to delete block comments *with their newlines*;
    diagnostics are numbered on the stripped text, so every line after a
    multi-line comment was reported too high. This pins the exact coordinates.
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "tools.ts").write_text(
        "/**\n"
        " * Block comment\n"
        " * spanning lines\n"
        " */\n"
        'const BASE = "/api/v1/tools/sequence";\n'
        "                                           // inline\n"
        "function post(path: string) {\n"
        "  return request(`${BASE}${path}`, {});\n"
        "}\n",
        encoding="utf-8",
    )
    failures = guard.inspect(guard.collect(src))
    assert any("tools.ts:5:" in f and "BASE" in f for f in failures), failures
    assert any("tools.ts:8:" in f and "request path" in f for f in failures), failures
