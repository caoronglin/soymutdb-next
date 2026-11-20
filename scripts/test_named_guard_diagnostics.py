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

A third shape is quieter than both: a runner may *call* ``describe_assertion``
and still discard its return value, restoring a dead ``{exc or ...}`` fallback
in the report line. The existing pins only see that the helper is imported and
called somewhere in the file (or, for the inline-``str`` shape, that a reviewed
substring is present), so such a runner stays green while its red line prints
nothing after the colon. This suite also pins that every wired runner renders
the cause it computes, from the real report f-string inside its
``except AssertionError`` handler -- a quoted spelling in a docstring or an
ablation fixture cannot stand in for the report line.

The report line is identified by its sink, not by "any f-string in the
handler": only a ``print(f"FAIL ...")`` or a ``collector.append(f"...")``
reaches the operator. A debug ``print(f"debug: raw={exc}")`` beside a correct
report is legitimate context; reading it as the report rejects correct bytes
with a message that is false about them. Requiring a leading ``FAIL`` label
instead would be wrong for the nine inline runners, whose report f-string has
no label at all and relies on the append sink.

It reads committed sources (AST, stdlib only) and does not need pytest's
fixtures, a 3.15 venv, an API import or a workspace install.

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
HELPER_RUNNERS = (
    "scripts/test_locale_language_purity.py",
    "scripts/test_mcp_openapi_parity.py",
)

# Runners the helper is NOT required in, because a later change routed them
# through an inline ``str(exc) or 'assertion failed'`` fallback instead. It is
# still a non-empty cause for a red gate; what it loses is the file:line of the
# failing precondition. Kept as a literal list, not a derived one, so moving a
# runner between the two shapes is the reviewed edit.
INLINE_STR_RUNNERS = (
    "scripts/check_openapi_inline_body_integrity.py",
    "scripts/test_contracts_layer_self_containment.py",
    "scripts/test_openapi_422_unified_envelope.py",
    "scripts/test_openapi_baseline_sync.py",
    "scripts/test_openapi_behavior_contracts.py",
    "scripts/test_openapi_snapshot_body_integrity.py",
    "scripts/test_openapi_snapshot_contract.py",
    "scripts/test_openapi_operation_id_floor.py",
    "scripts/test_openapi_operation_parameter_floor.py",
)

# The set the wired-runner equality pins: every runner that renders a caught
# AssertionError into a FAIL line, whichever of the two shapes it uses.
RUNNERS = HELPER_RUNNERS + INLINE_STR_RUNNERS

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


def inline_str_fallback(source: str, filename: str) -> bool:
    """A runner that renders the cause with ``str(exc)`` and no helper import."""
    if filename == Path(__file__).name:
        # This suite quotes the fallback it forbids; it is not a runner.
        return False
    tree = ast.parse(source, filename=filename)
    if any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == GUARD
        for node in ast.walk(tree)
    ):
        return False
    return 'str(exc) or "assertion failed"' in source or (
        "str(exc) or 'assertion failed'" in source
    )


def _runner_uses_helper() -> list[str]:
    problems: list[str] = []
    for relative in HELPER_RUNNERS:
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
    # Both shapes count as wired: the helper (``describe_assertion(exc, ...)``)
    # and the inline ``str(exc) or 'assertion failed'`` fallback a later change
    # restored in runners that no longer import the helper. Dropping the import
    # *and* the call is what turns a runner silent, and that is what this
    # equality has to see.
    for path in sorted((ROOT / "scripts").glob("*.py")):
        if inline_str_fallback(path.read_text(encoding="utf-8"), path.name):
            discovered.add(f"scripts/{path.name}")
    pinned = set(RUNNERS)
    assert discovered == pinned, (
        f"unpinned wired runner(s): {sorted(discovered - pinned)}; "
        f"stale pin(s): {sorted(pinned - discovered)}"
    )


def _is_report_sink(call: ast.Call) -> bool:
    """Whether this call's first f-string is the handler's failure *report*.

    Two reviewed sinks carry the cause to the operator on this tree:

    * ``print(f"FAIL ...: {cause}")`` -- emitted directly by the runner;
    * ``problems.append(f"...: {cause}")`` -- collected, then emitted by the
      driver as ``print(f"FAIL: {problem}")``.

    Any other f-string in the handler (``print(f"debug: raw={exc}")``, a log
    call, a temporary) is context. It may legitimately render the bare
    exception object: ``AssertionError`` being truthy only makes a *dead
    fallback* dead, and a debug line carries no fallback at all. Requiring the
    leading ``FAIL`` label would instead be wrong for the nine inline runners,
    whose report f-string has no label and relies on the append sink.

    Admission rule: a new emit shape is added here as a reviewed edit. An
    unrecognised sink makes the report f-string invisible, and the runner is
    then named for rendering no cause -- fail closed, not silently green.
    """
    if not call.args or not isinstance(call.args[0], ast.JoinedStr):
        return False
    joined = call.args[0]
    if isinstance(call.func, ast.Name) and call.func.id == "print":
        first = joined.values[0] if joined.values else None
        return (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and first.value.lstrip().upper().startswith("FAIL")
        )
    return isinstance(call.func, ast.Attribute) and call.func.attr == "append"


def _rendered_exceptions(source: str, filename: str) -> list[tuple[int, ast.expr]]:
    """The cause expressions a runner formats into its failure report line.

    Only f-strings handed to a report sink inside a handler that catches
    ``AssertionError`` count -- a quoted fallback spelling in a docstring, an
    ablation fixture, or a debug line beside the report is not the report.
    ``_runner_uses_helper`` sees a *call* anywhere in the file and
    ``inline_str_fallback`` sees a *substring* anywhere in the file, so a runner
    that calls the helper but discards its result (or keeps the old spelling in
    a comment while reverting to a dead fallback) stays green while its red
    line prints nothing after the colon.
    """
    tree = ast.parse(source, filename=filename)
    rendered: list[tuple[int, ast.expr]] = []
    for handler in ast.walk(tree):
        if not isinstance(handler, ast.ExceptHandler) or handler.type is None:
            continue
        names = (
            [handler.type]
            if not isinstance(handler.type, ast.Tuple)
            else list(handler.type.elts)
        )
        if not any(
            isinstance(node, ast.Name) and node.id == "AssertionError"
            for node in names
        ):
            continue
        for call in ast.walk(handler):
            if not isinstance(call, ast.Call) or not _is_report_sink(call):
                continue
            joined = call.args[0]
            for value in joined.values:
                if isinstance(value, ast.FormattedValue):
                    rendered.append((joined.lineno, value.value))
    return rendered


EXCEPTION_NAMES = frozenset({"exc", "error", "e"})


def _renders_the_helper_result(expr: ast.expr) -> bool:
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == GUARD
    )


def _renders_the_exception_object(expr: ast.expr) -> bool:
    """The dead shape: the exception object itself, not its ``str()``.

    ``{exc or 'assertion failed'}`` and a bare ``{exc}`` are dead because
    ``AssertionError`` is truthy even when ``str(exc) == ''``. The reviewed
    ``{str(exc) or 'assertion failed'}`` shape is *not* dead -- converting the
    exception first makes the fallback reachable -- so a Name nested inside a
    ``str()`` call must not be counted.
    """
    if isinstance(expr, ast.Name) and expr.id in EXCEPTION_NAMES:
        return True
    if isinstance(expr, ast.BoolOp) and any(
        isinstance(value, ast.Name) and value.id in EXCEPTION_NAMES
        for value in expr.values
    ):
        return True
    return False


def _scanner_problems(relative: str, source: str) -> list[str]:
    problems: list[str] = []
    rendered = _rendered_exceptions(source, relative)
    if not rendered:
        return [f"{relative} renders no cause from its caught AssertionError"]
    if relative in HELPER_RUNNERS and not any(
        _renders_the_helper_result(expr) for _, expr in rendered
    ):
        problems.append(
            f"{relative} calls {GUARD} but never renders its return value "
            "into the FAIL line"
        )
    for lineno, expr in rendered:
        if _renders_the_exception_object(expr):
            problems.append(
                f"{relative}:{lineno} renders the exception object directly "
                "in its report line; the fallback is dead and the cause is empty"
            )
    return problems


def rendered_cause_errors() -> list[str]:
    problems: list[str] = []
    for relative in RUNNERS:
        problems.extend(_scanner_problems(relative, _source(relative)))
    return problems


def test_every_runner_renders_the_cause_it_computes() -> None:
    """A red gate must print the named cause, not just compute it."""
    found = rendered_cause_errors()
    assert not found, found


def test_a_debug_line_is_not_the_failure_report_line() -> None:
    """A correct runner may log the raw exception next to its report line.

    #265's first scanner collected every ``FormattedValue`` in every f-string
    inside the handler, so a ``print(f"debug: raw={exc}")`` beside a report
    that renders ``describe_assertion(...)`` was rejected as "renders the
    exception object directly; the fallback is dead". Both halves of that
    message are false about a debug line: it is not the report, and no
    fallback lives there.

    Two-way control: the probe must be *clean*, and the bare exception it
    carries must really be outside a report sink with a second, independent
    ``ast.walk``. A clean result from a probe with no bare exception would be
    vacuous rather than earned by the narrowing.
    """
    host = "scripts/test_mcp_openapi_parity.py"
    source = '''
import sys
def run(fn, problems):
    try:
        fn()
    except AssertionError as exc:
        print(f"debug: raw={exc}", file=sys.stderr)
        problems.append(f"{fn.__name__}: {describe_assertion(exc, fn)}")
'''
    rendered = _rendered_exceptions(source, host)
    # The two formatted values of the report f-string, and no third from the
    # debug line. Widening the scope back to "every f-string" makes this 3.
    assert len(rendered) == 2, rendered
    assert any(
        _renders_the_helper_result(expr) for _, expr in rendered
    ), "the report line's helper result was missed"
    assert not any(
        _renders_the_exception_object(expr) for _, expr in rendered
    ), "a debug line leaked into the report"
    assert _scanner_problems(host, source) == [], (
        "a correct runner was rejected for its debug line"
    )

    tree = ast.parse(source, filename=host)
    debug_joined = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.JoinedStr)
        and any(
            isinstance(value, ast.FormattedValue)
            and _renders_the_exception_object(value.value)
            for value in node.values
        )
    ]
    assert len(debug_joined) == 1, "the probe lost its debug f-string"
    enclosing = [
        call
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and call.args
        and call.args[0] is debug_joined[0]
    ]
    assert len(enclosing) == 1
    assert not _is_report_sink(enclosing[0]), (
        "the debug f-string was classified as a report sink"
    )
    assert debug_joined[0].lineno not in {lineno for lineno, _ in rendered}

    # Control, not reading: re-implement #265's "every f-string in the
    # handler" scope here and require that it *would* reject these correct
    # bytes. Without this, a widened scanner could pass by simply seeing no
    # exception object anywhere, rather than because the report is narrow.
    wide_rendered = [
        (node.lineno, value.value)
        for handler in ast.walk(tree)
        if isinstance(handler, ast.ExceptHandler) and handler.type is not None
        for node in ast.walk(handler)
        if isinstance(node, ast.JoinedStr)
        for value in node.values
        if isinstance(value, ast.FormattedValue)
    ]
    assert len(wide_rendered) == 3, wide_rendered
    assert any(
        _renders_the_exception_object(expr) for _, expr in wide_rendered
    ), "the widened scope lost the false positive it is meant to reproduce"
    assert not any(
        _renders_the_exception_object(expr) for _, expr in rendered
    ), "the narrowed scope let the debug exception through"


def test_a_dead_report_is_still_named_when_a_debug_line_is_present() -> None:
    """Narrowing must not become under-reach: a dead *report* stays red."""
    host = "scripts/test_openapi_snapshot_body_integrity.py"
    source = '''
import sys
def run(test, problems):
    try:
        test()
    except AssertionError as exc:
        print(f"debug: raw={exc}", file=sys.stderr)
        problems.append(f"{test.__name__}: {exc or 'assertion failed'}")
'''
    problems = _scanner_problems(host, source)
    assert any(
        "renders the exception object directly" in problem for problem in problems
    ), problems


def test_a_cause_rendered_only_in_debug_does_not_save_a_dead_report() -> None:
    """The helper result must be in the report, not merely somewhere."""
    host = "scripts/test_mcp_openapi_parity.py"
    source = '''
import sys
def run(fn, problems):
    try:
        fn()
    except AssertionError as exc:
        problems.append(f"{fn.__name__}: {exc or 'assertion failed'}")
        print(f"debug: {describe_assertion(exc, fn)}", file=sys.stderr)
'''
    problems = _scanner_problems(host, source)
    assert any("never renders its return value" in p for p in problems), problems
    assert any(
        "renders the exception object directly" in p for p in problems
    ), problems


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

    # (4) a runner that computes the cause but never prints it must be
    # rejected. The helper pin and the wired-runner equality only see that
    # ``describe_assertion`` is called somewhere in the file.
    host = "scripts/test_mcp_openapi_parity.py"
    original = _source(host)
    discarding = original.replace(
        'print(f"FAIL self-test: {fn.__name__}: {describe_assertion(exc, fn)}")',
        'describe_assertion(exc, fn)\n'
        '            print(f"FAIL self-test: {fn.__name__}: '
        "{exc or 'assertion failed'}\")",
        1,
    )
    assert discarding != original, "render ablation did not change the bytes"
    assert any(
        "never renders its return value" in problem
        for problem in _scanner_problems(host, discarding)
    ), "a discarded helper result was not detected"

    # (5) an inline-str runner reverted to the dead object fallback while
    # keeping the reviewed spelling in a comment must also be named. The
    # substring-based ``inline_str_fallback`` cannot see this.
    inline_host = "scripts/test_openapi_snapshot_body_integrity.py"
    inline_original = _source(inline_host)
    dead = inline_original.replace(
        'problems.append(f"{test.__name__}: '
        "{str(exc) or 'assertion failed'}\")",
        "# reviewed spelling: {str(exc) or 'assertion failed'}\n"
        '            problems.append(f"{test.__name__}: '
        "{exc or 'assertion failed'}\")",
        1,
    )
    assert dead != inline_original, "dead-fallback ablation did not change the bytes"
    assert any(
        "renders the exception object directly" in problem
        for problem in _scanner_problems(inline_host, dead)
    ), "a dead fallback hidden behind a comment was not detected"

    # (6) the committed bytes pass all three scanners -- the pins reject the
    # regressions, not the fix itself.
    assert _runner_uses_helper() == []
    assert _empty_list_asserts_are_messaged() == []
    assert rendered_cause_errors() == []


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
