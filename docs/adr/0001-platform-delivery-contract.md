# ADR-0001: Platform toolchain, Compose profiles, and OCI delivery

Status: Accepted

Date: 2026-08-20

## Context

SoyMutDB has one monorepo toolchain but several independently operated runtime
capabilities. A floating Node major, implicit Compose service selection, and
tag-based deployment allow the build, verification, and production bytes to
diverge. Local Docker availability is also not a reliable prerequisite for
contributors.

The approved frontend compatibility lines are React 19.2, TypeScript 5.9,
Vite 6, and Ant Design 6. The package migration may change source and lockfile
in its own wave, but it must retain this platform boundary and pass a frozen
pnpm install before release.

## Decision

### Toolchain

- Node.js 24.19.0 is the repository and CI runtime. `.nvmrc`,
  `.node-version`, `package.json`, and every Node-based workflow express the
  same Node 24 LTS line.
- pnpm 11.21.0 is exact in `packageManager`, the engine contract, and CI.
- The workspace catalog records React 19.2.0, React DOM 19.2.0, TypeScript
  5.9.3, Vite 6.4.3, and Ant Design 6.6.1 as shared platform decisions.
  React remains a workspace override as well so transitive peers cannot select
  another runtime. Web and Admin consume Ant Design through `catalog:`.
- `@ant-design/pro-components` remains declared until the source migration has
  zero imports. Its removal and the lockfile rewrite are separate reviewed
  steps; changing a manifest without rewriting the lock is intentionally not
  presented as a frozen-install-ready release.

### Compose capability profiles

The canonical profile vocabulary is
`core,jbrowse,blast,analyses,mcp,cloudflare-tunnel`.

| Profile | Responsibility | Default production selection |
| --- | --- | --- |
| `core` | Stores, migrations, API, general/ingest workers, scheduler, ingress, monitoring | Yes |
| `jbrowse` | Optional self-hosted JBrowse image on a loopback port | No; static hosting is primary |
| `blast` | BLAST queue worker | Yes |
| `analyses` | Analysis queue worker | Yes |
| `mcp` | Authenticated MCP adapter | Yes |
| `cloudflare-tunnel` | Narrow tunnel origin and connector | No; explicit operator opt-in |

`COMPOSE_PROFILES=core,blast,analyses,mcp` is the supported default. Optional
profiles are added to that set; they do not replace `core`. Every production
service declares a profile, so an omitted or misspelled profile cannot silently
start an unrelated capability.

### OCI publication and deployment identity

CI may attach a human-readable date/commit tag for discovery, but a tag is not
a deployment identity. After pushing each verified API, Worker, MCP, and
JBrowse image, CI resolves the registry manifest digest, verifies the remote
digest, and emits a sorted `release-contract/oci-image-refs.txt` containing
only `image@sha256` references. Its checksum is recorded in
`OCI_SHA256SUMS`; the SHA-256 of the signed `release-manifest.json` is exposed
as the `release-contract-sha256` job output and in the workflow run summary.

Production accepts `API_IMAGE_REF`, `WORKER_IMAGE_REF`, `MIGRATE_IMAGE_REF`,
`MIGRATE_CLICKHOUSE_IMAGE_REF`, `MCP_IMAGE_REF`, and `JBROWSE_IMAGE_REF` — one
reference per release image, including the two one-shot migration services
(which used to borrow the API/Worker references and could therefore migrate with
the wrong release). `deploy/scripts/upgrade.sh` rejects tags, validates every
remote manifest, and records the exact references in `.release-state.json`.
Production Compose contains no build fallback that a release can reach: the
`build:` blocks are discarded by the `x-service-local-*` `!reset` anchors and
only apply through `scripts/compose-local.sh`.

Docker acceptance runs in CI. CI validates every supported profile with
`docker compose config`, then uses independent native amd64 and arm64 jobs.
Each architecture must build, runtime-smoke, pass blocking Trivy scans and
produce SPDX SBOMs before its exact image tar is uploaded. The publish job
loads both validated packages, pushes architecture-specific temporary tags,
merges them, and rejects any index whose platform set is not exactly
`linux/amd64,linux/arm64`.

Only the publish job receives `packages: write` and `id-token: write`. It uses
keyless Cosign to sign platform digests and final indexes, attaches SPDX and
SLSA provenance attestations, verifies those signatures immediately, and signs
the source-bound `release-manifest.json` as a blob. Local contract tests remain
daemon-free and network-free; a workflow definition is not evidence that an
ARM runner, registry or Sigstore service has actually succeeded.

### Blue/green traffic contract

The repository's fixed-port Compose topology is not treated as an implicit
second slot. Deployment and rollback scripts consume a signed release manifest
and call an absolute external adapter using `stage`, `verify`, `switch`, and
`current` commands. A promotion updates atomic slot state only after traffic
reports the intended slot. Rollback requires the previous signed manifest and
its recorded digest. The adapter/load balancer implementation and a real drill
remain infrastructure gates; see [the blue/green contract](../../deploy/blue-green.md).

## Rollback

Rollback reuses the previous four digest references from
`.release-state.json`; it never resolves a previous tag again. The first
digest-only release cannot automatically roll back to a legacy state file
that recorded tags. Operators must retain the previous verified OCI contract
and seed digest references before that cutover.

Profile selection is independently reversible: remove an optional profile
from `COMPOSE_PROFILES` and reconcile the project. Removing `core` is not a
supported partial-production mode.

## Consequences

- Re-tagging an OCI manifest cannot change bytes used by a later deployment.
- The optional JBrowse container can be operated without changing the primary
  static-hosting topology.
- CI registry publication is slightly longer because it resolves and checks
  every remote digest.
- Infrastructure images remain version-tagged in this wave; digest pinning for
  third-party images requires a separately reviewed refresh and provenance
  policy.
- After the source migration is ready, the release integrator must run
  `pnpm install --lockfile-only` from the repository root and review the Ant
  Design 6 dependency/peer diff before validating `pnpm install
  --frozen-lockfile`.
