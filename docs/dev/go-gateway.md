# Go read gateway (stage 1)

`apps/gateway-go` is the first stage of moving SoyMutDB's read-hot core to Go.
It serves one public aggregate — `GET /api/v1/stats/homepage` — and nothing
else. Python keeps every write path, import, release workflow and admin glue;
PostgreSQL remains the single authoritative store. The gateway introduces no
new data store, no cache of its own and no schema.

## Scope and non-goals

In scope (stage 1):

- `GET /healthz` → `{"status":"ok","service":"soymutdb-gateway"}`
- `GET /api/v1/stats/homepage` → byte-compatible `HomepageStats` JSON
- Read-only PostgreSQL sessions enforced by the connection, not by convention
- Contract tests: unit tests for config/HTTP/timestamps, a PostgreSQL
  integration test with a rolled-back fixture, and a live parity check against
  the Python API

Out of scope (later stages): public search, variant pages, JBrowse data,
authentication, admin APIs, exports, analytics ingestion. Those stay on the
Python API until a stage explicitly moves them and the
`docs/dev/database-core-contract.md` matrix is extended for the new surface.

## Contract

The JSON body is the same object `apps/api/app/schemas/analytics.py`
(`HomepageStats`) publishes, with the same keys in the same order:

```
total_variants, snp_count, indel_count, sv_count, gene_count,
mutant_line_count, release_count, assembly_count, seed_accessions,
last_release_date, last_release_name
```

Semantics are ported from
`apps/api/app/api/v1/stats.py::_load_homepage_stats`:

- the aggregate is bound to the singleton `active_release` pointer (id = 1)
  **only when** that release has `status = 'published'`; a pointer at a draft
  or rolled-back release answers the zero aggregate;
- genes are counted through the release's assemblies (genes have no release
  column);
- mutant lines need `is_public`, `NOT is_deleted` and a non-null `public_id`;
- seed lots are counted through those public mutant lines;
- `release_count` is the publication history: every `status = 'published'`
  release, not a property of the bound release;
- variant facts need the release published **and** the fact to name either no
  line (`mutant_line_name = ''`) or a public line of the same release — the
  `variant_fact_visibility` predicate;
- `indel_count = INS + DEL`; `total_variants` also includes `MNV`, so it is not
  the sum of SNP + Indel + SV;
- timestamps render exactly as Pydantic v2 does: UTC, six fractional digits
  only when microseconds are non-zero, literal `Z` suffix, `null` values stay
  `null`.

No request parameter selects a release. The public contract does not expose a
release pin, so the gateway does not accept one.

## Read-only enforcement

`config.NormalizeDatabaseURL` accepts the DSN forms the Python services
publish (`postgresql+asyncpg://`, `postgresql+psycopg://`,
`postgresql+psycopg2://`), rewrites them to `postgres://`, and appends
`default_transaction_read_only=on` (URL query or keyword DSN form). lib/pq
forwards unknown keys as startup runtime parameters, so every session on the
pool rejects writes at the server even if a future handler contains a bug.
`sslmode` is not forced: production deployments must supply it, and local
PostgreSQL needs `?sslmode=disable` because lib/pq defaults to `require`.

## Driver substitution: lib/pq instead of pgx

The task originally named pgx. This workstation has no reachable Go module
proxy, and `github.com/lib/pq` v1.10.9 is available from the Debian archive,
so it is vendored under `apps/gateway-go/vendor` and the build runs fully
offline (`GOFLAGS=-mod=vendor GOPROXY=off`). The store only uses
`database/sql` (`QueryRowContext` + `Scan`), so swapping in pgx's `stdlib`
driver later is a driver import plus a small `Querier` implementation, not a
rewrite. Vendored third-party code is covered by its own LICENSE.txt.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SOYMUTDB_DATABASE_URL` | required | PostgreSQL DSN (SQLAlchemy form accepted) |
| `SOYMUTDB_GATEWAY_ADDR` | `:18020` | listen address |
| `SOYMUTDB_GATEWAY_MAX_OPEN_CONNS` | `10` | pool size |
| `SOYMUTDB_GATEWAY_MAX_IDLE_CONNS` | `5` | idle connections |
| `SOYMUTDB_GATEWAY_QUERY_TIMEOUT` | `5s` | per-request deadline |

## Run and verify

```bash
cd apps/gateway-go
GOFLAGS=-mod=vendor GOPROXY=off go vet ./...
GOFLAGS=-mod=vendor GOPROXY=off go test ./...

# PostgreSQL-backed fixture (transaction is rolled back):
SOYMUTDB_GATEWAY_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev?sslmode=disable' \
  GOFLAGS=-mod=vendor GOPROXY=off go test ./internal/stats -run TestHomepageAgainstPostgres -v

GOFLAGS=-mod=vendor GOPROXY=off go build -o /tmp/soymutdb-gateway ./cmd/gateway
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev?sslmode=disable' \
  /tmp/soymutdb-gateway

# Contract parity against the live Python API:
bash scripts/verify-gateway-parity.sh
```

The integration test asserts exact counts for a fixture that covers every
visibility branch (public line, no line, INS/DEL fold, MNV in the total,
deleted line, private line, non-null-`public_id` rule, a fact from another
release) and asserts that pointing `active_release` at a draft answers zeros.

## Rollout

Stage 1 is deliberately not on the request path. To try it:

1. run the gateway next to the Python API on the same PostgreSQL;
2. route **only** `/api/v1/stats/homepage` to it at the reverse proxy;
3. run `scripts/verify-gateway-parity.sh` against both origins;
4. keep the Python route as the fallback until the parity check is part of
   the release evidence for a full release cycle.

The parity script treats a body mismatch or a status mismatch as a failure. An
empty database (no published release) must produce identical zero bodies with
`null` release metadata on both sides.

CI wiring is intentionally not part of this stage: no current build image
carries Go, and adding a stage means a new image and pipeline job. Until then
the commands above are the local gate, and the vendored tree keeps them
network-free.

## Stage 2: public search (planned)

Search moves only behind the same invariants that bound it today:

- results remain release- and assembly-scoped; v4 and v5 are distinct
  namespaces and are never collapsed;
- only released, public records with a non-null `public_id` are returned;
  internal identifiers disclose neither the record nor its existence;
- the keyset cursor contract (release + assembly + filters bound) is reused,
  not re-invented, and the OpenAPI/client contract is extended before the
  gateway starts answering the route;
- negative leakage tests (response bodies, URLs, logs, artifacts) are part of
  the merge gate, per `docs/dev/database-core-contract.md`.