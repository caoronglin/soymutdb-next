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

## The pin

`scripts/check_static_placeholder_scan.py` reads both scanners' committed
bytes and pins:

- a reviewed `SHARED` floor (the four origins/markers) present in **both**;
- the two `smoke.sh` grep calls carry the **identical** pattern;
- `check-production-artifact.sh`'s `PATTERNS=()` keeps `localhost:8000`
  (its documented, behaviourally-guarded extra);
- `test_production_artifact_scan.py` still plants every shared token;
- any *other* extra on either side is a **divergence**, reported by name.

`--self-test` plants seven one-sided drifts (including the §4a ablation)
on copies of the bytes and asserts each is caught, so a weakened pin cannot
pass vacuously. `scripts/test_static_placeholder_scan.py` pins from a second
file that the plain call is wired into `smoke_contracts()`, that it is listed
in `REQUIRED_GUARD_CALLS`, that the companion suite itself is collected, and
that the guard's `self_test()` still has teeth when `check()` is gutted.

The `--self-test` is **not** wired as a standalone layer call: that would add
a row to `check_contracts_self_test_teeth.py`'s `_WIRED_SELF_TESTS` equality
floor, a file three in-flight PRs owned at landing time. It is exercised
in-process by the companion suite instead, which is the same shape
`test_contracts_registry_collection.py` uses.

## Adding an origin

Add it to `SHARED`, to `smoke.sh`'s two grep lines, to
`check-production-artifact.sh`'s `PATTERNS=()`, and to
`test_production_artifact_scan.py`'s plant list **in the same commit**. The
guard fails closed on any subset. A production-only token belongs in
`PRODUCTION_ONLY` plus a behavioural plant, with the same reviewed edit.
