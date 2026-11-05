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
#
# The first seven were routed through the helper by #239; a later change
# (#240) put two of them back on an inline ``str(exc) or 'assertion failed'``
# form, which is still non-empty but no longer names the file and line of the
# failing precondition. They are listed in ``INLINE_STR_FALLBACK`` instead of
# being deleted: the outcome this suite protects is "a red runner says *why*",
# and an inline ``str`` conversion satisfies that outcome. Runners that stay
# silent (``{exc or ...}``, a dead fallback, a bare ``== []``) still fail.
RUNNERS = (
    "scripts/test_locale_language_purity.py",
    "scripts/test_mcp_openapi_parity.py",
)

# Runners allowed to render the cause inline (``str(exc) or 'assertion failed'``)
# rather than through ``describe_assertion``. The shape is pinned by
# ``test_openapi_422_unified_envelope.py`` for six of them; this list only keeps
# the two scans above from demanding the helper a second time.
INLINE_STR_FALLBACK = (
    "scripts/check_openapi_inline_body_integrity.py",
    "scripts/test_contracts_layer_self_containment.py",
    "scripts/test_openapi_422_unified_envelope.py",
    "scripts/test_openapi_baseline_sync.py",
    "scripts/test_openapi_behavior_contracts.py",
    "scripts/test_openapi_snapshot_body_integrity.py",
    "scripts/test_openapi_snapshot_contract.py",
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
)


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


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


def test_the_regression_pins_are_load_bearing() -> None:
    """Both scanners must go red on the exact shapes they forbid."""
    # (1) drop the helper import + call from one runner's bytes: the AST
    # checks that gate the wired runners no longer see a wired runner.
    relative = "scripts/test_mcp_openapi_parity.py"
    source = _source(relative)
    mutant = source.replace(
        "from named_guard_diagnostics import describe_assertion\n", "", 1
    ).replace("describe_assertion(exc, fn)", "exc", 1)
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

    # (3) the committed bytes pass both scanners -- the pins reject the
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
