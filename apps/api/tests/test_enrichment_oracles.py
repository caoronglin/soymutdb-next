"""Independent numerical oracles and a regression for truncated right tails."""

import math
import random
import tracemalloc

import pytest
from scipy.stats import false_discovery_control, hypergeom

from app.services.enrichment_service import benjamini_hochberg, hypergeom_sf


@pytest.mark.parametrize(
    "N,K,n,k",
    [
        (20, 5, 4, 2),
        (10, 8, 4, 1),
        (10, 8, 4, 2),
        (10, 8, 4, 5),
        (10, 10, 4, 4),
        (10, 10, 4, 5),
        (10, 0, 4, 1),
        (10, 5, 0, 0),
        (56000, 100, 500, 10),
        (56000, 20000, 20000, 7143),
        (2000000, 1000000, 1000000, 1),
    ],
)
def test_hypergeometric_inclusive_right_tail_matches_scipy(N, K, n, k):
    # scipy.sf is exclusive: P(X >= k) is sf(k - 1), not sf(k).
    expected = float(hypergeom.sf(k - 1, N, K, n))
    got = hypergeom_sf(N, K, n, k)
    assert math.isfinite(got) and 0 <= got <= 1
    assert got == pytest.approx(expected, rel=5e-8, abs=1e-14)


def test_small_hypergeometric_support_exhaustively_matches_scipy():
    for N in range(1, 12):
        for K in range(N + 1):
            for n in range(N + 1):
                for k in range(min(K, n) + 2):
                    expected = float(hypergeom.sf(k - 1, N, K, n))
                    assert hypergeom_sf(N, K, n, k) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "N,K,n,k",
    [
        # Deep right tails: an absolute tolerance would accept a value wrong by
        # many orders of magnitude, so these assert relative precision instead.
        (56000, 100, 500, 60),
        (56000, 2000, 500, 150),
        (2000000, 1000000, 1000000, 1),
    ],
)
def test_hypergeometric_deep_right_tail_keeps_relative_precision(N, K, n, k):
    expected = float(hypergeom.sf(k - 1, N, K, n))
    got = hypergeom_sf(N, K, n, k)
    assert got > 0, "a representable tail must not collapse to zero"
    assert got == pytest.approx(expected, rel=1e-8, abs=0)


@pytest.mark.parametrize("pvalues", [[0, 1, 0.01, 0.01, 0.2], [1], [0], [1e-100, 1e-50, 0.5]])
def test_bh_preserves_order_and_matches_scipy(pvalues):
    assert benjamini_hochberg(pvalues) == pytest.approx(
        false_discovery_control(pvalues, method="bh").tolist(), rel=1e-12, abs=0
    )


def test_bh_randomized_ties_and_extremes_match_scipy():
    rng = random.Random(17)
    values = [rng.random() for _ in range(1000)] + [0.0, 1.0, 0.01, 0.01]
    assert benjamini_hochberg(values) == pytest.approx(
        false_discovery_control(values, method="bh").tolist(), rel=1e-12, abs=0
    )
    assert benjamini_hochberg([]) == []


def test_hypergeometric_large_support_streams_without_a_tail_list():
    # 200,000 terms would require megabytes if retained as Python floats.
    tracemalloc.start()
    try:
        probability = hypergeom_sf(800000, 400000, 400000, 200000)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 256_000
    assert probability == pytest.approx(
        float(hypergeom.sf(199999, 800000, 400000, 400000)), rel=5e-8, abs=0
    )


def test_hypergeometric_significance_decisions_match_scipy():
    cases = []
    for N, K, n in ((56000, 1000, 500), (56000, 20000, 20000), (2000000, 100000, 10000)):
        boundary = int(hypergeom.isf(0.05, N, K, n))
        cases.extend((N, K, n, boundary + offset) for offset in (0, 1, 2))
    expected = [float(hypergeom.sf(k - 1, N, K, n)) for N, K, n, k in cases]
    actual = [hypergeom_sf(*case) for case in cases]
    assert [p <= 0.05 for p in actual] == [p <= 0.05 for p in expected]
    expected_q = false_discovery_control(expected, method="bh").tolist()
    actual_q = benjamini_hochberg(actual)
    assert actual_q == pytest.approx(expected_q, rel=5e-8, abs=1e-14)
    assert [q <= 0.05 for q in actual_q] == [q <= 0.05 for q in expected_q]


def test_hypergeometric_both_sides_of_mean_and_positive_support_match_scipy():
    rng = random.Random(29)
    for _ in range(100):
        N = rng.randint(100, 56000)
        K, n = rng.randint(1, N), rng.randint(1, N)
        mean = n * K // N
        for k in (mean - 1, mean, mean + 1, mean + 2):
            expected = float(hypergeom.sf(k - 1, N, K, n))
            assert hypergeom_sf(N, K, n, k) == pytest.approx(expected, rel=5e-8, abs=1e-14)
