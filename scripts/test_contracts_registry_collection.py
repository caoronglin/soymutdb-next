"""Regression coverage for the contracts-layer registry/collection guard.

The guard itself is stdlib-only and runs before pytest is guaranteed. These
tests are collected by the contracts layer (and by a plain pytest run over
scripts/) and prove the guard's failure directions on synthetic input,
without depending on the real tree's exact suite count. The CI-side wiring
is asserted against the committed ``ci-job-steps.sh`` bytes so a hand-merge
that drops the ``--self-test`` line is caught here too.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD_PATH = ROOT / "scripts" / "check_contracts_registry_collection.py"

spec = importlib.util.spec_from_file_location(
    "check_contracts_registry_collection", GUARD_PATH
)
assert spec and spec.loader
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

REQUIRED = sorted(guard.REQUIRED_GUARD_CALLS)

# Independent reviewed floor on the guard's own --self-test case count. This
# is a SECOND file: the guard prints a count measured from emitted results, so
# a shortened case loop shrinks the number and its evidence together. The teeth
# guard does not audit this guard (its success signature says ``cases``, not
# ``mutations``), and the plain run never reads the self-test output. Only a
# collected, independent literal can name a shrunken loop. Keep in step with
# ``check_contracts_registry_collection._REVIEWED_CASE_FLOOR``; raise both in
# one reviewed commit when a case is added, and say why. 49 -> 50: one
# decisive plant for the async-``TestCase`` no-op green.
_EXPECTED_SELF_TEST_CASES = 50


# Exercises the *process* exit code of the canonical ``--self-test`` entry,
# not just the in-process ``self_test()`` return value. A caller that discards
# ``self_test()``'s return (e.g. ``import ...; g.self_test()``) prints the drift
# yet exits 0, so the only safe assertion is on the real subprocess rc.
_RC_DRIVER = r"""
import importlib.util, sys
spec = importlib.util.spec_from_file_location("g", sys.argv[1])
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
smoke, ci, files = g.load_sources()
if sys.argv[2] == "drift":
    slot = "    scripts/test_mcp_release_binding_wiring.py\n"
    assert slot in smoke, "array slot missing"
    smoke = smoke.replace(
        slot, "    scripts/check_mcp_release_binding.py --self-test\n" + slot, 1
    )
g.load_sources = lambda: (smoke, ci, files)
g.sys.argv = ["g", "--self-test"]
raise SystemExit(g.main())
"""

CI_OK = (
    "smoke_contracts_run() {\n"
    f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
    '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
    "}\n"
)


def _smoke(entries: list[str], calls: list[str]) -> str:
    lines = ["smoke_contracts() {", "  local tests=("]
    lines += [f"    {e}" for e in entries]
    lines.append("  )")
    for call in calls:
        lines.append('  "${PYTHON_BIN}" ' + call + ' || rc=$?')
    lines.append('  "${PYTHON_BIN}" -m pytest "${tests[@]}" -q || rc=$?')
    lines += ["}", ""]
    return "\n".join(lines)


def _files() -> dict[str, str]:
    return {c: "# guard\n" for c in REQUIRED}


class RegistryCollectionGuardTests(unittest.TestCase):
    def test_clean_registry_passes(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        self.assertEqual(guard.check(smoke, files, CI_OK), [])

    def test_phantom_entry_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py", "scripts/test_phantom.py"], REQUIRED
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        files["scripts/test_phantom.py"] = "def helper():\n    return 1\n"
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(any("no collectible test" in f for f in failures), failures)

    def test_missing_registry_file_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_gone.py"], REQUIRED)
        failures = guard.check(smoke, _files(), CI_OK)
        self.assertTrue(any("does not exist" in f for f in failures), failures)

    def test_duplicate_entry_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py", "scripts/test_example.py"], REQUIRED
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(any("duplicate" in f for f in failures), failures)

    def test_dropped_guard_call_is_caught(self) -> None:
        smoke = _smoke(
            ["scripts/test_example.py"], ["scripts/check-toolchain-pins.py"]
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(any("was dropped" in f for f in failures), failures)

    def test_guard_call_floor_covers_the_committed_layer(self) -> None:
        """A wired guard outside the floor can be dropped with a green SMOKE PASS."""
        smoke_bytes, _ci, _files = guard.load_sources()
        wired = set(guard.guard_calls(smoke_bytes))
        self.assertEqual(
            wired,
            set(guard.REQUIRED_GUARD_CALLS),
            "standalone guard calls and REQUIRED_GUARD_CALLS drifted apart: "
            "a wired-but-unpinned call is removable without a red layer",
        )

    def test_dropping_a_newly_landed_guard_call_is_caught(self) -> None:
        """The inline-body pin landed outside the original floor."""
        smoke_bytes, ci_bytes, files = guard.load_sources()
        victim = "scripts/check_openapi_inline_body_integrity.py"
        self.assertIn(victim, guard.REQUIRED_GUARD_CALLS)
        dropped = "\n".join(
            line for line in smoke_bytes.splitlines() if victim not in line
        ) + "\n"
        self.assertNotEqual(dropped, smoke_bytes)
        failures = guard.check(dropped, files, ci_bytes)
        self.assertTrue(
            any("was dropped" in f and victim in f for f in failures), failures
        )

    def test_wired_guard_outside_the_floor_is_caught(self) -> None:
        """Adding a call without pinning it is the drift that reopens the hole."""
        smoke = _smoke(["scripts/test_example.py"], REQUIRED + [
            "scripts/check_extra_wiring_probe.py"
        ])
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        files["scripts/check_extra_wiring_probe.py"] = "# guard\n"
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(
            any("is wired but not pinned" in f for f in failures), failures
        )

    def test_guard_call_without_file_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        files.pop("scripts/check_nginx_security_headers.py")
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(any("does not exist" in f for f in failures), failures)

    def test_driver_registry_failure_must_propagate(self) -> None:
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        body = _smoke(["scripts/test_example.py"], REQUIRED)
        prefix = (
            guard.DRIVER_MARKER
            + "\n"
            + '  "${PYTHON_BIN}" scripts/check_contracts_registry_collection.py '
        )
        suffix = "\n  run_layer contracts smoke_contracts\nfi\n\n"
        swallowed = guard.check(prefix + "|| rc=$?" + suffix + body, files)
        self.assertTrue(any("not propagated" in f for f in swallowed), swallowed)
        propagated = guard.check(
            prefix + '|| FAILED+=("contracts registry")' + suffix + body, files
        )
        self.assertEqual(propagated, [])

    def test_unittest_style_suite_counts_as_collectible(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = (
            "import unittest\n\nclass T(unittest.TestCase):\n"
            "    def test_case(self):\n        self.assertTrue(True)\n"
        )
        failures = guard.check(smoke, files, CI_OK)
        self.assertFalse(
            any("no collectible test" in f for f in failures), failures
        )

    def test_ci_self_test_wiring_is_required(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        self.assertEqual(guard.check(smoke, files, CI_OK), [])

        for dropped in (
            "smoke_contracts_run() {\n}\n",
            "smoke_contracts_run() {\n"
            f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}"\n'
            "}\n",
            "smoke_contracts_run() {\n"
            f'  bash "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
            "}\n",
        ):
            with self.subTest(dropped=dropped.strip()):
                failures = guard.check(smoke, files, dropped)
                self.assertTrue(
                    any("not wired" in f for f in failures), failures
                )

    def test_ci_self_test_line_may_be_reindented_with_its_body(self) -> None:
        """A body re-indent moves every line, so nothing is nested.

        This used to accept a *lone* line at any width, which is the blind spot
        that let `dead() { ...; }` through: one statement moved a level deeper
        gates nothing while still containing the expected substring.
        """
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        for indent in ("    ", "\t"):
            ci = (
                "smoke_contracts_run() {\n"
                + indent
                + 'ensure_contracts_python\n'
                + indent
                + f'python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
                + indent
                + 'bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
                + "}\n"
            )
            with self.subTest(indent=repr(indent)):
                self.assertEqual(guard.check(smoke, files, ci), [])

    def test_ci_self_test_neutralised_by_a_shell_operator_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        line = f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test'
        for suffix in (" || true", " || :", " 2>/dev/null", "  # note", " | tail -1"):
            ci = (
                "smoke_contracts_run() {\n"
                + line
                + suffix
                + "\n"
                '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
                "}\n"
            )
            with self.subTest(suffix=suffix):
                failures = guard.check(smoke, files, ci)
                self.assertTrue(
                    failures, "an operator that eats the exit status passed"
                )
                self.assertTrue(
                    any("standalone statement" in f for f in failures), failures
                )

    def test_ci_self_test_wrapped_in_a_dead_command_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        line = f'python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test'
        wrappers = {
            "a function that is never called": f"  dead() {{ {line}; }}\n",
            "an if-false branch": f"  if false; then {line}; fi\n",
            "a backgrounded subshell": f"  ( {line} ) &\n",
            "a call chained after &&": f"  true && {line}\n",
            "a line moved a level deeper": f"  ensure_contracts_python\n    {line}\n",
        }
        for label, body in wrappers.items():
            ci = (
                "smoke_contracts_run() {\n"
                + body
                + '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
                + "}\n"
            )
            with self.subTest(wrapper=label):
                failures = guard.check(smoke, files, ci)
                self.assertTrue(failures, f"{label} kept the gate dead")

    def test_duplicated_ci_self_test_line_is_caught(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        line = f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
        ci = (
            "smoke_contracts_run() {\n"
            + line
            + line
            + '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
            + "}\n"
        )
        failures = guard.check(smoke, files, ci)
        self.assertTrue(any("2 times" in f for f in failures), failures)

    def test_self_test_reports_every_emitted_case(self) -> None:
        """The reported count must be measured, never a drifting constant.

        A hardcoded ``+ N`` summary stays green while over- or under-counting
        the probes that actually ran -- the same "registered but not collected"
        shape this guard exists to kill. Run the real ``--self-test`` against
        the committed tree and pin reported == emitted result lines.
        """
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = guard.self_test()
        out = buf.getvalue()
        self.assertEqual(rc, 0, out)
        emitted = [
            line
            for line in out.splitlines()
            if line.startswith("PASS self-test:")
            or line.startswith("FAIL self-test:")
        ]
        self.assertTrue(emitted, out)
        reported = [
            int(line.split()[1])
            for line in out.splitlines()
            if line.startswith("self-test: ")
            and line.split()[1].isdigit()
            and "cases" in line
        ]
        self.assertEqual(len(reported), 1, out)
        self.assertEqual(reported[0], len(emitted),
                         f"reported {reported[0]} but emitted {len(emitted)}: {out}")

    def test_committed_ci_wiring_is_gated(self) -> None:
        """The real script must satisfy every property, not just the tests."""
        _smoke_text, ci_steps, _files_text = guard.load_sources()
        body = guard.ci_contracts_function(ci_steps)
        self.assertEqual(guard.ci_wiring_errors(body), [])

    def test_ci_self_test_must_run_before_the_layer(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        ci = (
            "smoke_contracts_run() {\n"
            '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
            f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
            "}\n"
        )
        failures = guard.check(smoke, files, ci)
        self.assertTrue(any("runs after" in f for f in failures), failures)

    def test_commented_out_standalone_guard_is_rejected(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED).replace(
            '  "${PYTHON_BIN}" ' + REQUIRED[0] + ' || rc=$?',
            '  # "${PYTHON_BIN}" ' + REQUIRED[0] + ' || rc=$?',
            1,
        )
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        failures = guard.check(smoke, files, CI_OK)
        self.assertTrue(any("was dropped" in f for f in failures), failures)

    def test_commented_out_driver_line_is_rejected(self) -> None:
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        body = _smoke(["scripts/test_example.py"], REQUIRED)
        prefix = (
            guard.DRIVER_MARKER
            + "\n"
            + '  # "${PYTHON_BIN}" scripts/check_contracts_registry_collection.py '
            + '|| FAILED+=("contracts registry")\n'
            + "  run_layer contracts smoke_contracts\nfi\n\n"
        )
        failures = guard.check(prefix + body, files)
        self.assertTrue(any("not propagated" in f for f in failures), failures)

    def test_ci_ordering_fails_closed_when_layer_call_is_gone(self) -> None:
        """No layer call means no reference point: do not silently skip."""
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        ci = (
            "smoke_contracts_run() {\n"
            f'  python3 "${{REPO_ROOT}}/scripts/{guard.GUARD_NAME}" --self-test\n'
            "}\n"
        )
        failures = guard.check(smoke, files, ci)
        self.assertTrue(any("call is missing" in f for f in failures), failures)

        # A renamed profile argument must not lose the ordering reference.
        renamed = CI_OK.replace("--profile contracts", "--profile static", 1)
        self.assertEqual(guard.check(smoke, files, renamed), [])


    def test_a_flag_bearing_tests_row_is_rejected(self) -> None:
        """A tests=() row is expanded verbatim into the pytest argv.

        ``registry()`` ignores a row that carries ``--self-test`` (its regex
        ends at ``.py``), yet that row is a real array element: pytest aborts
        the whole layer with ``unrecognized arguments`` / exit 4 before any
        suite is collected. The full-line check must name it.
        """
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        for bad in (
            "    scripts/check_x.py --self-test\n",
            "    scripts/test_example.py -q --maxfail=1\n",
        ):
            with self.subTest(bad=bad.strip()):
                smoke = _smoke([], REQUIRED).replace(
                    "  local tests=(\n",
                    "  local tests=(\n" + bad + "    scripts/test_example.py\n",
                    1,
                )
                failures = guard.check(smoke, files, CI_OK)
                self.assertTrue(
                    any("not a bare pytest path" in f for f in failures),
                    failures,
                )

    def test_a_clean_bare_path_row_is_accepted(self) -> None:
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        self.assertEqual(guard.check(smoke, files, CI_OK), [])

    def test_self_test_exit_status_reaches_the_process(self) -> None:
        """``clean tree drifts`` must fail closed through the process rc.

        ``self_test()`` returns 1 on a dirty clean-tree check, but a caller
        that invokes it without ``SystemExit`` would print the drift and still
        exit 0 -- while CI reads only the rc. Pin the real entry point: a
        flag-bearing ``tests=()`` row must make canonical ``--self-test`` exit
        non-zero, and the clean tree must exit 0.
        """
        result = subprocess.run(
            [sys.executable, "-c", _RC_DRIVER, str(GUARD_PATH), "drift"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("clean tree drifts", result.stdout)

        clean = subprocess.run(
            [sys.executable, "-c", _RC_DRIVER, str(GUARD_PATH), "clean"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)

        tail = "\n".join(GUARD_PATH.read_text(encoding="utf-8").splitlines()[-3:])
        self.assertIn("raise SystemExit(main())", tail)

    def test_ci_layer_call_must_stay_a_bare_statement(self) -> None:
        smoke = _smoke(["scripts/test_example.py"], REQUIRED)
        files = _files()
        files["scripts/test_example.py"] = "def test_one():\n    assert True\n"
        bare = '  bash "${REPO_ROOT}/scripts/smoke.sh" --profile contracts\n'
        for suffix in (" || true", " || :", " 2>/dev/null", " | tail -1", "  # ignored"):
            ci = CI_OK.replace(bare, bare.rstrip() + suffix + "\n", 1)
            with self.subTest(suffix=suffix):
                failures = guard.check(smoke, files, ci)
                self.assertTrue(
                    any("standalone statement" in f for f in failures), failures
                )


    def test_a_dropped_registered_suite_is_named(self) -> None:
        """An equality cannot see a row deletion; an independent floor can.

        Deleting a row lowers ``active rows`` and ``len(registry())`` together.
        ``PINNED_SUITES`` is a separate literal, so the deletion is named.
        """
        smoke, ci, files = guard.load_sources()
        row = "    scripts/test_motion_policy.py\n"
        self.assertIn(row, smoke)
        for label, mutated in {
            "deleted": smoke.replace(row, "", 1),
            "commented out": smoke.replace(row, "    # " + row.strip() + "\n", 1),
        }.items():
            with self.subTest(shape=label):
                failures = guard.wiring_errors(mutated, files, ci)
                self.assertTrue(
                    any("pinned gating suite" in f for f in failures), failures
                )

    def test_a_suite_added_without_a_pin_is_named(self) -> None:
        """A floor only covers rows that existed when it was written.

        A row that lands after ``PINNED_SUITES`` gets no protection: its later
        deletion drops the extractor's input and output together and the layer
        still prints a smaller count over ``SMOKE PASS``. Measured on live
        ``main`` on 2026-11-05 with three such rows (``#228``, ``#231``, ``#232``):
        deleting any of them exited 0. The pin must therefore be an equality.
        """
        smoke, ci, files = guard.load_sources()
        row = "    scripts/test_motion_policy.py\n"
        self.assertIn(row, smoke)
        self.assertEqual(guard.wiring_errors(smoke, files, ci), [])
        files = dict(files)
        files["scripts/test_unpinned_new_suite.py"] = "def test_one():\n    assert True\n"
        mutated = smoke.replace(
            row, "    scripts/test_unpinned_new_suite.py\n" + row, 1
        )
        with self.subTest(shape="added without a pin"):
            failures = guard.wiring_errors(mutated, files, ci)
            self.assertTrue(
                any("not pinned in PINNED_SUITES" in f for f in failures), failures
            )

    def test_the_unpinned_probe_isolated_from_missing_file_failures(self) -> None:
        """The self-test's unpinned case must exercise only the equality half.

        If the case adds a row but leaves its file out of ``files``, ``check()``
        already reports "suite has no collectible test" and the case still
        prints PASS after ``pinned_suite_errors()`` loses its ``unpinned``
        comprehension. Planting the file makes that ablation go red, so the
        probe is load-bearing rather than vacuous.
        """
        smoke, ci, files = guard.load_sources()
        self.assertEqual(guard.wiring_errors(smoke, files, ci), [])

        source = GUARD_PATH.read_text()
        planted = (
            '    unpinned_files = dict(files)\n'
            '    unpinned_files["scripts/test_unpinned_new_suite.py"] = (\n'
            '        "def test_unpinned():\\n    assert True\\n"\n'
            '    )\n'
        )
        self.assertIn(planted, source, "the probe is no longer planted on disk")

        ablation = ('    unpinned = registered - PINNED_SUITES\n',
                    '    unpinned = set()\n')
        self.assertIn(ablation[0], source, "ablation anchor missing")
        ablated = source.replace(*ablation, 1)

        import types
        for label, body in {"planted": source, "ablated": ablated}.items():
            with self.subTest(shape=label):
                module = types.ModuleType("guard_" + label)
                module.__file__ = str(GUARD_PATH)
                exec(compile(body, str(GUARD_PATH), "exec"), module.__dict__)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = module.self_test()
                if label == "planted":
                    self.assertEqual(rc, 0, "clean planted tree regressed")
                else:
                    self.assertEqual(rc, 1, "ablation stayed green: probe is vacuous")

    def test_the_unpinned_probe_fails_for_the_pin_only(self) -> None:
        """The self-test case must assert the failure IS the pin, not just any
        failure.

        A generic ``bool(found)`` passes even when the plant is removed: the
        missing-file error fires first and the probe stays green. The dedicated
        report must require exactly one failure naming ``PINNED_SUITES``; both
        ``plant removed`` and ``unpinned = set()`` must turn it red.
        """
        source = GUARD_PATH.read_text()
        needle = '"not pinned in PINNED_SUITES" in unpinned_found[0]'
        self.assertIn(needle, source, "the failure-for-the-pin assertion is gone")
        self.assertIn("len(unpinned_found) == 1", source,
                      "the single-failure isolation is gone")

        import types
        plant = (
            '    unpinned_files["scripts/test_unpinned_new_suite.py"] = (\n'
            '        "def test_unpinned():\\n    assert True\\n"\n'
            '    )\n'
        )
        self.assertIn(plant, source, "the probe is no longer planted on disk")
        ablation = ('    unpinned = registered - PINNED_SUITES\n',
                    '    unpinned = set()\n')
        for label, body in {
            "planted": source,
            "plant removed": source.replace(plant, "", 1),
            "unpinned ablated": source.replace(*ablation, 1),
        }.items():
            with self.subTest(shape=label):
                module = types.ModuleType("guard_" + label.replace(" ", "_"))
                module.__file__ = str(GUARD_PATH)
                exec(compile(body, str(GUARD_PATH), "exec"), module.__dict__)
                with contextlib.redirect_stdout(io.StringIO()):
                    rc = module.self_test()
                self.assertEqual(rc, 0 if label == "planted" else 1, label)

    def test_the_gating_pytest_call_must_stay_a_bare_statement(self) -> None:
        smoke, ci, files = guard.load_sources()
        line = '  "${PYTHON_BIN}" -m pytest "${tests[@]}" -q || rc=$?\n'
        self.assertIn(line, smoke)
        self.assertEqual(guard.wiring_errors(smoke, files, ci), [])
        shapes = {
            "-k deselect": line.replace(" -q ||", ' -q -k "not interval" ||'),
            "--deselect": line.replace(
                " -q ||", " -q --deselect=scripts/test_motion_policy.py ||"
            ),
            "--ignore": line.replace(
                " -q ||", " -q --ignore=scripts/test_motion_policy.py ||"
            ),
            "|| true": line.replace("|| rc=$?", "|| true"),
            "redirection": line.replace(" -q ||", " -q >/dev/null ||"),
            "deleted": "",
        }
        for label, replacement in shapes.items():
            with self.subTest(shape=label):
                failures = guard.wiring_errors(
                    smoke.replace(line, replacement, 1), files, ci
                )
                self.assertTrue(
                    any("gating pytest invocation" in f for f in failures), failures
                )

    def test_a_redirected_standalone_guard_still_gates(self) -> None:
        """``>/dev/null`` on a guard call is not a dropped call.

        ``GUARD_CALL`` tolerates internal redirection via ``[^|]*?`` and the
        exit status still propagates through ``|| rc=$?``: diagnostics are
        swallowed, the gate is live. Honest boundary, not a hole.
        """
        smoke, ci, files = guard.load_sources()
        call = (
            '  "${PYTHON_BIN}" scripts/check_openapi_published_enums.py '
            "--self-test || rc=$?\n"
        )
        self.assertIn(call, smoke)
        redirected = call.replace(" --self-test", " --self-test >/dev/null")
        self.assertEqual(
            guard.wiring_errors(smoke.replace(call, redirected, 1), files, ci), []
        )


    def test_self_test_runs_every_reviewed_case(self) -> None:
        """The emitted case count must meet an independent reviewed floor.

        ``self_test()`` prints ``N cases`` where N is measured from the result
        lines it emitted. A ``cases[:8]`` edit keeps that summary honest --
        8 cases, 8 lines, 0 failures -- while dropping most of the probes.
        Neither the guard's plain run nor the teeth guard reads this output.
        The collected companion is the only reader, so the floor lives here,
        in the second file, not beside the count it judges.
        """
        source = GUARD_PATH.read_text(encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = guard.self_test()
        out = buf.getvalue()
        reported = [
            int(line.split()[1])
            for line in out.splitlines()
            if line.startswith("self-test: ")
            and line.split()[1].isdigit()
            and "cases" in line
        ]
        self.assertEqual(len(reported), 1, out)
        self.assertEqual(rc, 0, out)
        self.assertGreaterEqual(
            reported[0],
            _EXPECTED_SELF_TEST_CASES,
            f"only {reported[0]} mutation case(s) ran; the reviewed floor is "
            f"{_EXPECTED_SELF_TEST_CASES}. A shrunken case loop would keep "
            f"the guard, the teeth guard and the whole layer green: {out}",
        )
        self.assertEqual(
            reported[0],
            sum(
                1 for line in out.splitlines()
                if line.startswith("PASS self-test:")
                or line.startswith("FAIL self-test:")
            ),
            out,
        )
        # The floor is a literal in both files, not a number one side derives.
        self.assertIn(
            f"_REVIEWED_CASE_FLOOR = {_EXPECTED_SELF_TEST_CASES}",
            source,
            "the guard's own reviewed floor drifted from the companion's",
        )

    def test_the_case_loop_walks_the_full_container(self) -> None:
        """The loop must consume ``cases`` itself, not a hand-picked slice.

        The reviewed floor counts emitted results, so a ``cases[:8]`` edit is
        caught by the number alone. This AST assertion names the shape too:
        ``for ... in cases:`` is the reviewed contract, and a reader that
        quietly walks fewer cases has the same meaning as a guard that checks
        less. A legitimate new case needs no edit here.
        """
        import ast

        tree = ast.parse(GUARD_PATH.read_text(encoding="utf-8"))
        loops = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.target, ast.Tuple)
            and any(
                isinstance(elt, ast.Name) and elt.id == "mutated_smoke"
                for elt in node.target.elts
            )
        ]
        self.assertEqual(len(loops), 1, "the case loop shape changed")
        self.assertIsInstance(loops[0].iter, ast.Name, "the loop is sliced")
        self.assertEqual(loops[0].iter.id, "cases", "the loop no longer walks cases")

    def test_a_shrunken_case_loop_is_named_by_the_reviewed_floor(self) -> None:
        """Decisive ablation: slice the loop, the floor must go red.

        Both limbs matter: the shrunken loop must still print a clean-looking
        ``0 failure(s)`` summary (or the ablation proves nothing), and the
        reviewed floor must be the thing that turns it red. The companion is
        collected, so this runs in the contracts layer.
        """
        import types

        source = GUARD_PATH.read_text(encoding="utf-8")
        # Build the shrunken body from whatever loop shape the committed guard
        # uses, so this ablation proves the floor's two limbs even when the
        # real tree is itself drifted (a setup assertion would only be a
        # noisier third door). The loop-shape test above names a real drift.
        pattern = re.compile(
            r"    for label, mutated_smoke, mutated_files, mutated_ci in "
            r"cases(?:\[:\d+\])?:\n"
        )
        match = pattern.search(source)
        self.assertIsNotNone(match, "the case loop shape changed")
        shrunken = (
            source[: match.start()]
            + "    for label, mutated_smoke, mutated_files, mutated_ci in cases[:8]:\n"
            + source[match.end() :]
        )
        self.assertNotEqual(shrunken, source, "ablation did not apply")

        def run(body: str) -> tuple[int, str]:
            module = types.ModuleType("guard_shrunken")
            module.__file__ = str(GUARD_PATH)
            exec(compile(body, str(GUARD_PATH), "exec"), module.__dict__)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = module.self_test()
            return rc, buf.getvalue()

        # Control limb: with the floor itself gutted too, the shrunken loop is
        # a clean-looking short run -- 34 cases, 34 PASS lines, 0 failures.
        # Without this limb the ablation could be red for an unrelated reason.
        no_floor = shrunken.replace(
            "_REVIEWED_CASE_FLOOR = 50\n",
            "_REVIEWED_CASE_FLOOR = 0\n",
            1,
        )
        self.assertNotEqual(no_floor, shrunken, "floor ablation did not apply")
        control_rc, control_out = run(no_floor)
        self.assertEqual(control_rc, 0, control_out)
        self.assertIn("0 failure(s)", control_out, control_out)
        emitted = sum(
            1 for line in control_out.splitlines()
            if line.startswith("PASS self-test:")
        )
        self.assertLess(emitted, _EXPECTED_SELF_TEST_CASES, control_out)

        # Floor limb: the same bytes with the reviewed floor intact go red,
        # and the message names the shrunken loop rather than a lost probe.
        rc, out = run(shrunken)
        self.assertEqual(rc, 1, out)
        self.assertIn("below the reviewed floor", out, out)
        self.assertEqual(
            sum(1 for line in out.splitlines() if line.startswith("PASS self-test:")),
            emitted,
            "the floor must not change which probes run, only judge the count",
        )


    def test_unittest_plan_is_read_by_both_wired_entry_points(self) -> None:
        """The empty-plan verdict must be reachable from both entry points.

        ``ci-job-steps.sh`` gates the contracts layer with this guard's
        ``--self-test``; ``smoke.sh`` gates it with the plain run. Both call
        ``wiring_errors()``, so both must see the frontend gate's unittest
        plan. Pin the two committed lines from this second file.
        """
        ci = (ROOT / "scripts/ci-job-steps.sh").read_text(encoding="utf-8")
        smoke = (ROOT / "scripts/smoke.sh").read_text(encoding="utf-8")
        ci_body = guard.ci_contracts_function(ci)
        self.assertTrue(
            any(
                guard.CI_SELF_TEST.match(line)
                for line in ci_body.splitlines()
            ),
            "the CI entry point no longer invokes the guard's --self-test",
        )
        self.assertIsNotNone(
            guard.driver_propagates(smoke),
            "the local entry point no longer has the driver-level call",
        )
        self.assertTrue(
            guard.driver_propagates(smoke),
            "the local entry point no longer propagates the plain run's failure",
        )
        # Both wired forms must reach the same composed validator, or one of
        # them can retire the unittest-plan reader without the other noticing.
        source = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("wiring_errors(smoke, files, ci_steps)", source)
        self.assertIn("return self_test()", source)

    def test_empty_unittest_plan_is_named(self) -> None:
        """Decisive ablation: the reader must use unittest's collection rule.

        Rewriting the suite's ``unittest.TestCase`` base into a plain class
        keeps every module-level ``def test_*`` name pytest would collect, but
        ``unittest discover`` collects 0 and still prints ``OK`` / ``rc=0``.
        A reader reusing ``collectible_tests()`` would stay green.
        """
        smoke, ci, files = guard.load_sources()
        script = files[guard.CONTRACT_SH]
        suite = "packages/api-client/python_tests/test_api_error_code_vocabulary.py"
        self.assertEqual(guard.unittest_plan_errors(script, files), [])

        mutated = dict(files)
        mutated[suite] = files[suite].replace(
            "class ApiErrorVocabularyTests(unittest.TestCase):",
            "class ApiErrorVocabularyTests:",
            1,
        )
        failures = guard.wiring_errors(smoke, mutated, ci)
        self.assertTrue(
            any("0 TestCase methods" in f for f in failures), failures
        )

        # The pytest-shaped reader would call the same bytes healthy: this is
        # what makes the cell real rather than a second copy of the registry
        # check.
        self.assertEqual(
            guard.unittest_collectible_tests(mutated[suite], suite), []
        )
        self.assertTrue(
            any(
                item.name.startswith("test")
                for item in __import__("ast").parse(mutated[suite]).body
                if isinstance(item, (__import__("ast").FunctionDef,))
            ) is False,
            "the ablated file should keep its methods inside the class",
        )

    def test_unittest_plan_is_not_pinned_by_a_derived_reader(self) -> None:
        """A literal pin, not a value computed from the bytes it audits."""
        source = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("UNITTEST_DISCOVER = re.compile(", source)
        self.assertIn('UNITTEST_START = "packages/api-client/python_tests"', source)
        self.assertIn("def unittest_collectible_tests(", source)
        self.assertNotIn(
            "unittest_collectible_tests = collectible_tests",
            source,
            "the unittest reader must not alias the pytest-shaped reader",
        )

    def test_a_neutralised_unittest_discover_line_is_named(self) -> None:
        """Dropping or chaining the discover call must fail by name."""
        smoke, ci, files = guard.load_sources()
        call = (
            'python3 -m unittest discover -s "$PKG_DIR/python_tests" '
            '-p "test_*.py"'
        )
        script = files[guard.CONTRACT_SH]
        self.assertIn(call, script)
        for label, replacement in {
            "dropped": "",
            "chained": call + " || true",
            "redirected": call + " 2>/dev/null",
            "repatterned": call.replace("test_*.py", "check_*.py"),
        }.items():
            with self.subTest(shape=label):
                mutated = dict(files)
                mutated[guard.CONTRACT_SH] = script.replace(call, replacement, 1)
                failures = guard.wiring_errors(smoke, mutated, ci)
                self.assertTrue(
                    any("unittest discover" in f for f in failures), failures
                )


    def test_async_testcase_noop_green_is_named(self) -> None:
        """A counted async test method whose body never runs must fail closed.

        ``unittest.TestLoader`` counts ``async def test_*`` on a plain
        ``TestCase`` and the runner prints ``Ran 1 test`` / ``OK`` / ``rc=0``
        while the coroutine is never awaited. The old reader sees a healthy
        plan; the new door must name the method from committed bytes.
        """
        smoke, ci, files = guard.load_sources()
        script = files[guard.CONTRACT_SH]
        suite = "packages/api-client/python_tests/test_api_error_code_vocabulary.py"
        self.assertEqual(guard.unittest_plan_errors(script, files), [])
        self.assertEqual(guard.unittest_noop_test_methods(files[suite], suite), [])

        mutated = dict(files)
        mutated[suite] = files[suite].replace(
            "    def test_clean_tree_has_no_golden_drift(self) -> None:",
            "    async def test_clean_tree_has_no_golden_drift(self) -> None:",
            1,
        )
        self.assertNotEqual(mutated[suite], files[suite])
        # Pre-fix control: on these exact drifted bytes the old reader's
        # verdict is green. That is what makes the new door load-bearing:
        # removing it must make the drift silent again, not merely keep a
        # name on the collectible list. Rebuild the pre-fix reader from the
        # same source with the no-op door switched off -- asserting the
        # current reader's collectible name would hold on clean bytes too.
        pre_fix_spec = importlib.util.spec_from_file_location(
            "pre_fix_registry_collection", GUARD_PATH
        )
        pre_fix = importlib.util.module_from_spec(pre_fix_spec)
        pre_fix_spec.loader.exec_module(pre_fix)
        pre_fix.unittest_noop_test_methods = lambda _source, _path: []
        self.assertEqual(pre_fix.unittest_plan_errors(script, mutated), [])
        self.assertTrue(
            any("test_clean_tree_has_no_golden_drift" in n
                for n in guard.unittest_noop_test_methods(mutated[suite], suite))
        )
        failures = guard.wiring_errors(smoke, mutated, ci)
        self.assertTrue(
            any("async test methods whose bodies never run" in f
                for f in failures), failures
        )
        # Both wired entry points go through wiring_errors(); assert the plain
        # guard call reddens too, not just an in-process helper.
        self.assertTrue(guard.unittest_plan_errors(script, mutated))

    def test_asyncio_testcase_async_tests_are_not_flagged(self) -> None:
        """IsolatedAsyncioTestCase awaits async tests legitimately.

        A blanket "no async test methods" ban would reject a valid suite.
        The reader recognises only ``TestCase`` by name, so an
        ``IsolatedAsyncioTestCase`` class is deliberately out of scope.
        """
        source = (
            "import unittest\n"
            "class LiveTests(unittest.IsolatedAsyncioTestCase):\n"
            "    async def test_awaited(self):\n"
            "        raise AssertionError('boom')\n"
        )
        self.assertEqual(
            guard.unittest_noop_test_methods(source, "synthetic.py"), []
        )
        self.assertEqual(
            guard.unittest_collectible_tests(source, "synthetic.py"), []
        )

    def test_async_plant_is_registered_in_the_guard_self_test(self) -> None:
        """The decisive plant must be wired into the guard's own self-test."""
        source = GUARD_PATH.read_text(encoding="utf-8")
        self.assertIn("def unittest_noop_test_methods(", source)
        self.assertIn(
            "async def test_clean_tree_has_no_golden_drift(self) -> None:",
            source,
            "the self-test plant for the async no-op green is missing",
        )
        self.assertIn(
            "PASS self-test: an async TestCase no-op green is named", source
        )


if __name__ == "__main__":
    unittest.main()
