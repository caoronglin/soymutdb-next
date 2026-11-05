# Static placeholder-scan pin

## The gap (§4a, PR #206)

The placeholder-origin regex is committed **twice**, in two scanners:

| file | shape | reads back |
| --- | --- | --- |
| `scripts/smoke.sh` `smoke_static()` | one grep regex, invoked twice | **nothing** |
| `check-production-artifact.sh` `PATTERNS=()` | array | `test_production_artifact_scan.py` |

Measured on live `main`: deleting `jbrowse\.example\.com` from both
`smoke.sh` grep lines leaves the registry guard, the teeth guard, the
production scanner's behavioural suite and `smoke.sh --profile contracts`
all **green**. The static layer simply stops looking for that origin.
Count of readers of `smoke.sh`'s copy is 0; the two copies are not phantoms,
only the first one is unguarded.

## Two axes, not one

The pin in `scripts/check_static_placeholder_scan.py` reads both scanners'
committed bytes and pins **tokens** and **corpora** separately. Conflating
them is the mistake this doc prevents: on live `main` the scanners agree on
four tokens and disagree on everything else.

### Tokens

| surface | `smoke.sh` | `check-production-artifact.sh` |
| --- | --- | --- |
| `SHARED` (reviewed floor) | 4 tokens, twice | 4 tokens in `PATTERNS=()` |
| `PRODUCTION_ONLY` | absent | `localhost:8000` in `PATTERNS=()` |
| `LOOPBACK_ONLY` | absent | `localhost`, `127\.0\.0\.1` in `LOOPBACK_PATTERNS=()` |

So the one-sided surface is **two token groups**, not one. "The identical
pattern" is true of the four shared tokens and of nothing else. Both
production-only groups are reviewed, behaviourally-guarded differences;
dropping either, or adding any other extra on either side, is a divergence
reported by name.

### Corpora

| scanner | corpus |
| --- | --- |
| `smoke_static()` | `--include` = `*.html`, `*.js`, `*.json`; identical set in both calls |
| `scan_pattern()` | every file type (`grep -rIl`, no `--include`); excludes the two manifests |
| `scan_loopback()` | every file type except `*.js`, `*.mjs`, `*.map` and the two manifests |

These are **not equal, by design**. `smoke_static()`'s `--include` set is a
reviewed *subset decision*, not an accident: it never reads `_headers`. The
production scanner's whole-tree `scan_pattern()` does, and so does the
narrower `scan_loopback()` (its doc comment names `_headers` as a target).
The guard pins all three corpora as literals, so a silent `--include` change,
an added `--exclude`, or a narrowed `scan_pattern()` is a divergence.

## `_headers` blind spot: its own cell

`apps/web/scripts/finalize-csp.ts` L49 writes `<DIST_DIR>/_headers`, and its
CSP line is rewritten each build with **the configured API origin** (documented
at `apps/web/public/_headers` L54-58). A misconfigured `localhost:8000` thus
lands in built `_headers` — a file `smoke_static()` cannot see.

Measured with a fixture (`dist/index.html` + `dist/_headers` carrying
`connect-src http://localhost:8000`, nothing else):

| check | result |
| --- | --- |
| `check-production-artifact.sh --allow-demo` | **FAIL** — `_headers` hit by loopback patterns |
| `smoke.sh --profile static --static-dir <fixture>` | **SMOKE PASS** |
| token-only pin | **OK** (two scanners pinned, read back) |

The third row is the point: a pin over tokens alone blesses this divergence
as-is. **Ownership decision:** loopback-in-`_headers` is
`check-production-artifact.sh`'s job alone, plus the header contract
`check_artifact_headers.py` (`PLACEHOLDER_RE` includes `localhost`). Both
already run in `verify-frontend-artifacts.sh` after the build; the static
layer is deliberately not extended. A corpus flip that adds
`--include='_headers'` to `smoke.sh` must be a reviewed edit in the same
commit as updating `SMOKE_CORPUS` here — the guard fails closed otherwise.

## The pin

`scripts/check_static_placeholder_scan.py` reads both scanners' committed
bytes and pins:

- the reviewed `SHARED` floor present in **both**;
- the two `smoke.sh` grep calls carry the **identical** pattern and corpus;
- `PATTERNS=()` keeps `localhost:8000`, `LOOPBACK_PATTERNS=()` keeps its two
  loopback binds; any other extra on either side is a **divergence**;
- the three corpora above;
- `test_production_artifact_scan.py` still plants every shared token.

`--self-test` plants eleven one-sided drifts on copies of the bytes and
asserts each is caught (§4a ablation, token additions/drops, and three
corpus drifts), so a weakened pin cannot pass vacuously.
`scripts/test_static_placeholder_scan.py` pins from a second file that the
plain call is wired into `smoke_contracts()`, that it is listed in
`REQUIRED_GUARD_CALLS`, that the companion suite itself is collected, that
`self_test()` still has teeth when `check()` is gutted, and that the
corpora are pinned, unequal, and read back.

The `--self-test` is **not** wired as a standalone layer call: that would add
a row to `check_contracts_self_test_teeth.py`'s `_WIRED_SELF_TESTS` equality
floor, a file other in-flight PRs owned at landing time. It is exercised
in-process by the companion suite instead, which is the same shape
`test_contracts_registry_collection.py` uses.

## Adding an origin

Add it to `SHARED`, to `smoke.sh`'s two grep lines, to
`check-production-artifact.sh`'s `PATTERNS=()`, and to
`test_production_artifact_scan.py`'s plant list **in the same commit**. The
guard fails closed on any subset. A production-only token belongs in
`PRODUCTION_ONLY` or `LOOPBACK_ONLY` plus a behavioural plant. Changing a
corpus (any `--include` / `--exclude`) is a separate reviewed edit to the
matching corpus constant here, with a self-test plant in the same commit.
