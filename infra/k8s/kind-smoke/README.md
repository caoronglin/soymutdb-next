# Kubernetes Kind smoke harness

This directory is a CI-only Kubernetes validation harness. It is intentionally
not a supported production Kubernetes deployment and does not replace the
repository's Compose/systemd production path.

The CI job downloads the checksum-verified `linux/amd64` runtime image package,
loads the API and Worker images into a local Kind cluster, and applies these
manifests. `imagePullPolicy: Never` ensures the pods cannot silently pull a
different registry image. The job then verifies both rollouts and the API
liveness endpoint through a Kubernetes Service port-forward. The Worker has
named `/metrics` readiness and liveness probes, and CI verifies its
`soymutdb_worker_up` metric after rollout.

The harness uses development-safe, in-memory dependencies solely to prove the
container workloads start under the Kubernetes restricted Pod Security
Standard. It pins the images' non-root UID/GID (1000), so kubelet can validate
the Dockerfiles' named `soymutdb` user before startup, and sets `fsGroup: 1000`
so the mounted `/tmp` `emptyDir` remains writable. It does not validate database migrations, production secrets,
network policies, autoscaling, persistent storage, or a Kubernetes arm64
cluster. Native Docker CI remains the multi-platform evidence: each workload
image is independently built, smoked, scanned, and inventoried on native
amd64 and arm64 runners before release publication.
