# Bounded in-process rate-limit fallback

`apps/api/app/core/ratelimit.py` keeps one process-local counter map per
limiter as a dev-only fallback when Redis is unavailable. S-2 of
`docs/superpowers/plans/2026-09-15-phase-1-baseline-security-plan.md` requires
that map to stay bounded (`FALLBACK_MAX_KEYS = 2048`).

Two copies of the pruning logic had drifted apart:

- `RequestRateLimiter` pruned stale windows **and** hard capped the map.
- `LoginRateLimiter` (and its `ExternalArticlePreviewRateLimiter` /
  `PublicBlastRateLimiter` subclasses) used a hardcoded `2048` and only
  pruned stale windows.

A flood of distinct identities inside **one** fixed window produces keys that
are all current, so pruning removes nothing and the dictionary grows without
bound. A functional control measured 5096 entries after 2548 `enforce()` calls
on the unfixed source.

Both families now call one `_bound_fallback_counts()` helper: prune stale
windows first, then cap unconditionally. This is a memory bound on a dev-only
fallback; the production fail-open/fail-closed and budget semantics are
unchanged. `tests/test_ratelimit.py` and `tests/test_request_rate_limit.py`
each pin the bound for their own limiter family.

## Verify

```bash
cd apps/api && .venv/bin/python -m pytest \
  tests/test_ratelimit.py tests/test_request_rate_limit.py -q
```
