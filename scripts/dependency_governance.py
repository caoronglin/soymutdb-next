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
from datetime import date, timedelta
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_VERSION = 1

# `scripts/compose_loader.py` is a sibling module, not an installed package: the
# suite is collected by path (`pytest scripts/…`), which does not put `scripts/`
# on `sys.path`.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from compose_loader import load_compose  # noqa: E402  (needs the path above)


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
    # pnpm >= 10 splits the lockfile into two YAML documents: the first holds
    # the self-managed packageManager dependencies (a single ``.`` importer with
    # ``packageManagerDependencies``); the real project lock carries the
    # workspace importers, settings, catalogs and overrides. Pick the project
    # lock (the document with the most importers), not the manager shim.
    documents = [
        document
        for document in yaml.safe_load_all(lock_path.read_text(encoding="utf-8"))
        if isinstance(document, dict)
    ]
    lock = max(documents, key=lambda document: len(document.get("importers") or {}))
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
    # Parsed with the shared Compose loader rather than `yaml.safe_load`: the
    # explicit docker-compose.local.yml override uses the Compose-only `!reset`
    # tag, and a plain loader refuses any document that carries one. Keeping the
    # single loader means a tag reintroduced here cannot break the graph again.
    compose = load_compose(compose_path)
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

    # Pipeline configurations are a graph input, not a hidden constant: the
    # CNB pipeline is the primary delivery path and the GitHub workflows remain
    # the secondary mirror. Record every declared source so reproducibility does
    # not depend on one CI vendor's file staying in place.
    pipeline_sources = [
        "scripts/check-dockerfile-copy.sh",
        "scripts/check-supply-chain.sh",
    ]
    for config_path in (
        ".cnb.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/baseline-validation.yml",
        ".github/workflows/pages.yml",
        ".github/workflows/e2e-smoke.yml",
    ):
        if (ROOT / config_path).is_file():
            pipeline_sources.append(config_path)

    return _graph("oci", {"pipelines": pipeline_sources}, nodes, edges)


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


# The interpreter the license checks must be read back through. The check's own
# `uv run --project <app>` is the environment the distribution metadata lives in,
# so the probe replays exactly that selection instead of guessing a path.
PROBE_SCRIPT = """
import importlib.metadata as metadata
import json
import sys

# The probe reads the three metadata sources a wheel can publish, in the same
# precedence the projection applies them: the authoritative PEP 639
# `License-Expression`, then the leaf of a Trove `License ::` classifier, then
# the legacy free-text `License` field. `pip-licenses` reads only the last two
# (its `METADATA_KEYS["license"]` is the legacy field), which is why a wheel
# that declares only `License-Expression` is reported `UNKNOWN`.

# `License :: OSI Approved` is a category, not a license: it names no grant, so
# it is never surfaced as a declaration (umap-learn publishes exactly that).
CATEGORY_LEAF = "osi approved"


def classifier_leafs(message):
    leafs = []
    for value in message.get_all("Classifier") or []:
        if not value.startswith("License ::"):
            continue
        leaf = value.rsplit("::", 1)[-1].strip()
        if not leaf or leaf.lower() == CATEGORY_LEAF:
            continue
        if leaf.lower() not in {seen.lower() for seen in leafs}:
            leafs.append(leaf)
    return leafs


def declarations(message):
    expression = (message.get("License-Expression") or "").strip()
    if expression:
        return expression
    leafs = classifier_leafs(message)
    if leafs:
        return "; ".join(leafs)
    legacy = (message.get("License") or "").strip()
    if not legacy or legacy.upper() == "UNKNOWN":
        return None
    if "\\n" in legacy or len(legacy) > 120:
        # A licence TEXT pasted into the legacy field is not a machine-readable
        # declaration: scipy, python-dateutil and scverse-misc all do this. The
        # projection must fail closed on it instead of comparing prose.
        return None
    return legacy


# `importlib.metadata.distributions()` defaults to the interpreter's own search
# path only when it can resolve the package context; passing `sys.path`
# explicitly is the portable spelling and is what makes the probe describe the
# same distribution set the analyzer's report does.
declared = {}
for distribution in metadata.distributions(path=sys.path):
    name = distribution.metadata["Name"]
    if not name:
        continue
    declared[name.lower()] = {
        "license": distribution.metadata.get("License"),
        "license_expression": distribution.metadata.get("License-Expression"),
        "declared": declarations(distribution.metadata),
    }
print(json.dumps(declared, sort_keys=True))
"""


def _probe_declared_licenses(command: list[str]) -> dict[str, Any]:
    """Read every installed distribution's declared licence, in-process.

    This is the reader that `pip-licenses` cannot provide: it reads the PEP 639
    `License-Expression` field directly, and it does so in the SAME environment
    the analyzer's report describes, so the two cannot disagree about which
    packages exist. `uv run --project <app>` accepts a trailing command, so the
    probe replaces the analyzer's own command tail instead of re-deriving it.
    """
    probe_command = _rewrite_for_probe(command)
    if probe_command is None:
        return {}
    completed = subprocess.run(
        probe_command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        return {}
    try:
        probed = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {}
    return probed if isinstance(probed, dict) else {}


def _rewrite_for_probe(command: list[str]) -> list[str] | None:
    """Turn `uv run … pip-licenses …` into `uv run … python -c <probe>`.

    Returns `None` for any check that is not a recognizable `uv run` invocation,
    so an unknown shape degrades to "no probe data" and the report is used
    exactly as before, rather than silently probing the wrong environment.
    """
    if "uv" not in command or "run" not in command:
        return None
    try:
        run_index = command.index("run")
    except ValueError:  # pragma: no cover - guarded by the membership check
        return None
    if run_index + 1 >= len(command):
        return None
    # Everything up to (but excluding) the analyzer entry point is the `uv run`
    # selector: `--locked --no-dev --project <app> --with pip-licenses==5.0.0`.
    tail = command[run_index + 1 :]
    entry = next(
        (
            index
            for index, argument in enumerate(tail)
            if argument in ("pip-licenses", "piplicenses")
        ),
        None,
    )
    if entry is None:
        return None
    selector: list[str] = []
    index = 0
    while index < entry:
        argument = tail[index]
        if argument.startswith("-"):
            selector.append(argument)
            # A `--flag value` pair keeps its value; `--flag=value` does not.
            if "=" not in argument and index + 1 < entry:
                index += 1
                selector.append(tail[index])
        else:
            selector.append(argument)
        index += 1
    return ["uv", "run", *selector, "python", "-c", PROBE_SCRIPT]


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

    # 2. Optional normalized re-evaluation of the analyzer's own report. The
    #    analyzer's raw comparison is the process exit code; when the policy
    #    declares `normalize: license-expressions` the report is the authority
    #    instead, because the raw comparison cannot see a PEP 639 declaration
    #    and the gate would be failing on packages whose licence the allow-list
    #    already accepts. The analyzer's crash is never re-interpreted: a
    #    non-zero exit without a usable report stays a failure.
    normalization = check.get("normalize")
    if report_available and normalization == "license-expressions":
        declared = _probe_declared_licenses(command)
        if declared:
            _write_json(output / f"{name}.declared-licenses.json", declared)
        passed, findings = evaluate_license_report(
            report_path, check, declared=declared
        )
        detail_path = output / f"{name}.findings.log"
        if findings:
            detail_path.write_text("\n".join(findings) + "\n", encoding="utf-8")
        else:
            detail_path.unlink(missing_ok=True)
        result_row["findings"] = findings
        result_row["status"] = "passed" if passed else "failed"
        result_row["reason"] = (
            "passed" if passed else f"{len(findings)} license findings"
        )
    elif report_available and normalization == "accepted-advisories":
        try:
            acceptances = load_advisory_acceptances(
                ROOT / str(check.get("accept_file", ""))
            )
        except (AcceptancePolicyError, json.JSONDecodeError) as exc:
            # A malformed acceptance file must never read as "nothing to
            # accept", which would pass the very findings it fails to describe.
            result_row["status"] = "failed"
            result_row["reason"] = f"acceptance_policy_invalid:{exc}"
            result_row["findings"] = [str(exc)]
        else:
            try:
                passed, findings, accepted = evaluate_advisory_report(
                    report_path, acceptances
                )
            except (AcceptancePolicyError, json.JSONDecodeError) as exc:
                result_row["status"] = "failed"
                result_row["reason"] = f"acceptance_report_unreadable:{exc}"
                result_row["findings"] = [str(exc)]
            else:
                detail_path = output / f"{name}.findings.log"
                if findings:
                    detail_path.write_text("\n".join(findings) + "\n", encoding="utf-8")
                else:
                    detail_path.unlink(missing_ok=True)
                result_row["findings"] = findings
                result_row["accepted"] = accepted
                result_row["status"] = "passed" if passed else "failed"
                result_row["reason"] = (
                    "passed" if passed
                    else f"{len(findings)} unaccepted advisory finding(s)"
                )
    elif normalization is not None:
        result_row["status"] = "failed"
        result_row["reason"] = f"normalization_unavailable:{normalization}"
    return result_row



# -----------------------------------------------------------------------------
# Signed advisory acceptances
# -----------------------------------------------------------------------------
# A vulnerability with no published fix cannot be remediated, only acknowledged.
# That acknowledgement is a governance artifact: it names one advisory for one
# package, records who accepted it and when it stops applying, and states why
# the finding is not reachable.
#
# It is deliberately not a suppression list. Four properties keep it from
# behaving like one:
#
#   * Narrow. Matching is on advisory id AND package. A second high finding in
#     the same package, or a different advisory, still fails.
#   * Expiring. An entry past `expires_on` fails the gate rather than degrading
#     to a warning, and no entry may be written more than MAX_ACCEPTANCE_DAYS
#     out, so a pass cannot be bought with a far-future date.
#   * Non-rotting. An entry that no longer matches any reported finding fails as
#     stale, so an acceptance cannot outlive the problem it was written for.
#   * Visible. Accepted findings are reported with their expiry, in the evidence
#     and in the summary, instead of being dropped from the output.
#
# None of this may rescue a broken analyzer: the report has to exist and parse,
# exactly as for license normalization.
MAX_ACCEPTANCE_DAYS = 90
ACCEPTANCE_REQUIRED_FIELDS = (
    "advisory",
    "package",
    "vulnerable_range",
    "rationale",
    "accepted_by",
    "accepted_on",
    "expires_on",
)


class AcceptancePolicyError(ValueError):
    """The acceptance file is missing, malformed, or over-permissive."""


def _parse_iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise AcceptancePolicyError(f"not an ISO date: {value!r}") from exc


def load_advisory_acceptances(path: Path, *, today: date | None = None) -> list[dict[str, Any]]:
    """Read and validate the acceptance file, or raise.

    Validation happens before any analyzer runs, so a malformed directive is a
    policy error rather than a pass that depends on which report is evaluated.
    """
    today = today or date.today()
    if not path.is_file():
        raise AcceptancePolicyError(f"missing acceptance file {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise AcceptancePolicyError("unsupported advisory acceptance schema_version")
    entries = payload.get("acceptances")
    if not isinstance(entries, list):
        raise AcceptancePolicyError("advisory acceptances must be a list")

    horizon = today + timedelta(days=MAX_ACCEPTANCE_DAYS)
    validated: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise AcceptancePolicyError(f"acceptance #{index} is not an object")
        missing = [f for f in ACCEPTANCE_REQUIRED_FIELDS if not str(entry.get(f, "")).strip()]
        if missing:
            raise AcceptancePolicyError(
                f"acceptance #{index} ({entry.get('advisory', '?')}) is missing "
                f"{', '.join(missing)}; an unsigned acceptance is not an acceptance"
            )
        key = (str(entry["advisory"]), str(entry["package"]))
        if key in seen:
            raise AcceptancePolicyError(f"duplicate acceptance for {key[0]} / {key[1]}")
        seen.add(key)
        try:
            expires = _parse_iso_date(str(entry["expires_on"]))
            _parse_iso_date(str(entry["accepted_on"]))
        except AcceptancePolicyError as exc:
            raise AcceptancePolicyError(f"acceptance {key[0]}: {exc}") from exc
        if expires > horizon:
            raise AcceptancePolicyError(
                f"acceptance {key[0]} expires {expires.isoformat()}, beyond the "
                f"{MAX_ACCEPTANCE_DAYS}-day maximum ({horizon.isoformat()}); "
                "a short acceptance and a re-review is the point"
            )
        validated.append({**entry, "_expires": expires, "_today": today})
    return validated


def evaluate_advisory_report(
    report_path: Path, acceptances: list[dict[str, Any]]
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """Split a pnpm audit report into unaccepted findings, text, and accepted.

    Returns (passed, findings, accepted). `accepted` is returned rather than
    folded into the pass so the summary can keep printing the expiry.
    """
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    advisories = payload.get("advisories")
    if not isinstance(advisories, dict):
        raise AcceptancePolicyError("pnpm audit report has no `advisories` object")

    unaccepted: list[str] = []
    accepted: list[dict[str, Any]] = []
    consumed: set[tuple[str, str]] = set()
    for raw in advisories.values():
        if raw.get("severity") not in ("high", "critical"):
            continue
        advisory = str(raw.get("github_advisory_id") or raw.get("url") or raw.get("id"))
        package = str(raw.get("module_name"))
        match = next(
            (
                a
                for a in acceptances
                if str(a["advisory"]) == advisory and str(a["package"]) == package
            ),
            None,
        )
        if match is None:
            unaccepted.append(
                f"{package}: {raw.get('severity')} {advisory}; "
                f"vulnerable={raw.get('vulnerable_versions')} "
                f"fixed={raw.get('patched_versions') or 'unknown'}"
            )
            continue
        consumed.add((advisory, package))
        expires = match["_expires"]
        expired = expires < match["_today"]
        accepted.append(
            {
                "advisory": advisory,
                "package": package,
                "expires_on": expires.isoformat(),
                "expired": expired,
                "accepted_by": str(match["accepted_by"]),
            }
        )
        if expired:
            unaccepted.append(
                f"{package}: acceptance for {advisory} expired on "
                f"{expires.isoformat()} (accepted by {match['accepted_by']}); "
                "re-review and renew, or fix the dependency"
            )

    for entry in acceptances:
        key = (str(entry["advisory"]), str(entry["package"]))
        if key in consumed:
            continue
        if entry["_expires"] < entry["_today"]:
            continue  # already reported as expired above
        unaccepted.append(
            f"{entry['package']}: acceptance for {entry['advisory']} matches no "
            f"reported finding; delete it — a stale acceptance is not a record "
            "of a live risk"
        )

    return not unaccepted, unaccepted, accepted


def _audit_failure_evidence(row: dict[str, Any], output: Path) -> list[str]:
    """Bounded actionable diagnostic, never a new pass/fail decision."""
    # Accepted findings are emitted first, for every check and including a
    # pass. A gate that only prints them on failure would make a successful run
    # indistinguishable from one where the advisory had actually been fixed —
    # which is exactly the state an acceptance must never be mistaken for.
    accepted_evidence = [
        "  {}: {} {} (accepted by {}, expires {})".format(
            item["package"],
            "EXPIRED" if item.get("expired") else "accepted",
            item["advisory"],
            item["accepted_by"],
            item["expires_on"],
        )
        for item in row.get("accepted") or []
    ]
    if row.get("status") == "passed":
        return accepted_evidence
    name = str(row["name"])
    report = output / str(row.get("report", ""))
    if not report.is_file():
        return accepted_evidence + [
            f"  {name}: report unavailable; see analyzer stderr / CI artifacts"
        ]
    try:
        detail = json.loads(report.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError):
        return accepted_evidence + [f"  {name}: report is not readable JSON"]
    if not isinstance(detail, dict):
        return accepted_evidence + [f"  {name}: unexpected report shape"]
    evidence: list[str] = []
    if name == "pnpm-audit":
        advisories = detail.get("advisories") or {}
        for item in advisories.values() if isinstance(advisories, dict) else []:
            if item.get("severity") not in {"high", "critical"}:
                continue
            evidence.append(
                f"  {item.get('severity')} {item.get('module_name')}: "
                f"{item.get('vulnerable_versions')}; "
                f"fixed={item.get('patched_versions') or 'unknown'} "
                f"{item.get('url')}"
            )
    elif name.startswith("pip-audit-"):
        for package in detail.get("dependencies", []):
            for vuln in package.get("vulns", []):
                fixes = ", ".join(vuln.get("fix_versions") or []) or "no known fix"
                evidence.append(
                    f"  {package.get('name')}=={package.get('version')}: "
                    f"{vuln.get('id')}; fixed={fixes}"
                )
    elif name == "knip":
        unused = detail.get("files", [])
        issues = detail.get("issues", [])
        evidence.append(
            f"  {len(unused)} candidate unused files, "
            f"{len(issues)} files with dependency/export issues; "
            "review entrypoints before removal"
        )
        evidence.extend(f"  unused: {file}" for file in unused[:5])
    elif name == "pnpm-duplicate-versions":
        if "Run pnpm dedupe" in detail.get("stdout", ""):
            evidence.append("  pnpm dedupe --check recommends lockfile deduplication")
    return (accepted_evidence + evidence)[:40]


def run_audits(config_path: Path, output: Path) -> int:
    output.mkdir(parents=True, exist_ok=True)
    policy = json.loads(config_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported dependency governance policy schema")
    checks = policy.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("dependency governance policy must contain checks")
    for check in checks:
        if check.get("normalize") == "license-expressions":
            allow_file = check.get("allow_file")
            if not isinstance(allow_file, str) or not allow_file:
                raise ValueError(
                    f"{check.get('name')}: normalize=license-expressions "
                    "requires an allow_file"
                )
            if not (ROOT / allow_file).is_file():
                raise ValueError(
                    f"{check.get('name')}: missing allow_file {allow_file}"
                )
            # Validate the declared exceptions before any analyzer runs, so a
            # malformed or too-permissive directive is a policy error rather
            # than a pass that depends on which report happens to be evaluated.
            allow_path = ROOT / allow_file
            allowed = _load_allowed_licenses(allow_path)
            for fixup_name, fixup_license in _load_undeclared_fixups(
                allow_path
            ).items():
                for option in normalize_license_options(fixup_license):
                    if option.casefold() not in allowed:
                        raise ValueError(
                            f"{allow_path.name}: {_UNDECLARED_DIRECTIVE} "
                            f"{fixup_name} names {option!r}, which the "
                            "allow-list does not carry"
                        )

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
        for detail in _audit_failure_evidence(row, output):
            print(detail)
    print(f"dependency governance: {status} ({output})")
    return 0 if status == "passed" else 1


# ---------------------------------------------------------------------------
# License-expression normalization
# ---------------------------------------------------------------------------
# `python-licenses-*` must normalise the raw `License` value before it applies
# the allow-list, and this is not a nicety -- it is the difference between a
# gate that reports real findings and one that reports noise.
#
# Until build cnb-a2o-1k29qhq06 the analyzers compared the raw value with a
# case-insensitive, whitespace-trimmed set membership test, which disagrees with
# the allow-list in three ways. Reproduced on the pinned interpreter
# (python:3.14 / pip-licenses 5.0.0), `python-licenses-api` fails with:
#
#   license UNKNOWN not in allow-only licenses was found for package
#   fastapi:0.137.1
#
# even though the allow-list carries `MIT`, and the dependency graph is
# unchanged: 32 of the 85 packages are reported, none of them for a reason a
# human can act on.
#
#   1. PEP 639. A modern wheel declares its licence only in the core metadata
#      `License-Expression` field (`License-Expression: MIT`) and carries no
#      `Classifier: License :: OSI Approved :: MIT License` and no legacy
#      `License:` field. pip-licenses 5.0.0 reads neither the former nor the
#      latter two (see its `METADATA_KEYS`), so it reports `UNKNOWN`.
#      Packages: fastapi, pydantic, Mako, MarkupSafe, anyio, ...
#   2. Compound expressions. SPDX allows `A AND B` / `A OR B` / `A WITH B`. The
#      allow-list contains atom identifiers, so the raw string never matches:
#      `aiohttp` reports `Apache-2.0 AND MIT`, which no entry spells out.
#   3. A fragment that needs normalisation before it can be compared, while
#      its neighbours make the whole string match anyway: the pair
#      `Apache Software License; MIT License` passes as a whole, which is
#      exactly what concealed this for as long as only pypi.org's
#      classifier-based metadata was in play.
#
# The projection is deliberately fail-closed: it is a two-valued judgement on a
# *complete* permission grant, so preserving AND/OR as a tree would be wrong --
# `MIT OR GPL-3.0-only` grants a choice and is therefore acceptable, while
# `MIT AND GPL-3.0-only` requires both and is not. Asking "is every alternative
# acceptable on its own" is the conservative reading of an OR, and it is the
# only reading that needs no licence-tree model here.
#
# Every substitution lives in this table and nowhere else, so the policy stays
# auditable: a PEP 639 declaration is authoritative metadata, while the legacy
# free-text `License` field is not, so `UNKNOWN` deliberately stays unknown and
# keeps failing closed.

# Compiler/toolchain exceptions that a free-text field appends to an otherwise
# already-allowed licence ("GPL-2.0 WITH Linux-syscall-note"). They add nothing
# to the permission grant, so they normalise away.
LICENSE_OPTION_SUFFIXES = (
    "linux-syscall-note",
    "llvm-exception",
)


def _strip_wrapping_parentheses(fragment: str) -> str:
    """Drop only the parentheses that wrap the whole fragment.

    `The Unlicense (Unlicense)` must survive intact -- the trailing parentheses
    belong to the licence's own name -- while `(MIT OR Apache-2.0)` must not
    leave a stray `(MIT`.
    """
    fragment = fragment.strip()
    while fragment.startswith("(") and fragment.endswith(")"):
        inner = fragment[1:-1]
        depth = 0
        balanced = True
        for character in inner:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth < 0:
                    balanced = False
                    break
        if depth > 0:
            balanced = False
        if not balanced:
            break
        fragment = inner.strip()
    return fragment


def _without_option_suffix(fragment: str) -> str:
    """`GPL-2.0 WITH Linux-syscall-note` is `GPL-2.0` plus an exception.

    `WITH` binds to its own operand, so it is not an operator of the grant and
    the exception adds nothing to the permission, which is why it normalises
    away instead of becoming an option of its own.
    """
    lowered = fragment.casefold()
    for suffix in LICENSE_OPTION_SUFFIXES:
        marker = f" with {suffix}"
        if lowered.endswith(marker):
            return fragment[: -len(marker)].strip()
    return fragment


def _canonical_option(fragment: str) -> str:
    """Reduce an operand to the option the allow-list is compared against."""
    return _without_option_suffix(_strip_wrapping_parentheses(fragment))


def _parenthesis_is_grouping(text: str, start: int) -> bool:
    """True when the `(` at `start` opens a license *expression* group.

    A license name can contain parentheses of its own -- `The Unlicense
    (Unlicense)`, `Mozilla Public License 2.0 (MPL 2.0)` -- so a `(` is only
    grouping when its content is itself an expression, i.e. it contains an
    `AND`/`OR` operator or a nested group. Otherwise the parentheses belong to
    the operand and are kept verbatim.
    """
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                content = text[start + 1 : index]
                return bool(re.search(r"\b(AND|OR)\b|\(", content, re.IGNORECASE))
        index += 1
    return False


def _tokenize_grant(text: str) -> list[str]:
    """Split a grant into parentheses, operators, and operand fragments.

    Grouping parentheses become their own tokens so the parser can see the tree
    an expression describes; parentheses that are part of a license name are
    kept inside their operand. `WITH` is folded into the operand on its left,
    not emitted as an operator, because it binds to that operand.
    """
    tokens: list[str] = []
    current: list[str] = []
    index = 0
    # Nesting depth of operand-internal parentheses, so a license name's own
    # `(...)` is copied through instead of being mistaken for a group close.
    operand_depth = 0
    # Only the uppercase SPDX operators are operators: a free-text license
    # name legitimately contains the English word ("GNU General Public License
    # v3 or later (GPLv3+)"), which must stay inside its operand.
    pattern = re.compile(r"\b(AND|OR)\b")
    while index < len(text):
        character = text[index]
        if character == "(":
            if operand_depth == 0 and _parenthesis_is_grouping(text, index):
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(character)
            else:
                operand_depth += 1
                current.append(character)
            index += 1
            continue
        if character == ")" and operand_depth > 0:
            operand_depth -= 1
            current.append(character)
            index += 1
            continue
        if character == ")":
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(character)
            index += 1
            continue
        match = pattern.match(text, index)
        if match is not None:
            if current:
                tokens.append("".join(current))
                current = []
            tokens.append(match.group(1).upper())
            index = match.end()
            continue
        current.append(character)
        index += 1
    if current:
        tokens.append("".join(current))
    return [token for token in tokens if token.strip()]


class _GrantParser:
    """Recursive-descent parser for an SPDX-style license grant.

    It parses ``A OR B``, ``A AND B``, ``(A OR B) AND C`` and nested groups,
    then distributes the tree into disjunctive normal form: a list of
    alternatives, each of which is the list of options that alternative
    requires. Distribution is what the allow-list needs -- a nested OR inside an
    AND grants a *choice of complete grants*, so collapsing it into a single
    unmatchable fragment would fail a package whose license the policy accepts.
    """

    def __init__(self, tokens: list[str]) -> None:
        self._tokens = tokens
        self._position = 0

    def _peek(self) -> str | None:
        return self._tokens[self._position] if self._position < len(self._tokens) else None

    def _next(self) -> str | None:
        token = self._peek()
        if token is not None:
            self._position += 1
        return token

    def parse(self) -> list[list[str]]:
        alternatives = self._parse_or()
        while self._peek() is not None:
            # Unconsumed input means the expression was malformed; the stray
            # tokens stay visible rather than being silently dropped.
            token = self._next()
            assert token is not None
            if token not in ("(", ")"):
                alternatives = self._and(alternatives, [[token]])
        return alternatives

    def _parse_or(self) -> list[list[str]]:
        alternatives = self._parse_and()
        while (self._peek() or "").upper() == "OR":
            self._next()
            alternatives = alternatives + self._parse_and()
        return alternatives

    def _parse_and(self) -> list[list[str]]:
        alternatives = self._parse_atom()
        while (self._peek() or "").upper() == "AND":
            self._next()
            alternatives = self._and(alternatives, self._parse_atom())
        return alternatives

    def _parse_atom(self) -> list[list[str]]:
        token = self._next()
        if token is None:
            return []
        if token == "(":
            inner = self._parse_or()
            if self._peek() == ")":
                self._next()
            return inner
        if token.upper() in ("AND", "OR"):
            return []
        canonical = _canonical_option(token)
        return [[canonical]] if canonical else []

    @staticmethod
    def _and(
        left: list[list[str]], right: list[list[str]]
    ) -> list[list[str]]:
        """Cartesian product: an AND requires every option of both sides."""
        if not left or not right:
            return left or right
        combined: list[list[str]] = []
        for left_option in left:
            for right_option in right:
                merged = list(left_option)
                for option in right_option:
                    if option.casefold() not in {
                        present.casefold() for present in merged
                    }:
                        merged.append(option)
                combined.append(merged)
        return combined


def _options_of(expression: str) -> list[str]:
    """Flat option list of a single AND-joined expression."""
    options: list[str] = []
    for alternative in _GrantParser(_tokenize_grant(expression)).parse():
        for option in alternative:
            if option.casefold() not in {present.casefold() for present in options}:
                options.append(option)
    return options


def license_grant_alternatives(value: Any) -> list[list[str]]:
    """Project a raw `License` value into its granted alternatives.

    The value is a *grant*, so the return type is a list of alternatives and
    each alternative is the list of options it requires:

      * `;` and `OR` produce alternatives -- any one of them is enough;
      * `AND` requires every option inside one alternative, distributed over any
        nested `OR`, so `MIT AND (Apache-2.0 OR BSD-3-Clause)` yields the two
        complete grants `MIT AND Apache-2.0` and `MIT AND BSD-3-Clause`;
      * `WITH` is not an operator of the grant at all.

    A flat option list would silently lose that structure and accept
    `MIT AND GPL-3.0-only` because `MIT` is allowed. `Apache-2.0 AND MIT`,
    `Apache-2.0;MIT` and `Apache-2.0; MIT License` all project to two
    single-option alternatives.
    """
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    # A modern analyzer can label the source (`License: MIT`); that prefix is
    # metadata formatting, not part of the license name, and would otherwise
    # never match an allow-list entry.
    if ":" in raw and raw.split(":", 1)[0].strip().isidentifier():
        raw = raw.split(":", 1)[1].strip()
    if not raw:
        return []
    alternatives: list[list[str]] = []
    # `;` is the historical separator for independent declarations; treat it as
    # a choice so a value that lists several options is not read as an AND.
    for declaration in raw.split(";"):
        tokens = _tokenize_grant(declaration)
        if not tokens:
            continue
        for alternative in _GrantParser(tokens).parse():
            if alternative and alternative not in alternatives:
                alternatives.append(alternative)
    return alternatives


def normalize_license_options(value: Any) -> list[str]:
    """Flat view of `license_grant_alternatives`, for reporting and assertions."""
    options: list[str] = []
    for alternative in license_grant_alternatives(value):
        for option in alternative:
            if option.casefold() not in {entry.casefold() for entry in options}:
                options.append(option)
    return options


#: Directive prefix for a per-package exception to the fail-closed rule.
_UNDECLARED_DIRECTIVE = "@allow-undeclared"


def _load_allowed_licenses(path: Path) -> set[str]:
    allowed: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if entry and not entry.startswith("#"):
            if entry.startswith(_UNDECLARED_DIRECTIVE):
                continue
            allowed.add(entry.casefold())
    return allowed


def _load_undeclared_fixups(path: Path) -> dict[str, str]:
    """Per-package `UNKNOWN` fixups declared in the allow-list file.

    `@allow-undeclared <name>=<license>` accepts *one* package that publishes no
    license metadata at all, and only with the license stated in the directive.
    It is deliberately narrow: it cannot whitelist a graph, and the license it
    names still has to be in the allow-list, so an exception is as reviewable as
    any other policy line.
    """
    fixups: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry.startswith(_UNDECLARED_DIRECTIVE):
            continue
        body = entry[len(_UNDECLARED_DIRECTIVE) :].strip()
        name, separator, license_value = body.partition("=")
        name = name.strip()
        license_value = license_value.strip()
        if not separator or not name or not license_value:
            raise ValueError(
                f"{path.name}: malformed {_UNDECLARED_DIRECTIVE} directive: {entry}"
            )
        fixups[name.casefold()] = license_value
    return fixups


# The column the allow-list is applied to when the probe has nothing to say.
# `pip-licenses --from=mixed` labels a PEP 639 `License-Expression` and falls
# back to the legacy `License` field, so this is the analyzer's own value.
LICENSE_FIELD = "License"


def _declared_license(
    entry: dict[str, Any],
    declared: dict[str, Any] | None = None,
) -> Any:
    """Read the declared licence out of one pip-licenses JSON row.

    The analyzer cannot be made to read a PEP 639 `License-Expression` through
    its allowed-only path, and the failure it produces is not detectable in its
    JSON output: a wheel that publishes `License-Expression: MIT` and nothing
    else yields the literal string `"UNKNOWN"`, indistinguishable from a package
    with no licence at all. So the probe's reading (`declared`) is the authority
    when it ran, and the analyzer's value is kept for a package the probe could
    not describe -- which keeps the projection fail-closed.
    """
    name = str(entry.get("Name", "")).strip().casefold()
    probed = (declared or {}).get(name)
    if isinstance(probed, dict):
        # The probe ran and described this distribution. Its `declared` value is
        # the authority -- including when it is empty, which means the wheel
        # publishes no machine-readable declaration at all. Falling back to the
        # analyzer's raw `License` field here would reintroduce exactly the
        # pasted licence TEXT the probe refused (scverse-misc), so an empty
        # reading becomes `UNKNOWN` and the gate fails closed.
        value = probed.get("declared")
        if value:
            return value
        raw_expression = probed.get("license_expression")
        # A probe from an older revision may not carry `declared`; its
        # `License-Expression` is still authoritative.
        return raw_expression or "UNKNOWN"
    value = entry.get(LICENSE_FIELD)
    if value is None:
        value = entry.get("License-Metadata")
    return value


def evaluate_license_report(
    report_path: Path,
    policy: dict[str, Any],
    declared: dict[str, Any] | None = None,
) -> tuple[bool, list[str]]:
    """Re-apply the allow-list to a `python-licenses-*` report, normalised.

    Returns `(passed, findings)`; `findings` is empty when the projection agrees
    with the analyzer's exit code.

    `declared` is the probed per-distribution metadata (see
    `_probe_declared_licenses`). The probe reads the declarations the analyzer
    cannot -- the PEP 639 `License-Expression` first of all -- so when it ran,
    that is what the allow-list is applied to. The report still decides which
    packages are in scope, and a package the probe could not describe keeps
    whatever the report says, so the projection stays fail-closed.
    """
    allow_path = ROOT / str(policy["allow_file"])
    allowed = _load_allowed_licenses(allow_path)
    fixups = _load_undeclared_fixups(allow_path)
    for fixup_name, fixup_license in fixups.items():
        for option in normalize_license_options(fixup_license):
            if option.casefold() not in allowed:
                raise ValueError(
                    f"{allow_path.name}: {_UNDECLARED_DIRECTIVE} {fixup_name} "
                    f"names {option!r}, which the allow-list does not carry"
                )
    entries = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise TypeError(f"{report_path.name}: expected a JSON list of packages")
    findings: list[str] = []
    for entry in entries:
        name = str(entry.get("Name", "<unnamed>"))
        version = str(entry.get("Version", "?"))
        license_value = _declared_license(entry, declared)
        # A fixup only ever replaces an `UNKNOWN` declaration, and only for the
        # package it names.
        if (
            str(license_value).strip().upper() == "UNKNOWN"
            and name.casefold() in fixups
        ):
            license_value = fixups[name.casefold()]
        alternatives = license_grant_alternatives(license_value)
        if not alternatives:
            findings.append(f"{name}:{version} declares no license")
            continue
        # The declaration is a grant: an OR is satisfied by ONE acceptable
        # alternative, while an AND needs EVERY option in its alternative.
        # `MIT OR GPL-3.0-only` grants a choice and is acceptable;
        # `MIT AND GPL-3.0-only` also requires the GPL and is not. A package is
        # only flagged when no alternative is acceptable in full.
        acceptable = [
            alternative
            for alternative in alternatives
            if all(option.casefold() in allowed for option in alternative)
        ]
        if not acceptable:
            offending = sorted(
                {option for alternative in alternatives for option in alternative}
            )
            findings.append(
                f"{name}:{version} is {'; '.join(offending)}"
            )
    return (not findings), findings




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
