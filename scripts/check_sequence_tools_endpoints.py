#!/usr/bin/env python3
"""Guard the sequence-tools router against a stale-base endpoint reversion.

PR #108 was rebased onto a base older than the P2 sequence-tools work and
carried the *old* 8-endpoint ``tools_sequence.py`` wholesale: ``/statistics``
replaced ``/stats``, ``/intervals`` replaced ``/inspect``, and ``/capabilities``
disappeared. It also carried the matching ``openapi.json`` / ``openapi.d.ts``,
so ``check-contract.sh`` compared the reverted backend against the reverted
snapshot and said OK, while ``test_openapi_snapshot_contract.py`` reads the
*generated* document and never looks at routes only present in source.

This guard reads the committed Python source directly. It does not read
``openapi.json``, does not import the FastAPI app, and does not depend on an API
venv, so it cannot be silenced by reverting source, snapshot and tests together.
``check-contract.sh`` stays the sole authority on export/snapshot agreement;
this is the source-level complement it was missing.

Pinned invariants:

- every published operation is still declared, including ``/inspect`` and
  ``/capabilities``;
- the retired legacy spellings ``/statistics`` and ``/intervals`` are gone.

``--source-path`` points the guard at any tree, which is how ``--self-test`` and
the regression tests below exercise the negative cases without a live repo.
"""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "apps/api/app/api/v1/tools_sequence.py"

#: Every operation the public contract promises, as (method, path). The method
#: is pinned too: ``/capabilities`` silently turning into a POST is a contract
#: break even though the path string survives.
REQUIRED_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("get", "/capabilities"),
    ("post", "/reverse-complement"),
    ("post", "/match"),
    ("post", "/align"),
    ("post", "/stats"),
    ("post", "/orfs"),
    ("post", "/translate"),
    ("post", "/kmers"),
    ("post", "/inspect"),
)

#: Legacy spellings from the pre-P2 8-endpoint router. Their return means the
#: branch was rebased onto a base that predates the sequence-tools work.
RETIRED_PATHS: tuple[str, ...] = ("/statistics", "/intervals")

ROUTER_PREFIX = "/tools/sequence"

_DECORATOR = re.compile(
    r"^\s*@router\.(get|post|put|patch|delete)\(\s*[\"']([^\"']+)[\"']", re.MULTILINE
)
_PREFIX = re.compile(r"APIRouter\(\s*prefix\s*=\s*[\"']([^\"']+)[\"']")


def strip_comments(text: str) -> str:
    """Drop comments and docstrings so prose cannot satisfy or trip a pin.

    The module docstring names ``GET /capabilities`` and the retired paths; a
    naive scan would treat that text as a declaration. Strings are not removed
    wholesale because route paths *are* strings, so only comment lines and
    triple-quoted blocks go.
    """
    text = re.sub(r'"""(?:[\s\S]*?)"""', "", text)
    text = re.sub(r"'''(?:[\s\S]*?)'''", "", text)
    return re.sub(r"#[^\n]*", "", text)


def declared_endpoints(source: str) -> list[tuple[str, str]]:
    body = strip_comments(source)
    return [(method.lower(), path) for method, path in _DECORATOR.findall(body)]


def inspect(source: str) -> list[str]:
    failures: list[str] = []
    body = strip_comments(source)

    prefix = _PREFIX.search(body)
    if not prefix:
        failures.append("tools_sequence.py no longer declares an APIRouter prefix")
    elif prefix.group(1).rstrip("/") != ROUTER_PREFIX:
        failures.append(
            f"router prefix is {prefix.group(1)!r}, expected {ROUTER_PREFIX!r}"
        )

    declared = declared_endpoints(source)
    if not declared:
        failures.append("tools_sequence.py declares no @router routes at all")
        return failures

    declared_set = set(declared)
    for method, path in REQUIRED_ENDPOINTS:
        if (method, path) not in declared_set:
            failures.append(
                f"missing route: {method.upper()} {path}"
                + (
                    " (dropped by the pre-P2 8-endpoint reversion)"
                    if path in {"/inspect", "/capabilities", "/stats"}
                    else ""
                )
            )

    # A path can be present under the wrong verb after a careless rebase; report
    # that distinctly so the diagnostic names the actual defect.
    for method, path in REQUIRED_ENDPOINTS:
        if (method, path) in declared_set:
            continue
        other = sorted(m for m, p in declared_set if p == path and m != method)
        if other:
            failures.append(
                f"route {path} is declared as {'/'.join(other).upper()}, expected {method.upper()}"
            )

    for path in RETIRED_PATHS:
        if any(p == path for _, p in declared_set):
            failures.append(
                f"retired legacy route is back: {path} (pre-P2 8-endpoint spelling)"
            )

    duplicates = sorted(
        {route for route in declared if declared.count(route) > 1}
    )
    for method, path in duplicates:
        failures.append(f"route {method.upper()} {path} is declared more than once")

    return failures


def self_test() -> int:
    """Negative-first checks: each broken source below must be rejected."""
    good = (
        'router = APIRouter(prefix="/tools/sequence", tags=["tools"])\n'
        "\n"
        '@router.get("/capabilities")\n'
        "async def caps(): ...\n"
        "\n"
        '@router.post("/reverse-complement")\n'
        "async def rc(): ...\n"
        "\n"
        '@router.post("/match")\n'
        "async def match(): ...\n"
        "\n"
        '@router.post("/align")\n'
        "async def align(): ...\n"
        "\n"
        '@router.post("/stats")\n'
        "async def stats(): ...\n"
        "\n"
        '@router.post("/orfs")\n'
        "async def orfs(): ...\n"
        "\n"
        '@router.post("/translate")\n'
        "async def translate(): ...\n"
        "\n"
        '@router.post("/kmers")\n'
        "async def kmers(): ...\n"
        "\n"
        '@router.post("/inspect")\n'
        "async def inspect_(): ...\n"
    )
    assert inspect(good) == [], inspect(good)
    # The pin is data too. Derive the published set from the known-good router
    # above rather than restating the list: deleting one line from
    # REQUIRED_ENDPOINTS then fails here, not just in the external wiring test.
    assert tuple(REQUIRED_ENDPOINTS) == tuple(declared_endpoints(good)), (
        "REQUIRED_ENDPOINTS no longer matches the published router set"
    )

    # The exact reversion PR #108 carried: 8 endpoints, legacy spellings, no
    # /inspect or /capabilities.
    reverted = (
        'router = APIRouter(prefix="/tools/sequence", tags=["tools"])\n'
        '@router.post("/reverse-complement")\n'
        "async def rc(): ...\n"
        '@router.post("/match")\n'
        "async def match(): ...\n"
        '@router.post("/align")\n'
        "async def align(): ...\n"
        '@router.post("/statistics")\n'
        "async def stats(): ...\n"
        '@router.post("/orfs")\n'
        "async def orfs(): ...\n"
        '@router.post("/translate")\n'
        "async def translate(): ...\n"
        '@router.post("/kmers")\n'
        "async def kmers(): ...\n"
        '@router.post("/intervals")\n'
        "async def inspect_(): ...\n"
    )
    failures = inspect(reverted)
    assert any("GET /capabilities" in f for f in failures), failures
    assert any("POST /inspect" in f for f in failures), failures
    assert any("POST /stats" in f for f in failures), failures
    assert any("retired legacy route is back: /statistics" in f for f in failures), failures
    assert any("retired legacy route is back: /intervals" in f for f in failures), failures

    # Dropping one route from an otherwise current router must be caught, so the
    # guard does not only recognise the whole-file swap.
    assert inspect(good.replace('@router.post("/inspect")\n', "")) != []

    # Verb drift: the path survives but the contract does not.
    drifted = good.replace('@router.get("/capabilities")', '@router.post("/capabilities")')
    assert inspect(drifted) != []

    # Comment-only text must neither satisfy a pin nor trip a retired path.
    commented = good.replace('@router.post("/inspect")\n', "") + (
        '# @router.post("/inspect") was removed\n'
    )
    assert inspect(commented) != [], "a commented-out route must not count as declared"
    assert inspect(good + '\n# legacy: /statistics, /intervals\n') == []

    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "tools_sequence.py"
        path.write_text(reverted, encoding="utf-8")
        assert main(["--source-path", str(path)]) == 1
        path.write_text(good, encoding="utf-8")
        assert main(["--source-path", str(path)]) == 0
        path.unlink()
        assert main(["--source-path", str(path)]) == 1
    print("sequence-tools endpoint guard self-test passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-path", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument(
        "--self-test", action="store_true", help="run the built-in negative cases"
    )
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.source_path.is_file():
        print(
            f"sequence-tools endpoint contract failed: {args.source_path} is missing",
            file=sys.stderr,
        )
        return 1
    failures = inspect(args.source_path.read_text(encoding="utf-8"))
    if failures:
        print("sequence-tools endpoint contract failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print(
            "  restore apps/api/app/api/v1/tools_sequence.py to the P2 9-endpoint "
            "router; do not rebase onto a base older than the sequence-tools work",
            file=sys.stderr,
        )
        return 1
    print("sequence-tools endpoint contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
