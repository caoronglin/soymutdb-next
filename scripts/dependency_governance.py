"""Generate dependency graphs and run fail-closed dependency analyzers.

Graph generation reads committed lock/configuration files and never needs a
Docker daemon. Audit commands are argument arrays from a reviewed JSON policy;
they are never evaluated through a shell. Every analyzer receives an explicit
passed, failed, or unavailable status and the command exits nonzero unless all
checks pass with their declared report present.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _graph(
    ecosystem: str,
    source: object,
    nodes: dict[str, dict[str, Any]],
    edges: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "ecosystem": ecosystem,
        "status": "passed",
        "source": source,
        "source_revision": os.environ.get("GITHUB_SHA", "working-tree"),
        "nodes": [nodes[node_id] for node_id in sorted(nodes)],
        "edges": sorted(
            edges,
            key=lambda edge: (
                str(edge.get("from", "")),
                str(edge.get("to", "")),
                str(edge.get("relation", "")),
                str(edge.get("name", "")),
            ),
        ),
    }


def _workspace_name(importer: str) -> str:
    package_path = (
        ROOT / importer / "package.json" if importer != "." else ROOT / "package.json"
    )
    if not package_path.is_file():
        return importer
    return json.loads(package_path.read_text(encoding="utf-8")).get("name", importer)


def _pnpm_package_id(name: str, resolution: object) -> str:
    return f"package:{name}@{resolution}"


def _pnpm_graph() -> dict[str, Any]:
    lock_path = ROOT / "pnpm-lock.yaml"
    lock = yaml.safe_load(lock_path.read_text(encoding="utf-8"))
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    snapshots = lock.get("snapshots", {})
    for key, metadata in snapshots.items():
        node_id = f"package:{key}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "resolved-package",
            "resolution": key,
        }
        for dependency_kind in ("dependencies", "optionalDependencies"):
            for name, resolution in (metadata.get(dependency_kind, {}) or {}).items():
                target = _pnpm_package_id(name, resolution)
                nodes.setdefault(
                    target,
                    {
                        "id": target,
                        "kind": "resolved-package-reference",
                        "name": name,
                        "resolution": str(resolution),
                    },
                )
                edges.append(
                    {
                        "from": node_id,
                        "to": target,
                        "relation": dependency_kind,
                        "name": name,
                    }
                )

    for importer, metadata in lock.get("importers", {}).items():
        node_id = f"workspace:{importer}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "workspace",
            "name": _workspace_name(importer),
            "path": importer,
        }
        for dependency_kind in (
            "dependencies",
            "devDependencies",
            "optionalDependencies",
        ):
            for name, declaration in (metadata.get(dependency_kind, {}) or {}).items():
                resolution = declaration.get(
                    "version", declaration.get("specifier", "unresolved")
                )
                if isinstance(resolution, str) and resolution.startswith("link:"):
                    relative = PurePosixPath(importer) / resolution.removeprefix(
                        "link:"
                    )
                    target_path = str(PurePosixPath(os.path.normpath(str(relative))))
                    target = f"workspace:{target_path}"
                else:
                    target = _pnpm_package_id(name, resolution)
                nodes.setdefault(
                    target,
                    {
                        "id": target,
                        "kind": "dependency-reference",
                        "name": name,
                        "resolution": str(resolution),
                    },
                )
                edges.append(
                    {
                        "from": node_id,
                        "to": target,
                        "relation": dependency_kind,
                        "name": name,
                        "specifier": str(declaration.get("specifier", "")),
                    }
                )

    return _graph(
        "pnpm",
        {
            "path": "pnpm-lock.yaml",
            "lockfile_version": str(lock.get("lockfileVersion")),
        },
        nodes,
        edges,
    )


def _uv_source(package: dict[str, Any]) -> str:
    source = package.get("source", {})
    if not source:
        return "unknown"
    key, value = next(iter(source.items()))
    return f"{key}:{value}"


def _uv_graph() -> dict[str, Any]:
    projects = {
        "api": ROOT / "apps/api/uv.lock",
        "worker": ROOT / "apps/worker/uv.lock",
        "mcp-server": ROOT / "apps/mcp-server/uv.lock",
    }
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []

    for project, lock_path in projects.items():
        lock = tomllib.loads(lock_path.read_text(encoding="utf-8"))
        sources.append(
            {
                "project": project,
                "path": str(lock_path.relative_to(ROOT)),
                "lock_version": lock.get("version"),
                "revision": lock.get("revision"),
            }
        )
        candidates: dict[str, list[str]] = {}
        package_rows: list[tuple[str, dict[str, Any]]] = []
        for index, package in enumerate(lock.get("package", [])):
            name = str(package["name"])
            version = str(package.get("version", "workspace"))
            source = _uv_source(package)
            node_id = f"uv:{project}:{name}=={version}:{source}:{index}"
            nodes[node_id] = {
                "id": node_id,
                "kind": "python-package",
                "project": project,
                "name": name,
                "version": version,
                "source": source,
            }
            candidates.setdefault(name, []).append(node_id)
            package_rows.append((node_id, package))

        for node_id, package in package_rows:
            for dependency in package.get("dependencies", []):
                name = str(dependency["name"])
                targets = candidates.get(name, [])
                requested_version = dependency.get("version")
                if requested_version is not None:
                    targets = [
                        target
                        for target in targets
                        if nodes[target].get("version") == str(requested_version)
                    ]
                if not targets:
                    target = f"uv:{project}:unresolved:{name}"
                    nodes.setdefault(
                        target,
                        {
                            "id": target,
                            "kind": "dependency-reference",
                            "project": project,
                            "name": name,
                        },
                    )
                    targets = [target]
                for target in targets:
                    edge = {
                        "from": node_id,
                        "to": target,
                        "relation": "dependency",
                        "name": name,
                    }
                    for qualifier in ("marker", "extra"):
                        if qualifier in dependency:
                            edge[qualifier] = dependency[qualifier]
                    edges.append(edge)

    return _graph("uv", sources, nodes, edges)


def _compose_graph() -> dict[str, Any]:
    compose_path = ROOT / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    declared_networks = set((compose.get("networks") or {}).keys())
    declared_volumes = set((compose.get("volumes") or {}).keys())

    for network in declared_networks:
        node_id = f"network:{network}"
        nodes[node_id] = {"id": node_id, "kind": "network", "name": network}
    for volume in declared_volumes:
        node_id = f"volume:{volume}"
        nodes[node_id] = {"id": node_id, "kind": "volume", "name": volume}

    for service_name, service in compose["services"].items():
        node_id = f"service:{service_name}"
        nodes[node_id] = {
            "id": node_id,
            "kind": "service",
            "name": service_name,
            "profiles": sorted(service.get("profiles", [])),
            "image": service.get("image"),
        }
        depends_on = service.get("depends_on") or {}
        if isinstance(depends_on, list):
            dependencies = depends_on
        else:
            dependencies = depends_on.keys()
        for dependency in dependencies:
            edges.append(
                {
                    "from": node_id,
                    "to": f"service:{dependency}",
                    "relation": "depends_on",
                }
            )
        for network in service.get("networks", []) or []:
            network_name = network if isinstance(network, str) else str(network)
            if network_name in declared_networks:
                edges.append(
                    {
                        "from": node_id,
                        "to": f"network:{network_name}",
                        "relation": "network",
                    }
                )
        for mount in service.get("volumes", []) or []:
            source = (
                mount.split(":", 1)[0]
                if isinstance(mount, str)
                else mount.get("source")
            )
            if source in declared_volumes:
                edges.append(
                    {
                        "from": node_id,
                        "to": f"volume:{source}",
                        "relation": "volume",
                    }
                )

    return _graph("compose", {"path": "docker-compose.yml"}, nodes, edges)


_FROM_PATTERN = re.compile(
    r"^\s*FROM(?:\s+--platform=\S+)?\s+(?P<image>\S+)(?:\s+AS\s+(?P<alias>\S+))?\s*$",
    flags=re.IGNORECASE,
)
_COPY_FROM_PATTERN = re.compile(
    r"^\s*COPY\s+--from=(?P<source>\S+)\s+.+$",
    flags=re.IGNORECASE,
)


def _oci_graph() -> dict[str, Any]:
    releases = {
        "api": ("infra/docker/Dockerfile.api", "."),
        "worker": ("infra/docker/Dockerfile.worker", "."),
        "mcp": ("apps/mcp-server/Dockerfile", "apps/mcp-server"),
        "jbrowse": ("apps/jbrowse/Dockerfile", "."),
    }
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for platform in ("linux/amd64", "linux/arm64"):
        node_id = f"platform:{platform}"
        nodes[node_id] = {"id": node_id, "kind": "platform", "name": platform}

    for release, (dockerfile_name, context) in releases.items():
        release_id = f"release:{release}"
        nodes[release_id] = {
            "id": release_id,
            "kind": "release-image",
            "name": release,
            "dockerfile": dockerfile_name,
            "context": context,
        }
        for platform in ("linux/amd64", "linux/arm64"):
            edges.append(
                {
                    "from": release_id,
                    "to": f"platform:{platform}",
                    "relation": "published_for",
                }
            )

        aliases: set[str] = set()
        current_stage = release_id
        dockerfile = ROOT / dockerfile_name
        for line_number, line in enumerate(
            dockerfile.read_text(encoding="utf-8").splitlines(), 1
        ):
            match = _FROM_PATTERN.match(line)
            if match is None:
                copy_match = _COPY_FROM_PATTERN.match(line)
                if copy_match is None:
                    continue
                copy_source = copy_match.group("source")
                if copy_source.lower() in aliases:
                    copy_target = f"stage:{release}:{copy_source.lower()}"
                    copy_kind = "dockerfile-stage"
                else:
                    copy_target = f"base-image:{copy_source}"
                    copy_kind = "base-image"
                nodes.setdefault(
                    copy_target,
                    {"id": copy_target, "kind": copy_kind, "name": copy_source},
                )
                edges.append(
                    {
                        "from": current_stage,
                        "to": copy_target,
                        "relation": "copy_from",
                        "dockerfile": dockerfile_name,
                        "line": line_number,
                    }
                )
                continue
            image = match.group("image")
            alias = (match.group("alias") or "").lower()
            if image.lower() in aliases:
                target = f"stage:{release}:{image.lower()}"
                kind = "dockerfile-stage"
            else:
                target = f"base-image:{image}"
                kind = "base-image"
            nodes.setdefault(target, {"id": target, "kind": kind, "name": image})
            edges.append(
                {
                    "from": release_id,
                    "to": target,
                    "relation": "from",
                    "dockerfile": dockerfile_name,
                    "line": line_number,
                }
            )
            if alias:
                stage_id = f"stage:{release}:{alias}"
                nodes[stage_id] = {
                    "id": stage_id,
                    "kind": "dockerfile-stage",
                    "name": alias,
                    "dockerfile": dockerfile_name,
                }
                aliases.add(alias)
                current_stage = stage_id
                edges.append(
                    {
                        "from": stage_id,
                        "to": target,
                        "relation": "from",
                        "line": line_number,
                    }
                )
            else:
                current_stage = release_id

    return _graph("oci", {"workflow": ".github/workflows/ci.yml"}, nodes, edges)


def generate_graphs(output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    generators = {
        "pnpm": _pnpm_graph,
        "uv": _uv_graph,
        "compose": _compose_graph,
        "oci": _oci_graph,
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": "passed",
        "source_revision": os.environ.get("GITHUB_SHA", "working-tree"),
        "graphs": {},
    }

    for name, generator in generators.items():
        path = output / f"{name}.json"
        try:
            graph = generator()
        except Exception as exc:  # noqa: BLE001 - preserve partial evidence
            graph = {
                "schema_version": SCHEMA_VERSION,
                "ecosystem": name,
                "status": "failed",
                "reason": f"{type(exc).__name__}: {exc}",
                "nodes": [],
                "edges": [],
            }
            manifest["status"] = "failed"
        _write_json(path, graph)
        manifest["graphs"][name] = {
            "path": path.name,
            "sha256": _sha256(path),
            "status": graph["status"],
        }

    _write_json(output / "manifest.json", manifest)
    print(f"dependency graph generation: {manifest['status']} ({output})")
    return 0 if manifest["status"] == "passed" else 1


def _safe_report_path(output: Path, relative: str) -> Path:
    requested = PurePosixPath(relative)
    if requested.is_absolute() or ".." in requested.parts:
        raise ValueError(f"unsafe report path: {relative}")
    path = (output / Path(*requested.parts)).resolve()
    if path != output.resolve() and output.resolve() not in path.parents:
        raise ValueError(f"report path escapes output directory: {relative}")
    return path


def _expand_command(command: list[str], output: Path) -> list[str]:
    replacements = {
        "{output_dir}": str(output.resolve()),
        "{root}": str(ROOT),
    }
    expanded: list[str] = []
    for argument in command:
        for marker, value in replacements.items():
            argument = argument.replace(marker, value)
        expanded.append(argument)
    return expanded


def _executable_available(executable: str) -> bool:
    if os.path.isabs(executable):
        path = Path(executable)
        return path.is_file() and os.access(path, os.X_OK)
    return shutil.which(executable) is not None


def _report_is_available(path: Path, report_format: str) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if report_format == "json":
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False
    return True


def _run_check(check: dict[str, Any], output: Path) -> dict[str, Any]:
    name = str(check["name"])
    category = str(check["category"])
    command = _expand_command([str(value) for value in check["command"]], output)
    report = check["report"]
    report_path = _safe_report_path(output, str(report["path"]))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path = output / f"{name}.stderr.log"
    stdout_log_path = output / f"{name}.stdout.log"
    for stale_path in (report_path, stderr_path, stdout_log_path):
        stale_path.unlink(missing_ok=True)
    result_row: dict[str, Any] = {
        "category": category,
        "exit_code": None,
        "name": name,
        "reason": "executable_not_found",
        "report": str(report["path"]),
        "report_available": False,
        "status": "unavailable",
    }

    if not command or not _executable_available(command[0]):
        stderr_path.write_text(
            f"required executable unavailable: {command[0] if command else '<empty command>'}\n",
            encoding="utf-8",
        )
        return result_row

    cwd_value = str(check.get("cwd", "."))
    cwd = (ROOT / cwd_value).resolve()
    if cwd != ROOT and ROOT not in cwd.parents:
        raise ValueError(f"audit cwd escapes repository: {cwd_value}")

    completed = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    mode = str(report["mode"])
    if mode == "stdout":
        report_path.write_text(completed.stdout, encoding="utf-8")
    elif mode == "file":
        stdout_log_path.write_text(completed.stdout, encoding="utf-8")
    elif mode == "status":
        _write_json(
            report_path,
            {
                "command": command,
                "exit_code": completed.returncode,
                "stderr_log": stderr_path.name,
                "stdout": completed.stdout,
            },
        )
    else:
        raise ValueError(f"unsupported report mode for {name}: {mode}")

    report_available = _report_is_available(
        report_path, str(report.get("format", "text"))
    )
    result_row.update(
        {
            "exit_code": completed.returncode,
            "reason": "passed"
            if completed.returncode == 0
            else "analyzer_exit_nonzero",
            "report_available": report_available,
            "status": "passed"
            if completed.returncode == 0 and report_available
            else "failed",
        }
    )
    if completed.returncode == 0 and not report_available:
        result_row["reason"] = "missing_or_invalid_report"
    return result_row


def run_audits(config_path: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    policy = json.loads(config_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported dependency governance policy schema")
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("dependency governance policy must contain checks")

    rows: list[dict[str, Any]] = []
    for check in checks:
        try:
            row = _run_check(check, output)
        except Exception as exc:  # noqa: BLE001 - record runner errors per check
            row = {
                "category": str(check.get("category", "unknown")),
                "exit_code": None,
                "name": str(check.get("name", "invalid-check")),
                "reason": f"runner_error:{type(exc).__name__}:{exc}",
                "report": str((check.get("report") or {}).get("path", "")),
                "report_available": False,
                "status": "failed",
            }
        rows.append(row)

    status = "passed" if all(row["status"] == "passed" for row in rows) else "failed"
    summary = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "source_revision": os.environ.get("GITHUB_SHA", "working-tree"),
        "checks": rows,
    }
    _write_json(output / "summary.json", summary)
    for row in rows:
        print(f"{row['name']}: {row['status']} ({row['reason']})")
    print(f"dependency governance: {status} ({output})")
    return 0 if status == "passed" else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    graphs = subparsers.add_parser("graphs", help="generate normalized machine graphs")
    graphs.add_argument("--output", type=Path, required=True)
    audit = subparsers.add_parser(
        "audit", help="run every configured dependency analyzer"
    )
    audit.add_argument("--config", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.command == "graphs":
        return generate_graphs(args.output.resolve())
    return run_audits(args.config.resolve(), args.output.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
