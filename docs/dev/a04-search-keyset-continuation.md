# A-04 Global Search Keyset Continuation

## Scope

`SearchService.global_search()` currently carries one decimal offset cursor across every queried source. This is sufficient for shallow continuation but has offset cost and cannot represent an independent stable position for each result type. This document specifies a backwards-compatible keyset continuation migration.

## Source ordering

Only sources actually queried by the service participate in a keyset cursor:

| Source | Stable ordering | Keyset terminal position |
| --- | --- | --- |
| genes | `Gene.id` | last integer id |
| publications | `Publication.id` | last integer id |
| mutant lines | `MutantLine.name, MutantLine.id` | last name and id pair |

`variant` and `phenotype` are public enum values but are not currently queried by `global_search()`. They must not be assigned fictional keyset positions.

## Cursor format

New cursors should be URL-safe base64 encoded JSON, versioned and strictly validated before query construction. A conceptual cursor is:

```json
{
  "v": 1,
  "q": "normalized query fingerprint",
  "types": ["gene", "publication", "mutant_line"],
  "positions": {
    "gene": {"id": 123},
    "publication": {"id": 44},
    "mutant_line": {"name": "L-12", "id": 8}
  }
}
```

Validation requirements:

- reject malformed base64/JSON, unknown versions, unexpected keys, invalid scalar types, and query/type fingerprint mismatches before reaching SQL;
- use source-specific predicates (`id > :id`, or `(name, id) > (:name, :id)`);
- only advance a source position if that source returned an item in the preceding page;
- emit no cursor when every active source is exhausted.

## Compatibility and rollout

Existing clients and database tests use decimal cursors such as `"1"` and `"2"`. Until a versioned client migration is complete:

1. decimal-only cursors retain existing offset behavior;
2. a valid opaque v1 cursor uses keyset behavior;
3. malformed opaque cursors follow the explicitly chosen contract (recommended: validation error, never a silent SQL fallback);
4. emitted new cursors are opaque only after the client contract has accepted them.

This prevents a mixed deploy from silently changing pagination semantics.

## Required acceptance tests

- opaque cursor encode/decode and malformed/type/query mismatch rejection;
- real PostgreSQL multi-page continuation for genes and publications;
- duplicate mutant-line names prove `(name, id)` tie-breaking has no duplicate/skip;
- legacy decimal cursor behavior remains covered;
- no source query receives another source's terminal position.

## Current boundary

No keyset query implementation is introduced by this design. The current offset continuation remains the stable public behavior until the API/client compatibility decision and the acceptance tests above are implemented.
