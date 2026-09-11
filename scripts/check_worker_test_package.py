#!/usr/bin/env python3
"""Guard the worker test package marker.

Regression
    Once the PostgreSQL service actually worked, the worker suite failed during
    *collection* -- before a single test ran:

        apps/worker/tests/test_gene_resolution.py:25: in <module>
            from tests.test_module_tsv_postgres_integration import postgres_engine
        E   ModuleNotFoundError: No module named 'tests.test_module_tsv_postgres_integration'

    ``test_gene_resolution.py`` reuses the shared integration fixture by its
    package path. That import only resolves when ``apps/worker/tests`` is an
    importable package that sits on ``sys.path`` as ``tests``. Pytest's default
    ``prepend`` import mode puts the *test directory* on ``sys.path`` and
    imports each file as a top-level module, which is enough for a single file
    but not for a cross-module import.

Why it stayed hidden
    Nothing ever ran this module: the stage could not reach a database at all,
    so the whole file was skipped behind the Testcontainers failure. A fix that
    only made PostgreSQL reachable would have traded 116 errors for one
    collection error, and collection errors abort the run -- so the rest of the
    worker suite would not have executed at all.

What is asserted
    * ``apps/worker/tests/__init__.py`` exists and is tracked by git (a file
      that is only in the working tree disappears from a CI checkout -- the
      repository already lost ``.cnb/env/`` to an unanchored ``.gitignore``).
    * Every ``from tests.<module> import`` in the worker suite names a module
      that exists.
    * The import target is genuinely resolvable under the import mode pytest
      actually uses, reproduced directly (it is not the repository root, and
      assuming it was is what made the first version of this check fail).

Run: python3 scripts/check_worker_test_package.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKER_TESTS = ROOT / "apps" / "worker" / "tests"
PACKAGE_MARKER = WORKER_TESTS / "__init__.py"
CROSS_IMPORT = re.compile(r"^\s*from\s+tests\.([\w.]+)\s+import", re.M)


def git_available() -> bool:
    """Whether a `git` executable can be resolved at all.

    A missing prerequisite must never read as a pass, so the caller reports the
    skipped tracked-state check instead of letting `subprocess.run` raise.
    """
    return shutil.which("git") is not None


def fail(message: str) -> int:
    print(f"worker test package check FAILED: {message}", file=sys.stderr)
    return 1


def main() -> int:
    if not PACKAGE_MARKER.is_file():
        return fail(
            f"{PACKAGE_MARKER.relative_to(ROOT)} is missing; `from tests.<module> "
            "import ...` cannot resolve and collection aborts"
        )

    if git_available():
        tracked = subprocess.run(
            ["git", "ls-files", "--cached", "--error-unmatch", str(PACKAGE_MARKER)],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        if tracked.returncode != 0:
            return fail(
                f"{PACKAGE_MARKER.relative_to(ROOT)} exists but is not tracked by git; "
                "a CI checkout would not have it"
            )
    else:
        # No git in this environment (a tarball checkout, or a minimal runner
        # image). The tracked-state claim cannot be made here, but it must not
        # be reported as a pass either: a swallowed FileNotFoundError would turn
        # a missing prerequisite into a green gate, which is exactly the failure
        # mode this check exists to prevent. Say so and keep checking what can
        # still be checked.
        print(
            "worker test package check: git is unavailable, so the "
            f"{PACKAGE_MARKER.relative_to(ROOT)} tracked-state check is SKIPPED "
            "for this run",
            file=sys.stderr,
        )

    imported: set[str] = set()
    for path in sorted(WORKER_TESTS.glob("test_*.py")):
        for match in CROSS_IMPORT.finditer(path.read_text(encoding="utf-8")):
            module = match.group(1).split(".")[0]
            imported.add(module)
            target = WORKER_TESTS / f"{module}.py"
            if not target.is_file():
                return fail(
                    f"{path.relative_to(ROOT)} imports tests.{match.group(1)} "
                    f"but {target.relative_to(ROOT)} does not exist"
                )
            # The imported module must itself be collected as a test module, or
            # a "reuse the fixture" import would silently come from a non-test.
            if not target.name.startswith("test_"):
                return fail(
                    f"{path.relative_to(ROOT)} imports tests.{match.group(1)}, "
                    "which is not a test module"
                )

    # Prove the resolution the gate actually performs, not just that the files
    # are present. pytest's `prepend` import mode derives the package name from
    # the first directory *without* an `__init__.py` above the test file, and
    # puts its parent on sys.path. For apps/worker/tests/*.py that directory is
    # apps/worker (which has no __init__.py), so the package must be importable
    # as `tests` with apps/worker on sys.path. Reproduce exactly that, rather
    # than a convenient-but-different path.
    probe = (
        "import importlib.util as u, sys;"
        "mods = sys.argv[1:];"
        "missing = [m for m in mods if u.find_spec('tests.' + m) is None];"
        "print('resolved from:', sys.path[0]);"
        "print('missing:', missing);"
        "sys.exit(1 if missing else 0)"
    )
    resolved = subprocess.run(
        [sys.executable, "-c", probe, *sorted(imported)],
        cwd=WORKER_TESTS.parent,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(WORKER_TESTS.parent), "PATH": "/usr/bin:/bin"},
    )
    if resolved.returncode != 0:
        return fail(
            "cross-module imports do not resolve with PYTHONPATH=<repo root>:\n"
            f"{resolved.stdout}{resolved.stderr}"
        )

    print(
        "worker test package check passed "
        f"({len(imported)} cross-module import(s): {', '.join(sorted(imported)) or 'none'})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
