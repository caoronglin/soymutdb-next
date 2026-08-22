"""Fail closed on the small, CI-only Kind workload manifest contract.

The checker intentionally validates only ``infra/k8s/kind-smoke``.  That
directory is an amd64 test harness, not a production Kubernetes abstraction;
keeping the policy explicit prevents it from becoming an unreviewed deployment
path by accident.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import yaml

EXPECTED_NAMESPACE = "soymutdb-kind-smoke"
EXPECTED_IMAGES = {
    "api": "soymutdb-api:ci-amd64",
    "worker": "soymutdb-worker:ci-amd64",
}
EXPECTED_ENVIRONMENTS = {
    "api": [
        {"name": "SOYMUTDB_APP_ENV", "value": "dev"},
        {"name": "SOYMUTDB_OUTBOX_DISPATCHER_ENABLED", "value": "false"},
    ],
    "worker": [
        {"name": "SOYMUTDB_CELERY_BROKER_URL", "value": "memory://"},
        {"name": "SOYMUTDB_CELERY_RESULT_BACKEND", "value": "cache+memory://"},
        {"name": "PROMETHEUS_MULTIPROC_DIR", "value": "/tmp/prometheus-multiproc"},
        {"name": "HOME", "value": "/tmp"},
        {"name": "TMPDIR", "value": "/tmp"},
    ],
}
EXPECTED_KUSTOMIZATION_KEYS = frozenset(
    {"apiVersion", "kind", "namespace", "resources"}
)
EXPECTED_RESOURCES = ("namespace.yaml", "api.yaml", "worker.yaml")
EXPECTED_DOCUMENTS = frozenset(
    {
        ("v1", "Namespace", EXPECTED_NAMESPACE),
        ("apps/v1", "Deployment", "api"),
        ("v1", "Service", "api"),
        ("apps/v1", "Deployment", "worker"),
    }
)
SENSITIVE_ENV_NAME = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PRIVATE_KEY|API_KEY)", re.IGNORECASE
)


class ManifestError(ValueError):
    """A manifest does not satisfy the narrow Kind smoke contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ManifestError(message)


def _mapping(value: Any, context: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{context} must be a mapping")
    return value


def _load_documents(directory: Path) -> list[dict[str, Any]]:
    kustomization_path = directory / "kustomization.yaml"
    _require(kustomization_path.is_file(), f"missing {kustomization_path}")
    kustomization = _mapping(
        yaml.safe_load(kustomization_path.read_text(encoding="utf-8")), "kustomization"
    )
    _require(
        set(kustomization) == EXPECTED_KUSTOMIZATION_KEYS,
        "kustomization may only declare apiVersion, kind, namespace, and resources",
    )
    _require(
        kustomization.get("apiVersion") == "kustomize.config.k8s.io/v1beta1",
        "kustomization must use kustomize.config.k8s.io/v1beta1",
    )
    _require(
        kustomization.get("kind") == "Kustomization", "manifest must be a Kustomization"
    )
    _require(
        kustomization.get("namespace") == EXPECTED_NAMESPACE,
        f"kustomization namespace must be {EXPECTED_NAMESPACE}",
    )
    resources = kustomization.get("resources")
    _require(
        resources == list(EXPECTED_RESOURCES),
        "kustomization resources must exactly match the approved Kind harness files",
    )

    documents: list[dict[str, Any]] = []
    for resource in resources:
        _require(
            isinstance(resource, str) and resource,
            "resource names must be non-empty strings",
        )
        resource_path = directory / resource
        _require(
            resource_path.parent == directory,
            f"resource escapes kind directory: {resource}",
        )
        _require(resource_path.is_file(), f"missing resource: {resource}")
        for document in yaml.safe_load_all(resource_path.read_text(encoding="utf-8")):
            if document is not None:
                documents.append(_mapping(document, resource))
    return documents


def _document_identity(document: dict[str, Any]) -> tuple[str, str, str]:
    api_version = document.get("apiVersion")
    kind = document.get("kind")
    metadata = _mapping(document.get("metadata"), "document.metadata")
    name = metadata.get("name")
    _require(
        all(isinstance(value, str) and value for value in (api_version, kind, name)),
        "each Kind smoke document must have apiVersion, kind, and metadata.name",
    )
    return api_version, kind, name


def _validate_document_set(documents: list[dict[str, Any]]) -> None:
    identities = [_document_identity(document) for document in documents]
    _require(
        len(identities) == len(EXPECTED_DOCUMENTS)
        and set(identities) == EXPECTED_DOCUMENTS,
        "Kind smoke documents must exactly match the approved workload set",
    )


def _named_document(
    documents: list[dict[str, Any]], kind: str, name: str
) -> dict[str, Any]:
    matches = [
        document
        for document in documents
        if document.get("kind") == kind
        and _mapping(document.get("metadata"), f"{kind}.metadata").get("name") == name
    ]
    _require(len(matches) == 1, f"expected exactly one {kind}/{name}")
    return matches[0]


def _validate_pod_security(
    deployment: dict[str, Any], container: dict[str, Any]
) -> None:
    name = _mapping(deployment["metadata"], "deployment.metadata")["name"]
    pod = _mapping(
        _mapping(deployment["spec"], f"{name}.spec")["template"], f"{name}.template"
    )
    pod_spec = _mapping(pod["spec"], f"{name}.pod.spec")
    _require(
        pod_spec.get("automountServiceAccountToken") is False,
        f"{name} must not mount a token",
    )
    _require(
        "serviceAccountName" not in pod_spec,
        f"{name} may not declare serviceAccountName",
    )
    for field in ("hostNetwork", "hostPID", "hostIPC"):
        _require(pod_spec.get(field) is False, f"{name} must set {field}: false")
    pod_security = _mapping(
        pod_spec.get("securityContext"), f"{name}.pod.securityContext"
    )
    _require(
        pod_security.get("runAsNonRoot") is True, f"{name} pod must run as non-root"
    )
    _require(
        pod_security.get("runAsUser") == 1000, f"{name} pod must pin runtime UID 1000"
    )
    _require(
        pod_security.get("runAsGroup") == 1000, f"{name} pod must pin runtime GID 1000"
    )
    _require(pod_security.get("fsGroup") == 1000, f"{name} pod must pin fsGroup 1000")
    seccomp = _mapping(pod_security.get("seccompProfile"), f"{name}.pod.seccompProfile")
    _require(
        seccomp.get("type") == "RuntimeDefault",
        f"{name} must use RuntimeDefault seccomp",
    )

    security = _mapping(
        container.get("securityContext"), f"{name}.container.securityContext"
    )
    _require(
        security.get("runAsNonRoot") is True, f"{name} container must run as non-root"
    )
    _require(
        security.get("allowPrivilegeEscalation") is False,
        f"{name} must disable privilege escalation",
    )
    _require(
        security.get("readOnlyRootFilesystem") is True,
        f"{name} root filesystem must be read-only",
    )
    capabilities = _mapping(
        security.get("capabilities"), f"{name}.container.capabilities"
    )
    _require(capabilities.get("drop") == ["ALL"], f"{name} must drop all capabilities")
    _require(
        security.get("privileged") in (None, False), f"{name} must not be privileged"
    )

    ports = container.get("ports", [])
    _require(isinstance(ports, list), f"{name} ports must be a list")
    _require(
        all(isinstance(port, dict) and "hostPort" not in port for port in ports),
        f"{name} may not declare hostPort",
    )

    resources = _mapping(container.get("resources"), f"{name}.container.resources")
    for field in ("requests", "limits"):
        values = _mapping(resources.get(field), f"{name}.container.resources.{field}")
        _require(
            all(
                isinstance(values.get(key), str) and values[key]
                for key in ("cpu", "memory")
            ),
            f"{name} must have cpu and memory {field}",
        )
    volumes = pod_spec.get("volumes", [])
    expected_runtime_tmp_size = "256Mi" if name == "api" else "512Mi"
    _require(
        volumes
        == [
            {
                "name": "runtime-tmp",
                "emptyDir": {"sizeLimit": expected_runtime_tmp_size},
            }
        ],
        f"{name} must use only the approved runtime-tmp emptyDir volume",
    )


def _validate_no_literal_sensitive_env(container: dict[str, Any], name: str) -> None:
    env = container.get("env", [])
    _require(isinstance(env, list), f"{name} env must be a list")
    for item in env:
        entry = _mapping(item, f"{name}.env entry")
        env_name = entry.get("name")
        _require(isinstance(env_name, str) and env_name, f"{name} env name is required")
        if SENSITIVE_ENV_NAME.search(env_name):
            value_from = _mapping(
                entry.get("valueFrom"), f"{name}.{env_name}.valueFrom"
            )
            _require("value" not in entry, f"{name}.{env_name} may not be a literal")
            _require(
                isinstance(value_from.get("secretKeyRef"), dict),
                f"{name}.{env_name} must use secretKeyRef",
            )


def _validate_runtime_environment(container: dict[str, Any], name: str) -> None:
    _require(
        container.get("env") == EXPECTED_ENVIRONMENTS[name],
        f"{name} environment must exactly match the approved Kind smoke configuration",
    )


def _validate_deployment(documents: list[dict[str, Any]], name: str) -> None:
    deployment = _named_document(documents, "Deployment", name)
    pod_spec = _mapping(
        _mapping(
            _mapping(deployment["spec"], f"{name}.spec")["template"], f"{name}.template"
        )["spec"],
        f"{name}.pod.spec",
    )
    _require("initContainers" not in pod_spec, f"{name} may not declare initContainers")
    containers = pod_spec.get("containers")
    _require(
        isinstance(containers, list) and len(containers) == 1,
        f"{name} needs one container",
    )
    container = _mapping(containers[0], f"{name}.container")
    _require(container.get("name") == name, f"{name} container must have the same name")
    _require(
        container.get("image") == EXPECTED_IMAGES[name],
        f"{name} image must be verified amd64 tag",
    )
    _require(
        container.get("imagePullPolicy") == "Never",
        f"{name} must not pull another image",
    )
    _validate_pod_security(deployment, container)
    _validate_no_literal_sensitive_env(container, name)
    _validate_runtime_environment(container, name)

    if name == "api":
        for probe_name in ("livenessProbe", "readinessProbe"):
            probe = _mapping(container.get(probe_name), f"api.{probe_name}")
            http_get = _mapping(probe.get("httpGet"), f"api.{probe_name}.httpGet")
            _require(
                http_get.get("path") == "/api/v1/health/live"
                and http_get.get("port") == "http",
                f"api {probe_name} must use /api/v1/health/live over named http port",
            )
    else:
        env_names = {
            item.get("name")
            for item in container.get("env", [])
            if isinstance(item, dict)
        }
        _require(
            {
                "SOYMUTDB_CELERY_BROKER_URL",
                "SOYMUTDB_CELERY_RESULT_BACKEND",
                "PROMETHEUS_MULTIPROC_DIR",
            }
            <= env_names,
            "worker must configure isolated Kind runtime dependencies",
        )
        _require(
            container.get("ports") == [{"name": "metrics", "containerPort": 9808}],
            "worker must expose its named Prometheus metrics port",
        )
        for probe_name in ("livenessProbe", "readinessProbe"):
            probe = _mapping(container.get(probe_name), f"worker.{probe_name}")
            http_get = _mapping(probe.get("httpGet"), f"worker.{probe_name}.httpGet")
            _require(
                http_get.get("path") == "/metrics"
                and http_get.get("port") == "metrics",
                f"worker {probe_name} must use /metrics over named metrics port",
            )
        mounts = container.get("volumeMounts", [])
        _require(
            any(
                isinstance(mount, dict)
                and mount.get("name") == "runtime-tmp"
                and mount.get("mountPath") == "/tmp"
                for mount in mounts
            ),
            "worker needs a writable /tmp emptyDir under a read-only root filesystem",
        )


def validate(directory: Path) -> None:
    documents = _load_documents(directory)
    _validate_document_set(documents)
    namespace = _named_document(documents, "Namespace", EXPECTED_NAMESPACE)
    labels = _mapping(
        _mapping(namespace["metadata"], "namespace.metadata").get("labels"),
        "namespace.labels",
    )
    _require(
        labels.get("pod-security.kubernetes.io/enforce") == "restricted",
        "namespace must enforce the restricted Pod Security Standard",
    )
    _require(
        labels.get("pod-security.kubernetes.io/enforce-version") == "latest",
        "namespace enforce-version must be latest for the restricted policy",
    )
    _validate_deployment(documents, "api")
    _validate_deployment(documents, "worker")

    service = _named_document(documents, "Service", "api")
    service_spec = _mapping(service.get("spec"), "service.spec")
    _require(service_spec.get("type") == "ClusterIP", "API service must be ClusterIP")
    _require(
        service_spec.get("ports")
        == [{"name": "http", "port": 80, "targetPort": "http"}],
        "API service must expose only named HTTP on port 80",
    )


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <kind-smoke-directory>", file=sys.stderr)
        return 2
    try:
        validate(Path(argv[1]).resolve())
    except (ManifestError, OSError, yaml.YAMLError) as error:
        print(
            f"Kubernetes Kind smoke manifest validation failed: {error}",
            file=sys.stderr,
        )
        return 1
    print("Kubernetes Kind smoke manifests passed (CI-only linux/amd64 harness).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
