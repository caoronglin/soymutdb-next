#!/usr/bin/env python3
"""Every wired ``--self-test`` guard must still execute its mutation cases.

Twenty guards are wired into ``smoke_contracts()`` through ``--self-test``
(this guard's own call is the twenty-first). For most of them that is the only
invocation in the layer, so their plain ``check()`` never runs here. Three are
called twice on purpose: their plain run is the only call that reads the
committed tree. ``BOTH_CALLS`` pins that set -- deleting a plain run otherwise
keeps every gate and the whole contracts layer green while the guard never
inspects the real source. The registry guard
(``check_contracts_registry_collection.py``) pins that each call *exists* and
is listed in ``REQUIRED_GUARD_CALLS`` -- it does not read the body the
call reaches. Measured on live main: replacing
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
import ast
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
        "scripts/check_openapi_response_surface.py",
        "scripts/check_openapi_operation_annotations.py",
        "scripts/check_openapi_field_constraints.py",
        "scripts/check_openapi_required_fields.py",
        "scripts/check_variant_summary_assembly_consistency.py",
        "scripts/check_openapi_published_enums.py",
        "scripts/check_visible_i18n.py",
    }
)

# Reviewed literal floor: wired guards whose *second* (plain) call is the only
# thing that reads the committed tree. The registry guard pins a guard's path,
# not how many times it is invoked, so deleting this plain run keeps its path
# in REQUIRED_GUARD_CALLS, keeps the --self-test call green and keeps the whole
# layer at SMOKE PASS. A floor must be hand-written, not derived from the bytes
# it audits: a single-file edit cannot drop both the call and its own pin here.
BOTH_CALLS: frozenset[str] = frozenset(
    {
        "scripts/check_api_error_code_vocabulary.py",
        "scripts/check_error_code_catalog.py",
        "scripts/check_variant_summary_assembly_consistency.py",
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
        r"error-code catalog self-test passed \([1-9]\d* negative cases \+ clean tree\)"
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
    "scripts/check_openapi_response_surface.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_openapi_operation_annotations.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_openapi_field_constraints.py": re.compile(
        r"self-test: \d+ cases, 0 failure\(s\)"
    ),
    "scripts/check_openapi_required_fields.py": re.compile(
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

# Per-wire drift plants. A success signature is a string a gutted body can
# also write: ``print("... self-test passed"); return 0`` reproduces every
# pinned marker while detecting nothing. The signature pin therefore only
# proves "the body still emits agreed evidence", not "the body still detects
# a planted drift".
#
# So each guard whose signature a one-line gut *can* fake (the ones that print
# a single summary line) also gets a drift plant: a source edit that disables
# its detection entry point. The probe applies the plant to the real tree, runs
# the wired ``--self-test``, and requires a non-zero exit. A guard that prints
# its signature but no longer plants anything stays green on the signature
# check and goes red here.
#
# Guards that print per-case evidence (``ok: planted 'x' -> caught``) cannot be
# faked by a summary line, so their signature already carries the proof and
# they need no plant. ``_DRIFT_COVERED`` is a floor over the thin set: adding a
# thin guard without a plant fails closed.
#
# (path, anchor, replacement, why the plant is a drift)
_DRIFT_PLANTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "scripts/check_app_shell_assets.py",
        '    """Check Umi\'s icon declaration and every built tree that exists."""\n',
        '    """Check Umi\'s icon declaration and every built tree that exists."""\n'
        "    return  # planted drift: detection disabled\n",
        "the shell check stops reporting failures",
    ),
    (
        "scripts/check_bio_core_wheel_abi.py",
        "def filename_failures(name: str, arch: str) -> list[str]:\n",
        "def filename_failures(name: str, arch: str) -> list[str]:\n"
        "    return []  # planted drift: detection disabled\n",
        "filename scrutiny accepts every tag",
    ),
    (
        "scripts/check_openapi_auth_surface.py",
        "def failures(snapshot: str, main: str, deps: str, auth: str, config: str) -> list[str]:\n",
        "def failures(snapshot: str, main: str, deps: str, auth: str, config: str) -> list[str]:\n"
        "    return []  # planted drift: detection disabled\n",
        "the auth surface accepts every ablation",
    ),
    (
        "scripts/check_openapi_baseline_sync.py",
        "    found: list[str] = []\n\n    if tree is not None:",
        "    found: list[str] = []\n    return found  # planted drift: detection disabled\n"
        "\n    if tree is not None:",
        "baseline drift is never reported",
    ),
    (
        "scripts/check_openapi_inline_body_integrity.py",
        "    found: list[str] = []\n"
        "    pinned = _INLINE_BODY_BASELINE if baseline is None else baseline",
        "    found: list[str] = []\n    return found  # planted drift: detection disabled\n"
        "    pinned = _INLINE_BODY_BASELINE if baseline is None else baseline",
        "inline body drift is never reported",
    ),
    (
        "scripts/check_openapi_published_enums.py",
        '    """Return ``(problems, compared_enum_pairs)``."""\n    found: list[str] = []',
        '    """Return ``(problems, compared_enum_pairs)``."""\n    found: list[str] = []\n'
        "    return found, 0  # planted drift: detection disabled",
        "published enum drift is never reported",
    ),
    (
        "scripts/check_visible_i18n.py",
        "def collect(root: Path) -> dict[str, int]:\n    counts: dict[str, int] = {}\n",
        "def collect(root: Path) -> dict[str, int]:\n    counts: dict[str, int] = {}\n"
        "    return counts  # planted drift: detection disabled\n",
        "the collector finds no hardcoded strings",
    ),
    (
        "scripts/check_api_error_code_vocabulary.py",
        '    """Return the list of contract violations (empty means the tree is clean)."""\n',
        '    """Return the list of contract violations (empty means the tree is clean)."""\n'
        "    return []  # planted drift: detection disabled\n",
        "the vocabulary check accepts every drift",
    ),
    (
        "scripts/check_error_code_catalog.py",
        "            problems = check_tree(tree)\n",
        "            problems = []  # planted drift: the planted trees are never read\n",
        "the catalog self-test never reads its planted trees",
    ),
    (
        "scripts/check_error_code_doc_counts.py",
        "    problems: list[str] = []\n    try:\n        counts = measured(root)\n",
        "    problems: list[str] = []\n    return problems  # planted drift: detection disabled\n"
        "    try:\n        counts = measured(root)\n",
        "the doc counts accept every stale number",
    ),
    (
        "scripts/check_error_code_gate_wiring.py",
        '    problems: list[str] = []\n    body = contracts_body(root)\n',
        '    problems: list[str] = []\n    return problems  # planted drift: detection disabled\n'
        "    body = contracts_body(root)\n",
        "an unwired gate is never reported",
    ),
    (
        "scripts/check_mcp_manifest_reconcile.py",
        '    """Return named failures; empty means the declarations agree."""\n',
        '    """Return named failures; empty means the declarations agree."""\n'
        "    return []  # planted drift: detection disabled\n",
        "manifest drift is never reported",
    ),
    (
        "scripts/check_mcp_release_binding.py",
        '    """Return human-readable failures; empty means the contract holds."""\n',
        '    """Return human-readable failures; empty means the contract holds."""\n'
        "    return []  # planted drift: detection disabled\n",
        "release binding drift is never reported",
    ),
    (
        "scripts/check_openapi_field_constraints.py",
        '    """Return human-readable failures; empty means the contract is pinned."""\n',
        '    """Return human-readable failures; empty means the contract is pinned."""\n'
        "    return []  # planted drift: detection disabled\n",
        "field constraint drift is never reported",
    ),
    (
        "scripts/check_openapi_required_fields.py",
        "def failures(\n",
        "def failures(\n    return []  # planted drift: detection disabled\n",
        "the required-field pin accepts every ablation",
    ),
    (
        "scripts/check_openapi_operation_annotations.py",
        "    rows = _snapshot_rows(document)\n    found: list[str] = []\n",
        "    rows = {}  # planted drift: the annotations are never read\n"
        "    found: list[str] = []\n",
        "annotation drift is never reported",
    ),
    (
        "scripts/check_openapi_operation_id_floor.py",
        '    """Return human-readable failures; empty means the contract is pinned."""\n',
        '    """Return human-readable failures; empty means the contract is pinned."""\n'
        "    return []  # planted drift: detection disabled\n",
        "operationId drift is never reported",
    ),
    (
        "scripts/check_openapi_operation_parameter_floor.py",
        '    """Return human-readable failures; empty means the contract is pinned."""\n',
        '    """Return human-readable failures; empty means the contract is pinned."""\n'
        "    return []  # planted drift: detection disabled\n",
        "parameter drift is never reported",
    ),
    (
        "scripts/check_openapi_response_surface.py",
        '    """Return human-readable failures; empty means the contract is pinned."""\n',
        '    """Return human-readable failures; empty means the contract is pinned."""\n'
        "    return []  # planted drift: detection disabled\n",
        "response surface drift is never reported",
    ),
    (
        "scripts/check_variant_summary_assembly_consistency.py",
        "def run(visibility: Path, stats: Path) -> list[str]:\n",
        "def run(visibility: Path, stats: Path) -> list[str]:\n"
        "    return []  # planted drift: detection disabled\n",
        "the cross-assembly exclusion is never reported",
    ),
)

# A second plant per wired guard, at the self-test entry point instead of at a
# check: stop the plain run reading the committed tree. This is the shape the
# per-case evidence floor cannot see. A guard whose self-test plants its own
# mutations in memory or on temp copies prints every ``ok: <plant> -> caught``
# line whether or not the plain run reads anything, so a gutted entry point
# keeps the signature, keeps the declared count and keeps the evidence lines --
# while the guard swears the committed tree is clean. Measured on 999a39b3:
# check_error_code_catalog.self_test with ``problems = []`` before each
# ``check_tree(tree)`` kept all twelve per-case lines and the whole contracts
# layer at SMOKE PASS.
#
# So every wired guard carries both plants, and the probe requires the wired
# ``--self-test`` to stay green *and* the plain run to report the untouched tree
# as clean. Only the second half is a signal.
#
# (path, anchor, replacement)
_SELF_TEST_GUTS: tuple[tuple[str, str, str], ...] = (
    (
        "scripts/check_api_error_code_vocabulary.py",
        '    problems = check(args.root)\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_app_shell_assets.py",
        '    failures = run()\n',
        '    failures = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_bio_core_wheel_abi.py",
        '        failures += source_failures()\n',
        '        failures += []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_error_code_catalog.py",
        '    problems = check_tree(args.root.resolve())\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_error_code_doc_counts.py",
        '    problems = check(ROOT)\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_error_code_gate_wiring.py",
        '    problems = check(ROOT)\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_mcp_manifest_reconcile.py",
        '    failures = check(\n',
        '    failures = []  # planted drift: the plain run reads nothing\n    check(\n',
    ),
    (
        "scripts/check_mcp_release_binding.py",
        '        failures = check(spec, _read(MANIFEST_PY), _read(SERVER_PY))\n',
        '        failures = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_auth_surface.py",
        '    found = failures(*_load())\n',
        '    found = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_baseline_sync.py",
        '    problems = failures(ref=args.ref, base=args.base)\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_field_constraints.py",
        "    found = failures()\n",
        "    found = []  # planted drift: the plain run reads nothing\n",
    ),
    (
        "scripts/check_openapi_required_fields.py",
        "    found = failures()\n",
        "    found = []  # planted drift: the plain run reads nothing\n",
    ),
    (
        "scripts/check_openapi_inline_body_integrity.py",
        '    found = failures(*_load())\n',
        '    found = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_operation_annotations.py",
        "    problems = check()\n",
        "    problems = []  # planted drift: the plain run reads nothing\n",
    ),
    (
        "scripts/check_openapi_operation_id_floor.py",
        '    found = failures()\n',
        '    found = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_operation_parameter_floor.py",
        '    found = failures()\n',
        '    found = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_openapi_published_enums.py",
        '    problems, compared = failures(document, constraints)\n',
        '    problems, compared = [], 0  # planted drift: the plain run reads nothing\n',
    ),
    (
        "scripts/check_openapi_response_surface.py",
        '    found = failures()\n',
        '    found = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_variant_summary_assembly_consistency.py",
        '    problems = run(args.visibility, args.stats)\n',
        '    problems = []  # planted drift: the plain run stops reading the real tree\n',
    ),
    (
        "scripts/check_visible_i18n.py",
        '    counts = collect(ROOT)\n    if args.update_baseline:\n',
        '    counts = {}  # planted drift: the plain run reads nothing\n'
        '    if args.update_baseline:\n',
    ),
)

# A per-case line for one caught mutation: ``PASS self-test: <case> -> caught``,
# ``ok: <plant> -> caught``, ``self-test OK   <label>``. Anchored at line start
# so prose and tracebacks cannot pay for missing evidence, and the payload must
# be non-empty: ``PASS self-test: -> caught`` names nothing.
_EVIDENCE_LINE = re.compile(
    r"^[ \t]*(?:PASS self-test: \S.*|ok: \S.*|self-test OK\s+\S.*)$",
    re.MULTILINE,
)

# The count the same run claims its cases number. The guards spell it
# "9 mutations", "10 cases", "12 negative cases", "11 wiring cases",
# "6 plants", "6 ablations": an optional modifier word sits before the noun.
_DECLARED_CASES = re.compile(
    r"(?<!\d)(\d+)\s+(?:[a-z][a-z-]*\s+)?(?:cases|mutations|plants|ablations)\b",
    re.IGNORECASE,
)

_DRIFT_COVERED: frozenset[str] = frozenset(p for p, _, _, _ in _DRIFT_PLANTS)
_GUT_COVERED: frozenset[str] = frozenset(p for p, _, _ in _SELF_TEST_GUTS)

# Who is audited for per-case evidence: the drift-planted guards whose success
# line states a case count. The audit is the *second* leg of the design -- a
# drift plant needs a check to disable, a gutter plant needs a plain run to gut,
# and a guard with neither is distinguished from a ``print(<summary>); return 0``
# body only by the per-case lines its output carries. Listed as literals rather
# than derived from the plants, so a guard cannot be excused by editing the
# plant table alone. Measured on 999a39b3: every member passes on the committed
# tree, so membership is a property of the guards, not a favour granted here.
EVIDENCE_MEMBERS: frozenset[str] = frozenset(
    {
        "scripts/check_api_error_code_vocabulary.py",
        "scripts/check_error_code_catalog.py",
        "scripts/check_error_code_doc_counts.py",
        "scripts/check_error_code_gate_wiring.py",
        "scripts/check_mcp_manifest_reconcile.py",
        "scripts/check_mcp_release_binding.py",
        "scripts/check_openapi_field_constraints.py",
        "scripts/check_openapi_required_fields.py",
        "scripts/check_openapi_operation_annotations.py",
        "scripts/check_openapi_operation_id_floor.py",
        "scripts/check_openapi_operation_parameter_floor.py",
        "scripts/check_openapi_response_surface.py",
        "scripts/check_variant_summary_assembly_consistency.py",
    }
)


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


def plain_guard_calls(smoke: str) -> set[str]:
    """Paths with a plain (no ``--self-test``) standalone call in the layer."""
    out: set[str] = set()
    for path, raw_args in GUARD_CALL.findall(contracts_function(smoke)):
        if "--self-test" not in raw_args.split() and path != SELF:
            out.add(path)
    return out


def both_call_errors(smoke: str, wired: dict[str, list[str]]) -> list[str]:
    """Fail closed when a pinned both-calls guard loses its plain run."""
    plain = plain_guard_calls(smoke)
    problems = [
        f"both-calls guard {p!r} lost its plain run in the contracts layer: "
        "the --self-test call alone never reads the committed tree"
        for p in sorted(BOTH_CALLS - plain)
    ]
    problems += [
        f"both-calls guard {p!r} is pinned but no longer wired via --self-test"
        for p in sorted(BOTH_CALLS - set(wired))
    ]
    problems += [
        f"wired --self-test guard {p!r} also has a plain run but is not in BOTH_CALLS"
        for p in sorted((set(wired) & plain) - BOTH_CALLS)
    ]
    return problems


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


def _declared_cases(path: Path, function: str, mapping: str) -> int | None:
    """Count the case rows of ``mapping`` in ``function``; None if unreadable.

    Case containers come in four committed shapes: a dict/list/tuple literal,
    ``cases.append(...)`` calls, ``cases[key] = ...`` subscript writes, and a
    module-level literal (``CLAIMS``) that the self-test iterates. All are
    counted from source, never from printed output. Only half the evidence: a
    container survives an edit that empties the loop over it, so a count read
    here can agree with a success line no case produced.
    :func:`_loop_consumes` covers the other half.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    function_node = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        ),
        None,
    )
    if function_node is None:
        return None

    def literal_size(node: ast.AST) -> int | None:
        if isinstance(node, ast.Dict):
            return len(node.keys)
        if isinstance(node, (ast.List, ast.Tuple)):
            return len(node.elts)
        return None

    total = 0
    seen = False
    for inner in ast.walk(function_node):
        if isinstance(inner, (ast.Assign, ast.AnnAssign)):
            targets = inner.targets if isinstance(inner, ast.Assign) else [inner.target]
            value = inner.value
            if value is None:
                continue
            if any(isinstance(t, ast.Name) and t.id == mapping for t in targets):
                size = literal_size(value)
                if size is not None:
                    total += size
                    seen = True
            for target in targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == mapping
                ):
                    total += 1
                    seen = True
        if (
            isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and inner.func.attr == "append"
            and isinstance(inner.func.value, ast.Name)
            and inner.func.value.id == mapping
        ):
            total += 1
            seen = True
    if seen:
        return total
    # The case rows live at module level (e.g. ``CLAIMS``); still reviewed
    # bytes, still unreachable without the loop check below.
    for inner in tree.body:
        if isinstance(inner, (ast.Assign, ast.AnnAssign)):
            targets = inner.targets if isinstance(inner, ast.Assign) else [inner.target]
            value = inner.value
            if value is None:
                continue
            if any(isinstance(t, ast.Name) and t.id == mapping for t in targets):
                size = literal_size(value)
                if size is not None:
                    return size
    return 0


def _loop_consumes(path: Path, function: str, mapping: str) -> bool:
    """True when some ``for`` in ``function`` iterates ``mapping`` itself.

    The forgery this rejects is an edit inside the guard: keep the ``cases``
    dict, replace the loop iterable with an empty literal, and print a count
    the guard computes itself. The dict is then dead weight that no printed
    signature can see, so the iterable is required to *name* the mapping.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.For) and any(
                isinstance(n, ast.Name) and n.id == mapping for n in ast.walk(inner.iter)
            ):
                return True
        return False
    return False


# Guards whose self-test must still *reach* its declared ablations. A signature
# pins the shape of one printed line, and a guard that prints that shape from a
# number it computes itself forges it -- measured on the #256 tree: emptying the
# loop and printing ``len(cases)`` still emitted ``(12 negative cases + clean
# tree)``, rc=0, this probe green.
#
# The drift and gutter plants of #281/#282 each disable one check or one entry
# point; neither says anything about a *case being deleted*. Deleting the
# decisive co-revert case from ``check_openapi_operation_id_floor.py`` leaves
# its self-test at ``10 cases, 0 failure(s)`` while every plant, signature,
# evidence line and count check here stays green. So every ``EVIDENCE_MEMBERS``
# guard now pins a reviewed floor on its own case rows, read from source, plus
# a loop that names the container. A deleted case then names itself. Adding a
# member without a row fails closed (:func:`evidence_floor_errors`).
#
# (guard, source file holding self_test, function, case container, floor)
_CASE_FLOOR: dict[str, tuple[str, str, str, int]] = {
    "scripts/check_api_error_code_vocabulary.py": (
        "scripts/check_api_error_code_vocabulary.py", "_self_test", "cases", 9,
    ),
    "scripts/check_error_code_catalog.py": (
        "scripts/check_error_code_catalog.py", "self_test", "cases", 12,
    ),
    "scripts/check_error_code_doc_counts.py": (
        "scripts/check_error_code_doc_counts.py", "self_test", "CLAIMS", 5,
    ),
    "scripts/check_error_code_gate_wiring.py": (
        "scripts/check_error_code_gate_wiring.py", "_self_test", "ablations", 9,
    ),
    "scripts/check_mcp_manifest_reconcile.py": (
        "scripts/test_mcp_manifest_reconcile.py", "self_test", "checks", 12,
    ),
    "scripts/check_mcp_release_binding.py": (
        "scripts/check_mcp_release_binding.py", "run_self_test", "cases", 6,
    ),
    "scripts/check_openapi_operation_id_floor.py": (
        "scripts/check_openapi_operation_id_floor.py", "self_test", "cases", 11,
    ),
    "scripts/check_openapi_operation_parameter_floor.py": (
        "scripts/check_openapi_operation_parameter_floor.py", "self_test", "cases", 13,
    ),
    "scripts/check_openapi_field_constraints.py": (
        "scripts/check_openapi_field_constraints.py", "self_test", "cases", 5,
    ),
    "scripts/check_openapi_response_surface.py": (
        "scripts/check_openapi_response_surface.py", "self_test", "cases", 10,
    ),
    "scripts/check_openapi_required_fields.py": (
        "scripts/check_openapi_required_fields.py", "self_test", "cases", 6,
    ),
    "scripts/check_openapi_operation_annotations.py": (
        "scripts/check_openapi_operation_annotations.py", "self_test", "cases", 7,
    ),
    "scripts/check_variant_summary_assembly_consistency.py": (
        "scripts/check_variant_summary_assembly_consistency.py", "self_test", "cases", 6,
    ),
}


def declared_case_errors(root: Path = ROOT) -> list[str]:
    """Fail closed when a pinned self-test no longer reaches its own ablations."""
    problems: list[str] = []
    for guard_path, (source, function, mapping, floor) in sorted(_CASE_FLOOR.items()):
        if guard_path not in _WIRED_SELF_TESTS:
            problems.append(f"case floor {guard_path!r} is pinned but no guard is wired")
            continue
        target = root / source
        declared = _declared_cases(target, function, mapping)
        if declared is None:
            problems.append(f"{source} declares no {function}()/{mapping} to audit")
        elif declared < floor:
            problems.append(
                f"{source} {function}() declares {declared} mutation case(s), "
                f"below the pinned floor of {floor}: a case was deleted without "
                "a reviewed edit"
            )
        elif not _loop_consumes(target, function, mapping):
            problems.append(
                f"{source} {function}() no longer iterates its {mapping} "
                "mapping: the declared cases are unreachable, so the success "
                "line reports a count nothing produced"
            )
    return problems


def evidence_floor_errors() -> list[str]:
    """Every audited per-case guard must pin a reviewed case floor."""
    problems = [
        f"per-case guard {p!r} is audited for evidence but has no _CASE_FLOOR "
        "row: deleting one of its cases would be invisible"
        for p in sorted(EVIDENCE_MEMBERS - set(_CASE_FLOOR))
    ]
    problems += [
        f"case floor {p!r} targets a guard that is not audited for per-case evidence"
        for p in sorted(set(_CASE_FLOOR) - EVIDENCE_MEMBERS)
    ]
    return problems


def _declared_case_count(output: str) -> int | None:
    """The single N the run claims in its success line; None if ambiguous."""
    counts = {int(n) for n in _DECLARED_CASES.findall(output)}
    return counts.pop() if len(counts) == 1 else None


def evidence_lines(output: str) -> tuple[int | None, int]:
    """(declared cases, distinguished per-case lines) for one guard's output."""
    return _declared_case_count(output), sum(
        1 for line in output.splitlines() if _EVIDENCE_LINE.match(line)
    )


def evidence_errors(results: dict[str, tuple[int, str]]) -> list[str]:
    """A declared case count with fewer per-case lines than it claims.

    The row is a claim about the *output*, so it is checked against the output:
    N cases need N distinguished lines naming what was caught. Deliberately
    one-sided -- extra lines stay green -- so a legitimate rephrasing, a
    subtest or a wider plant cannot turn this into a format audit, and the
    count itself is never pinned, so an added ablation passes. The other
    direction is already covered one layer up: a guard that stops printing the
    count at all loses its ``_SIGNATURES`` marker.
    """
    problems: list[str] = []
    for path in sorted(EVIDENCE_MEMBERS):
        rc, output = results.get(path, (1, "guard was not probed"))
        if rc != 0:
            continue  # an unreachable self-test is reported by teeth_errors
        declared, emitted = evidence_lines(output)
        if declared is None:
            problems.append(
                f"{path} is audited for per-case evidence but its success line "
                "declares no single case count to measure it against"
            )
        elif emitted < declared:
            problems.append(
                f"{path} claims {declared} case(s) but printed {emitted} per-case "
                "line(s): the summary is written, the evidence is not"
            )
    return problems


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
    drift_results: dict[object, tuple[int, str]] | None = None,
    gut_results: dict[object, tuple[int, str]] | None = None,
) -> list[str]:
    text = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    try:
        wired = wired_self_tests(text)
    except ValueError as exc:
        return [str(exc)]
    problems = (
        floor_errors(wired)
        + both_call_errors(text, wired)
        + drift_floor_errors()
        + evidence_floor_errors()
        + declared_case_errors(root)
        + gut_anchor_errors(root)
    )
    if results is None:
        results = probe(wired, root=root)
    if drift_results is None:
        drift_results = drift_probe(wired, root=root)
    if gut_results is None:
        gut_results = gut_probe(wired, root=root)
    return (
        problems
        + teeth_errors(wired, results)
        + evidence_errors(results)
        + drift_errors(wired, drift_results)
        + gut_errors(wired, gut_results)
    )


def _plant(
    root: Path, path: str, fragment: str, replacement: str, argv: list[str], label: str
) -> tuple[int, str]:
    """Apply one plant to the real tree, run ``argv``, restore the bytes."""
    target = root / path
    try:
        original = target.read_text(encoding="utf-8")
    except OSError as exc:
        return 1, f"could not read {path}: {exc}"
    if fragment not in original:
        return 1, f"{label} anchor missing from {path}"
    # Sanity: the plant must not be a no-op, or it proves nothing.
    mutated = original.replace(fragment, replacement, 1)
    if mutated == original:
        return 1, f"{label} for {path} changed nothing"
    try:
        target.write_text(mutated, encoding="utf-8")
        try:
            result = subprocess.run(
                argv, capture_output=True, text=True, cwd=root, timeout=90, check=False
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 1, f"could not run {path}: {exc}"
        return result.returncode, result.stdout + result.stderr
    finally:
        target.write_text(original, encoding="utf-8")


def drift_probe(
    wired: dict[str, list[str]], root: Path = ROOT, runner: list[str] | None = None
) -> dict[object, tuple[int, str]]:
    """Plant one drift per guard and run its wired ``--self-test``.

    Returns (path, "wire") -> (rc, output) for the *mutated* tree. A guard that
    detects the plant exits non-zero; a guard that only prints a signature
    exits 0.
    """
    base = runner if runner is not None else [sys.executable]
    out: dict[object, tuple[int, str]] = {}
    for path, fragment, replacement, _why in _DRIFT_PLANTS:
        if path not in wired:
            continue
        out[(path, "wire")] = _plant(
            root, path, fragment, replacement, base + [path] + wired[path], "drift plant"
        )
    return out


def gut_probe(
    wired: dict[str, list[str]], root: Path = ROOT, runner: list[str] | None = None
) -> dict[object, tuple[int, str]]:
    """Stop the plain run reading the tree; run the wired call, then the plain one.

    Keys are ``(path, "self-test")`` and ``(path, "plain")``: the same plant,
    two calls. The first must stay green, the second must report the untouched
    tree as clean.
    """
    base = runner if runner is not None else [sys.executable]
    out: dict[object, tuple[int, str]] = {}
    for path, fragment, replacement in _SELF_TEST_GUTS:
        if path not in wired:
            continue
        out[(path, "self-test")] = _plant(
            root, path, fragment, replacement, base + [path] + wired[path], "gut plant"
        )
        out[(path, "plain")] = _plant(
            root, path, fragment, replacement, base + [path], "gut plant"
        )
    return out


def drift_errors(
    wired: dict[str, list[str]], results: dict[object, tuple[int, str]]
) -> list[str]:
    problems: list[str] = []
    for path in sorted(_DRIFT_COVERED):
        if path not in wired:
            problems.append(
                f"pinned drift plant {path!r} targets a guard that is not wired"
            )
            continue
        rc, _output = results.get((path, "wire"), (0, "guard was not probed"))
        if rc == 0:
            why = next(w for p, _, _, w in _DRIFT_PLANTS if p == path)
            problems.append(
                f"{path} --self-test stayed green on a planted drift "
                f"({why}); it emits its signature without detecting anything"
            )
    return problems


def gut_errors(
    wired: dict[str, list[str]], results: dict[object, tuple[int, str]]
) -> list[str]:
    """A gutted entry point keeps the self-test green; the plain run betrays it."""
    problems: list[str] = []
    for path in sorted(_GUT_COVERED):
        if path not in wired:
            problems.append(
                f"pinned self-test gut {path!r} targets a guard that is not wired"
            )
            continue
        self_rc, self_output = results.get((path, "self-test"), (0, "guard was not probed"))
        plain_rc, _plain_output = results.get((path, "plain"), (0, "guard was not probed"))
        if self_rc != 0:
            # The gutter has to survive the guard's own --self-test, or
            # something other than the plain run caught it and the plant says
            # nothing about the entry point.
            problems.append(
                f"{path} --self-test went red on a plant that only stops the plain "
                f"run reading the real tree: {self_output.strip()[:160]}"
            )
        if plain_rc != 0:
            problems.append(
                f"{path} still failed its plain run after the entry point stopped "
                "reading the real tree, so the plant proved nothing"
            )
    return problems


def gut_anchor_errors(root: Path = ROOT) -> list[str]:
    """A registered gut anchor must sit on the plain-run path, not in self_test().

    ``gut_probe()`` only compares exit codes: a plant that never reaches the
    plain run keeps ``plain_rc == 0`` and is indistinguishable from one the
    guard survived. The docstring claim "stop the plain run reading the tree"
    is a property of the source, so check the source. Adding a wire whose gut
    lands inside ``self_test()`` is now named instead of silently passing.
    """
    problems: list[str] = []
    for path, fragment, _replacement in _SELF_TEST_GUTS:
        source_path = root / path
        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append(f"could not read {path}: {exc}")
            continue
        needle = fragment.splitlines()[0].strip()
        lines = [i + 1 for i, line in enumerate(source.splitlines()) if needle in line]
        if not lines:
            problems.append(f"gut anchor {needle!r} is missing from {path}")
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            problems.append(f"could not parse {path}: {exc}")
            continue
        owners = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and any(node.lineno <= n <= (node.end_lineno or node.lineno) for n in lines)
        }
        if owners != {"main"}:
            problems.append(
                f"gut anchor for {path} sits in {sorted(owners) or ['no function']}, "
                "not in main(): the plant cannot reach the plain run"
            )
    return problems


def drift_floor_errors() -> list[str]:
    """Every wired guard needs both plants; neither set can absorb the other."""
    problems = [
        f"wired --self-test guard {p!r} has no drift plant in _DRIFT_PLANTS"
        for p in sorted(set(_WIRED_SELF_TESTS) - _DRIFT_COVERED)
    ]
    problems += [
        f"drift-planted guard {p!r} has no _SELF_TEST_GUTS entry"
        for p in sorted(_DRIFT_COVERED - _GUT_COVERED)
    ]
    problems += [
        f"drift plant {p!r} targets a guard that is not wired"
        for p in sorted(_DRIFT_COVERED - set(_WIRED_SELF_TESTS))
    ]
    problems += [
        f"self-test gut {p!r} targets a guard that is not wired"
        for p in sorted(_GUT_COVERED - set(_WIRED_SELF_TESTS))
    ]
    problems += [
        f"self-test gut {p!r} targets a guard with no drift plant"
        for p in sorted(_GUT_COVERED - _DRIFT_COVERED)
    ]
    return problems


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

    # 6. The decisive gap this guard exists to close one layer down: a self-test
    # gutted to ``print(<pinned signature>); return 0`` still satisfies the
    # signature check -- the marker is a string a mutator can write -- while
    # detecting nothing. The drift probe must catch it. Both limbs are asserted:
    # the signature check stays green (or the case proves nothing) and the
    # planted drift turns the wired call red.
    marker = "app shell asset self-test passed"
    poisoned = (0, marker + "\n")
    signature_blind = not teeth_errors(
        wired, {**control, "scripts/check_app_shell_assets.py": poisoned}
    )
    drift_caught = drift_errors(
        wired, {"scripts/check_app_shell_assets.py": (0, marker + "\n")}
    )
    cases.append(
        (
            "a marker-preserving gut defeats the signature pin but not the drift probe",
            "check_app_shell_assets.py",
            signature_blind
            and any("check_app_shell_assets.py" in f for f in drift_caught),
        )
    )

    # 7. The cell the evidence audit exists to close, stated in output form: a
    # self-test gutted to ``print(<pinned summary>); return 0`` keeps both the
    # signature and the declared count, because both are strings a mutator
    # copies. What it cannot copy is the evidence. Asserted directly, and the
    # negative half is asserted too, or this case would pass on any wiring.
    member = sorted(EVIDENCE_MEMBERS)[0]
    forged = "self-test: 12 cases, 0 failure(s)\n"
    caught = evidence_errors({member: (0, forged)})
    cases.append(
        (
            "a summary-only self_test() is caught by the per-case evidence floor",
            member,
            evidence_lines(forged) == (12, 0)
            and len(caught) == 1
            and "printed 0 per-case line(s)" in caught[0]
            and evidence_errors({target: (0, forged)}) == []
            and not evidence_errors(control),
        )
    )

    # 8. The cell this guard kept paying for one branch over: a guard whose
    # self-test plants its own mutations emits every per-case line whether or
    # not the plain run reads anything, so gutting the entry point keeps the
    # signature, the count and the evidence. Assert both limbs again -- the
    # replayed self-test must stay green, and the plain run is what catches it.
    gutted = "scripts/check_error_code_catalog.py"
    replayed = (0, "  ok: planted 'extra code' -> caught (1 problem(s))\n"
                   "error-code catalog self-test passed (12 negative cases + clean tree)\n")
    self_test_blind = not teeth_errors(wired, {**control, gutted: replayed})
    plain_caught = any(
        gutted in f
        for f in gut_errors(
            wired,
            {(gutted, "self-test"): replayed, (gutted, "plain"): (1, "")},
        )
    )
    cases.append(
        (
            "an entry point gutted to replay PASS keeps the self-test green "
            "and is caught by the plain run",
            gutted,
            self_test_blind and plain_caught,
        )
    )

    # 9. The wiring shape the guard's plants cannot see: deleting the plain
    # run of a both-calls guard (not gutting its body) keeps every --self-test
    # green, keeps its path in REQUIRED_GUARD_CALLS and keeps the whole layer
    # at SMOKE PASS -- the guard then never reads the committed tree. Pin the
    # plain call itself, and assert both limbs: clean tree has no error, the
    # deleted plain run is named by the BOTH_CALLS floor.
    victim = "scripts/check_variant_summary_assembly_consistency.py"
    dropped_plain = "\n".join(
        line for line in smoke.splitlines()
        if line.strip() != f'"${{PYTHON_BIN}}" {victim} || rc=$?'
    ) + "\n"
    cases.append(
        (
            "deleting a both-calls guard's plain run is caught by BOTH_CALLS",
            victim,
            dropped_plain != smoke
            and not both_call_errors(smoke, wired)
            and any(victim in f for f in both_call_errors(dropped_plain, wired)),
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
