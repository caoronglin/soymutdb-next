"""Exercise official pyDEG with synthetic counts; never a production adapter."""

import argparse
import hashlib
import importlib.metadata as md
import inspect
import json
import multiprocessing
import os
import pathlib
import platform
import resource
import sys
import time
import traceback
import warnings


def checksum(data):
    return hashlib.sha256(data.to_csv(lineterminator="\n").encode()).hexdigest()


def qualify(report, output):
    import numpy as np
    import omicverse as ov
    import pandas as pd
    from scipy.stats import ttest_ind
    from statsmodels.stats.multitest import multipletests

    cls = ov.bulk.pyDEG
    report["stages"]["official_import"] = "passed"
    report["versions"] = {d.metadata["Name"]: d.version for d in md.distributions()}
    assert md.version("omicverse") == "2.3.2"
    assert md.version("pydeseq2") == "0.5.4"
    report["api_signatures"] = {
        name: str(inspect.signature(getattr(cls, name)))
        for name in ("__init__", "normalize", "deg_analysis")
    }
    report["source_sha256"] = hashlib.sha256(inspect.getsource(cls).encode()).hexdigest()
    rng = np.random.default_rng(report["seed"])
    counts = rng.poisson(100, size=(200, 8)).astype("int64")
    counts[:20, 4:] = rng.poisson(500, size=(20, 4))
    counts[20:40, :4] = rng.poisson(500, size=(20, 4))
    counts[-2, :] = 0
    counts[-1, :] = 100
    control = [f"control_{i}" for i in range(4)]
    treated = [f"treated_{i}" for i in range(4)]
    raw = pd.DataFrame(
        counts, index=[f"toy_gene_{i:03d}" for i in range(200)], columns=control + treated
    )
    metadata = pd.DataFrame(
        {"condition": ["control"] * 4 + ["treated"] * 4}, index=raw.columns
    )
    original = raw.copy(deep=True)
    raw.to_csv(output / "toy-counts.csv")
    metadata.to_csv(output / "toy-metadata.csv")
    report["data"] = {
        "shape": list(raw.shape), "dtype": str(raw.values.dtype),
        "counts_sha256": checksum(raw), "metadata_sha256": checksum(metadata),
        "contrast": "treated relative to control", "group1": treated, "group2": control,
        "zero_count_gene": "toy_gene_198", "constant_gene": "toy_gene_199",
    }
    obj = cls(raw)
    norm = obj.normalize()
    assert raw.equals(original) and obj.raw_data.equals(original)
    assert np.isfinite(norm.values).all() and not norm.equals(raw)
    report["stages"]["normalize"] = "passed"
    report["normalization"] = {
        "size_factors": obj.size_factors.to_dict(), "caller_raw_counts_unchanged": True,
        "object_raw_data_unchanged": True, "object_data_dtype": str(obj.data.values.dtype),
        "normalized_sha256": checksum(norm),
    }
    params = {
        "alpha": 0.05, "multipletests_method": "fdr_bh", "n_cpus": 1,
        "cooks_filter": False, "independent_filter": False,
    }
    result = obj.deg_analysis(treated, control, method="ttest", **params)
    assert np.isfinite(result[["log2FC", "pvalue", "qvalue"]].values).all()
    assert result.pvalue.between(0, 1).all() and result.qvalue.between(0, 1).all()
    assert (result.loc[raw.index[:20], "log2FC"] > 0).all()
    assert (result.loc[raw.index[20:40], "log2FC"] < 0).all()
    assert len(result) == 199 and "toy_gene_198" not in result.index
    assert int((result.qvalue < 0.05).sum()) == 40
    # Reproduce the published rule, NOT an endorsement of NaN -> significant zero.
    pvalues = ttest_ind(norm[treated].T.values, norm[control].T.values).pvalue
    bh = multipletests(np.nan_to_num(pvalues, nan=0), method="fdr_bh")[1]
    keep = np.isfinite(pvalues)
    assert result.index.equals(raw.index[keep])
    assert np.allclose(result.qvalue.values, bh[keep], rtol=1e-12, atol=1e-15)
    filtered_first = multipletests(pvalues[keep], method="fdr_bh")[1]
    report["ttest"] = {
        "parameters": {"method": "ttest", **params}, "rows": len(result),
        "significant_q_lt_005": int((result.qvalue < 0.05).sum()),
        "positive_engineered": 20, "negative_engineered": 20,
        "filtered_genes": raw.index.difference(result.index).tolist(),
        "BH_verified_published_nan_to_zero_rule": True,
        "max_difference_from_filter_NA_before_BH": float(
            np.max(abs(result.qvalue.values - filtered_first))
        ),
        "columns": list(result.columns), "output_sha256": checksum(result),
    }
    result.to_csv(output / "toy-ttest-results.csv")
    report["stages"]["normalized_ttest"] = "passed"
    try:
        obj.deg_analysis(treated, control, method="DEseq2", **params)
    except ValueError as exc:
        assert str(exc) == "The count matrix should only contain integers."
        report["normalized_DEseq2_probe"] = {
            "status": "expected_failure", "type": "ValueError", "message": str(exc)
        }
    else:
        raise AssertionError("normalized same-object DEseq2 unexpectedly accepted float counts")
    fresh = cls(raw)
    de = fresh.deg_analysis(treated, control, method="DEseq2", **params)
    valid = de[["log2FC", "pvalue", "padj"]].notna().all(axis=1)
    assert len(de) == 200 and int(valid.sum()) == 199
    assert de.index[~valid].tolist() == ["toy_gene_198"]
    assert np.isfinite(de.loc[valid, ["log2FC", "pvalue", "padj"]].values).all()
    assert de.loc[valid, "pvalue"].between(0, 1).all()
    assert de.loc[valid, "padj"].between(0, 1).all()
    assert (de.loc[raw.index[:20], "log2FC"] > 0).all()
    assert (de.loc[raw.index[20:40], "log2FC"] < 0).all()
    assert int((de.padj < 0.05).sum()) == 40
    pv = de.pvalue.notna()
    assert np.allclose(
        de.loc[pv, "padj"], multipletests(de.loc[pv, "pvalue"], method="fdr_bh")[1],
        rtol=1e-12, atol=1e-15,
    )
    assert raw.equals(original) and fresh.raw_data.equals(original)
    report["deseq2"] = {
        "parameters": {"method": "DEseq2", **params}, "rows": len(de),
        "finite_rows": int(valid.sum()), "NA_genes": de.index[~valid].tolist(),
        "significant_padj_lt_005": int((de.padj < 0.05).sum()),
        "positive_engineered": 20, "negative_engineered": 20,
        "BH_verified": True, "caller_raw_counts_unchanged": True,
        "input": "fresh object with original integer counts",
        "columns": list(de.columns), "output_sha256": checksum(de),
    }
    de.to_csv(output / "toy-deseq2-results.csv")
    report["stages"]["raw_counts_DEseq2"] = "passed"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error("assertions must remain enabled; do not use -O or PYTHONOPTIMIZE")
    output = args.output.absolute()
    output.mkdir(parents=True, exist_ok=False)
    source = pathlib.Path(__file__).resolve().parent
    report = {
        "scope": "M3 isolated experimental qualification; not production readiness",
        "python": platform.python_version(), "platform": platform.platform(),
        "machine": platform.machine(), "seed": 20261008,
        "assembly": "synthetic-toy-only", "release": "synthetic-toy-only", "stages": {},
        "lock_sha256": hashlib.sha256((source / "requirements.lock").read_bytes()).hexdigest(),
        "warnings": [
            "Preserve raw counts: normalized same-object DEseq2 rejects noninteger counts.",
            "ttest substitutes NaN p with 0 before BH, then filters; not a production default.",
            "DEseq2 ignores multipletests_method; PyDESeq2 applies BH on non-NA pvalues.",
            "OmicVerse omits DeseqStats n_cpus; PYTHON_CPU_COUNT=1 is required here.",
        ],
        "uncovered": [
            "public reference dataset/scientific benchmark", "M4 adapter/invalid-input matrix",
            "M5 jobs/persistence/cancellation", "M6 API/UI", "M7 images/production",
            "other platforms/ABIs and production worker environment decision",
        ],
    }
    start = time.monotonic()
    try:
        assert sys.version_info[:2] == (3, 14)
        assert platform.system() == "Linux" and platform.machine() == "x86_64"
        assert multiprocessing.cpu_count() == 1
        assert os.environ.get("PYTHON_CPU_COUNT") == "1"
        assert all(os.environ.get(key) == "1" for key in (
            "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMBA_NUM_THREADS"
        ))
        report["resources"] = {
            "cpu_affinity": sorted(os.sched_getaffinity(0)),
            "multiprocessing_cpu_count": multiprocessing.cpu_count(),
            "address_space_limit_bytes": resource.getrlimit(resource.RLIMIT_AS)[0],
        }
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            qualify(report, output)
            report["warnings"].extend(str(item.message) for item in caught)
        report["status"] = "qualified_with_method_caveats"
    except Exception:  # noqa: BLE001 -- record unexpected failures, then return nonzero.
        report["status"] = "failed"
        report["failure"] = traceback.format_exc()
    finally:
        report["elapsed_seconds"] = time.monotonic() - start
        report["max_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        (output / "qualification.json").write_text(
            json.dumps(report, indent=2, allow_nan=False) + "\n"
        )
        print(json.dumps(report, indent=2, allow_nan=False))
    return 0 if report["status"] == "qualified_with_method_caveats" else 1


if __name__ == "__main__":
    sys.exit(main())
