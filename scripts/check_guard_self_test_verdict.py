#!/usr/bin/env python3
"""A ``--self-test`` that cannot fail is not a self-test.

Every wired guard prints its own verdict and then chooses its exit status. When
that status is computed *before* the last batch of planted mutations, the
batch's verdicts are still printed and then thrown away: the guard exits 0
while listing the plants it failed to catch. The contracts layer reads the exit
status, not the stdout, so the gate is dead while its output looks honest.

``scripts/check_openapi_published_enums.py`` shipped exactly that shape. Its
marker self-test printed

    FAIL: a generated @enum marker is retyped was not caught

and then ran

    result = 0

which discarded the verdict; with all three marker doors gutted the guard
printed ``OK (17 ablations)`` over three FAIL lines and exited 0.

``check_contracts_self_test_teeth.py`` does not close this cell, by
construction: its drift and gut plants require the wired ``--self-test`` to
stay *green* while a check is disabled. A guard that already swallows its own
verdict passes every plant in that suite. This guard measures the one thing
none of the others do -- the shape of the function that computes the exit
status -- and it does so structurally, on committed bytes, with no import of
the guards themselves.

What is checked
---------------
For every guard wired through ``--self-test`` in ``smoke_contracts()``, the
function that computes its status (``_self_test`` / ``self_test`` /
``run_self_test`` / ``_run_all``, in the guard or in the module it delegates
to) must not assign a verdict name back to a pass value after a verdict has
already been recorded. A single initialiser is the normal shape and is
accepted; so is a reset placed before every plant. A reset after an earlier
verdict write is reported with its line, because every plant caught before it
is printed and thrown away.

Deliberately not flagged: guards that return a plain expression
(``return 0 if not failures else 1``), delegate to ``sys.exit``, or assemble
the exit literal at the end. Those discard nothing, and a guard that reported
them would be noise.

A guard whose status function cannot be located fails closed: "wired with
``--self-test`` but the verdict is nowhere to be found" is not proof that it is
load-bearing.

Usage:
    python3 scripts/check_guard_self_test_verdict.py
    python3 scripts/check_guard_self_test_verdict.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SMOKE = ROOT / "scripts" / "smoke.sh"

# This guard's own --self-test call would recurse, so it is audited by the
# companion suite from a second file instead. Its status function returns
# ``failures_found`` growth, which has no pass reset to find.
SELF = "scripts/check_guard_self_test_verdict.py"

# Standalone ``"${PYTHON_BIN}" scripts/check_*.py ... || rc=$?`` calls inside
# smoke_contracts(). Optional arguments sit between the path and the pipe.
GUARD_CALL = re.compile(
    r'^[ \t]*"\$\{PYTHON_BIN\}"\s+(scripts/[A-Za-z0-9_./-]+\.py)'
    r'([^|]*?)\s*\|\|\s*rc=\$\?',
    re.MULTILINE,
)

# ``--self-test`` handled by handing the work to another module.
DELEGATION = re.compile(
    r"^[ \t]*from[ \t]+(scripts\.[A-Za-z0-9_.]+)[ \t]+import[ \t]+"
    r"(?:self_test|_run_all)\b"
    r"|^[ \t]*import[ \t]+(test_[A-Za-z0-9_]+)[ \t]+as[ \t]+\w+",
    re.MULTILINE,
)

# The count a self-test prints in its success line, and the per-case lines it
# prints alongside it. Kept here as well as in the teeth guard on purpose: a
# guard whose own verdict shape is the subject should not borrow the reader
# that audits it.
DECLARED_CASES = re.compile(
    r"(?<!\d)(\d+)\s+(?:[a-z][a-z-]*\s+)?(?:cases|mutations|plants|ablations)\b",
    re.IGNORECASE,
)
EVIDENCE_LINE = re.compile(
    r"^[ \t]*(?:PASS self-test: \S.*|ok: \S.*|self-test OK\s+\S.*)$",
    re.MULTILINE,
)

# Who carries per-case evidence: guards whose success line also states a case
# count. A reviewed literal floor, not derived from the output it audits.
EVIDENCE_MEMBERS: frozenset[str] = frozenset(
    {
        "scripts/check_mcp_manifest_reconcile.py",
        "scripts/check_mcp_release_binding.py",
        "scripts/check_openapi_auth_surface.py",
        "scripts/check_openapi_baseline_sync.py",
        "scripts/check_openapi_inline_body_integrity.py",
        "scripts/check_openapi_operation_id_floor.py",
        "scripts/check_openapi_operation_parameter_floor.py",
        "scripts/check_openapi_operation_annotations.py",
        "scripts/check_openapi_field_constraints.py",
        "scripts/check_openapi_required_fields.py",
        "scripts/check_openapi_response_surface.py",
        "scripts/check_variant_summary_assembly_consistency.py",
        "scripts/check_error_code_gate_wiring.py",
        "scripts/check_api_error_code_vocabulary.py",
        "scripts/check_error_code_catalog.py",
    }
)

SELF_TEST_NAMES: tuple[str, ...] = (
    "_self_test",
    "self_test",
    "_run_all",
    "run_self_test",
    "run_self_tests",
)

# Names a status function can use for "how did it go".
VERDICT_NAMES: frozenset[str] = frozenset(
    {"result", "rc", "status", "code", "exit_code", "bad", "errors", "problems", "failures"}
)

# The pass value for each of those names when it holds a constant.
PASS_CONSTANTS: tuple[object, ...] = (0, False, "", "0", None)


def contracts_function(smoke: str) -> str:
    marker = "smoke_contracts() {"
    if marker not in smoke:
        raise ValueError("smoke.sh no longer defines smoke_contracts()")
    return smoke.split(marker, 1)[1].split("\n}\n", 1)[0]


def wired_self_tests(smoke: str) -> list[str]:
    """Guards the contracts layer invokes with ``--self-test``."""
    found: list[str] = []
    for path, raw_args in GUARD_CALL.findall(contracts_function(smoke)):
        if "--self-test" in raw_args.split() and path not in found:
            found.append(path)
    return found


def _is_pass_constant(node: ast.AST | None) -> bool:
    """Whether an assigned value clears the verdict to a pass."""
    if node is None:
        return False
    if isinstance(node, ast.Constant):
        return node.value in PASS_CONSTANTS
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return not node.elts
    if isinstance(node, ast.Dict):
        return not node.keys
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_pass_constant(node.operand)
    if isinstance(node, ast.Call):
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        return name in {"list", "tuple", "set", "dict"} and not node.args
    return False


def _touches_verdict(node: ast.AST) -> bool:
    """Whether an expression reads a verdict name at all.

    ``problems = [] if condition else problems`` re-assigns an empty container,
    but the value is derived from the current one -- it is a filter, not a
    reset, and the verdict it filtered still decides the exit status.
    """
    return any(
        isinstance(sub, ast.Name) and _is_verdict_name(sub.id)
        for sub in ast.walk(node)
    )


def _is_verdict_name(name: str) -> bool:
    """Whether a written name holds one of the verdict fields.

    Prefix and suffix matching, because guards spell the same field
    ``result``, ``failures``, ``failures_count``, ``problems_amount`` and
    ``total_failures``. Matching the bare set would let a rename slip an
    otherwise identical reset past the check.
    """
    if name in VERDICT_NAMES:
        return True
    return any(name.startswith(n) or name.endswith(n) for n in VERDICT_NAMES)


def _writes_a_verdict(node: ast.AST) -> bool:
    """Whether the assignment's *value* carries the status.

    The target name is the weak half of the signal: ``results = 0`` is a case
    counter that shares a prefix with ``result``. What makes an assignment a
    verdict write is a pass/fail literal going into it -- that is the shape
    that can discard a verdict. ``results += 1`` and ``problems.append(x)``
    are both "a mutation was recorded", and both belong to a counter.
    """
    if isinstance(node, ast.AugAssign):
        return True
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, ast.AnnAssign):
        value = node.value
    else:
        return False
    if value is None:
        return False
    return not isinstance(value, (ast.Compare, ast.Attribute, ast.Subscript)) and (
        _is_pass_constant(value) or _is_fail_constant(value)
    )


def _is_fail_constant(node: ast.AST) -> bool:
    """Whether a value records a failure (``1``, ``True``, a non-empty list)."""
    if isinstance(node, ast.Constant):
        return node.value not in PASS_CONSTANTS
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_fail_constant(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return bool(node.elts)
    return False


def _verdict_targets(node: ast.AST) -> list[str]:
    """Verdict names an assignment writes, if any."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        targets = [node.target]
    elif isinstance(node, ast.AugAssign):
        # ``failures_count += 1`` is how nearly every guard records a caught
        # mutation; ignoring it made the "a verdict was recorded before this
        # reset" half of the check blind on the commonest shape.
        targets = [node.target]
    else:
        return []
    names: list[str] = []
    for target in targets:
        if isinstance(target, ast.Name) and _is_verdict_name(target.id):
            names.append(target.id)
        elif isinstance(target, ast.Tuple):
            names.extend(
                item.id
                for item in target.elts
                if isinstance(item, ast.Name) and _is_verdict_name(item.id)
            )
    return names


def _target_line(node: ast.AST) -> int:
    if isinstance(node, ast.AnnAssign):
        return node.target.lineno
    if isinstance(node, ast.AugAssign):
        return node.target.lineno
    return node.targets[0].lineno  # type: ignore[attr-defined]


def _status_function(tree: ast.Module) -> ast.FunctionDef | None:
    """The function that computes a guard's ``--self-test`` status."""
    # Module-level definitions win; a nested definition is the fallback for
    # guards that build the runner inside ``main``.
    for holder in tree.body:
        if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if holder.name in SELF_TEST_NAMES:
                return holder
    for holder in ast.walk(tree):
        if isinstance(holder, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if holder.name in SELF_TEST_NAMES:
                return holder
    return None


def delegated_source(text: str) -> str | None:
    """The module a guard hands ``--self-test`` to, if it does."""
    match = DELEGATION.search(text)
    if match is None:
        return None
    dotted = match.group(1) or f"scripts.{match.group(2)}"
    target = ROOT / (dotted.replace(".", "/") + ".py")
    if not target.is_file():
        return None
    return target.read_text(encoding="utf-8")


def resolve_status_source(path: Path) -> tuple[str, str] | None:
    """``(label, source)`` for the code deciding this guard's ``--self-test`` rc."""
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    if _status_function(ast.parse(text)) is not None:
        return path.name, text
    delegated = delegated_source(text)
    if delegated is None or _status_function(ast.parse(delegated)) is None:
        return None
    match = DELEGATION.search(text)
    assert match is not None  # delegated_source() found one
    return (match.group(1) or f"scripts.{match.group(2)}").split(".")[-1] + ".py", delegated


def discarded_verdicts(source: str) -> list[str]:
    """Pass-resets that can discard an already recorded verdict."""
    tree = ast.parse(source)
    func = _status_function(tree)
    if func is None:
        return []
    writes = [
        _target_line(node)
        for node in ast.walk(func)
        if _verdict_targets(node)
        and _writes_a_verdict(node)
        and not _is_pass_constant(getattr(node, "value", None))
    ]
    if not writes:
        return []
    initialiser = min(writes)
    later = [w for w in writes if w != initialiser]
    first_write = min(later) if later else initialiser
    problems: list[str] = []
    for node in ast.walk(func):
        names = _verdict_targets(node)
        value = getattr(node, "value", None)
        if not names or not _is_pass_constant(value) or _touches_verdict(value):
            continue
        line = _target_line(node)
        earlier = [w for w in writes if w < line]
        if not earlier or line == initialiser:
            continue
        problems.append(
            f"{func.name}() assigns {names[0]!r} a pass value at line {line}, "
            f"after a verdict was already written (first at line {first_write}): "
            "every plant caught before that line is printed and then discarded"
        )
    return problems


def guard_errors(path: str, root: Path = ROOT) -> list[str]:
    """Findings for one wired guard."""
    full = root / path
    if not full.is_file():
        return [f"{path} is wired with --self-test but is not committed"]
    try:
        resolved = resolve_status_source(full)
    except SyntaxError as exc:
        return [f"{path} --self-test status cannot be read: {exc}"]
    if resolved is None:
        # Fail closed: a verdict that cannot be located is not provably read.
        return [
            f"{path} is wired with --self-test but no status function could be "
            "resolved (define _self_test/self_test/run_self_test/_run_all, or "
            "delegate with `from scripts.<module> import self_test`)"
        ]
    label, source = resolved
    try:
        problems = discarded_verdicts(source)
    except SyntaxError as exc:
        return [f"{label} --self-test status cannot be read: {exc}"]
    return [f"{label}: {problem}" for problem in problems]


def check(smoke: str | None = None, root: Path = ROOT) -> list[str]:
    text = smoke if smoke is not None else SMOKE.read_text(encoding="utf-8")
    try:
        wired = wired_self_tests(text)
    except ValueError as exc:
        return [str(exc)]
    if not wired:
        return ["no --self-test guard call is wired in smoke_contracts()"]
    problems: list[str] = []
    for path in wired:
        if path == SELF:
            continue
        problems.extend(guard_errors(path, root))
    return problems


def self_test() -> int:
    """Each planted reset must be reported; the honest shapes must not be."""
    failures: list[str] = []

    def expect(label: str, source: str, should_report: bool) -> None:
        reported = bool(discarded_verdicts(source))
        if reported != should_report:
            failures.append(
                f"plant {label!r} was "
                f"{'reported, but it discards nothing' if reported else 'not reported'}"
            )

    expect(
        "a pass reset after the plant loop",
        "def _self_test():\n"
        "    result = 0\n"
        "    for plant in plants:\n"
        "        if not caught(plant):\n"
        "            result = 1\n"
        "    result = 0\n"
        "    return result\n",
        True,
    )
    expect(
        "a sole initialiser at the top",
        "def _self_test():\n"
        "    result = 0\n"
        "    for plant in plants:\n"
        "        if not caught(plant):\n"
        "            result = 1\n"
        "    return result\n",
        False,
    )
    expect(
        "no verdict field at all",
        "def _self_test():\n"
        "    for plant in plants:\n"
        "        print(caught(plant))\n"
        "    return 0\n",
        False,
    )
    expect(
        "a reset that runs before every plant",
        "def _self_test():\n"
        "    result = 0\n"
        "    result = 0\n"
        "    return result\n",
        False,
    )
    expect(
        "clearing the failure list after the loop",
        "def self_test():\n"
        "    problems = []\n"
        "    for plant in plants:\n"
        "        if not caught(plant):\n"
        "            problems = [plant]\n"
        "    problems = []\n"
        "    return 1 if problems else 0\n",
        True,
    )
    expect(
        "a differently named verdict field",
        "def run_self_test():\n"
        "    bad = 0\n"
        "    for plant in plants:\n"
        "        if not caught(plant):\n"
        "            bad = 1\n"
        "    bad = 0\n"
        "    return bad\n",
        True,
    )
    expect(
        "an exit literal assembled at the end",
        "def self_test():\n"
        "    problems = []\n"
        "    problems.append('x')\n"
        "    return 1 if problems else 0\n",
        False,
    )

    expect(
        "a counter that shares a prefix with a verdict name",
        "def self_test():\n"
        "    results = 0\n"
        "    failures_seen = 0\n"
        "    for label in cases:\n"
        "        results += 1\n"
        "    return 1 if failures_seen else 0\n",
        False,
    )
    expect(
        "a failure literal into a derived name",
        "def self_test():\n"
        "    failures_count = 0\n"
        "    for plant in plants:\n"
        "        failures_count += 1\n"
        "    failures_count = 0\n"
        "    return 1 if failures_count else 0\n",
        True,
    )

    # The decisive control, on real bytes: the clean status function of the
    # guard that carried this bug must stay unflagged, so the check is not
    # reporting every multi-branch self-test.
    for label, path in (
        ("the fixed enum guard on this tree", ROOT / "scripts/check_openapi_published_enums.py"),
        ("the error-code gate wiring guard", ROOT / "scripts/check_error_code_gate_wiring.py"),
    ):
        if not path.is_file():
            failures.append(f"control {label!r} is missing ({path})")
            continue
        resolved = resolve_status_source(path)
        if resolved is None:
            failures.append(f"control {label!r} has no resolvable status function")
        elif discarded_verdicts(resolved[1]):
            failures.append(f"control {label!r} is reported as discarding its verdict")

    for problem in failures:
        print(f"FAIL self-test: {problem}", file=sys.stderr)
    if failures:
        return 1
    print(f"self-test: 11 cases, 0 failure(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    problems = check()
    if problems:
        for problem in problems:
            print(f"guard self-test verdict: FAIL: {problem}", file=sys.stderr)
        return 1
    wired = len(wired_self_tests(SMOKE.read_text(encoding="utf-8")))
    print(f"guard self-test verdict: OK ({wired} wired self-tests keep their verdict)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
