# Blue/green release adapter contract

SoyMutDB does not claim that the current single-host Compose file can run two
complete stacks concurrently: its databases and ingress use fixed host ports,
and duplicating the authoritative data plane would be unsafe. Blue/green
promotion therefore uses a small fail-closed host contract around an
environment-specific adapter. The adapter may target two hosts, two container
platform services, or two application-only slots connected to the same managed
data plane.

## Required release evidence

The `publish-images` CI job produces the artifact
`oci-release-contract-<git-sha>`. It contains:

- `release-manifest.json`, binding the source commit to API, Worker, MCP, and
  JBrowse multi-architecture `image@sha256` references;
- signed linux/amd64 and linux/arm64 package references plus SPDX JSON SBOMs;
- SLSA provenance predicates for each multi-architecture index;
- `release-manifest.sigstore.json`, the keyless Cosign bundle for the manifest;
- checksums for the manifest and evidence files.

Both slot scripts verify the caller-supplied manifest checksum, Sigstore bundle,
workflow certificate identity, image signatures, provenance attestations, SBOM
attestations, and signed-manifest-bound local provenance/SBOM checksums before
asking an adapter to change state.

Set the exact trusted workflow identity and the adapter path:

```bash
export SOYMUTDB_RELEASE_CERTIFICATE_IDENTITY='https://github.com/OWNER/REPO/.github/workflows/ci.yml@refs/heads/main'
export BLUE_GREEN_ADAPTER=/usr/local/libexec/soymutdb-blue-green-adapter
```

`cosign`, `jq`, `sha256sum`, and `flock` must be installed on the deployment
host. Verification needs access to the OCI registry and the Sigstore
Fulcio/Rekor services unless the organization supplies an equivalent verified
offline bundle policy.

## Adapter interface

`BLUE_GREEN_ADAPTER` must be an absolute executable path. It receives one of
four subcommands; scripts invoke it as an argument array and never use `eval`.

| Command | Arguments | Required result |
| --- | --- | --- |
| `stage` | `SLOT MANIFEST_PATH MANIFEST_SHA256` | Pull only manifest digest refs, start/update the inactive slot, return nonzero on any failure |
| `verify` | `SLOT MANIFEST_SHA256` | Probe readiness and a release-identity endpoint until that slot reports the exact manifest SHA-256 |
| `switch` | `SLOT` | Atomically direct new traffic to the requested healthy slot |
| `current` | none | Print exactly `blue` or `green` for the slot currently receiving traffic |

The adapter owns infrastructure-specific health URLs, load-balancer APIs and
credentials. It must not report `verify` success based only on process
liveness. The old slot remains running after promotion so rollback does not
re-resolve a tag or rebuild an image.

## State bootstrap and operations

Before the first scripted promotion, create a root-owned mode-0600 state file
whose active digest matches an already verified release:

```json
{
  "schema_version": 1,
  "active_slot": "blue",
  "active_release_manifest_sha256": "<64 lowercase hex>",
  "previous_slot": null,
  "previous_release_manifest_sha256": null,
  "promoted_at": "2026-08-20T00:00:00Z"
}
```

The default path is `/var/lib/soymutdb/blue-green-state.json`; override it with
`BLUE_GREEN_STATE_FILE` for a managed environment. Promotion is:

```bash
bash deploy/scripts/blue-green-deploy.sh \
  release-contract/release-manifest.json \
  <manifest-sha256> \
  release-contract/release-manifest.sigstore.json
```

Rollback requires the retained previous release contract and checks that its
checksum equals the previous checksum recorded in state:

```bash
bash deploy/scripts/blue-green-rollback.sh \
  previous-release/release-manifest.json \
  <previous-manifest-sha256> \
  previous-release/release-manifest.sigstore.json
```

Operations are serialized with `flock`. Before staging or rollback
verification, `current` must match the active slot recorded in state; any
control-plane drift aborts the operation. A failed post-switch verification
asks the adapter to restore the original slot. The state file is written
through a temporary file and atomic rename only after `current` confirms the
new route. If restoring traffic fails, the script emits a CRITICAL message and
exits nonzero; external load-balancer alerts and an operator are still required.

## Infrastructure gates not implemented in this repository

- availability and quota of GitHub's native `ubuntu-24.04-arm` runner;
- arm64 base images, Python wheels, and Trivy support for every release image;
- GHCR package permissions and retention for temporary architecture tags;
- GitHub OIDC, Sigstore Fulcio/Rekor availability and organization trust policy;
- a protected `main` environment with required reviewers, if production policy
  requires approval beyond CI success;
- a concrete two-slot adapter, release-identity endpoint, load balancer,
  credentials, health thresholds and alert routing;
- a real promotion and rollback drill proving connection draining, background
  worker compatibility and database migration behavior.

Until these gates are supplied and exercised, the scripts and workflow are
verifiable contracts, not evidence that production blue/green deployment has
already succeeded.
