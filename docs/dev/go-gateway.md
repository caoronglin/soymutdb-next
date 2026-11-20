# Go gateway

`apps/gateway-go` is the staged Go serving layer for SoyMutDB. It answers two
things itself — the read-only homepage aggregate and the built admin console
artifact — and reverse-proxies the rest of `/api/*` to the Python API. Python
keeps every write path, import, release workflow and admin glue; PostgreSQL
remains the single authoritative store. The gateway introduces no new data
store, no cache of its own and no schema.

Two stages exist in one binary:

| Stage | Scope |
| --- | --- |
| 1 | `GET /api/v1/stats/homepage`, byte-compatible with the Python contract |
| 2 (phase A) | serving layer for the admin console: static artifact, `/api/*` proxy, compression, rate limiting, readiness |
| 3 (phase B, implemented) | public, unauthenticated read endpoints answered from PostgreSQL (starting with the assembly list) |

## Routes

| Method | Path | Answered by |
| --- | --- | --- |
| `GET` | `/healthz` | the gateway: `{"status":"ok","service":"soymutdb-gateway"}` |
| `GET`/`HEAD` | `/readyz` | the gateway: artifact + upstream readiness (see below) |
| `GET` | `/api/v1/stats/homepage` | the gateway: the stage-1 aggregate |
| `GET` | `/api/v1/genes/assemblies` | the gateway: the stage-3 published-release assembly list |
| `GET` | `/api/v1/genes/assemblies/{id}/chromosomes` | the gateway: the chromosomes of one in-scope assembly |
| `GET` | `/api/v1/releases/active` | the gateway: the release the public surface serves |
| `GET` | `/api/v1/content/news` | the gateway: the published news articles (plain array) |
| `GET` | `/api/v1/news` | the gateway: the published news articles (paginated envelope) |
| `GET` | `/api/v1/content/publications` | the gateway: the publication list |
| `GET` | `/api/v1/content/pages` | the gateway: the published static pages |
| `GET` | `/api/v1/content/downloads` | the gateway: the downloadable files of the published release |
| `GET` | `/api/v1/tracks/categories` | the gateway: the track-category list |
| any | `/api/…` | reverse proxy to `SOYMUTDB_GATEWAY_UPSTREAM_URL` |
| `GET`/`HEAD` | everything else | the static artifact (admin console) |

`/api/v1/stats/homepage` is **not** proxied: it is the route
`scripts/verify-gateway-parity.sh` compares byte for byte with the Python API,
so it has to be answered by the gateway. `/api` without the trailing slash is
redirected to `/api/` by the standard library mux. Other methods on
`/healthz`, `/readyz` and the stats route answer `405` with
`{"detail":"Method Not Allowed"}`.

## Stage 3: public read endpoints (phase B — implemented)

The gateway answers a small, growing set of **public GET** routes itself via
`internal/readmodel`. The first is `GET /api/v1/genes/assemblies`; the package
is built so more can be added without touching the proxy or the static handler.
Every port follows three rules:

1. **Published only.** The release is resolved from the singleton
   `active_release` pointer **joined to `releases.status = 'published'`**. With
   no published release the answer is an empty list, never draft data. The
   Python dev API may fall back to a draft when
   `SOYMUTDB_LOCAL_TEST_PREVIEW_ENABLED` is set; the gateway deliberately does
   not, because it is a public serving surface.
2. **Read only.** The process opens PostgreSQL with
   `default_transaction_read_only=on`; the read model issues only `SELECT`s
   against prepared statements. Writes, imports and release workflow remain in
   Python.
3. **Whitelisted fields, no permission logic.** The JSON shape is the public
   schema. Admin authorization stays in Python; a route that needs a session
   must not be added here.

An assembly that does not belong to the published release answers **404**, not
`200 []`: an empty list would claim "that assembly exists and has no
chromosomes", a claim the data never made, and it would disclose the existence
of an unpublished row. The same 404 answers an unknown assembly, so the two
cannot be told apart.

A route that answers a free-form dictionary (the track-category list) keeps
exactly the keys the Python service returns: the display name and description
are admin-internal and were never part of the public contract. Adding a column
to the table must not silently widen the public answer.

Two routes may serve the same resource in different shapes — `/api/v1/news`
answers a paginated envelope, `/api/v1/content/news` a plain array — so they
have separate handlers. Sharing one handler between them would quietly change
one route's contract.

A failed query answers `503`, never `[]`: an empty result means "nothing is
published", which is a valid answer, and a failure must not masquerade as one.

### Parity check

`apps/gateway-go/scripts/check-read-parity.sh <route>` compares the parsed JSON
of the gateway and the Python API. It covers every stage-3 route:

```bash
for route in /api/v1/genes/assemblies \
             /api/v1/genes/assemblies/1/chromosomes \
             /api/v1/releases/active \
             /api/v1/content/news \
             /api/v1/content/publications \
             /api/v1/content/pages \
             /api/v1/content/downloads \
             /api/v1/tracks/categories \
             "/api/v1/news?page=2&page_size=1"; do
  bash apps/gateway-go/scripts/check-read-parity.sh "$route"
done
```

The script refuses to run unless an active **published** release exists, so it
cannot leave a database in a mutated state. A route whose data is empty on
both sides proves little: seed a row in a throwaway database first, compare,
then remove it. It is read-only: it refuses to run unless an
active **published** release already exists, so it cannot leave a test database
in a mutated state. To verify locally with the draft-only dev database, publish
a release in a throwaway database first, run the script, then restore the
original release and pointer.

Timestamp formatting is part of the contract: the SQL uses
`to_char(..., 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')` when a row has microseconds and
omits the fraction when it does not, matching pydantic's JSON mode. A plain
`to_char` without `.US` silently drops microseconds and breaks parity.

## Static artifact (admin console)

The artifact directory is `SOYMUTDB_GATEWAY_STATIC_DIR` (the build output of
`apps/admin`, i.e. `apps/admin/dist`). It is resolved and validated at startup:
a missing directory, or one without `index.html`, refuses to start.

Routing rules:

- a request that resolves to a regular file is served with its own MIME type,
  its own cache policy, `HEAD` and `Range` support;
- `/` and any path whose last segment has no file extension fall back to
  `index.html` — the console has a manual client-side route tree, so
  `/releases/7` must load the shell;
- a path that names a file does **not** fall back: a missing `.js`/`.css` file,
  or anything under `/assets/` or `/fonts/`, answers `404` with
  `{"detail":"Not Found"}`. Returning the HTML shell with `200` for a missing
  hashed chunk turns a deploy mistake into a script-parse error in the browser;
- request paths are cleaned into a rooted slash path and the joined result is
  checked to stay inside the artifact, so `..` segments cannot escape it.

MIME types come from an explicit table (`.html .js .mjs .css .json .svg .woff2
.woff .ttf .png .jpg .jpeg .gif .webp .ico .txt .wasm .map`), never from
`mime.TypeByExtension`, which reads the host's `mime.types` and would answer
differently on two machines serving the same bytes. Unknown extensions are
`application/octet-stream` with `X-Content-Type-Options: nosniff`.

Cache policy has three classes:

| Class | Rule | `Cache-Control` |
| --- | --- | --- |
| content-hashed | under `/assets/`, or a name containing `.<8+ hex digits>.` | `public, max-age=31536000, immutable` |
| documents | `index.html` and any other `.html` | `no-cache` |
| everything else | fonts, favicon | `public, max-age=3600` |

Hashed filenames are not confined to `/assets/`: this artifact also emits
`umi.<hash>.js` and `<id>.<hash>.chunk.css` at the root, which is why
immutability is decided by name shape as well as directory.

### Security headers and `_headers`

The static responses carry `X-Content-Type-Options: nosniff`,
`Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY`
and a `Permissions-Policy`. The artifact's CSP is the
`<meta http-equiv="Content-Security-Policy">` inside `index.html`, so it travels
with the document through any front door, including this one.

**The artifact's `_headers` file is a Cloudflare Pages convention and is not
interpreted by the gateway.** Cache-Control comes from the table above, CSP
from the document meta tag, and HSTS stays with whatever terminates TLS — this
process cannot tell whether the client's connection was encrypted, so claiming
HSTS here would be a guess. Proxied API responses are passed through unchanged;
the Python API sets its own security headers.

## Reverse proxy

Requests under `/api/` are forwarded to `SOYMUTDB_GATEWAY_UPSTREAM_URL` with
method, body, headers and status preserved. Design points:

- **Streaming.** `FlushInterval: -1` plus a gzip writer that flushes per chunk:
  a proxied response is forwarded as it arrives, never accumulated. The
  transport keeps 32 idle connections per host (the standard library default of
  2 serializes a proxied workload) and does not silently decompress upstream
  bodies (`DisableCompression`), which would desynchronize the response headers
  from the bytes being forwarded.
- **Forwarding headers are replaced, not extended.** The gateway is the front
  door, so it deletes any client-supplied `X-Forwarded-For`, `Forwarded` and
  `X-Real-IP` and writes only the TCP peer address it can vouch for
  (`X-Forwarded-For`, `X-Real-IP`, and an RFC 7239 `Forwarded` with
  `for`/`proto`/`host`). A client cannot claim an address the API trusts. In the
  Compose profile the gateway joins `api-proxy` and targets the `api-local`
  alias, so the API's `SOYMUTDB_FORWARDED_ALLOW_IPS` covers it.
- **Bounded.** `SOYMUTDB_GATEWAY_PROXY_TIMEOUT` bounds the whole proxied
  exchange (context deadline plus a transport `ResponseHeaderTimeout`, 5s dial
  timeout). A deadline answers `504` with `{"detail":"Gateway Timeout"}`; any
  other transport failure answers `502` with `{"detail":"Bad Gateway"}`. A
  proxied request never hangs and never returns an HTML error page.
- **No credentials.** A userinfo component in the upstream URL is rejected at
  startup, so no secret can reach a response or a log line by that route. Proxy
  failures are logged with the transport error for the operator; the readiness
  answer (below) never carries the upstream address.

## Compression

gzip only. Brotli is deliberately absent: the standard library has no brotli
encoder and the gateway's dependency tree is vendored and offline, so `br`
would cost a third-party module. `Accept-Encoding` is parsed with its
q-values; an explicit `gzip;q=0` wins over a wildcard.

Compressed when: `GET`/`HEAD`, status `200`, no `Range`, the response carries
no `Content-Encoding` yet, the media type is `text/*` or one of
`application/json`, `application/javascript`, `application/xml`,
`application/manifest+json`, `image/svg+xml`, and either the length is unknown
or at least 512 bytes. A proxied response that already carries
`Content-Encoding` is forwarded untouched (no double compression), and non-200
statuses keep their plain JSON bodies.

`Vary: Accept-Encoding` is added to every negotiable response, including the
identity ones, so a shared cache stores one variant per encoding. When a body
is compressed, `Content-Length` is removed (the encoded length is not known
before the stream ends) and the encoder is created on the first body byte, so a
`HEAD` cannot report the length of an empty gzip stream. Level is
`gzip.BestSpeed`: the payloads are small text files and the gateway is latency
sensitive.

Measured on this workstation (`go test -bench` , Intel Xeon E5-2697A, 2000
iterations, in-process handlers so the numbers are server CPU only):

| Benchmark | ns/op | body bytes on the wire |
| --- | --- | --- |
| `BenchmarkStaticDocument` (1164 B HTML, identity) | 32 560 | 1164 |
| `BenchmarkStaticDocumentGzip` | 60 437 | 179 |
| `BenchmarkStaticChunk` (67 500 B JS, identity) | 69 423 | 67 500 |
| `BenchmarkStaticChunkGzip` | 179 132 | 614 |
| `BenchmarkProxyPath` (loopback upstream, 60 B JSON) | 259 280 | 60 |
| `BenchmarkHomepageResponse` (in-process aggregate) | 3 683 | ~250 |

gzip costs ~1.9x server CPU on the document and ~2.6x on the 64 KiB chunk, and
returns 6.5x / 110x fewer bytes. The proxy number is dominated by two loopback
round trips and is a shape, not a budget.

## Rate limiting

A token bucket per client on the **proxied** `/api/*` path only.

- Key: the TCP peer address — the same value written into `X-Forwarded-For`, so
  "the client" has one definition.
- Defaults: 30 tokens/s sustained with a burst of 60 (`SOYMUTDB_GATEWAY_RATE_LIMIT_RATE`,
  `…_BURST`). A console session that fires a dozen calls per page never sees it;
  a scripted scrape gets 30 requests/s and then `429`.
- Exhaustion answers `429` with `{"detail":"Too Many Requests"}` and
  `Retry-After` in whole seconds (rounded up, minimum 1).
- Memory is bounded: at most `SOYMUTDB_GATEWAY_RATE_LIMIT_CLIENTS` (default
  4096) buckets are tracked, and the least recently used key is evicted first,
  so a scan of random addresses cannot grow the map. An evicted client starts
  from a full bucket instead of being refused for the rest of its life.
- Static assets are never rate limited. One admin page load fetches dozens of
  hashed files from local disk while a session issues a handful of API calls;
  limiting the assets would break first loads and protect nothing. The
  gateway-served stats route is not limited either (it is a single prepared
  statement behind the same proxy-level protection as the rest of the site).

## Health and readiness

`GET /healthz` is unchanged: liveness for the process.

`GET`/`HEAD /readyz` reports whether this instance can serve:

```json
{"status":"ready","checks":{"admin_artifact":"ok","api_upstream":"ok"}}
```

It answers `503` with `"status":"unready"` when either check fails, and the
failure labels are fixed words — `missing` for the artifact, `ok` / `timeout` /
`unreachable` / `unhealthy` for the upstream — so the response never discloses
the upstream address or any credential. The upstream check is
`GET {upstream}/api/v1/health/ready` (the probe the release scripts poll),
bounded to 2s; the artifact check re-stats `index.html`, so an unplugged volume
is noticed.

## Configuration

`internal/config` is the only place that reads the environment, and it fails
closed: a missing database URL, artifact directory or upstream URL refuses to
start with a message naming the variable.

| Variable | Default | Meaning |
| --- | --- | --- |
| `SOYMUTDB_DATABASE_URL` | required | PostgreSQL DSN (SQLAlchemy form accepted); the session is forced read-only |
| `SOYMUTDB_GATEWAY_ADDR` | `:18020` | listen address |
| `SOYMUTDB_GATEWAY_MAX_OPEN_CONNS` | `10` | pool size |
| `SOYMUTDB_GATEWAY_MAX_IDLE_CONNS` | `5` | idle connections |
| `SOYMUTDB_GATEWAY_QUERY_TIMEOUT` | `5s` | per-request deadline for the stats aggregate |
| `SOYMUTDB_GATEWAY_STATIC_DIR` | required | built admin artifact directory |
| `SOYMUTDB_GATEWAY_UPSTREAM_URL` | required | Python API base URL (`http`/`https`, no credentials, no query) |
| `SOYMUTDB_GATEWAY_PROXY_TIMEOUT` | `30s` | deadline for one proxied request |
| `SOYMUTDB_GATEWAY_READ_TIMEOUT` | `5m` | server read deadline (a client body, e.g. an import upload) |
| `SOYMUTDB_GATEWAY_RATE_LIMIT_RATE` | `30` | proxied requests per second per client |
| `SOYMUTDB_GATEWAY_RATE_LIMIT_BURST` | `60` | bucket capacity (largest instant burst) |
| `SOYMUTDB_GATEWAY_RATE_LIMIT_CLIENTS` | `4096` | tracked clients before LRU eviction |

The server sets `ReadHeaderTimeout` (5s), `IdleTimeout` (60s) and
`MaxHeaderBytes` (16 KiB) as constants, and deliberately no `WriteTimeout`:
every response is either a small aggregate or a stream, and a fixed write
deadline would abort a large export mid-body while it was still being
delivered. The proxy deadline and the API's own limits bound slow responses.

## Read-only enforcement and driver substitution (stage 1)

`config.NormalizeDatabaseURL` accepts the DSN forms the Python services publish
(`postgresql+asyncpg://`, `postgresql+psycopg://`, `postgresql+psycopg2://`),
rewrites them to `postgres://`, and appends
`default_transaction_read_only=on` (URL query or keyword DSN form). lib/pq
forwards unknown keys as startup runtime parameters, so every session on the
pool rejects writes at the server even if a future handler contains a bug.
`sslmode` is not forced: production deployments must supply it, and local
PostgreSQL needs `?sslmode=disable` because lib/pq defaults to `require`.

`github.com/lib/pq` v1.10.9 is vendored under `apps/gateway-go/vendor`, so the
build runs fully offline (`GOFLAGS=-mod=vendor GOPROXY=off`). The store only
uses `database/sql`, so swapping in pgx's `stdlib` driver later is a driver
import plus a small `Querier` implementation, not a rewrite. Vendored
third-party code is covered by its own LICENSE.txt.

## The stats contract (stage 1)

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

## Compose profile

The gateway is an **opt-in additional front door**. `nginx` (`core`) stays the
default; nothing in the `gateway` profile changes it, and the `core` profile
does not start the gateway.

```bash
docker compose --profile core --profile gateway up -d
```

Both profiles are required: `api` and `postgres` live in `core`, and
`--profile gateway` alone stops with "depends on undefined service".

| Part | Value |
| --- | --- |
| profile | `gateway` |
| artifact | `${GATEWAY_ADMIN_DIST:-./apps/admin/dist}` mounted read-only at `/srv/admin` |
| upstream | `http://api-local:8010` (the `api-proxy` alias the API trusts) |
| published port | `127.0.0.1:${GATEWAY_PORT:-8083}` → `18020` |
| healthcheck | `wget --spider http://localhost:18020/readyz` (busybox `wget` from the image's alpine base) |
| hardening | `cap_drop: ALL`, `no-new-privileges`, `read_only`, `tmpfs: /tmp`, non-root `USER` |
| limits | `${GATEWAY_MEMORY_LIMIT:-256m}`, `${GATEWAY_CPU_LIMIT:-1.0}`, `${GATEWAY_PIDS_LIMIT:-256}` |

`apps/gateway-go/Dockerfile` builds the image with a vendored, offline Go build
(`GOFLAGS=-mod=vendor GOPROXY=off`, `CGO_ENABLED=0`, `-trimpath`) onto
`alpine:3.21` with `ca-certificates`.

### NOT DONE: the image is not in the release contract

Nothing in this repository builds, scans, signs or attests this image today:
there is no `gateway` entry in `scripts/list-images.sh`, so the release
pipeline does not build it, `trivy` does not scan it, the SBOM does not include
it, and the release manifest does not attest it. `GATEWAY_IMAGE_REF` in
`docker-compose.yml` is a normal fail-closed `image@sha256` reference, but the
digest must currently be produced **out-of-band** by building
`apps/gateway-go/Dockerfile` yourself. Promoting the gateway into the release
contract (image list, scan, SBOM, signing, manifest, `.env.example` digest) is
unstarted work, not a completed change.

## Run and verify

```bash
cd apps/gateway-go
GOFLAGS=-mod=vendor GOPROXY=off gofmt -l ./cmd ./internal
GOFLAGS=-mod=vendor GOPROXY=off go vet ./...
GOFLAGS=-mod=vendor GOPROXY=off go test ./...

# Benchmarks (static with/without gzip, proxy path with an in-process upstream):
GOFLAGS=-mod=vendor GOPROXY=off go test ./internal/httpapi -bench . -benchtime 2000x -run XXX

# PostgreSQL-backed stage-1 fixture (transaction is rolled back):
SOYMUTDB_GATEWAY_TEST_DATABASE_URL='postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev?sslmode=disable' \
  GOFLAGS=-mod=vendor GOPROXY=off go test ./internal/stats -run TestHomepageAgainstPostgres -v

GOFLAGS=-mod=vendor GOPROXY=off go build -o /tmp/soymutdb-gateway ./cmd/gateway
SOYMUTDB_DATABASE_URL='postgresql+asyncpg://soymutdb:soymutdb@127.0.0.1:5432/soymutdb_dev?sslmode=disable' \
SOYMUTDB_GATEWAY_STATIC_DIR="$PWD/../admin/dist" \
SOYMUTDB_GATEWAY_UPSTREAM_URL='http://127.0.0.1:8010' \
  /tmp/soymutdb-gateway

# Serving-layer behaviour against a running instance:
curl -sI -H 'Accept-Encoding: gzip' http://127.0.0.1:18020/            # Content-Encoding: gzip
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18020/some/spa/route   # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18020/assets/missing.js # 404
curl -s http://127.0.0.1:18020/readyz

# Contract parity against the Python API (same database on both sides):
SOYMUTDB_PARITY_PYTHON_URL=http://127.0.0.1:18010/api/v1/stats/homepage \
SOYMUTDB_PARITY_GATEWAY_URL=http://127.0.0.1:18020/api/v1/stats/homepage \
  bash scripts/verify-gateway-parity.sh
```

The stage-1 integration test asserts exact counts for a fixture that covers
every visibility branch (public line, no line, INS/DEL fold, MNV in the total,
deleted line, private line, non-null-`public_id` rule, a fact from another
release) and asserts that pointing `active_release` at a draft answers zeros.

## Rollout

Stage 1 is deliberately not on the request path; the `gateway` profile is the
opt-in way to try stage 2. To use it:

1. build the image out-of-band from `apps/gateway-go/Dockerfile` and set
   `GATEWAY_IMAGE_REF` to its digest (see the NOT DONE section);
2. build the admin artifact (`apps/admin/dist`) or point
   `GATEWAY_ADMIN_DIST` at a published one;
3. `docker compose --profile core --profile gateway up -d`;
4. run `scripts/verify-gateway-parity.sh` against the Python API and the
   gateway before sending traffic;
5. keep the `core` profile (nginx) as the fallback front door until the parity
   check is part of the release evidence for a full release cycle.

The parity script treats a body mismatch or a status mismatch as a failure. An
empty database (no published release) is documented as producing identical zero
bodies on both sides — note that the Python API's opt-in
`local_test_preview` fallback binds to a draft release when no published one
exists, so on such a preview database the Python side answers draft aggregates
by design and parity is not meaningful until a release is published.

CI wiring for the binary is intentionally not part of these stages: no current
build image carries Go, so the commands above are the local gate and the
vendored tree keeps them network-free.

## Stage 3: public search (planned)

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