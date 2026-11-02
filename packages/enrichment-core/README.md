# Experimental enrichment SF candidate

Not connected to production. Current Python service remains the statistical owner;
BH stays in Python. Both bindings call the same constant-space f64 kernel.

## Contract

- Inclusive survival probability `P(X >= k)` for integer counts `[N,K,n,k]`.
- `1 <= N <= 2_000_000`, `0 <= K,n <= N`; `k` is nonnegative u64.
  Support boundaries return exactly 1/0, including k above support.
- Python `sf_batch(rows)` accepts only list/tuple batches and list/tuple four-count
  rows; integers only, not bool/float/NaN/string. Returns values in input order.
- `hypergeom_sf(N,K,n,k)` is a same-kernel scalar wrapper **only** for conservative
  complete-service benchmark comparisons; it does not replace batch evidence.
- Entire batch validated before calculation: <=100,000 rows and <=50,000,000
  actually traversed support terms. Limits reject work; they do not approximate it.
- Full finite tail recurrence, scaled from the near-mean end; Kahan weight sum,
  Neumaier log-gamma sum, direct deep right tails, `expm1` left-tail complement.
  No fixed truncation, no tail arrays, no fallback. Log-gamma cancellation remains
  a numerical limitation; arbitrary counts above the documented N cap are rejected.
- PyO3 detaches numerical work and checks Python signals between batch rows and
  once before publishing output. Cancellation discards all computed values.
  Latency is bounded by one row (at most 1,000,000 recurrence steps under N cap).
  Scalar wrapper has only the resource cap, not batch signal polling.
- CLI `soymutdb-enrichment-sf`: one JSON array document on stdin **through EOF**,
  one JSON probability array on stdout. <=16MiB input; errors exit 2 with stderr
  and no stdout. Caller SIGTERM/SIGKILL cancels the whole process; no result is
  emitted until the complete batch succeeds. No streaming/NDJSON protocol.

## Reproduce on the qualified host

From the workspace root, use an isolated Rust 1.99.0 toolchain, uv 0.11.33 and
CPython 3.14.8. Supply `UV_BIN` and `PYTHON314` as existing executable paths;
set `CARGO_HOME`/`RUSTUP_HOME` to the isolated toolchain and put its bin on PATH.
Choose a **new** ignored scratch directory. The real-data test additionally
requires the [frozen normalized GO snapshot](<../../.validation/m2-upstream-20261008/go.normalized.tsv>)
(SHA256
`ea7d4572f234fa3afd7b3503b38e5bc3884fbe048168cc65632c978b1e0ebd0f`);
local evidence/data are intentionally not committed. Missing data is not a pass.

```bash
set -e
: "${UV_BIN:?uv 0.11.33 executable}" "${PYTHON314:?CPython 3.14.8 executable}"
: "${M2_SCRATCH:?new ignored scratch directory}"
test ! -e "$M2_SCRATCH" && test ! -L "$M2_SCRATCH"
mkdir "$M2_SCRATCH"
export CARGO_TARGET_DIR="$M2_SCRATCH/target" UV_CACHE_DIR="$M2_SCRATCH/uv-cache"
export UV_PYTHON_DOWNLOADS=never CARGO_BUILD_JOBS=1 RAYON_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
ulimit -v 8388608
"$UV_BIN" --no-config venv --python "$PYTHON314" "$M2_SCRATCH/env"
"$UV_BIN" --no-config pip install --python "$M2_SCRATCH/env/bin/python" \
  'maturin==1.12.6' 'numpy==2.5.3' 'scipy==1.18.1' 'pytest==9.0.2'
timeout --kill-after=5s 300 cargo test --locked --manifest-path packages/enrichment-core/Cargo.toml
timeout --kill-after=5s 300 cargo build --release --locked \
  --manifest-path packages/enrichment-core/Cargo.toml --bin soymutdb-enrichment-sf
timeout --kill-after=5s 300 "$M2_SCRATCH/env/bin/maturin" build --release --locked \
  --features python --manifest-path packages/enrichment-core/Cargo.toml \
  --interpreter "$M2_SCRATCH/env/bin/python" --out "$M2_SCRATCH/wheels"
"$UV_BIN" --no-config pip install --python "$M2_SCRATCH/env/bin/python" \
  "$M2_SCRATCH"/wheels/*.whl
export M2_CLI="$CARGO_TARGET_DIR/release/soymutdb-enrichment-sf"
timeout --kill-after=5s 120 "$M2_SCRATCH/env/bin/python" -m pytest \
  -p no:cacheprovider packages/enrichment-core/tests/test_m2_candidate.py -q
"$UV_BIN" --no-config pip check --python "$M2_SCRATCH/env/bin/python"
```

Cargo dependencies are pinned in the real lockfile; Python test-tool versions
above describe the verified host, not a production environment hash lock.
Formatting requires the isolated toolchain's `rustfmt` component. No API/worker
or M3 environment is modified.

Standalone examples:

```bash
printf '[[20,5,4,2],[10,8,4,5]]' | \
  .validation/m2-rust-20261008/target/release/soymutdb-enrichment-sf
.validation/m2-rust-20261008/pyenv/bin/python -c \
  'import soymutdb_enrichment_core as c; print(c.sf_batch([[20,5,4,2]]))'
```

Focused tests cover exhaustive small exact rational probabilities and independent
SciPy SF, mean/support edges, representable deep tails, significance/BH outcomes,
full-batch invalid/resource rejection, scalar equivalence, real public GO
annotation counts/checksum with a seeded synthetic query, CLI EOF/error/termination,
GIL release and Python signal cancellation. These focused tests do not establish
complete-path performance or deployment qualification. The separate 2026-10-09
real-annotation ASGI replay found **no >=20% p95 improvement**: keep optimized
Python, with no production integration. See the [canonical plan and evidence ledger](<../../docs/aegis/plans/2026-10-05-blast-diamond-and-enrichment-rust.md>).
Only this host's Linux x86_64 CPython 3.14 ABI is exercised, not arbitrary
manylinux hosts, TCP deployment or worker/job cancellation.
