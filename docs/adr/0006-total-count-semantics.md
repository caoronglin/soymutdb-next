# ADR-0006: `total_count` semantics — disambiguate page count from true total

Status: Accepted

Date: 2026-09-20

Decision source: Gate A (`docs/ops/gate-a-decision-brief-2026-09-20.md`).

## Context

`search_service.py` returns `total_count = len(current_page)` (lines 550, 595),
while `database-core-contract.md` §5 defines `total_count = null` as "hidden
total". A field named `total_count` that actually carries a page count is an
ambiguous contract. Evidence: `docs/ops/phase-0-fact-baseline-2026-09-20.md` D3.

## Decision

Disambiguate into explicit fields:

- `page_count`: number of hits in the current page (the former `len(...)` value);
- `total_count`: the true total **or** `null` when the total is intentionally
  hidden. Never a page count under this name.

A compatibility assessment is required before shipping: inspect the OpenAPI
type, the generated client, frontend usage, and any third-party consumers. If
changing `total_count` from `number` to `number|null` is breaking for a client,
use an API version strategy rather than silently changing the type. Backend
schema, OpenAPI, generated client, frontend, tests, and docs change together in
one PR (or a strictly dependent chain).

## Consequences

- Phase 4 search work and any OpenAPI/client regeneration wait on this.
- Rejected: keeping the current "page count under the name total_count".
- Cheap exact totals (small result sets) may be returned; large-set totals follow
  the pagination decision (ADR-API-01 interplay with D4 `COUNT(*)`).

---

## Amendment (review 2026-09-20, F4 — wording)

The final sentence referenced "ADR-API-01 interplay"; this ADR **is** ADR-API-01.
Correct reading: the large-set total decision is the trade-off with **D4
`COUNT(*)` cost** documented in the Phase 0 report, not a separate ADR.
