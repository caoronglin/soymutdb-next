# Core-only deployment

SoyMutDB's deployment is profile-based. The `core` profile is the database
product: PostgreSQL (authority), ClickHouse (projection), Redis, MinIO, the API,
the default/ingest workers, beat, nginx and the monitoring stack. Genome
browsing, BLAST, on-demand analyses and the MCP server are **optional services**
in their own profiles and are not required for search, entity detail, downloads
or content.

## Compose

```bash
# Core database service, no JBrowse / BLAST / analyses / MCP:
docker compose --profile core up --build

# Add an optional service to the same stack:
docker compose --profile core --profile jbrowse up -d
docker compose --profile core --profile blast  up -d
```

The optional services are declared in `docker-compose.yml` with their own
profiles (`jbrowse`, `blast`, `analyses`, `mcp`), so a core-only host never
starts them. nginx resolves `jbrowse`/`web`/`admin` through `extra_hosts`, so it
starts without those containers; requests to an unstarted optional route are the
only thing that fails.

## Portal build

A portal built for a core-only deployment must not link into a service that is
not running. Build it with the feature gate off:

```bash
VITE_JBROWSE_ENABLED=0 pnpm --filter @soymutdb/web build
```

`VITE_JBROWSE_ENABLED` is an explicit, build-time switch (`0`/`false`/`off`/
`no` disable). Absent or any other value keeps JBrowse enabled, so existing
deployments are unchanged. When disabled the portal:

- hides the genome-browser entry in the header navigation,
- resolves `/browser` and `/gbrowse` to an explicit "not available in this
  deployment" view instead of embedding an upstream that is not running,
- omits the "view in JBrowse" link on gene pages.

The routes stay registered, so a shared deep link still reaches an explanation
rather than a 404.

## Pages artifact

The static Pages artifact can be built without the JBrowse sub-app:

```bash
SOYMUTDB_JBROWSE_ENABLED=0 bash scripts/build-pages-artifact.sh
bash scripts/verify-pages-artifact.sh pages-dist
```

A core-only tree carries a `.no-jbrowse` marker (covered by `SHA256SUMS`);
`verify-pages-artifact.sh` and `stage-pages-publication.sh` accept the absence of
`soymutdb-jbrowse/index.html` **only** when that marker is present, so a tree
that lost the sub-app by accident still fails verification.

## Minimal compose variables

`deploy/.env.core-only.example` is the minimal docker-compose variable file for
a core-only stack: copy it to `.env` beside `docker-compose.yml`, fill the image
refs and secrets, and run `docker compose --profile core up -d`. It only lists
the variables the `core` profile requires; `deploy/.env.example` remains the
full reference (including the optional-service and publication-target values).
