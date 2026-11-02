#!/usr/bin/env python3
"""Regression coverage for the chart dependency closure gate (L1 + L2).

Two halves, because the gate has two halves:

- `ChartClosurePluginTests` drives `scripts/webpack/chart-closure-plugin.cjs`
  against a SYNTHETIC webpack graph (fake moduleGraph / chunkGraph / assets)
  through a node harness. No real build is needed, and none is permitted here:
  the real integration build belongs to a single owner after this change lands.
- `ChartClosureGateTests` drives `scripts/chart_closure_budget.py` over those
  manifests, each materialised as a real dist tree on a temp directory so gzip,
  sha256 and bidirectional enumeration run against actual bytes.

Run:  python3 -m unittest scripts.test_chart_closure_budget -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "scripts" / "webpack" / "chart-closure-plugin.cjs"
sys.path.insert(0, str(ROOT))

from scripts import chart_closure_budget as gate  # noqa: E402


# ---------------------------------------------------------------------------
# node harness: builds a synthetic compilation and writes a real manifest
# ---------------------------------------------------------------------------

HARNESS = r"""
const fs = require('node:fs');
const path = require('node:path');

const plugin = require(process.env.CC_PLUGIN);

const [repoRoot, distDir, outPath, scenario] = process.argv.slice(2);

const STORE = "node_modules/.pnpm";
function pkgPath(name, version, rel) {
  const flat = name.replace("/", "+");
  return STORE + "/" + flat + "@" + version + "/node_modules/" + name + "/" + rel;
}

const modules = new Map();
function makeModule(relPath) {
  if (modules.has(relPath)) return modules.get(relPath);
  const mod = { resource: path.join(repoRoot, relPath), rel: relPath, deps: [] };
  modules.set(relPath, mod);
  return mod;
}
function connect(from, to, type) {
  const kind = type || "harmony import";
  // Shape verified against real webpack 5.110.3: ModuleGraphConnection carries
  // `dependency` (which owns the type) and has NO `dependencyType` property.
  from.deps.push({ module: to, dependencyType: kind, dependency: { type: kind, category: "esm" } });
}
function makeConcatenated(relPath, innerModules) {
  const outer = makeModule(relPath);
  outer.modules = innerModules;
  return outer;
}

const SEED = "packages/charts/src/index.ts";

// "no_seed" builds a tree where the chart entry is never compiled, which is
// exactly the case the gate must refuse to paper over.
const seed = scenario === "no_seed" ? null : makeModule(SEED);
const theme = makeModule("packages/charts/src/theme.ts");
const color = makeModule("packages/charts/src/color.ts");
const glue = makeModule("apps/web/src/pages/home.tsx");
const react = makeModule(pkgPath("react", "19.3.0", "index.js"));
const scheduler = makeModule(pkgPath("scheduler", "0.27.0", "index.js"));
const antvA = makeModule(pkgPath("@antv/g2", "5.4.8", "esm/core.js"));
const antvB = makeModule(pkgPath("@antv/g2", "5.4.8", "esm/runtime.js"));
const dynamic = makeModule(pkgPath("@antv/g", "6.3.1", "lib/dynamic.js"));
// Only a tree that really pulls ECharts in has ECharts modules. Creating them
// unconditionally would put phantom engine modules in every scenario.
const legacyEngine = scenario === "unassigned_engine";
const echarts = legacyEngine ? makeModule(pkgPath("echarts", "5.5.1", "lib/echarts.js")) : null;
const zrender = legacyEngine ? makeModule(pkgPath("zrender", "5.5.1", "lib/zrender.js")) : null;

// The facade imports the platform and one tree-shaken concatenated bundle.
if (seed) connect(seed, theme, "harmony import");
if (seed) connect(seed, color, "harmony import");
connect(theme, react, "harmony import");

let concat = null;
if (!seed) {
  concat = null;
} else if (scenario === "no_concat") {
  connect(seed, antvA, "harmony import");
  connect(antvA, antvB, "harmony import");
} else {
  concat = makeConcatenated("packages/charts/src/ChartCanvas.tsx", [
    antvA, antvB, react, scheduler,
  ]);
  connect(seed, concat, "harmony import");
}

// A dynamic import() edge: the module lands in a separate async chunk and must
// still be inside the closure, or lazy engine cost would be invisible.
connect(theme, dynamic, "import()");

// Upstream route glue: app code that renders a chart. It is NOT part of the
// seed, so it is never charged, but it is present in the compilation.
if (seed) connect(glue, seed, "harmony import");

if (scenario === "unassigned_engine") {
  // App glue imports ECharts directly, so those modules are in the build but
  // outside the charts facade closure: the honest red state mid-migration.
  connect(glue, echarts, "harmony import");
  connect(echarts, zrender, "harmony import");
}

const PAYLOAD = {
  main: "self.__SOYMUTDB_MAIN__=1;" + "const route=()=>1;".repeat(400),
  charts: "self.__SOYMUTDB_CHARTS__=1;" + "const draw=()=>2;".repeat(900),
  vendor: "self.__SOYMUTDB_VENDOR__=1;" + "const dep=()=>3;".repeat(300),
};

function writeAsset(name, text) {
  const target = path.join(distDir, name);
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const buffer = Buffer.from(text, "utf8");
  fs.writeFileSync(target, buffer);
  return { name: name, raw_bytes: buffer.length, sha256: plugin.sha256Hex(buffer) };
}

const assets = [
  writeAsset("index.html", "<!doctype html><html><head></head><body></body></html>"),
  writeAsset("assets/main.11111111.js", PAYLOAD.main),
  writeAsset("assets/charts.22222222.js", PAYLOAD.charts),
  writeAsset("assets/vendor.33333333.js", PAYLOAD.vendor),
];

function makeChunk(name, file, chunkModules, initial) {
  return {
    id: name,
    name: name,
    files: new Set([file]),
    canBeInitial: () => Boolean(initial),
    members: chunkModules,
  };
}

// main carries closure AND route glue AND platform: a mixed chunk, charged whole.
// charts is a pure closure chunk; vendor exists only because of the dynamic edge.
const closureMembers = concat ? [concat] : [antvA, antvB];
const baseMain = scenario === "orphan_closure" || !seed
  ? [glue, react]
  : [glue, seed, theme, color].concat(closureMembers, [react]);
const mainMembers = baseMain.concat(legacyEngine ? [echarts, zrender] : []);

const chunks = [
  makeChunk("main", "assets/main.11111111.js", mainMembers, true),
  makeChunk("charts", "assets/charts.22222222.js", [theme, color].concat(closureMembers), false),
  makeChunk("vendor", "assets/vendor.33333333.js", [dynamic], false),
];

if (scenario === "copied_sw" || scenario === "compiled_sw") {
  assets.push(writeAsset("sw.js", "// copied service worker template"));
  if (scenario === "compiled_sw") chunks[0].files.add("sw.js");
}

const byModule = new Map();
for (const chunk of chunks) {
  for (const member of chunk.members) {
    if (!byModule.has(member)) byModule.set(member, []);
    byModule.get(member).push(chunk);
  }
}

const moduleGraph = {
  getOutgoingConnections(mod) {
    return mod.deps || [];
  },
};
const chunkGraph = {
  getChunkModulesIterable(chunk) {
    const members = chunk.members.slice();
    for (const member of chunk.members) {
      if (Array.isArray(member.modules)) members.push.apply(members, member.modules);
    }
    return members;
  },
  getModuleChunksIterable(mod) {
    return byModule.get(mod) || [];
  },
};

const manifest = plugin.buildManifest({
  app: "web",
  variant: "external",
  compilerName: "client",
  repoRoot: repoRoot,
  seedRelativePath: plugin.SEED_RELATIVE_PATH,
  modules: Array.from(modules.values()),
  moduleGraph: moduleGraph,
  chunkGraph: chunkGraph,
  chunks: chunks,
  assets: assets,
  assetIndex: new Map(assets.map((entry) => [entry.name, entry])),
});

fs.mkdirSync(path.dirname(outPath), { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(manifest, null, 2));
process.stdout.write("ok");
"""


def _run_harness(scenario_name: str, workdir: Path) -> tuple[dict, Path]:
    """Run the node harness once for one scenario."""
    if shutil.which("node") is None:
        raise RuntimeError("node is required to exercise the webpack plugin")
    repo_root = workdir / "repo"
    dist_dir = workdir / "dist"
    out_path = workdir / "manifest.json"
    repo_root.mkdir(parents=True, exist_ok=True)
    harness = workdir / "harness.cjs"
    harness.write_text(HARNESS, encoding="utf-8")
    result = subprocess.run(
        ["node", str(harness), str(repo_root), str(dist_dir), str(out_path), scenario_name],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "CC_PLUGIN": str(PLUGIN), "HOME": "/tmp"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"harness failed for {scenario_name}: {result.stderr}")
    return json.loads(out_path.read_text(encoding="utf-8")), dist_dir


_SCENARIOS: dict[str, dict] = {}
_STAGED: dict[str, Path] = {}
_TMP = tempfile.TemporaryDirectory(prefix="cc-harness-")


def scenario(name: str) -> dict:
    """Materialise one scenario manifest + dist tree, once per process."""
    if name not in _SCENARIOS:
        manifest, dist = _run_harness(name, Path(_TMP.name) / name)
        staged = Path(tempfile.mkdtemp(prefix=f"cc-{name}-"))
        shutil.copytree(dist, staged / "dist")
        _SCENARIOS[name] = manifest
        _STAGED[name] = staged
    return json.loads(json.dumps(_SCENARIOS[name]))


def staged_dist(name: str) -> Path:
    scenario(name)
    return _STAGED[name] / "dist"


def error_codes(manifest: dict) -> set:
    return {entry.get("check") for entry in manifest.get("errors", [])}


def closure_resources(manifest: dict) -> set:
    return {entry["resource"] for entry in manifest["closure"]["modules"]}


# ---------------------------------------------------------------------------
# wiring harness: the plugin must identify its own app and site variant from
# the compiler Umi hands it, without any config-time argument.
# ---------------------------------------------------------------------------

WIRING = r"""
const plugin = require(process.env.CC_PLUGIN);
const fs = require("node:fs");
const path = require("node:path");
const [mode, context, outputPath, variant, decorate] = process.argv.slice(2);

// Materialise the app directories so the plugin own-directory guard has
// something real to recognise.
function ensureApp(dir) {
  fs.mkdirSync(dir, { recursive: true });
  if (!fs.existsSync(path.join(dir, "package.json"))) {
    fs.writeFileSync(path.join(dir, "package.json"), "{}\n");
  }
}
if (decorate === "all") {
  if (context) ensureApp(context);
  let dir = outputPath;
  while (dir && path.basename(dir) !== "apps") {
    ensureApp(dir);
    dir = path.dirname(dir);
  }
}

if (variant) process.env.VITE_SITE_VARIANT = variant;
const compiler = {
  name: "client",
  context: context,
  options: {
    context: mode === "none" ? undefined : context,
    output: { path: outputPath },
  },
};
try {
  const target = plugin.resolveTarget(compiler);
  process.stdout.write(JSON.stringify(target));
} catch (error) {
  process.stdout.write(JSON.stringify({ error: error.message }));
}
"""


def wiring(
    context: str,
    output_path: str,
    variant: str | None,
    mode: str = "set",
    decorate: str = "all",
) -> dict:
    if shutil.which("node") is None:
        raise RuntimeError("node is required to exercise the webpack plugin")
    with tempfile.TemporaryDirectory() as raw:
        base = Path(raw) / "checkout" / "code"
        script = Path(raw) / "wiring.cjs"
        script.write_text(WIRING, encoding="utf-8")
        result = subprocess.run(
            [
                "node",
                str(script),
                mode,
                context.replace("{BASE}", str(base)),
                output_path.replace("{BASE}", str(base)),
                variant or "",
                decorate,
            ],
            env={"PATH": "/usr/bin:/bin:/usr/local/bin", "CC_PLUGIN": str(PLUGIN), "HOME": "/tmp"},
            capture_output=True,
            text=True,
        )
    return json.loads(result.stdout)


class ChartClosurePluginTests(unittest.TestCase):
    """L1: the real module-graph walk, driven by a synthetic webpack graph."""

    def test_forward_closure_follows_static_imports(self) -> None:
        resources = closure_resources(scenario("passing"))
        self.assertIn("packages/charts/src/index.ts", resources)
        self.assertIn("packages/charts/src/theme.ts", resources)
        self.assertIn("packages/charts/src/color.ts", resources)

    def test_dynamic_import_edge_is_traversed(self) -> None:
        manifest = scenario("passing")
        self.assertIn(
            "node_modules/.pnpm/@antv+g@6.3.1/node_modules/@antv/g/lib/dynamic.js",
            closure_resources(manifest),
        )
        self.assertGreaterEqual(manifest["closure"]["dynamic_edge_count"], 1)
        self.assertIn("import()", manifest["closure"]["edge_types"])

    def test_concatenated_inner_modules_join_the_closure(self) -> None:
        manifest = scenario("passing")
        self.assertIn(
            "node_modules/.pnpm/@antv+g2@5.4.8/node_modules/@antv/g2/esm/core.js",
            closure_resources(manifest),
        )
        concatenation = manifest["concatenation"]
        self.assertEqual(concatenation["concatenated_module_count"], 1)
        self.assertTrue(concatenation["tree_shaking_observed"])
        self.assertEqual(concatenation["inner_modules_unattributed"], 0)

    def test_absent_concatenation_still_attributes_everything(self) -> None:
        manifest = scenario("no_concat")
        self.assertFalse(manifest["concatenation"]["tree_shaking_observed"])
        self.assertIn(
            "node_modules/.pnpm/@antv+g2@5.4.8/node_modules/@antv/g2/esm/core.js",
            closure_resources(manifest),
        )
        self.assertEqual(manifest["engine_census"]["unassigned_count"], 0)

    def test_platform_packages_are_excluded_from_the_closure(self) -> None:
        manifest = scenario("passing")
        for resource in closure_resources(manifest):
            self.assertNotIn("/react@", resource)
            self.assertNotIn("/scheduler@", resource)
        self.assertEqual(manifest["platform_exclusions"], ["react", "react-dom", "scheduler"])
        self.assertGreater(manifest["excluded_platform"]["module_count"], 0)

    def test_mixed_chunk_is_flagged_and_charged_whole(self) -> None:
        manifest = scenario("passing")
        mixed = [chunk for chunk in manifest["chunks"] if chunk["mixed"]]
        self.assertTrue(mixed, "the main chunk carries closure plus route glue")
        self.assertTrue(all(chunk["charged"] for chunk in mixed))
        main = next(chunk for chunk in manifest["chunks"] if chunk["id"] == "main")
        self.assertGreater(main["foreign_module_count"], 0)
        self.assertEqual(manifest["totals"]["mixed_chunk_count"], len(mixed))

    def test_upstream_route_glue_is_not_in_the_closure(self) -> None:
        manifest = scenario("passing")
        self.assertNotIn("apps/web/src/pages/home.tsx", closure_resources(manifest))
        self.assertFalse(manifest["measurement_basis"]["counts_upstream_route_glue"])

    def test_engine_module_outside_the_closure_is_unassigned(self) -> None:
        manifest = scenario("unassigned_engine")
        self.assertEqual(manifest["engine_census"]["unassigned_count"], 2)
        packages = {entry["package"] for entry in manifest["engine_census"]["unassigned"]}
        self.assertEqual(packages, {"echarts", "zrender"})
        self.assertIn("unassignedengine", error_codes(manifest))

    def test_closure_module_without_a_chunk_is_reported(self) -> None:
        self.assertIn("closureunassigned", error_codes(scenario("orphan_closure")))

    def test_seed_missing_is_recorded_not_guessed(self) -> None:
        manifest = scenario("no_seed")
        self.assertEqual(manifest["seed"]["match_count"], 0)
        self.assertIn("seedmissing", error_codes(manifest))

    def test_manifest_records_no_absolute_path(self) -> None:
        report = gate.Report()
        gate.check_pathsafety(scenario("passing"), report)
        self.assertEqual(report.failed, [], report.failed[0].detail if report.failed else "")

    def test_budget_is_the_fixed_product_value(self) -> None:
        self.assertEqual(gate.DEFAULT_BUDGET_BYTES, 378880)
        self.assertEqual(scenario("passing")["budget_bytes"], 378880)


class ChartClosureWiringTests(unittest.TestCase):
    """The Umi registration must resolve to the three required manifest names."""

    def test_portal_external_is_the_default(self) -> None:
        target = wiring("{BASE}/apps/web", "{BASE}/apps/web/dist/external", None)
        self.assertEqual(
            target,
            {"app": "web", "variant": "external", "manifestName": "web-external"},
        )

    def test_portal_internal_follows_the_site_variant(self) -> None:
        target = wiring("{BASE}/apps/web", "{BASE}/apps/web/dist/internal", "internal")
        self.assertEqual(target["manifestName"], "web-internal")

    def test_admin_uses_the_default_variant(self) -> None:
        target = wiring("{BASE}/apps/admin", "{BASE}/apps/admin/dist", "external")
        self.assertEqual(
            target,
            {"app": "admin", "variant": "default", "manifestName": "admin-default"},
        )

    def test_output_path_rescues_a_missing_context(self) -> None:
        # mode="none" drops options.context, leaving compiler.context wrong too.
        target = wiring(
            "{BASE}/elsewhere", "{BASE}/apps/web/dist/external", "external", mode="none"
        )
        self.assertEqual(target["manifestName"], "web-external")

    def test_unknown_app_fails_loudly(self) -> None:
        target = wiring("{BASE}/apps/jbrowse", "{BASE}/apps/jbrowse/dist", None)
        self.assertIn("error", target)

    def test_a_directory_named_web_that_is_not_an_app_is_rejected(self) -> None:
        # The repository itself lives at .../code/web. A bare basename match
        # would write the portal manifest from the wrong tree, so the plugin
        # requires a real package.json as well as the right basename.
        target = wiring(
            "{BASE}/code/web",
            "{BASE}/unrelated/dist",
            None,
            mode="none",
            decorate="none",
        )
        self.assertIn("error", target)


class ChartClosureGateTests(unittest.TestCase):
    """L2: the checker, over real bytes on disk."""

    def _stage(self, tmp: Path, scenario_name: str, manifest: dict) -> tuple[Path, Path]:
        shutil.copytree(staged_dist(scenario_name), tmp / "dist")
        manifest_file = tmp / "manifest.json"
        manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_file, tmp / "dist"

    def _run(self, tmp: Path, scenario_name: str, manifest: dict, budget: int | None = None):
        manifest_file, dist = self._stage(tmp, scenario_name, manifest)
        return gate.run(
            manifest_file, dist, gate.DEFAULT_BUDGET_BYTES if budget is None else budget
        )

    def _failing(self, scenario_name: str, manifest: dict, check: str, budget: int | None = None):
        with tempfile.TemporaryDirectory() as raw:
            report = self._run(Path(raw), scenario_name, manifest, budget)
            self.assertIn(check, {entry.name for entry in report.failed})

    def test_clean_build_passes_every_check(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            report = self._run(Path(raw), "passing", manifest)
            self.assertEqual(
                [check.detail for check in report.failed], [],
                )
            names = {check.name for check in report.checks}
            self.assertLessEqual(
                {
                    "schema",
                    "pathsafety",
                    "seedmissing",
                    "closureunassigned",
                    "unassignedengine",
                    "assets",
                    "totals",
                    "budget",
                },
                names,
            )

    def test_budget_over_fails(self) -> None:
        self._failing("passing", scenario("passing"), "budget", budget=64)

    def test_manifest_may_not_carry_its_own_budget(self) -> None:
        manifest = scenario("passing")
        manifest["budget_bytes"] = 999999
        self._failing("passing", manifest, "budget")

    def test_unassigned_engine_fails_the_gate(self) -> None:
        self._failing("unassigned_engine", scenario("unassigned_engine"), "unassignedengine")

    def test_schema_violation_fails(self) -> None:
        manifest = scenario("passing")
        manifest["measurement_basis"]["proportional_scaling"] = True
        self._failing("passing", manifest, "schema")

    def test_missing_schema_key_fails(self) -> None:
        manifest = scenario("passing")
        del manifest["engine_census"]
        self._failing("passing", manifest, "schema")

    def test_path_safety_violation_fails(self) -> None:
        manifest = scenario("passing")
        manifest["closure"]["modules"][0]["resource"] = "/abs/path/to/engine.js"
        self._failing("passing", manifest, "pathsafety")

    def test_repo_root_leak_fails(self) -> None:
        manifest = scenario("passing")
        manifest["closure"]["modules"][0]["resource"] = "apps/web/src/" + str(ROOT) + "/x.js"
        self._failing("passing", manifest, "pathsafety")

    def test_seed_missing_fails(self) -> None:
        manifest = scenario("passing")
        manifest["seed"]["match_count"] = 0
        self._failing("passing", manifest, "seedmissing")

    def test_closure_unassigned_fails(self) -> None:
        manifest = scenario("passing")
        manifest["closure"]["modules"][0]["chunks"] = []
        self._failing("passing", manifest, "closureunassigned")

    def test_tampered_asset_fails_the_sha256_match(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            manifest_file, dist = self._stage(tmp, "passing", manifest)
            victim = dist / "assets" / "charts.22222222.js"
            victim.write_bytes(victim.read_bytes() + b"/* injected */")
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertIn("assets", {check.name for check in report.failed})

    def test_deleted_asset_fails_the_bidirectional_set_match(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            manifest_file, dist = self._stage(tmp, "passing", manifest)
            (dist / "assets" / "charts.22222222.js").unlink()
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertIn("assets", {check.name for check in report.failed})

    def test_unknown_extra_asset_fails(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            manifest_file, dist = self._stage(tmp, "passing", manifest)
            (dist / "assets" / "smuggled.44444444.js").write_text("nope", encoding="utf-8")
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertIn("assets", {check.name for check in report.failed})

    def test_post_build_service_worker_is_reported_not_charged(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            manifest_file, dist = self._stage(tmp, "passing", manifest)
            (dist / "sw.js").write_text("// gen-sw.js output", encoding="utf-8")
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertEqual([check.detail for check in report.failed], [])
            self.assertTrue(any("sw.js" in line for line in report.info))

    def test_copied_worker_template_can_be_replaced_by_post_build_generator(self) -> None:
        manifest = scenario("copied_sw")
        self.assertNotIn("sw.js", {asset["path"] for asset in manifest["assets"]})
        with tempfile.TemporaryDirectory() as raw:
            manifest_file, dist = self._stage(Path(raw), "copied_sw", manifest)
            (dist / "sw.js").write_text("// generated worker", encoding="utf-8")
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertEqual([check.detail for check in report.failed], [])

    def test_compiled_worker_chunk_still_requires_exact_sha256(self) -> None:
        manifest = scenario("compiled_sw")
        self.assertIn("sw.js", {asset["path"] for asset in manifest["assets"]})
        with tempfile.TemporaryDirectory() as raw:
            manifest_file, dist = self._stage(Path(raw), "compiled_sw", manifest)
            (dist / "sw.js").write_text("// tampered compiled chunk", encoding="utf-8")
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            self.assertIn("assets", {check.name for check in report.failed})

    def test_mixed_chunk_is_charged_at_full_gzip(self) -> None:
        manifest = scenario("passing")
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            manifest_file, dist = self._stage(tmp, "passing", manifest)
            report = gate.run(manifest_file, dist, gate.DEFAULT_BUDGET_BYTES)
            scratch = gate.Report()
            measured = gate.measure_dist(manifest, dist, scratch)
            self.assertIsNotNone(measured)
            charged = [chunk for chunk in manifest["chunks"] if chunk["charged"]]
            total = sum(
                measured.gzip[name] for chunk in charged for name in chunk["files"]
            )
            mixed = [chunk for chunk in charged if chunk["mixed"]]
            pure = [chunk for chunk in charged if not chunk["mixed"]]
            mixed_gzip = sum(measured.gzip[name] for chunk in mixed for name in chunk["files"])
            pure_gzip = sum(measured.gzip[name] for chunk in pure for name in chunk["files"])
            self.assertGreater(mixed_gzip, 0, "the mixed chunk must contribute real bytes")
            self.assertEqual(total, mixed_gzip + pure_gzip)
            budget_check = next(check for check in report.checks if check.name == "budget")
            self.assertIn(f"{total} B <=", budget_check.detail)

    def test_lazy_and_initial_are_info_only(self) -> None:
        manifest = scenario("passing")
        charged = [chunk for chunk in manifest["chunks"] if chunk["charged"]]
        self.assertTrue(any(chunk["initial"] for chunk in charged))
        self.assertTrue(any(not chunk["initial"] for chunk in charged))
        with tempfile.TemporaryDirectory() as raw:
            report = self._run(Path(raw), "passing", manifest)
            self.assertEqual([check.detail for check in report.failed], [])
            self.assertTrue(any("INFO" in line and "lazy" in line for line in report.info))
            # A lazy budget may not exist as a separate gate.
            self.assertNotIn("lazy", {check.name for check in report.checks})

    def test_missing_manifest_fails_with_a_build_hint(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            shutil.copytree(staged_dist("passing"), tmp / "dist")
            report = gate.run(tmp / "absent.json", tmp / "dist", gate.DEFAULT_BUDGET_BYTES)
            self.assertEqual([check.name for check in report.failed], ["manifest"])
            self.assertIn("chart-closure-plugin.cjs", report.failed[0].detail)

    def test_resolve_manifest_covers_all_three_trees(self) -> None:
        self.assertEqual(
            gate.resolve_manifest(ROOT / "apps/web/dist/external", None).name,
            "web-external.json",
        )
        self.assertEqual(
            gate.resolve_manifest(ROOT / "apps/web/dist/internal", None).name,
            "web-internal.json",
        )
        self.assertEqual(
            gate.resolve_manifest(ROOT / "apps/admin/dist", None).name,
            "admin-default.json",
        )
        with self.assertRaises(SystemExit):
            gate.resolve_manifest(ROOT / "apps/jbrowse/dist", None)


if __name__ == "__main__":
    unittest.main()
