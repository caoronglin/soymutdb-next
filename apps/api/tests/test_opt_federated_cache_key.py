"""OPT-03: the federated search cache key must carry the biological scope.

GAP-3 / cache-site.md S13: ``SearchCache.make_key`` used to hash only
``(query, sorted(sources))``, so a federated result cached for one release,
assembly or site variant could be served for another.  These tests pin both
halves of the required contract:

* a scoped key separates release / assembly / site variant, is canonical and
  stable, and never splits one logical scope across two keys;
* a fully unscoped key stays byte-identical to the pre-change algorithm, so
  existing callers and warm cache entries keep working.
"""

from __future__ import annotations

import hashlib

from app.core.site_variant import SiteVariant
from app.search.cache import KEY_NAMESPACE, SearchCache

SOURCES = ("ncbi", "uniprot")
QUERY = "Glyma.01G000100"


def _prechange_key(query: str, sources: tuple[str, ...]) -> str:
    """Independent re-implementation of the pre-OPT-03 key algorithm."""
    digest = hashlib.sha256()
    digest.update(query.encode("utf-8"))
    digest.update(b"|")
    for source in sorted(sources):
        digest.update(source.encode("utf-8"))
        digest.update(b",")
    return f"search:{digest.hexdigest()}"


# --------------------------------------------------------------- compatibility
def test_unscoped_key_equals_the_prechange_key() -> None:
    """DoD 2: omitted/None scope must keep producing the legacy key."""
    assert SearchCache.make_key(QUERY, SOURCES) == _prechange_key(QUERY, SOURCES)
    assert SearchCache.make_key(
        QUERY,
        SOURCES,
        site_variant=None,
        release_id=None,
        assembly_id=None,
        filters=None,
    ) == _prechange_key(QUERY, SOURCES)


def test_unscoped_key_keeps_prefix_and_sha256_hex_format() -> None:
    key = SearchCache.make_key(QUERY, SOURCES)
    assert key.startswith(f"{KEY_NAMESPACE}:")
    assert len(key.removeprefix(f"{KEY_NAMESPACE}:")) == 64


def test_unscoped_key_is_source_order_insensitive() -> None:
    assert SearchCache.make_key(QUERY, ("uniprot", "ncbi")) == SearchCache.make_key(
        QUERY, ("ncbi", "uniprot")
    )


# ------------------------------------------------------------------- separation
def _scoped(**scope: object) -> str:
    return SearchCache.make_key(QUERY, SOURCES, **scope)


def test_each_scope_axis_changes_the_key() -> None:
    """DoD 1: release OR assembly OR site variant must fork the key."""
    base = _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11
    )
    assert base != _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id=8, assembly_id=11
    )
    assert base != _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=12
    )
    assert base != _scoped(
        site_variant=SiteVariant.INTERNAL, release_id=7, assembly_id=11
    )
    assert base != _scoped(release_id=7, assembly_id=11)  # scoped vs unscoped
    assert len(
        {
            base,
            _scoped(site_variant=SiteVariant.EXTERNAL, release_id=8, assembly_id=11),
            _scoped(site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=12),
            _scoped(site_variant=SiteVariant.INTERNAL, release_id=7, assembly_id=11),
            _scoped(release_id=7, assembly_id=11),
        }
    ) == 5


def test_missing_scope_value_never_collides_with_a_concrete_one() -> None:
    assert _scoped(site_variant=SiteVariant.EXTERNAL, release_id=None) != _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id=7
    )
    assert _scoped(site_variant=SiteVariant.EXTERNAL, assembly_id=None) != _scoped(
        site_variant=SiteVariant.EXTERNAL, assembly_id=11
    )


def test_scoped_key_has_the_site_variant_segment() -> None:
    external = _scoped(site_variant=SiteVariant.EXTERNAL)
    internal = _scoped(site_variant=SiteVariant.INTERNAL)
    assert external.startswith(f"{KEY_NAMESPACE}:external:")
    assert internal.startswith(f"{KEY_NAMESPACE}:internal:")
    assert len(internal.rsplit(":", 1)[-1]) == 64


# ----------------------------------------------------------------- canonicality
def test_identical_scope_is_stable() -> None:
    """DoD 1: the same scope always produces the same key."""
    first = _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11
    )
    second = _scoped(
        release_id=7, assembly_id=11, site_variant=SiteVariant.EXTERNAL
    )
    assert first == second


def test_int_and_str_scope_values_do_not_fork_the_key() -> None:
    """One logical scope must not exist twice because of a type spelling."""
    assert _scoped(site_variant=SiteVariant.EXTERNAL, release_id=7, assembly_id=11) == _scoped(
        site_variant=SiteVariant.EXTERNAL, release_id="7", assembly_id="11"
    )
    assert _scoped(site_variant="external") == _scoped(site_variant=SiteVariant.EXTERNAL)
    assert _scoped(
        site_variant=SiteVariant.EXTERNAL, filters={"limit_per_source": 8}
    ) == _scoped(
        site_variant=SiteVariant.EXTERNAL, filters={"limit_per_source": "8"}
    )


def test_filter_key_order_is_irrelevant() -> None:
    assert _scoped(
        site_variant=SiteVariant.EXTERNAL, filters={"a": 1, "b": 2}
    ) == _scoped(site_variant=SiteVariant.EXTERNAL, filters={"b": 2, "a": 1})


def test_filter_values_change_the_key() -> None:
    assert _scoped(
        site_variant=SiteVariant.EXTERNAL, filters={"limit_per_source": 8}
    ) != _scoped(site_variant=SiteVariant.EXTERNAL, filters={"limit_per_source": 20})
    assert _scoped(site_variant=SiteVariant.EXTERNAL, filters={"limit_per_source": 8}) != _scoped(
        site_variant=SiteVariant.EXTERNAL
    )
