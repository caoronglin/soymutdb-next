#!/usr/bin/env python3
"""Chart dependency closure budget gate (L2).

`scripts/webpack/chart-closure-plugin.cjs` runs inside the real Umi/webpack
compilation and writes one attribution manifest per built tree:
`.build/chart-closure/{web-external,web-internal,admin-default}.json`. This
script is the half that DECIDES. It never trusts the manifest for a number it
can measure itself:

- every JavaScript asset the compilation recorded is matched against the files
  actually on disk, in BOTH directions, by sha256;
- gzip is recomputed from the on-disk bytes and the charged total is summed
  from those measurements, not copied out of the manifest;
- a chunk that carries at least one non-platform closure module is charged at
  100% of its real gzip, with no proportional scaling by raw size and no
  per-package estimate.

Failure modes, all of them blocking:
  schema            the manifest is not the shape this gate was written for
  pathsafety        an absolute path (repo root, home, drive letter) leaked
  seedmissing       packages/charts/src/index.ts was not compiled into the build
  closureunassigned a closure module (or a concatenated inner module) owns no
                    chunk, so its cost cannot be charged
  unassignedengine  echarts / zrender / @antv / @ant-design/plots modules exist
                    in the build but are outside the chart closure
  budget            the complete chart closure exceeds 370 KiB (378880 B)

`lazy` / `initial` are reported as INFO only: this gate measures the COMPLETE
chart dependency cost, so a split between first paint and a later dynamic
chunk is a fact to print, not a new product budget.

Usage:
    python3 scripts/chart_closure_budget.py --dist apps/web/dist/external
    python3 scripts/chart_closure_budget.py --dist apps/admin/dist --json
    python3 scripts/chart_closure_budget.py --manifest <path> --dist <dir>
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / ".build" / "chart-closure"

SCHEMA_VERSION = 1
GENERATOR = "chart-closure-plugin"
SEED_RELATIVE_PATH = "packages/charts/src/index.ts"

# 370 KiB. Fixed by the product decision, not by any measurement, and not
# derived from the historical 317646 B probe anchor.
DEFAULT_BUDGET_BYTES = 378880

# One table so check-bundle-size.sh and verify-frontend-artifacts.sh reach the
# same manifest through the same code.
DIST_MANIFESTS: tuple[tuple[str, str], ...] = (
    ("apps/web/dist/external", "web-external"),
    ("apps/web/dist/internal", "web-internal"),
    ("apps/admin/dist", "admin-default"),
)

# JavaScript that a POST-BUILD script writes into dist, not webpack. sw.js
# comes from apps/web/scripts/gen-sw.js, which runs after max build. The list
# is closed on purpose: an unknown extra .js file fails the gate.
POST_BUILD_JS = ("sw.js",)

REQUIRED_TOP_LEVEL = (
    "schema_version",
    "generator",
    "app",
    "variant",
    "budget_bytes",
    "measurement_basis",
    "platform_exclusions",
    "engine_families",
    "asset_dirs",
    "seed",
    "closure",
    "concatenation",
    "excluded_platform",
    "engine_census",
    "assets",
    "chunks",
    "totals",
    "unassigned_closure_modules",
    "errors",
)
REQUIRED_CHUNK_KEYS = ("id", "files", "initial", "charged", "mixed", "raw_bytes")
REQUIRED_ASSET_KEYS = ("path", "raw_bytes", "sha256", "is_js")

ABSOLUTE_PREFIXES = ("/", "\\\\")
SUSPICIOUS_PATH_FRAGMENTS = ("/home/", "/Users/", "/mnt/", "/private/var/", "/var/folders/")


@dataclass
class Check:
    """One gate outcome. `name` is the stable identifier CI greps for."""

    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str) -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    def note(self, line: str) -> None:
        self.info.append(line)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if not check.ok]


def gzip_size(data: bytes) -> int:
    """Actual gzip -9 size of these bytes, recomputed by the gate itself."""
    return len(gzip.compress(data, compresslevel=9, mtime=0))


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_manifest(dist: Path, explicit: Path | None) -> Path:
    """Map a built tree to its manifest name through the shared table."""
    if explicit is not None:
        return explicit
    try:
        relative = dist.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        relative = dist.as_posix()
    for prefix, name in DIST_MANIFESTS:
        if relative == prefix or relative.startswith(prefix + "/"):
            return MANIFEST_DIR / (name + ".json")
    known = ", ".join(prefix for prefix, _ in DIST_MANIFESTS)
    raise SystemExit(
        f"chart closure gate: cannot map dist tree {relative!r} to a manifest. "
        f"Known trees: {known}. Pass --manifest explicitly for a one-off layout."
    )


def enumerate_js(dist: Path, subdirectories: Iterable[str]) -> set[str]:
    """dist-relative posix paths of every .js file under the given subtrees."""
    roots = [dist / sub for sub in subdirectories] if list(subdirectories) else [dist]
    found: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.js"):
            if path.is_file():
                found.add(path.relative_to(dist).as_posix())
    return found


def looks_absolute(value: str) -> bool:
    if not value:
        return False
    if value.startswith(ABSOLUTE_PREFIXES):
        return True
    if len(value) >= 3 and value[1] == ":" and value[2] in "\\/":
        return True
    return False


def walk_strings(node: Any) -> Iterable[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from walk_strings(key)
            yield from walk_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk_strings(value)


def check_schema(manifest: dict[str, Any], report: Report) -> None:
    missing = [key for key in REQUIRED_TOP_LEVEL if key not in manifest]
    if missing:
        report.add("schema", False, "missing top-level key(s): " + ", ".join(missing))
        return
    if manifest.get("schema_version") != SCHEMA_VERSION:
        report.add(
            "schema",
            False,
            f"schema_version {manifest.get('schema_version')!r} != {SCHEMA_VERSION}",
        )
        return
    if manifest.get("generator") != GENERATOR:
        report.add("schema", False, f"generator {manifest.get('generator')!r} is not {GENERATOR!r}")
        return

    basis = manifest.get("measurement_basis")
    problems: list[str] = []
    if not isinstance(basis, dict):
        problems.append("measurement_basis must be an object")
    else:
        if basis.get("seed") != SEED_RELATIVE_PATH:
            problems.append(f"measurement_basis.seed is {basis.get('seed')!r}")
        for flag in ("proportional_scaling", "estimation", "self_attested_completeness"):
            if basis.get(flag) is not False:
                problems.append(f"measurement_basis.{flag} must be false, got {basis.get(flag)!r}")
        if basis.get("charge_rule") != "whole-js-chunk-actual-gzip":
            problems.append(f"measurement_basis.charge_rule is {basis.get('charge_rule')!r}")
    if not isinstance(manifest.get("assets"), list):
        problems.append("assets must be a list")
    if not isinstance(manifest.get("chunks"), list):
        problems.append("chunks must be a list")
    for chunk in manifest.get("chunks") or []:
        if not isinstance(chunk, dict) or any(key not in chunk for key in REQUIRED_CHUNK_KEYS):
            problems.append(f"chunk entry is missing {REQUIRED_CHUNK_KEYS}: {chunk!r}")
            break
    for asset in manifest.get("assets") or []:
        if not isinstance(asset, dict) or any(key not in asset for key in REQUIRED_ASSET_KEYS):
            problems.append(f"asset entry is missing {REQUIRED_ASSET_KEYS}: {asset!r}")
            break
    if problems:
        report.add("schema", False, "; ".join(problems))
    else:
        report.add(
            "schema",
            True,
            f"schema_version {SCHEMA_VERSION}, {len(manifest['chunks'])} chunk record(s), "
            f"{len(manifest['assets'])} asset record(s)",
        )


def check_pathsafety(manifest: dict[str, Any], report: Report) -> None:
    repo_root = ROOT.as_posix()
    try:
        home = Path.home().as_posix()
    except (RuntimeError, OSError):
        home = ""
    offenders: list[str] = []
    for value in walk_strings(manifest):
        if looks_absolute(value):
            offenders.append("absolute: " + repr(value[:80]))
            continue
        if repo_root in value or (len(home) > 1 and home in value):
            offenders.append("leaked root: " + repr(value[:80]))
            continue
        if any(fragment in value for fragment in SUSPICIOUS_PATH_FRAGMENTS):
            offenders.append("machine path: " + repr(value[:80]))
            continue
        if ".." in value.split("/"):
            offenders.append("parent traversal: " + repr(value[:80]))
    unique = sorted(set(offenders))
    if unique:
        report.add("pathsafety", False, "; ".join(unique[:5]))
    else:
        report.add("pathsafety", True, "every recorded path is repo-relative")


def check_seed(manifest: dict[str, Any], report: Report) -> None:
    seed = manifest.get("seed") or {}
    count = seed.get("match_count")
    relative = seed.get("relative_path")
    if relative != SEED_RELATIVE_PATH:
        report.add(
            "seedmissing", False, f"seed.relative_path {relative!r} != {SEED_RELATIVE_PATH!r}"
        )
        return
    if not isinstance(count, int) or count < 1:
        report.add(
            "seedmissing",
            False,
            f"{SEED_RELATIVE_PATH} was not compiled into this build (match_count={count!r}); "
            "the seed must be the module webpack really built, never a file on disk",
        )
        return
    report.add("seedmissing", True, f"{SEED_RELATIVE_PATH} compiled once ({count} match(es))")


def check_closure_assigned(manifest: dict[str, Any], report: Report) -> None:
    unassigned = manifest.get("unassigned_closure_modules") or []
    closure = manifest.get("closure") or {}
    modules = closure.get("modules") or []
    if not modules:
        report.add(
            "closureunassigned",
            False,
            "the closure is empty; nothing would be charged, which is never a pass",
        )
        return
    unattributed = [entry for entry in modules if not entry.get("chunks")]
    if unassigned or unattributed:
        sample = (unassigned or [entry.get("resource") for entry in unattributed])[:5]
        report.add(
            "closureunassigned",
            False,
            f"{len(unassigned) + len(unattributed)} closure module(s) own no chunk: {sample}",
        )
        return
    report.add(
        "closureunassigned",
        True,
        f"all {len(modules)} closure module(s) map to at least one emitted chunk",
    )


def check_engine_census(manifest: dict[str, Any], report: Report) -> None:
    census = manifest.get("engine_census") or {}
    unassigned = census.get("unassigned") or []
    total = census.get("module_count")
    in_closure = census.get("closure_module_count")
    if unassigned:
        packages = sorted({entry.get("package") for entry in unassigned if entry.get("package")})
        sample = [entry.get("resource") for entry in unassigned[:5]]
        report.add(
            "unassignedengine",
            False,
            f"{len(unassigned)} engine module(s) outside the closure ["
            + ", ".join(packages)
            + f"]; first: {sample}",
        )
        return
    if not isinstance(total, int) or total < 1:
        report.add(
            "unassignedengine",
            False,
            "the engine census found no echarts / zrender / @antv / @ant-design/plots "
            + "module at all; a build with no chart engine cannot satisfy a chart budget gate",
        )
        return
    report.add(
        "unassignedengine",
        True,
        f"{total} engine module(s) present, {in_closure} attributed to the closure",
    )


@dataclass
class MeasuredAssets:
    gzip: dict[str, int] = field(default_factory=dict)
    raw: dict[str, int] = field(default_factory=dict)


def measure_dist(manifest: dict[str, Any], dist: Path, report: Report) -> MeasuredAssets | None:
    """Enumerate the JS on disk, match it both ways, hash it, gzip it."""
    assets = manifest.get("assets") or []
    asset_dirs = manifest.get("asset_dirs") or []
    manifest_js = {
        entry["path"] for entry in assets if isinstance(entry, dict) and entry.get("is_js")
    }

    if not dist.is_dir():
        report.add("assets", False, f"dist tree does not exist: {dist}")
        return None

    disk_js = enumerate_js(dist, [])
    disk_js -= {path for path in POST_BUILD_JS if path not in manifest_js}
    if not disk_js:
        report.add(
            "assets",
            False,
            f"no .js file under {dist} within the manifest scope {asset_dirs or ["."]}",
        )
        return None

    missing_on_disk = sorted(manifest_js - disk_js)
    unknown_on_disk = sorted(disk_js - manifest_js)
    if missing_on_disk or unknown_on_disk:
        report.add(
            "assets",
            False,
            f"JS set mismatch. manifest-only ({len(missing_on_disk)}): {missing_on_disk[:5]}. "
            + f"disk-only ({len(unknown_on_disk)}): {unknown_on_disk[:5]}",
        )
        return None

    every_disk_js = enumerate_js(dist, [])
    out_of_scope = sorted(every_disk_js - manifest_js)
    unexpected = [entry for entry in out_of_scope if Path(entry).name not in POST_BUILD_JS]
    if unexpected:
        report.add(
            "assets",
            False,
            f"JavaScript in dist that webpack never emitted: {unexpected[:5]}",
        )
        return None

    measured = MeasuredAssets()
    mismatch: list[str] = []
    for entry in assets:
        if not isinstance(entry, dict) or not entry.get("is_js"):
            continue
        data = (dist / entry["path"]).read_bytes()
        if sha256_hex(data) != entry.get("sha256"):
            mismatch.append(entry["path"])
            continue
        measured.gzip[entry["path"]] = gzip_size(data)
        measured.raw[entry["path"]] = len(data)
    if mismatch:
        report.add(
            "assets", False, "sha256 mismatch (tampered or rebuilt asset): " + repr(mismatch[:5])
        )
        return None
    report.note(f"assets: {len(measured.gzip)} JS asset(s) verified by sha256, gzipped from disk")
    if out_of_scope:
        report.note(f"assets: post-build JavaScript outside webpack output: {out_of_scope}")
    report.add(
        "assets",
        True,
        f"{len(measured.gzip)} JS asset(s) match the manifest in both directions and by sha256",
    )
    return measured


def check_charge(
    manifest: dict[str, Any], measured: MeasuredAssets, budget: int, report: Report
) -> None:
    chunks = manifest.get("chunks") or []
    charged = [chunk for chunk in chunks if chunk.get("charged")]
    charged_gzip = 0
    charged_raw = 0
    missing: list[str] = []
    for chunk in charged:
        for name in chunk.get("files") or []:
            if name not in measured.gzip:
                missing.append(name)
                continue
            charged_gzip += measured.gzip[name]
            charged_raw += measured.raw[name]
    if missing:
        report.add(
            "assets", False, "charged chunk(s) reference unknown asset(s): " + repr(missing[:5])
        )
        return

    declared_raw = (manifest.get("totals") or {}).get("charged_raw_bytes")
    if isinstance(declared_raw, int) and declared_raw != charged_raw:
        report.add(
            "totals",
            False,
            f"manifest claims {declared_raw} charged raw bytes, the built tree holds {charged_raw}",
        )
    else:
        report.add("totals", True, f"charged raw bytes agree with the built tree: {charged_raw}")

    mixed = [chunk for chunk in charged if chunk.get("mixed")]
    initial = [chunk for chunk in charged if chunk.get("initial")]
    lazy = [chunk for chunk in charged if not chunk.get("initial")]

    def gzip_of(entries: list[dict[str, Any]]) -> int:
        return sum(measured.gzip[name] for chunk in entries for name in (chunk.get("files") or []))

    mixed_ids = ", ".join(str(chunk.get("id")) for chunk in mixed) or "none"
    report.note(
        f"INFO  initial chunks carry {gzip_of(initial)} B gzip, "
        + f"lazy chunks carry {gzip_of(lazy)} B gzip (INFO only, no lazy budget gate)",
    )
    report.note(
        f"INFO  {len(mixed)} mixed chunk(s) charged whole: "
        + f"{gzip_of(mixed)} B gzip ({mixed_ids})"
    )
    report.note(f"INFO  {len(charged)} of {len(chunks)} chunk(s) charged, whole-chunk actual gzip")

    declared_budget = manifest.get("budget_bytes")
    if declared_budget != budget:
        report.add(
            "budget",
            False,
            f"manifest budget {declared_budget!r} != gate budget {budget}; "
            + "a manifest may not carry its own cap",
        )
        return
    over = charged_gzip - budget
    if over > 0:
        report.add(
            "budget",
            False,
            f"complete chart closure {charged_gzip} B exceeds {budget} B "
            + f"({budget // 1024} KiB) by {over} B",
        )
    else:
        report.add(
            "budget",
            True,
            f"complete chart closure {charged_gzip} B <= {budget} B ({budget // 1024} KiB), "
            + f"headroom {budget - charged_gzip} B",
        )


def run(manifest_path: Path, dist: Path, budget: int) -> Report:
    report = Report()
    if not manifest_path.is_file():
        report.add(
            "manifest",
            False,
            f"chart closure manifest not found: {manifest_path}. It is written by "
            + "scripts/webpack/chart-closure-plugin.cjs during the app build; "
            + "build the tree before running this gate.",
        )
        return report
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        report.add("manifest", False, f"manifest is not valid JSON: {error}")
        return report
    if not isinstance(manifest, dict):
        report.add("manifest", False, "manifest root must be a JSON object")
        return report

    closure = manifest.get("closure") or {}
    concatenation = manifest.get("concatenation") or {}
    basis = manifest.get("measurement_basis") or {}
    report.note(
        f"app={manifest.get('app')} variant={manifest.get('variant')} "
        + f"closure={len(closure.get('modules') or [])} module(s) "
        + f"concatenation={concatenation.get('concatenated_module_count')} outer / "
        + f"{concatenation.get('inner_modules_in_closure')} inner in closure",
    )
    report.note(f"basis: {basis.get('statement', '')}")

    check_schema(manifest, report)
    check_pathsafety(manifest, report)
    check_seed(manifest, report)
    check_closure_assigned(manifest, report)
    check_engine_census(manifest, report)
    measured = measure_dist(manifest, dist, report)
    if measured is not None:
        check_charge(manifest, measured, budget, report)

    handled = {"seedmissing", "closureunassigned", "unassignedengine"}
    for error in manifest.get("errors") or []:
        name = error.get("check") if isinstance(error, dict) else "error"
        detail = str(error.get("detail") if isinstance(error, dict) else error)
        if name in handled:
            # Already surfaced by the dedicated check above, with fuller context.
            continue
        report.add(f"plugin:{name}", False, detail)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chart dependency closure budget gate")
    parser.add_argument("--dist", type=Path, required=True, help="built tree to measure")
    parser.add_argument("--manifest", type=Path, default=None, help="override the manifest path")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_BYTES)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    manifest_path = resolve_manifest(args.dist, args.manifest)
    report = run(manifest_path, args.dist, args.budget)

    if args.as_json:
        print(json.dumps({
            "manifest": manifest_path.as_posix(),
            "dist": args.dist.as_posix(),
            "budget_bytes": args.budget,
            "info": report.info,
            "checks": [vars(check) for check in report.checks],
            "failed": [check.name for check in report.failed],
        }, indent=2))
    else:
        print(f"chart closure gate  manifest={manifest_path}  dist={args.dist}")
        for line in report.info:
            print("  " + line)
        width = max((len(check.name) for check in report.checks), default=8)
        for check in report.checks:
            label = "PASS" if check.ok else "FAIL"
            print(f"  {label:<4}  {check.name:<{width}}  {check.detail}")
        if report.failed:
            names = ", ".join(sorted({check.name for check in report.failed}))
            print(f"chart closure gate: FAILED - {names}", file=sys.stderr)
        else:
            print("chart closure gate: OK")
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
