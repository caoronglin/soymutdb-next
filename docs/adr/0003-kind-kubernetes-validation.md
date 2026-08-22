# ADR 0003: CI-only Kind validation for verified container workloads

Status: Accepted

## Context

The supported production topology is Compose/systemd. There are no production
Kubernetes manifests, Helm charts, cluster credentials, storage classes, or
Kubernetes operations SLOs in this repository. Docker image checks alone prove
that an image starts on its native build platform, but they do not prove that a
restricted Kubernetes pod can schedule it, respect its probes, or serve traffic
through a Kubernetes Service.

## Decision

CI adds a small **CI-only** Kind harness at
`infra/k8s/kind-smoke/`. After the native Docker build, runtime smoke, Trivy,
and SPDX steps pass, the amd64 job exports a checksum-verified runtime image
package. The Kind job verifies its `SHA256SUMS`, reloads the package, checks
each Docker image's reported architecture, and loads the API and Worker into a
`linux/amd64` Kind cluster.

The workload manifests deliberately use `imagePullPolicy: Never`. Therefore a
pod cannot fall back to a registry tag in place of the checksum-verified local
image. The manifest-policy script enforces the restricted Pod Security Standard: non-root execution, `RuntimeDefault` seccomp, dropped Linux
capabilities, no privilege escalation, read-only root filesystems, no host
namespaces or `hostPath`, explicit CPU/memory resources, and no literal secret
environment values. Because the runtime Dockerfiles declare a named
`soymutdb` user, the manifests also pin its numeric UID/GID (`1000`) so the
kubelet can verify `runAsNonRoot` before starting the containers; `fsGroup:
1000` makes the mounted `/tmp` `emptyDir` writable by that user.

The runtime proof renders the Kustomize tree, applies it, waits for API and
Worker rollouts, reaches `/api/v1/health/live` through a Kubernetes Service
port-forward, and verifies `soymutdb_worker_up` from the Worker's local
Prometheus `/metrics` endpoint. The API uses its development-safe liveness
configuration and the Worker uses an in-memory Celery transport only for this
isolated container startup proof.

Native Docker CI remains the multi-platform source of evidence: it independently
builds, smokes, scans, inventories, and signs `linux/amd64` and `linux/arm64`
images. The Kind job intentionally adds Kubernetes orchestration evidence only
for the verified amd64 package.

## Non-goals

- This is not a production Kubernetes deployment, release target, or migration
  of the Compose/systemd runtime path.
- It does not prove an arm64 Kubernetes cluster, multi-node scheduling,
  autoscaling, GPU/high-memory worker placement, persistent data storage, or
  production networking.
- It does not exercise PostgreSQL/ClickHouse/Redis/MinIO migrations, real
  production secrets, Cloudflare Tunnel ingress, or a full Celery task flow.
- It does not establish a production Helm chart, Kustomize overlay, or cluster
  privilege model.

## Promotion criteria

Before declaring a production Kubernetes deployment supported, add all of the
following as reviewed, executable contracts:

1. A separate production overlay with **digest-pinned** image references that
   are verified against the signed OCI release contract; CI-only `:ci-amd64`
   tags must never become production input.
2. A secret-management integration (for example an external secret controller
   or an approved encrypted-secret flow), least-privilege service accounts, and
   no plaintext credentials in manifests, logs, or CI output.
3. Stateful dependency design: durable PostgreSQL/ClickHouse/Redis/MinIO
   provisioning or managed-service bindings, backup/restore evidence, schema
   migration Jobs, storage classes, and capacity limits.
4. Namespace isolation, default-deny `NetworkPolicy` rules, narrowly scoped
   evidence-backed egress, ingress/Tunnel separation, and authenticated admin
   origin controls.
5. Production readiness/liveness/startup probes against real dependencies,
   resource requests/limits based on measured workloads, disruption budgets,
   autoscaling policy where justified, observability, rollout health gates, and
   a tested rollback procedure.
6. Kubernetes runtime evidence for every supported architecture, including an
   actual arm64 Kubernetes cluster before claiming arm64 Kubernetes support.

Until these criteria are met, CI should describe this work only as an amd64
Kind validation harness and retain Compose/systemd as the production path.
