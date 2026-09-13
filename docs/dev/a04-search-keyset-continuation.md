# A-04 Global Search Keyset Continuation

## Scope

`SearchService.global_search()` currently carries one decimal offset cursor across every queried source. This is sufficient for shallow continuation but has offset cost and cannot represent an independent stable position for each result type. This document specifies a backwards-compatible keyset continuation migration.

## Source ordering

Only sources actually queried by the service participate in a keyset cursor:

| Source | Stable ordering | Keyset terminal position |
| --- | --- | --- |
| genes | external: `(match_rank DESC, Gene.accession, Gene.assembly_id)`; internal: `(match_rank DESC, Gene.accession, Gene.gene_pk)` | last rank/score and public accession/assembly or signed internal tie-breaker |
| publications | `(score DESC, Publication.id)` | last rank/score and integer id |
| mutant lines | external: `(match_rank DESC, MutantLine.public_id)`; internal: `(score DESC, MutantLine.name, MutantLine.id)` | last rank/score and public ID or signed name/id pair |

`variant` and `phenotype` are public enum values but are not currently queried by `global_search()`. They must not be assigned fictional keyset positions.

## Cursor format

New cursors should be URL-safe base64 encoded JSON, versioned and strictly validated before query construction. A conceptual cursor is:

```json
{
  "v": 1,
  "q": "normalized query fingerprint",
  "types": ["gene", "publication", "mutant_line"],
  "site_variant": "external",
  "release_id": 7,
  "assembly_id": 11,
  "positions": {
    "gene": {"rank": 1, "score": 1.0, "accession": "Glyma.01G000100", "assembly_id": 11, "exhausted": false},
    "publication": {"rank": 1, "score": 1.0, "id": 44, "exhausted": false},
    "mutant_line": {"rank": 1, "score": 1.0, "public_id": "SM000044", "exhausted": false}
  }
}
```

The JSON above is the authenticated cursor payload; the API emits an opaque
URL-safe representation using the repository's existing release-bound signing
primitive. External payloads use only public accession/assembly and `public_id`
keys; they never include a persistence primary key. Internal mutant cursors use
`name,id` and are accepted only through that same signed binding primitive.

Validation requirements:

- reject malformed encoding/payload, unknown versions, unexpected keys, invalid scalar types, and query/type fingerprint mismatches before reaching SQL;
- use score-first source-specific predicates, followed by the stable tie-breaker (for example `rank < :rank OR (rank = :rank AND accession > :accession ...)`);
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

The API accepts legacy pure-decimal cursors with their original offset
semantics. New searches emit sealed v1 cursors and consume each source's own
keyset position; `variant` and `phenotype` remain unsupported sources and are
never assigned fictional positions.
