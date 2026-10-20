#!/usr/bin/env python3
"""Regression coverage for the artifact build-path guard.

The PDF viewer regression that motivated the guard shipped
`file:///home/<builder>/.../node_modules/pdfjs-dist/...` inside an async chunk.
These tests pin the detector and prove a clean artifact passes.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import check_artifact_build_paths as guard  # noqa: E402


class ArtifactBuildPathTests(unittest.TestCase):
    def _write(self, directory: Path, name: str, body: str) -> Path:
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def test_clean_artifact_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "assets/a.js", 'var worker="/pdf.worker.min.mjs";')
            self.assertEqual(guard.find_leaks(Path(tmp)), [])

    def test_file_url_leak_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(
                Path(tmp),
                "assets/a.js",
                'new URL(".", "file:///home/builder/project/node_modules/pdfjs-dist/build/pdf.mjs")',
            )
            leaks = guard.find_leaks(Path(tmp))
            self.assertTrue(leaks, "file:/// host path must fail the guard")

    def test_repository_root_is_detected_even_without_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "assets/a.js", f'const p="{guard.REPO_ROOT}/apps/web";')
            self.assertTrue(guard.find_leaks(Path(tmp)))

    def test_mnt_and_users_paths_are_detected(self) -> None:
        for needle in ("/mnt/data02/workspace/x", "/Users/builder/x", "C:\\\\Users\\\\builder\\\\x"):
            with tempfile.TemporaryDirectory() as tmp:
                self._write(Path(tmp), "assets/a.js", f'const p="{needle}";')
                self.assertTrue(guard.find_leaks(Path(tmp)), needle)

    def test_non_artifact_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self._write(Path(tmp), "assets/a.txt", "file:///home/builder/x")
            self.assertEqual(guard.find_leaks(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
