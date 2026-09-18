# Production Build Mode & Artifact Hard Gate

SoyMutDB has **two distinct frontend build paths**. They must never be
conflated: a demo/fallback artifact is not a release, and a release artifact
must not carry demo fixtures or placeholder origins.

| | Demo / Preview build | **Production build** |
|---|---|---|
| `VITE_DEPLOYMENT_MODE` | `demo` (gh-pages) / `standard` / `minimal` | `production` |
| Sample SSG data | embedded `fallback-data.ts` fixtures (`SMDB-00001`…) | **release API** (must be reachable) |
| API fallback | embedded `fallback-data.ts` pages when API is down | **fail closed** — build aborts if the release API is unhealthy |
| Release id | not required | **`SOYMUTDB_RELEASE_ID` required** (positive int) |
| `manifest.json` + `SHA256SUMS` | not emitted | **emitted** over the final static tree |
| Artifact scan | `--allow-demo` (placeholder-origin only) | **strict** (rejects demo fixtures + placeholder origins) |

## How the production path is enforced

### 1. Strict deployment mode (`apps/web/src/lib/deployment.ts`)

`resolveDeploymentMode` now honours `production` (in addition to
`demo`/`minimal`/`standard`). `isProductionDeploymentMode(value)` is the single
source of truth the build scripts consult.

### 2. SSG & sample generation fail closed

`apps/web/scripts/ssg-build.ts` and `apps/web/scripts/generate-samples.ts` opt
into the guard via `isProductionDeploymentMode(process.env.VITE_DEPLOYMENT_MODE)`.

- `ssg-build.ts`: in `production`, `PRODUCTION_MODE && !apiAvailable` **throws**
  instead of silently using embedded fallback pages. The API base is REQUIRED
  (`SOYMUTDB_API_URL`/`VITE_API_BASE_URL`); it no longer falls back to
  `http://localhost:8000`.
- `generate-samples.ts`: in `production`, it is a hard error to combine
  `VITE_DEPLOYMENT_MODE=production` with a demo publication mode or a demo
  deployment, and the generator never reads `FALLBACK_VARIANTS`.

### 3. Release manifest (real release_id + SHA-256)

`apps/web/scripts/release-manifest.ts` is appended to the web `build` chain. In
`production` it:

1. requires a real `SOYMUTDB_RELEASE_ID`,
2. walks the final `dist/` tree and writes `manifest.json` (per-file SHA-256 +
   release metadata) and a fixed-format `SHA256SUMS` file.

In `demo`/`standard`/`minimal` mode it is a no-op. `SOYMUTDB_RELEASE_ID` is
added to `turbo.json` build env so the cache is invalidated when the release id
changes.

### 4. Production artifact scan (`scripts/check-production-artifact.sh`)

```bash
# Strict production gate — rejects demo fixtures + placeholder origins.
bash scripts/check-production-artifact.sh apps/web/dist

# Lighter gate for the gh-pages DEMO artifact — permits demo fixtures but still
# rejects placeholder origins baked into deployment-facing HTML.
bash scripts/check-production-artifact.sh apps/web/dist --allow-demo
```

Always blocked: `api.example.com`, `jbrowse.example.com`, `change-me`, and
loopback binds (`localhost` / `127.0.0.1`) in deployment-facing text files
(emitted `.js` bundles are skipped, because a runtime fallback literal like
`http://localhost:5175` legitimately survives minification).

Strict-only (the `--allow-demo` waiver): `SMDB-00001`, `Demo fixture`,
`demonstration data`, `VITE_DEMO_MODE`. The generic word `demo` is deliberately
NOT blocked — it appears legitimately in the UI (e.g. the "demo deployment
mode" help text and a `?demo=` search param).

Notes on false positives:

- Placeholder-origin documentation comments are stripped from emitted HTML
  (`base-template.ts`), so `api.example.com`/`jbrowse.example.com` only appear
  when a build is genuinely misconfigured with a placeholder origin.
- `www.example.com` (used as an example in the Admin analytics help text) is
  intentionally not matched by the placeholder patterns.

## `admin` / `jbrowse` sub-path support

- `apps/admin/vite.config.ts` reads `VITE_BASE_URL` and sets `base`, so the
  console can be served from `admin.soymutdb.org` or a protected custom origin
  instead of the domain root.
- `apps/jbrowse/vite.config.ts` already reads `VITE_BASE_URL` for `base`. When
  deploying under a sub-path, also set `VITE_JBROWSE_DATA_URL` to the matching
  prefix so the embedded data URLs resolve correctly.

## Pre-compressed `.gz` siblings (`SOYMUTDB_EMIT_GZ`)

`.gz` copies of static assets exist for exactly one consumer: nginx
`gzip_static` inside the release images (`infra/docker/web-nginx.conf`,
`infra/docker/admin-nginx.conf`). Cloudflare Pages and GitHub Pages do not read
them, so producing them for a published tree would double its size for nothing.

| Path | `SOYMUTDB_EMIT_GZ` | Result |
| --- | --- | --- |
| `scripts/build-sites.ts` (Pages / gh-pages) | unset | no `.gz`; any stale `.gz` in the tree is deleted |
| `infra/docker/Dockerfile.{web,admin}` | `1` | `.gz` emitted for nginx `gzip_static` |
| `scripts/build-static-apps.sh` | `1` (default) | matches the container path it stands in for |

Both the build chain (`apps/web/scripts/gzip-compress.ts`,
`apps/web/scripts/gen-sw.js`) and `infra/docker/precompress.sh` honour the flag.
`gen-sw.js` always deletes a stale `sw.js.gz`, even when it does not write one —
a leftover `.gz` from a container build would otherwise be served as the current
service worker.

Division of labour on the container path: the build chain covers
`.html/.css/.js/.svg/.json/.xml/.txt`; `precompress.sh` additionally covers
`.woff/.woff2/.ttf`, which the build chain never touches.

`precompress.sh` rewrites a `.gz` that is missing or older than its source and
leaves a current one alone. This matters because `gzip -k` *refuses* to
overwrite an existing `.gz` ("already exists; not overwritten") and would keep
the previous body, which `gzip_static` would then serve. It was never a build
breaker: the script uses `find … -exec … \;`, and only `-exec … +` propagates a
command failure. Regression cover:
`scripts/test_dockerfile_contracts.py::test_precompress_refreshes_stale_archives`.

## CI wiring (`.github/workflows/ci.yml`)

The `frontend` job builds the **demo** artifact (`VITE_DEPLOYMENT_MODE=demo`)
and runs `check-production-artifact.sh --allow-demo`: this prevents even the
demo artifact from baking placeholder origins into its deployment-facing HTML.
The **strict** production gate (no `--allow-demo`) runs in the release/deploy
workflow against the production artifact, which is where
`VITE_DEPLOYMENT_MODE=production`, a reachable release API and a real
`SOYMUTDB_RELEASE_ID` are available.

## Release images and the local-build path

The release image set — and therefore the set of artifacts this production gate
has to be coherent with — is declared once, in `scripts/list-images.sh`:

```
<name>|<context>|<dockerfile>
```

`scripts/build-release-image.sh` builds every entry, `scripts/release-contract.golden.sh`
publishes exactly that set, and `scripts/test_dockerfile_contracts.py` fails if an
image has no architecture proof, no runtime smoke gate, no Trivy scan or no SBOM.

Two of those images are the one-shot migrations, and they exist as separate
artifacts for a reason that is *not* cosmetics:

| Service | Variable | Why it is its own image |
| --- | --- | --- |
| `migrate` | `MIGRATE_IMAGE_REF` | It used to borrow `API_IMAGE_REF`. The api service runs a release **digest** while the migration step then stayed on the API **tag**, so a publish that updated only the digest references would run the *previous* release's migrations. |
| `migrate-clickhouse` | `MIGRATE_CLICKHOUSE_IMAGE_REF` | It used to borrow `WORKER_IMAGE_REF`, which pulled in ncbi-blast+, samtools, scanpy and Celery for a script that needs `clickhouse-connect`. |

### Building and running the production topology locally

`docker-compose.yml` requires `image@sha256` references and fails closed without
them. To run the *same* topology from a checkout — no registry, no release
artifact — use the wrapper, which builds the same Dockerfiles:

```bash
bash scripts/compose-local.sh build
bash scripts/compose-local.sh up -d
bash scripts/compose-local.sh down
```

The wrapper loads `docker-compose.local.yml` after the production file. Because
Compose interpolates each file before merging, the wrapper first supplies safe
local values for every production `${…:?…}` reference (`*_IMAGE_REF`, store
credentials, the MCP token, and the Grafana password). The production file
itself defines no `build:` at all — only the wrapper builds, with direct
`docker build` calls for the images declared in `scripts/list-images.sh` — so the
local file only overrides `image:` with ordinary `${API_IMAGE:-…}` scalars.
`!reset` is deliberately not used on `image`: Compose uses it to discard the
value rather than to set the supplied scalar. The production file itself remains
fail-closed (and build-free) when invoked directly. This wrapper is the *only*
supported local-build entry point; it is not a fallback the release path can
reach.
