"""Independent experiment tests; requires built wheel + M2_CLI, never imports API."""

import csv
import hashlib
import json
import math
import os
import random
import signal
import subprocess
import threading
import time
from pathlib import Path

import pytest
import soymutdb_enrichment_core as core
from scipy.stats import false_discovery_control, hypergeom

ROOT = Path(__file__).resolve().parents[3]
CLI = Path(os.environ["M2_CLI"]).resolve()


def cli(cases):
    return subprocess.run(
        [CLI],
        input=json.dumps(cases),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def compare(cases, rel=5e-8, absolute=1e-14):
    expected = [float(hypergeom.sf(k - 1, N, K, n)) for N, K, n, k in cases]
    actual = core.sf_batch(cases)
    assert len(actual) == len(expected)
    for case, got, want in zip(cases, actual, expected):
        assert math.isfinite(got) and 0 <= got <= 1, case
        assert math.isclose(got, want, rel_tol=rel, abs_tol=absolute), (case, got, want)
    result = cli(cases)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == actual
    return actual, expected


def test_exact_exhaustive():
    cases, expected = [], []
    for N in range(1, 13):
        for K in range(N + 1):
            for n in range(N + 1):
                lo, hi = max(0, n + K - N), min(n, K)
                for k in range(hi + 2):
                    cases.append([N, K, n, k])
                    expected.append(
                        sum(
                            math.comb(K, x) * math.comb(N - K, n - x)
                            for x in range(max(k, lo), hi + 1)
                        )
                        / math.comb(N, n)
                    )
    got = core.sf_batch(cases)
    assert got == pytest.approx(expected, abs=1e-12)
    compare(cases, absolute=1e-12)


def test_mean_boundaries_and_large_support():
    rng = random.Random(29)
    cases = [
        [10, 8, 4, 0],
        [10, 8, 4, 2],
        [10, 8, 4, 5],
        [10, 0, 4, 1],
        [10, 10, 4, 4],
        [10, 5, 0, 0],
        [800000, 400000, 400000, 200000],
        [2000000, 1000000, 1000000, 1],
        [2000000, 1000000, 1000000, 500000],
    ]
    for _ in range(100):
        N = rng.randint(100, 56000)
        K, n = rng.randint(1, N), rng.randint(1, N)
        mean = n * K // N
        cases.extend([N, K, n, max(0, mean + offset)] for offset in (-1, 0, 1, 2))
    compare(cases)
    assert core.sf_batch([]) == []
    assert core.sf_batch([(10, 8, 4, 5), (10, 8, 4, 2)]) == [0.0, 1.0]


def test_representable_deep_tail():
    cases = [
        [56000, 100, 500, 60],
        [56000, 2000, 500, 150],
        [2000000, 1000000, 1000000, 510000],
    ]
    actual, _ = compare(cases, rel=1e-8, absolute=0)
    assert all(p > 0 for p in actual)


def test_threshold_and_bh_remains_python():
    cases = []
    for N, K, n in (
        (56000, 1000, 500),
        (56000, 20000, 20000),
        (2000000, 100000, 10000),
    ):
        boundary = int(hypergeom.isf(0.05, N, K, n))
        cases.extend([N, K, n, boundary + d] for d in (0, 1, 2))
    actual, expected = compare(cases)
    actual += [0.0, 1.0, 0.01, 0.01]
    expected += [0.0, 1.0, 0.01, 0.01]

    def bh(p):
        result, prev = [0.0] * len(p), 1.0
        for rank, idx in reversed(
            list(enumerate(sorted(range(len(p)), key=p.__getitem__), 1))
        ):
            prev = min(prev, p[idx] * len(p) / rank)
            result[idx] = prev
        return result

    q = bh(actual)
    reference = false_discovery_control(expected, method="bh").tolist()
    assert q == pytest.approx(reference, rel=5e-8, abs=1e-14)
    assert [p <= 0.05 for p in actual] == [p <= 0.05 for p in expected]
    assert [p <= 0.05 for p in q] == [p <= 0.05 for p in reference]


@pytest.mark.parametrize(
    "invalid",
    [
        None,
        {},
        [1, 2, 3, 4],
        [[10, 5, 4]],
        [[10, 5, 4, 2, 0]],
        [[0, 0, 0, 0]],
        [[10, 11, 1, 0]],
        [[10, 1, 11, 0]],
        [[2000001, 1, 1, 0]],
        [[10, 5, 4, -1]],
        [[10, 5, 4, 2**64]],
        [[10, 5, 4, 2.0]],
        [[10, 5, 4, True]],
        [[10, 5, 4, float("nan")]],
        [[10, 5, 4, 2], [10, 5, -1, 2]],
        [[10, 5, 4, "2"]],
    ],
)
def test_invalid_atomic(invalid):
    with pytest.raises(ValueError):
        core.sf_batch(invalid)
    result = cli(invalid)
    assert result.returncode == 2 and result.stdout == "" and result.stderr


@pytest.mark.parametrize("position", range(4))
def test_each_count_position_rejects_invalid(position):
    for invalid in (-1, 2**64, 2.0, True, "2", float("nan"), float("inf")):
        row = [10, 5, 4, 2]
        row[position] = invalid
        with pytest.raises(ValueError):
            core.sf_batch([[10, 5, 4, 2], row])
        result = cli([[10, 5, 4, 2], row])
        assert result.returncode == 2 and not result.stdout


def test_resource_caps():
    for batch in (
        [[10, 5, 4, 2]] * 100001,
        [[2000000, 1000000, 1000000, 500000]] * 101,
    ):
        with pytest.raises(ValueError, match="resource cap"):
            core.sf_batch(batch)
        result = cli(batch)
        assert result.returncode == 2 and not result.stdout
    assert core.sf_batch([[10, 5, 4, 2**64 - 1]]) == [0.0]
    result = subprocess.run(
        [CLI],
        input=" " * (16 * 1024 * 1024 + 1),
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and not result.stdout


def test_scalar_same_kernel():
    cases = [[20, 5, 4, 2], [10, 8, 4, 5], [56000, 100, 500, 60]]
    assert [core.hypergeom_sf(*row) for row in cases] == core.sf_batch(cases)
    with pytest.raises(ValueError):
        core.hypergeom_sf(10, 5, 4, False)


def test_real_public_annotation_snapshot():
    source = ROOT / ".validation/m2-upstream-20261008/go.normalized.tsv"
    assert (
        hashlib.sha256(source.read_bytes()).hexdigest()
        == "ea7d4572f234fa3afd7b3503b38e5bc3884fbe048168cc65632c978b1e0ebd0f"
    )
    mapping, genes = {}, set()
    with source.open() as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            mapping.setdefault(row["term_id"], set()).add(row["gene_id"])
            genes.add(row["gene_id"])
    assert (sum(map(len, mapping.values())), len(genes), len(mapping)) == (
        61090,
        26028,
        1506,
    )
    sample = set(random.Random(17).sample(sorted(genes), 500))
    cases = [
        [len(genes), len(term), len(sample), len(sample & term)]
        for _, term in sorted(mapping.items())
    ]
    compare(cases, rel=1e-9, absolute=0)


def test_gil_release_during_computation():
    # Main thread probes while another thread is *inside* numerical work.
    started, finished = threading.Event(), threading.Event()
    duration = []

    def worker():
        started.set()
        begin = time.perf_counter()
        core.sf_batch([[2000000, 1000000, 1000000, 500000]] * 100)
        duration.append(time.perf_counter() - begin)
        finished.set()

    thread = threading.Thread(target=worker)
    thread.start()
    started.wait()
    probes = 0
    while not finished.wait(0.001):
        probes += 1
    thread.join()
    assert duration[0] > 0.01 and probes >= 2, (duration, probes)


def test_python_signal_cancellation():
    code = "import signal,soymutdb_enrichment_core as c; signal.setitimer(signal.ITIMER_REAL,.02); signal.signal(signal.SIGALRM,signal.default_int_handler); c.sf_batch([[2000000,1000000,1000000,500000]]*100); print('partial')"
    result = subprocess.run(
        [os.sys.executable, "-c", code],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode != 0 and result.stdout == ""
    assert "KeyboardInterrupt" in result.stderr


def test_cli_eof_errors_and_process_cancel():
    for payload in ("", "[", "[] []"):
        result = subprocess.run(
            [CLI], input=payload, text=True, capture_output=True, timeout=5, check=False
        )
        assert result.returncode == 2 and not result.stdout
    proc = subprocess.Popen(
        [CLI], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    try:
        proc.stdin.write(
            json.dumps([[2000000, 1000000, 1000000, 500000]] * 100).encode()
        )
        proc.stdin.close()
        proc.stdin = None
        time.sleep(0.02)
        proc.send_signal(signal.SIGTERM)
        out, _ = proc.communicate(timeout=5)
        assert proc.returncode == -signal.SIGTERM and not out
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
