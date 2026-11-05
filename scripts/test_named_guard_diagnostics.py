"""Pin every stdlib guard runner to non-empty, named failure causes.

On live ``b30af5a1``, injecting one real body drift into the generated client
made ``test_openapi_snapshot_body_integrity.py`` print 5 ``FAIL:`` lines, 3 of
them ending at the colon with no cause. The guard fired and the layer went red,
but the operator was not told which body moved. Two distinct causes:

* ``assert failures(*_load()) == []`` attaches no message to the
  ``AssertionError``, so the failure list is never rendered;
* bare setup assertions (``assert a in generated``) that lose their
  precondition likewise have no message, and ``AssertionError`` is **truthy**
  even when empty, so ``f"...: {exc or 'assertion failed'}"`` never falls back.

This suite pins both halves from a second file, so a one-file edit that
reintroduces either shape fails the contracts layer instead of shipping a
silent red. It reads committed sources (AST, stdlib only) and does not need
pytest's fixtures, a 3.15 venv, an API import or a workspace install.

Run directly or collect with pytest:
    python3 scripts/test_named_guard_diagnostics.py
    pytest scripts/test_named_guard_diagnostics.py -q
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import named_guard_diagnostics as helper  # noqa: E402

GUARD = "describe_assertion"

# The stdlib runners that render a caught AssertionError into a FAIL line.
# Each must (a) import the shared helper and (b) route its exception through it.
RUNNERS = (
    "scripts/check_openapi_inline_body_integrity.py",
    "scripts/test_contracts_layer_self_containment.py",
    "scripts/test_openapi_422_unified_envelope.py",
    "scripts/test_openapi_baseline_sync.py",
    "scripts/test_openapi_behavior_contracts.py",
    "scripts/test_openapi_snapshot_body_integrity.py",
    "scripts/test_openapi_snapshot_contract.py",
    "scripts/test_locale_language_purity.py",
    "scripts/test_mcp_openapi_parity.py",
    "scripts/test_openapi_operation_id_floor.py",
    "scripts/test_openapi_operation_parameter_floor.py",
)

# Assertions whose right-hand side is an empty list/tuple MUST carry a message:
# `assert found == [], found` is fine, `assert found == []` is silent.
MESSAGED_ASSERT_FILES = (
    "scripts/check_openapi_inline_body_integrity.py",
    "scripts/test_contracts_layer_self_containment.py",
    "scripts/test_openapi_422_unified_envelope.py",
    "scripts/test_openapi_baseline_sync.py",
    "scripts/test_openapi_behavior_contracts.py",
    "scripts/test_openapi_snapshot_body_integrity.py",
    "scripts/test_openapi_snapshot_contract.py",
    "scripts/test_locale_language_purity.py",
    "scripts/test_mcp_openapi_parity.py",
    "scripts/test_openapi_operation_id_floor.py",
    "scripts/test_openapi_operation_parameter_floor.py",
    # Not a test file: a *production* guard. `failures(...)[0]` was its only
    # red signal, so a silent assert there loses the reason at the source.
    "scripts/check_openapi_published_enums.py",
)


def _source(relative: str) -> str:
    path = ROOT / relative
    # A pinned but missing file must fail *this* suite, not crash it with a
    # traceback: an uncaught OSError skips the renderer and the operator reads
    # a stack instead of a cause.
    if not path.is_file():
        raise AssertionError(
            f"{relative} is pinned in this suite but does not exist"
        )
    return path.read_text(encoding="utf-8")


def _runner_uses_helper() -> list[str]:
    problems: list[str] = []
    for relative in RUNNERS:
        source = _source(relative)
        tree = ast.parse(source, filename=relative)
        imported = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "named_guard_diagnostics"
            and any(alias.name == GUARD for alias in node.names)
            for node in ast.walk(tree)
        )
        used = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == GUARD
            for node in ast.walk(tree)
        )
        if not imported or not used:
            problems.append(
                f"{relative} does not route its caught AssertionError through "
                f"{GUARD} (imported={imported}, used={used})"
            )
    return problems


def _empty_list_asserts_are_messaged() -> list[str]:
    problems: list[str] = []
    for relative in MESSAGED_ASSERT_FILES:
        tree = ast.parse(_source(relative), filename=relative)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assert) or node.msg is not None:
                continue
            if not isinstance(node.test, ast.Compare):
                continue
            for op, right in zip(
                node.test.ops, node.test.comparators, strict=False
            ):
                if (
                    isinstance(op, ast.Eq)
                    and isinstance(right, (ast.List, ast.Tuple))
                    and not right.elts
                ):
                    problems.append(
                        f"{relative}:{node.lineno} asserts == [] with no message; "
                        "a failure would render an empty cause"
                    )
    return problems


def _unrewritten_check(source: str):
    """Compile a check so pytest's assertion rewriting cannot inject a message.

    Pytest rewrites ``assert`` in collected test modules to carry a rich
    message. The runners in the wild are plain ``python3 file.py`` invocations,
    where a bare assert raises ``AssertionError('')``. Compiling a source file
    (rather than the collected module) keeps the probe faithful to that shape,
    and a real path lets ``traceback`` read the failing line back.
    """
    import tempfile

    path = Path(tempfile.mkdtemp()) / "guard_diagnostic_probe.py"
    path.write_text(source, encoding="utf-8")
    namespace: dict[str, object] = {"__file__": str(path)}
    exec(compile(source, str(path), "exec"), namespace)  # noqa: S102
    probe = namespace["probe"]
    probe._probe_path = path  # keep the file alive until the caller is done
    return probe


def test_helper_renders_a_non_empty_cause_for_an_empty_assertion_error() -> None:
    """The property the runners depend on: never return ''."""
    bare = _unrewritten_check(
        "def probe():\n"
        "    found = ['generated client declares 0 GeneDetail body(s)']\n"
        "    assert found == []"
    )
    named = _unrewritten_check(
        "def probe():\n"
        "    found = ['named drift']\n"
        "    assert not found, found"
    )
    try:
        bare()
    except AssertionError as exc:
        assert str(exc) == "", "probe was rewritten; AssertionError is not empty"
        cause = helper.describe_assertion(exc, bare)
        assert "assertion failed at" in cause, cause
        assert "assert found == []" in cause, cause
    else:
        raise AssertionError("bare probe did not fail")
    try:
        named()
    except AssertionError as exc:
        assert "named drift" in helper.describe_assertion(exc, named)
    else:
        raise AssertionError("named probe did not fail")
    assert helper.describe_assertion(AssertionError("  "), bare)


def test_helper_names_the_failing_source_line() -> None:
    bare = _unrewritten_check("def probe():\n    assert 1 == 2")
    try:
        bare()
    except AssertionError as exc:
        cause = helper.describe_assertion(exc, bare)
        assert "assertion failed at" in cause, cause
        assert "assert 1 == 2" in cause, cause
    else:
        raise AssertionError("bare probe did not fail")


def test_every_wired_runner_uses_the_helper() -> None:
    assert _runner_uses_helper() == []


def test_no_runner_asserts_against_an_empty_list_without_a_message() -> None:
    assert _empty_list_asserts_are_messaged() == []


def test_the_pinned_runner_list_actually_covers_the_wired_runners() -> None:
    """The pins must be an equality, not a floor.

    ``_runner_uses_helper`` only inspects the names in ``RUNNERS``, so dropping
    a row from that tuple makes the pin *smaller* and stays green -- exactly the
    "green because it stopped looking" shape. This check derives the wired
    runners from the committed bytes instead and compares sets.
    """
    discovered = set()
    for path in sorted((ROOT / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=path.name)
        # Detection is by construction: a handler that CATCHES an AssertionError
        # and calls the helper in the same block. Matching on a literal
        # ``except AssertionError as exc`` string misses
        # ``except (AssertionError, StopIteration)``, which is exactly how a
        # "stale pin" false positive reads.
        for handler in ast.walk(tree):
            if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
                continue
            names = (
                [handler.type]
                if not isinstance(handler.type, ast.Tuple)
                else list(handler.type.elts)
            )
            catches = any(
                isinstance(node, ast.Name) and node.id == "AssertionError"
                for node in names
            )
            if not catches:
                continue
            calls = any(
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == GUARD
                for node in ast.walk(handler)
            )
            if calls:
                discovered.add(f"scripts/{path.name}")
                break
    pinned = set(RUNNERS)
    assert discovered == pinned, (
        f"unpinned wired runner(s): {sorted(discovered - pinned)}; "
        f"stale pin(s): {sorted(pinned - discovered)}"
    )


def test_the_regression_pins_are_load_bearing() -> None:
    """Both scanners must go red on the exact shapes they forbid."""
    # (1) drop the helper import + call from one runner's bytes: the AST
    # checks that gate the wired runners no longer see a wired runner.
    relative = "scripts/test_openapi_snapshot_body_integrity.py"
    source = _source(relative)
    mutant = source.replace(
        "from named_guard_diagnostics import describe_assertion\n", "", 1
    ).replace("describe_assertion(exc, test)", "exc", 1)
    assert mutant != source, "ablation did not change the runner bytes"
    tree = ast.parse(mutant, filename=relative)
    imported = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "named_guard_diagnostics"
        and any(alias.name == GUARD for alias in node.names)
        for node in ast.walk(tree)
    )
    used = any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == GUARD
        for node in ast.walk(tree)
    )
    assert not imported and not used, "mutant still looks wired"

    # (2) a bare `assert found == []` must be detected by the AST scanner.
    bare = "def test_x():\n    found = [1]\n    assert found == []\n"
    offenders = [
        node
        for node in ast.walk(ast.parse(bare))
        if isinstance(node, ast.Assert)
        and node.msg is None
        and isinstance(node.test, ast.Compare)
        and any(
            isinstance(op, ast.Eq)
            and isinstance(right, (ast.List, ast.Tuple))
            and not right.elts
            for op, right in zip(node.test.ops, node.test.comparators, strict=False)
        )
    ]
    assert len(offenders) == 1, "bare == [] assert was not detected"

    # (3) a pinned-but-missing runner must be *named*, not crash the suite.
    # An uncaught OSError here would skip the renderer entirely and print a
    # traceback instead of a cause -- the same silence, one layer down.
    try:
        (ROOT / "scripts" / "no_such_pinned_runner_probe.py").read_text(encoding="utf-8")
    except OSError:
        pass
    try:
        _source("scripts/no_such_pinned_runner_probe.py")
    except AssertionError as exc:
        assert "no_such_pinned_runner_probe.py" in str(exc), str(exc)
        assert "does not exist" in str(exc), str(exc)
    else:
        raise AssertionError("a missing pinned runner was not rejected")

    # (4) the committed bytes pass both scanners -- the pins reject the
    # regression, not the fix itself.
    assert _runner_uses_helper() == []
    assert _empty_list_asserts_are_messaged() == []


def _run() -> int:
    checks = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    problems: list[str] = []
    for check in checks:
        try:
            check()
        except AssertionError as exc:
            problems.append(f"{check.__name__}: {helper.describe_assertion(exc, check)}")
    if problems:
        for problem in problems:
            print(f"named-guard-diagnostics: FAIL: {problem}", file=sys.stderr)
        return 1
    print(f"named-guard-diagnostics: OK ({len(checks)} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(_run())
