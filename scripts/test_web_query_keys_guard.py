"""Source-level regression tests for the portal query-key guard.

The guard exists because the assembly catalogue is release- and site-scoped
(`apps/api/app/api/v1/genes.py` caches by `genes:assemblies:release:{id}`).
Two defects are guarded here because both produced a silent PASS on real
source:

1. It used to glob `apps/web/src/views/*.vue`, which has been empty since the
   Vue retirement — `len(consumers) == 0` held for every tree, so it could
   never fail.
2. It then extracted the factory arguments with `\\(([^)]*)\\)`, which stops
   at the first `)`. Every real call passes `getReleaseId()` inside the
   context, so `siteVariant` was invisible and nine correctly-scoped consumers
   were reported as violations. A guard that is wrong in the direction of
   "red" is still a guard that gets disabled.
"""
from pathlib import Path

import pytest

from scripts import check_web_query_keys as guard

SCOPED_CALL = """
const assembliesQuery = useQuery(assembliesQueryOptions({
  releaseId: getReleaseId(),
  siteVariant: SITE_VARIANT,
}));
"""


@pytest.fixture
def route_tree(tmp_path):
    routes = tmp_path / "apps/web/src/routes"
    routes.mkdir(parents=True)
    return routes


def put(routes: Path, name: str, text: str) -> None:
    target = routes / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def test_scoped_call_with_nested_call_is_accepted(route_tree):
    put(route_tree, "search.tsx", SCOPED_CALL)
    assert guard.main(["--routes-dir", str(route_tree)]) == 0


def test_empty_route_scan_is_a_failure_not_a_pass(route_tree, capsys):
    assert guard.main(["--routes-dir", str(route_tree)]) == 1
    assert "empty React route scan" in capsys.readouterr().err


def test_generated_and_test_files_are_not_consumers(route_tree):
    put(route_tree, "search.tsx", SCOPED_CALL)
    put(route_tree, "search.test.tsx", "useQuery(assembliesQueryOptions());")
    put(route_tree, ".umi/core/generated.ts", "useQuery(assembliesQueryOptions());")
    put(route_tree, "dist/bundle.ts", "useQuery(assembliesQueryOptions());")
    assert guard.main(["--routes-dir", str(route_tree)]) == 0


@pytest.mark.parametrize(
    "mutation",
    [
        pytest.param("  siteVariant: SITE_VARIANT,\n", id="site-variant-dropped"),
        pytest.param("  releaseId: getReleaseId(),\n", id="release-dropped"),
    ],
)
def test_dropping_a_scope_field_flips_the_guard(route_tree, mutation):
    put(route_tree, "search.tsx", SCOPED_CALL)
    assert guard.main(["--routes-dir", str(route_tree)]) == 0
    put(route_tree, "search.tsx", SCOPED_CALL.replace(mutation, ""))
    assert guard.main(["--routes-dir", str(route_tree)]) == 1
    put(route_tree, "search.tsx", SCOPED_CALL)
    assert guard.main(["--routes-dir", str(route_tree)]) == 0


def test_handwritten_key_and_direct_read_are_rejected(route_tree):
    put(route_tree, "handwritten.tsx", """
    const query = useQuery({ queryKey: ["assemblies", releaseId], queryFn: getAssemblies });
    """)
    assert guard.main(["--routes-dir", str(route_tree)]) == 1


def test_balanced_scanner_is_not_fooled_by_parentheses_in_strings():
    assert guard.call_arguments("f({ a: ')' })", 1) == "{ a: ')' }"
    assert guard.call_arguments("f({ a: '})' })", 1) == "{ a: '})' }"