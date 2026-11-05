#!/usr/bin/env python3
"""Every wired ``--self-test`` guard must still execute its mutation cases.

Twelve guards are wired into ``smoke_contracts()`` through ``--self-test``
alone: their plain ``check()`` is never invoked in the contracts layer. The
registry guard (``check_contracts_registry_collection.py``) pins that each
call *exists* and is listed in ``REQUIRED_GUARD_CALLS`` -- it does not read
the body the call reaches. Measured on live main: replacing
``check_app_shell_assets.self_test`` with ``return 0`` keeps the whole layer
at ``SMOKE PASS / 741 passed / 0 failed``. The call is present, pinned and
green while the guard has lost every assertion it owned.

This guard closes that cell by running each wired ``--self-test`` as a real
subprocess and requiring its pinned success signature in the output. A
no-op self-test emits nothing; a self-test that stopped planting mutations
cannot fake the signature without also emitting it. The signature floor is a
hand-written literal, not derived from the guards it audits: an edit that
weakens a guard and edits this file together is the reviewed action, and the
companion suite pins that the probe itself is wired and has teeth.

Usage:
    python3 scripts/check_contracts_self_test_teeth.py
    python3 scripts/check_contracts_self_test_teeth.py --self-test
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"

METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace"})

# Standalone ``"${PYTHON_BIN}" scripts/check_*.py ... || rc=$?`` calls inside
# smoke_contracts(). Optional arguments sit between the path and the pipe.
GUARD_CALL = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"\s+(scripts/[A-Za-z0-9_./-]+\.py)'
    r'([^|]*?)\s*\|\|\s*rc=\$\?',
    re.MULTILINE,
)

# Reviewed literal floor: the guards the contracts layer wires via
# --self-test. Adding a new one without pinning it here fails closed; dropping
# one is reported by name. This is a floor, not an allowlist derived from the
# layer, so it cannot be made self-consistent by deleting a row.
_WIRED_SELF_TESTS: frozenset[str] = frozenset(
    {
        "scripts/check_api_error_code_vocabulary.py",
        "scripts/check_app_shell_assets.py",
        "scripts/check_bio_core_wheel_abi.py",
        "scripts/check_error_code_catalog.py",
        "scripts/check_error_code_doc_counts.py",
        "scripts/check_error_code_gate_wiring.py",
        "scripts/check_mcp_manifest_reconcile.py",
        "scripts/check_mcp_release_binding.py",
        "scripts/check_openapi_auth_surface.py",
        "scripts/check_openapi_baseline_sync.py",
        "scripts/check_openapi_inline_body_integrity.py",
        "scripts/check_openapi_operation_id_floor.py",
        "scripts/check_openapi_operation_parameter_floor.py",
        "scripts/check_variant_summary_assembly_consistency.py",
        "scripts/check_openapi_published_enums.py",
        "scripts/check_visible_i18n.py",
    }
)

# Pinned success signatures. Counts are deliberately not pinned: a legitimate
# new ablation changes "OK (11 checks)" to "OK (12 checks)" and must stay
# green. What is pinned is the *shape of the evidence* -- the guard reports
# cases caught, not just an exit code. A gutted self_test returns 0 and prints
# nothing, which matches none of these.
_SIGNATURES: dict[str, re.Pattern[str]] = {
    "scripts/check_api_error_code_vocabulary.py": re.compile(
        r"SELF-TEST PASS: \d+ mutations each failed the guard"
    ),
    "scripts/check_app_shell_assets.py": re.compile(
        r"app shell asset self-test passed"
    ),
    "scripts/check_bio_core_wheel_abi.py": re.compile(
        r"self-test / ledger \+ source contract\]: PASS"
    ),
    "scripts/check_error_code_catalog.py": re.compile(
        r"error-code catalog self-test passed"
    ),
    "scripts/check_error_code_doc_counts.py": re.compile(
        r"error-code doc counts self-test passed"
    ),
    "scripts/check_error_code_gate_wiring.py": re.compile(
        r"SELF-TEST PASS: \d+ wiring cases each failed the guard"
    ),
    "scripts/check_mcp_manifest_reconcile.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_mcp_release_binding.py": re.compile(
        r"self-test: \d+ ablations caught, 0 missed"
    ),
    "scripts/check_openapi_auth_surface.py": re.compile(
        r"openapi-auth-surface: OK \(\d+ ablations\)"
    ),
    "scripts/check_openapi_baseline_sync.py": re.compile(
        r"openapi-baseline-sync-tests: OK \(\d+ checks\)"
    ),
    "scripts/check_openapi_inline_body_integrity.py": re.compile(
        r"openapi-inline-bodies: OK \(\d+ checks\)"
    ),
    "scripts/check_openapi_operation_id_floor.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_openapi_operation_parameter_floor.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_variant_summary_assembly_consistency.py": re.compile(
        r"SELF-TEST PASS: \d+ cases"
    ),
    "scripts/check_openapi_published_enums.py": re.compile(
        r"OK \(\d+ ablations\)"
    ),
    "scripts/check_visible_i18n.py": re.compile(r"visible i18n self-test passed"),
}


def contracts_function(smoke: str) -> str:
    marker = "smoke_contracts() {"
    if marker not in smoke:
        raise ValueError("smoke.sh no longer defines smoke_contracts()")
    return smoke.split(marker, 1)[1].split("\n}\n", 1)[0]


# This guard's own --self-test call is wired in the same layer. Probing it
# would recurse forever, so it is explicitly excluded from the audited set;
# the companion suite pins its wiring and teeth from a second file instead.
SELF = "scripts/check_contracts_self_test_teeth.py"


def wired_self_tests(smoke: str) -> dict[str, list[str]]:
    """path -> argv, for every standalone --self-test call in the layer."""
    out: dict[str, list[str]] = {}
    for path, raw_args in GUARD_CALL.findall(contracts_function(smoke)):
        args = raw_args.split()
        if "--self-test" not in args or path == SELF:
            continue
        out.setdefault(path, args)
    return out


def floor_errors(wired: dict[str, list[str]]) -> list[str]:
    found = set(wired)
    problems = [
        f"wired --self-test guard {p!r} was dropped from the contracts layer"
        for p in sorted(_WIRED_SELF_TESTS - found)
    ]
    problems += [
        f"wired --self-test guard {p!r} is not pinned in _WIRED_SELF_TESTS"
        for p in sorted(found - _WIRED_SELF_TESTS)
    ]
    problems += [
        f"pinned --self-test guard {p!r} has no success signature"
        for p in sorted(_WIRED_SELF_TESTS - set(_SIGNATURES))
    ]
    problems += [
        f"success signature {p!r} is pinned but no guard is wired"
        for p in sorted(set(_SIGNATURES) - _WIRED_SELF_TESTS)
    ]
    return problems


def probe(
    wired: dict[str, list[str]], root: Path = ROOT, runner: list[str] | None = None
) -> dict[str, tuple[int, str]]:
    """Run each wired --self-test as a real process; return (rc, output)."""
    base = runner if runner is not None else [sys.executable]
    out: dict[str, tuple[int, str]] = {}
    for path in sorted(wired):
        argv = base + [path] + wired[path]
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, cwd=root, timeout=90, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            out[path] = (1, f"could not run {path}: {exc}")
            continue
        out[path] = (result.returncode, result.stdout + result.stderr)
    return out


def teeth_errors(
    wired: dict[str, list[str]], results: dict[str, tuple[int, str]]
) -> list[str]:
    problems: list[str] = []
    for path in sorted(wired):
        rc, output = results.get(path, (1, "guard was not probed"))
        if rc != 0:
            problems.append(f"{path} --self-test exited {rc}: {output.strip()[:160]}")
            continue
        signature = _SIGNATURES.get(path)
        if signature is None:
            problems.append(f"{path} has no pinned success signature")
        elif not signature.search(output):
            problems.append(
                f"{path} --self-test emitted no pinned evidence of its "
                "mutation cases (a no-op self-test exits 0 and prints nothing)"
            )
    return problems


def check(
    smoke: str | None = None,
    results: dict[str, tuple[int, str]] | None = None,
    root: Path = ROOT,
) -> list[str]:
    text = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    try:
        wired = wired_self_tests(text)
    except ValueError as exc:
        return [str(exc)]
    problems = floor_errors(wired)
    if results is None:
        results = probe(wired, root=root)
    return problems + teeth_errors(wired, results)


def self_test() -> int:
    smoke = SMOKE.read_text(encoding="utf-8")
    clean = check(smoke=smoke)
    if clean:
        print(f"FAIL self-test: clean tree drifts: {clean}")
        return 1

    wired = wired_self_tests(smoke)
    cases: list[tuple[str, str, bool]] = []

    # 1. The decisive ablation, on real bytes: import one wired guard,
    # replace its self_test entry with a no-op (rc=0, empty output -- exactly
    # what a one-line gut produces) and prove the probe loses that guard's
    # signature while every other guard still emits its own. Running the
    # whole probe from a partial temp tree made all 13 guards fail to open,
    # so this plants the mutation in-process instead of faking a tree.
    target = "scripts/check_app_shell_assets.py"
    noop_runner = [
        sys.executable,
        "-c",
        "import importlib.util,sys;"
        "p=sys.argv[1];"
        "s=importlib.util.spec_from_file_location('gutted',p);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m.self_test=lambda:0;"
        "sys.argv=[p,'--self-test'];"
        "raise SystemExit(m.main())",
    ]

    def probe_with_noop(
        wired: dict[str, list[str]], root: Path = ROOT
    ) -> dict[str, tuple[int, str]]:
        out: dict[str, tuple[int, str]] = {}
        for path in sorted(wired):
            argv = (
                noop_runner + [path]
                if path == target
                else [sys.executable, path] + wired[path]
            )
            try:
                result = subprocess.run(
                    argv,
                    capture_output=True,
                    text=True,
                    cwd=root,
                    timeout=90,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                out[path] = (1, f"could not run {path}: {exc}")
                continue
            out[path] = (result.returncode, result.stdout + result.stderr)
        return out

    control = probe(wired)
    if teeth_errors(wired, control):
        print("FAIL self-test: clean tree is not clean")
        return 1
    results = probe_with_noop(wired)
    found = teeth_errors(wired, results)
    lost = [f for f in found if target in f and "no pinned evidence" in f]
    others = [f for f in found if target not in f]
    cases.append(
        (
            "a no-op self_test() is caught, and no other guard is collateral",
            target,
            len(lost) == 1 and not others,
        )
    )

    # 2. A guard that fails loudly is caught too (not just silent no-ops).
    broken = dict(results)
    broken["scripts/check_openapi_baseline_sync.py"] = (1, "boom")
    cases.append(
        (
            "a failing --self-test is reported by name",
            "check_openapi_baseline_sync.py",
            any("check_openapi_baseline_sync.py" in f for f in teeth_errors(wired, broken)),
        )
    )

    # 3. Dropping a wire from the layer is caught by the literal floor.
    dropped = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n', "", 1
    )
    cases.append(
        (
            "a dropped --self-test wire is caught",
            "check_visible_i18n.py",
            any("was dropped" in f for f in floor_errors(wired_self_tests(dropped))),
        )
    )

    # 4. Wiring a new guard without pinning it fails closed.
    added = smoke.replace(
        '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n',
        '  "${PYTHON_BIN}" scripts/check_visible_i18n.py --self-test || rc=$?\n'
        '  "${PYTHON_BIN}" scripts/check_new_guard.py --self-test || rc=$?\n',
        1,
    )
    cases.append(
        (
            "a wired-but-unpinned guard fails closed",
            "check_new_guard.py",
            any("not pinned" in f for f in floor_errors(wired_self_tests(added))),
        )
    )

    # 5. A guard that emits an unpinned success line is caught.
    fake = dict(results)
    fake["scripts/check_app_shell_assets.py"] = (0, "all good!\n")
    cases.append(
        (
            "an empty/unpinned self-test output is caught",
            "check_app_shell_assets.py",
            any("no pinned evidence" in f for f in teeth_errors(wired, fake)),
        )
    )

    for label, target_name, caught in cases:
        print(f"PASS self-test: {label} -> {target_name}")
        if not caught:
            print(f"FAIL self-test: {label} was NOT caught", file=sys.stderr)
            return 1
    print(f"self-test: {len(cases)} cases, 0 failure(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    problems = check()
    if problems:
        for problem in problems:
            print(f"FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"contracts self-test teeth: OK ({len(_WIRED_SELF_TESTS)} wired guards probed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
