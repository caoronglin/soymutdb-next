"""Contracts for the explicitly amd64-only Kind workload smoke test.

The repository's supported production topology remains Compose/systemd.  These
contracts deliberately cover a small Kubernetes harness that proves the
verified API and Worker image archives can be loaded into an amd64 Kind cluster
and run under restricted pod settings.  It is not a claim of production
multi-architecture Kubernetes support.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
KIND_DIR = ROOT / "infra" / "k8s" / "kind-smoke"
CHECKER = ROOT / "scripts" / "check-kubernetes-manifests.py"
ADR = ROOT / "docs" / "adr" / "0003-kind-kubernetes-validation.md"


def _documents() -> list[dict]:
    kustomization = yaml.safe_load((KIND_DIR / "kustomization.yaml").read_text())
    assert kustomization["apiVersion"] == "kustomize.config.k8s.io/v1beta1"
    assert kustomization["kind"] == "Kustomization"
    assert kustomization["namespace"] == "soymutdb-kind-smoke"

    documents: list[dict] = []
    for resource in kustomization["resources"]:
        documents.extend(
            document
            for document in yaml.safe_load_all((KIND_DIR / resource).read_text())
            if document
        )
    return documents


def _deployment(documents: list[dict], name: str) -> dict:
    return next(
        document
        for document in documents
        if document["kind"] == "Deployment" and document["metadata"]["name"] == name
    )


def _container(deployment: dict) -> dict:
    containers = deployment["spec"]["template"]["spec"]["containers"]
    assert len(containers) == 1
    return containers[0]


def _copy_kind_harness(destination: Path) -> None:
    for filename in ("kustomization.yaml", "namespace.yaml", "api.yaml", "worker.yaml"):
        shutil.copy2(KIND_DIR / filename, destination / filename)


def test_kind_smoke_manifest_runs_api_and_worker_as_restricted_amd64_workloads() -> (
    None
):
    documents = _documents()
    namespace = next(
        document for document in documents if document["kind"] == "Namespace"
    )
    assert namespace["metadata"]["name"] == "soymutdb-kind-smoke"
    assert (
        namespace["metadata"]["labels"]["pod-security.kubernetes.io/enforce"]
        == "restricted"
    )

    api = _container(_deployment(documents, "api"))
    worker = _container(_deployment(documents, "worker"))
    assert api["image"] == "soymutdb-api:ci-amd64"
    assert worker["image"] == "soymutdb-worker:ci-amd64"

    for deployment, container in (
        (_deployment(documents, "api"), api),
        (_deployment(documents, "worker"), worker),
    ):
        pod = deployment["spec"]["template"]["spec"]
        assert pod["hostNetwork"] is False
        assert pod["hostPID"] is False
        assert pod["hostIPC"] is False
        assert pod["securityContext"]["runAsNonRoot"] is True
        assert pod["securityContext"]["runAsUser"] == 1000
        assert pod["securityContext"]["runAsGroup"] == 1000
        assert pod["securityContext"]["fsGroup"] == 1000
        assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
        assert container["imagePullPolicy"] == "Never"
        assert container["securityContext"] == {
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
        }
        resources = container["resources"]
        assert set(resources["requests"]) == {"cpu", "memory"}
        assert set(resources["limits"]) == {"cpu", "memory"}
        assert all(volume.get("hostPath") is None for volume in pod["volumes"])

    assert api["livenessProbe"]["httpGet"]["path"] == "/api/v1/health/live"
    assert api["readinessProbe"]["httpGet"]["path"] == "/api/v1/health/live"
    assert {item["name"] for item in worker["env"]} >= {
        "SOYMUTDB_CELERY_BROKER_URL",
        "SOYMUTDB_CELERY_RESULT_BACKEND",
        "PROMETHEUS_MULTIPROC_DIR",
    }
    assert worker["ports"] == [{"name": "metrics", "containerPort": 9808}]
    for probe_name in ("livenessProbe", "readinessProbe"):
        assert worker[probe_name]["httpGet"] == {
            "path": "/metrics",
            "port": "metrics",
        }
    assert any(
        mount["mountPath"] == "/tmp" and mount["name"] == "runtime-tmp"
        for mount in worker["volumeMounts"]
    )

    service = next(document for document in documents if document["kind"] == "Service")
    assert service["metadata"]["name"] == "api"
    assert service["spec"]["type"] == "ClusterIP"
    assert service["spec"]["ports"] == [
        {"name": "http", "port": 80, "targetPort": "http"}
    ]


def test_kind_smoke_policy_checker_accepts_the_rendered_harness() -> None:
    result = subprocess.run(
        [sys.executable, str(CHECKER), str(KIND_DIR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "Kubernetes Kind smoke manifests passed" in result.stdout


def test_kind_smoke_policy_checker_rejects_kustomize_patches(tmp_path: Path) -> None:
    _copy_kind_harness(tmp_path)
    (tmp_path / "kustomization.yaml").write_text(
        """\
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: soymutdb-kind-smoke
resources:
  - namespace.yaml
  - api.yaml
  - worker.yaml
patches:
  - target:
      kind: Deployment
      name: api
    patch: |-
      - op: replace
        path: /spec/template/spec/containers/0/image
        value: example.invalid/unreviewed:latest
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "kustomization" in result.stderr


def test_kind_smoke_policy_checker_rejects_unapproved_resources(tmp_path: Path) -> None:
    _copy_kind_harness(tmp_path)
    (tmp_path / "unapproved.yaml").write_text(
        """\
apiVersion: v1
kind: ConfigMap
metadata:
  name: unapproved
""",
        encoding="utf-8",
    )
    kustomization_path = tmp_path / "kustomization.yaml"
    kustomization_path.write_text(
        kustomization_path.read_text(encoding="utf-8").replace(
            "  - worker.yaml\n", "  - worker.yaml\n  - unapproved.yaml\n"
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "resources" in result.stderr


def test_kind_smoke_policy_checker_rejects_unapproved_documents(tmp_path: Path) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8")
        + """\
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: unapproved
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "documents" in result.stderr


def test_kind_smoke_policy_checker_rejects_init_containers(tmp_path: Path) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            "      containers:\n",
            """\
      initContainers:
        - name: unapproved
          image: busybox:latest
      containers:
""",
            1,
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "initContainers" in result.stderr


def test_kind_smoke_policy_checker_requires_pinned_filesystem_group(
    tmp_path: Path,
) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace("        fsGroup: 1000\n", ""),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "fsGroup" in result.stderr


def test_kind_smoke_policy_checker_rejects_non_emptydir_runtime_volume(
    tmp_path: Path,
) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            """\
          emptyDir:
            sizeLimit: 256Mi
""",
            """\
          persistentVolumeClaim:
            claimName: unreviewed-storage
""",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "runtime-tmp" in result.stderr


def test_kind_smoke_policy_checker_rejects_host_ports(tmp_path: Path) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            "            containerPort: 8000\n",
            "            containerPort: 8000\n              hostPort: 8000\n",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "hostPort" in result.stderr


def test_kind_smoke_policy_checker_rejects_unapproved_environment(
    tmp_path: Path,
) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            """\
            - name: SOYMUTDB_OUTBOX_DISPATCHER_ENABLED
              value: "false"
""",
            """\
            - name: SOYMUTDB_OUTBOX_DISPATCHER_ENABLED
              value: "false"
            - name: SOYMUTDB_S3_ENDPOINT
              value: http://unreviewed.invalid:9000
""",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "environment" in result.stderr


def test_kind_smoke_policy_checker_requires_current_restricted_policy_version(
    tmp_path: Path,
) -> None:
    _copy_kind_harness(tmp_path)
    namespace_path = tmp_path / "namespace.yaml"
    namespace_path.write_text(
        namespace_path.read_text(encoding="utf-8").replace(
            "pod-security.kubernetes.io/enforce-version: latest",
            "pod-security.kubernetes.io/enforce-version: v1.24",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "enforce-version" in result.stderr


def test_kind_smoke_policy_checker_rejects_explicit_service_account(
    tmp_path: Path,
) -> None:
    _copy_kind_harness(tmp_path)
    api_path = tmp_path / "api.yaml"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            "      automountServiceAccountToken: false\n",
            "      serviceAccountName: unreviewed-service-account\n"
            "      automountServiceAccountToken: false\n",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(CHECKER), str(tmp_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "serviceAccountName" in result.stderr


def test_ci_kind_smoke_consumes_the_checksum_verified_amd64_archive_after_docker_validation() -> (
    None
):
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    docker_job = re.search(
        r"^  docker-build:\n.*?(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )
    kind_job = re.search(
        r"^  kubernetes-kind:\n.*?(?=^  [a-z0-9-]+:\n|\Z)",
        workflow,
        re.MULTILINE | re.DOTALL,
    )

    assert docker_job is not None
    assert kind_job is not None
    assert "matrix.arch == 'amd64'" in docker_job.group(0)
    job = kind_job.group(0)
    assert "needs: docker-build" in job
    # The amd64 package is produced by scripts/build-release-image.sh under the
    # `validate-runtime-images-*` prefix and consumed here by checksum.
    assert "validate-runtime-images-amd64" in job
    assert "sha256sum -c SHA256SUMS" in job
    assert "docker load" in job
    assert re.search(
        r"kind load docker-image\s+soymutdb-api:ci-amd64\s+soymutdb-worker:ci-amd64",
        job,
    )
    assert "python3 scripts/check-kubernetes-manifests.py infra/k8s/kind-smoke" in job
    assert "kubectl kustomize infra/k8s/kind-smoke" in job
    assert "kubectl apply -k infra/k8s/kind-smoke" in job
    assert re.search(r"kubectl -n .* rollout status deployment/api", job)
    assert re.search(r"kubectl -n .* rollout status deployment/worker", job)
    assert "/api/v1/health/live" in job
    # Worker metrics are read with the Python standard library: the runtime
    # image deliberately does not ship curl.
    assert "soymutdb_worker_up" in job
    assert "urllib.request" in job
    assert "127.0.0.1:9808/metrics" in job
    assert "soymutdb_worker_up(\\{[^}]*\\})?[[:space:]]+1" in job
    assert "docker build" not in job
    assert "linux/amd64" in job
    assert "multi-architecture Kubernetes" not in job


def test_kind_validation_adr_sets_ci_scope_non_goals_and_production_promotion_criteria() -> (
    None
):
    adr = ADR.read_text(encoding="utf-8")

    assert "Status: Accepted" in adr
    for required_text in (
        "CI-only",
        "linux/amd64",
        "checksum-verified",
        "imagePullPolicy: Never",
        "restricted Pod Security Standard",
        "/api/v1/health/live",
        "Non-goals",
        "production Kubernetes deployment",
        "arm64 Kubernetes cluster",
        "Promotion criteria",
        "digest-pinned",
        "secret",
        "NetworkPolicy",
        "rollback",
    ):
        assert required_text in adr
