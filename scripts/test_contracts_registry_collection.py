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
        ``main`` on 2026-11-05 with three such rows (``#228``, ``#231`` twice):
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



if __name__ == "__main__":
    unittest.main()
