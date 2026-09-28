"""Standard-library tests for the artifact isolation guard."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import check_site_artifact_isolation as checker

ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "scripts" / "check_site_artifact_isolation.py"


class ArtifactIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.external, self.internal = root / "external", root / "internal"
        self.external.mkdir()
        self.internal.mkdir()
        # OPT-07: the external variant must keep a top-level entry document,
        # symmetric with the internal `*.html` requirement in the verifier.
        (self.external / "index.html").write_text("public", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_checker(self, *sentinels: str) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(CHECKER),
            "--external-root",
            str(self.external),
            "--internal-root",
            str(self.internal),
        ]
        for sentinel in sentinels:
            command.extend(("--sentinel", sentinel))
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_clean_and_generic_field_label_pass(self) -> None:
        (self.external / "index.html").write_text(
            "public_id internal_id", encoding="utf-8"
        )
        result = self.run_checker("PRIVATE-001")
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_nested_text_and_binary_hits_are_relative_and_secret_free(self) -> None:
        nested = self.external / "nested"
        nested.mkdir()
        (nested / "page.json").write_text("SECRET-42", encoding="utf-8")
        (self.external / "chunk.bin").write_bytes(b"\x00SECRET-42\xff")
        result = self.run_checker("SECRET-42")
        self.assertEqual(result.returncode, 1)
        self.assertIn("nested/page.json", result.stderr)
        self.assertIn("chunk.bin", result.stderr)
        self.assertNotIn("SECRET-42", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_multiple_sentinels_are_deterministic(self) -> None:
        (self.external / "z.txt").write_text("FIRST", encoding="utf-8")
        (self.external / "a.txt").write_text("SECOND", encoding="utf-8")
        first = self.run_checker("FIRST", "SECOND")
        second = self.run_checker("FIRST", "SECOND")
        self.assertEqual(first.returncode, 1)
        self.assertEqual(second.returncode, 1)
        self.assertEqual(first.stderr, second.stderr)
        self.assertLess(first.stderr.index("a.txt"), first.stderr.index("z.txt"))
        self.assertNotIn("FIRST", first.stderr)
        self.assertNotIn("SECOND", first.stderr)

    def test_sentinel_in_path_is_redacted(self) -> None:
        directory = self.external / "dir-SECRET-NAME"
        directory.mkdir()
        (directory / "file-SECRET-NAME.json").write_text("clean", encoding="utf-8")
        result = self.run_checker("SECRET-NAME")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<sentinel-1>", result.stderr)
        self.assertNotIn("SECRET-NAME", result.stderr)

    def test_invalid_or_overlapping_configuration_fails_closed(self) -> None:
        missing = self.external / "missing"
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = checker.main(
                [
                    "--external-root",
                    str(missing),
                    "--internal-root",
                    str(self.internal),
                    "--sentinel",
                    "X",
                ]
            )
        self.assertEqual(exit_code, 2)
        self.assertIn("invalid artifact isolation configuration", stderr.getvalue())
        self.assertEqual(self.run_checker("").returncode, 2)
        self.assertIsNotNone(checker._validate_sentinels(["\x00"]))
        nested_internal = self.external / "internal-child"
        nested_internal.mkdir()
        self.assertIsNotNone(checker._validate_roots(self.external, nested_internal))

        nested_external = self.internal / "external-child"
        nested_external.mkdir()
        self.assertIsNotNone(checker._validate_roots(nested_external, self.internal))

    def test_external_symlink_is_rejected_without_following_outside(self) -> None:
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("PRIVATE", encoding="utf-8")
        (self.external / "outside-link").symlink_to(outside, target_is_directory=True)
        result = self.run_checker("PRIVATE")
        self.assertEqual(result.returncode, 1)
        self.assertIn("symlink not allowed", result.stderr)
        self.assertNotIn("PRIVATE", result.stderr)

    def test_missing_external_entry_html_fails_closed(self) -> None:
        # OPT-07 red-before: the legacy checker only scanned sentinels, so a
        # deleted external/index.html still exited 0; the internal entry was
        # ACTIVE while the external one was INERT (asymmetric).
        (self.external / "index.html").unlink()
        nested = self.external / "nested"
        nested.mkdir()
        (nested / "index.html").write_text("public", encoding="utf-8")
        result = self.run_checker("PRIVATE-001")
        self.assertEqual(result.returncode, 1)
        self.assertIn("FAIL", result.stderr)
        self.assertIn("HTML entry", result.stderr)
        self.assertEqual(result.stdout, "")
        # green-after control: restoring the top-level entry passes.
        (self.external / "index.html").write_text("public", encoding="utf-8")
        self.assertEqual(self.run_checker("PRIVATE-001").returncode, 0)

    def test_missing_html_entry_helper(self) -> None:
        (self.external / "index.html").unlink()
        self.assertIsNotNone(checker.missing_html_entry(self.external))
        (self.external / "index.html").write_text("public", encoding="utf-8")
        self.assertIsNone(checker.missing_html_entry(self.external))

    def test_default_sentinel_set_is_shared_and_covers_internal_origin(self) -> None:
        # OPT-08 red-before: the verifier's single noindex sentinel let a
        # leaked internal origin through. The default set is a named constant
        # shared with the shell gate instead of a private literal.
        self.assertIn("noindex, nofollow, noarchive", checker.DEFAULT_SENTINELS)
        self.assertIn("internal.soymutdb.invalid", checker.DEFAULT_SENTINELS)
        printed = subprocess.run(
            [sys.executable, str(CHECKER), "--print-default-sentinels"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(printed.returncode, 0)
        self.assertEqual(printed.stdout.splitlines(), list(checker.DEFAULT_SENTINELS))
        (self.external / "index.html").write_text(
            "public internal.soymutdb.invalid", encoding="utf-8"
        )
        # Backward compatibility: an explicit single sentinel still scans only
        # that value rather than silently widening to the defaults.
        self.assertEqual(self.run_checker("noindex, nofollow, noarchive").returncode, 0)
        self.assertEqual(self.run_checker(*checker.DEFAULT_SENTINELS).returncode, 1)
        # Omitting --sentinel falls back to the shared default set.
        self.assertEqual(self.run_checker().returncode, 1)

    def test_sentinel_in_empty_directory_name_is_reported(self) -> None:
        # OPT-09 red-before: the path check ran inside the file loop, so an
        # EMPTY directory whose name carried the sentinel exited 0.
        (self.external / "dir-SECRET-NAME").mkdir()
        result = self.run_checker("SECRET-NAME")
        self.assertEqual(result.returncode, 1)
        self.assertIn("directory path", result.stderr)
        self.assertIn("<sentinel-1>", result.stderr)
        self.assertNotIn("SECRET-NAME", result.stderr)

    def test_directory_hit_not_duplicated_for_file_inside(self) -> None:
        directory = self.external / "SECRET-NAME"
        directory.mkdir()
        (directory / "page.json").write_text("clean", encoding="utf-8")
        result = self.run_checker("SECRET-NAME")
        self.assertEqual(result.returncode, 1)
        # The file path already redacts the sentinel, so the directory must
        # not add a second diagnostic for the same location.
        self.assertNotIn("directory path", result.stderr)
        self.assertEqual(result.stderr.count("<sentinel-1>"), 1)


if __name__ == "__main__":
    unittest.main()
