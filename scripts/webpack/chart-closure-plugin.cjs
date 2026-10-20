/**
 * SoyMutDB chart dependency closure — webpack instrumentation (L1).
 *
 * Why this file exists
 * --------------------
 * The `charts` split-chunk group and `check-bundle-size.sh` measure ONE named
 * chunk. That under-reports the engine: during the ECharts -> AntV transition
 * the real engine landed partly in `charts`, partly in an unnamed vendor chunk
 * (`lodash`, `html2canvas`, `gl-matrix`, `d3-*`) and partly in `ui`
 * (`@ant-design/charts-util`), so the cap was checked against a number smaller
 * than the real chart cost in the shipped artifact. A chunk-name budget cannot
 * see that.
 *
 * This plugin measures the thing itself: the FORWARD DEPENDENCY CLOSURE of the
 * chart package entry that webpack really compiled, and the full gzip cost of
 * every JavaScript chunk that carries any part of that closure.
 *
 * Measurement rules (each one is a deliberate, reviewable choice)
 * -----------------------------------------------------------------
 * 1. Seed = the module webpack actually compiled for
 *    `packages/charts/src/index.ts`. It is found by scanning
 *    `compilation.modules` for a module whose resolved resource IS that file,
 *    never by assuming the file exists on disk. A missing seed is recorded and
 *    fails the gate; it is never silently replaced by a hypothetical module.
 * 2. Closure = BFS over `compilation.moduleGraph` outgoing connections, which
 *    includes dynamic `import()` edges. Concatenated inner modules are pulled
 *    in explicitly, because `ModuleConcatenationPlugin` folds them into one
 *    `ConcatenatedModule` and they are the bulk of a tree-shaken engine.
 * 3. Platform packages (`react`, `react-dom`, `scheduler`) are excluded from
 *    the closure: they are loaded by the platform, not by the chart engine,
 *    and are already covered by the `react` budget.
 * 4. Cost = the FULL actual gzip of every JS chunk containing at least one
 *    closure module. No raw-byte proportional scaling, no per-package
 *    estimation, no ratio proration of a mixed chunk. A chunk is a byte range
 *    the browser downloads; splitting it by module identity would be fiction.
 * 5. The engine census covers EVERY module in the compilation, not just the
 *    closure. An `echarts` / `zrender` / `@antv/*` / `@ant-design/plots` module
 *    that the closure does not account for is recorded as `unassigned` and is a
 *    hard checker failure — during the migration this is the honest red state,
 *    and there is deliberately no flag that turns it green.
 *
 * The plugin only WRITES a manifest. It never fails the build on a budget or
 * census problem: the build must stay usable while the migration is in flight,
 * and `scripts/chart_closure_budget.py` is the gate that decides.
 *
 * Deliberately NOT used (each was rejected for a concrete reason)
 * ---------------------------------------------------------------
 * - `stats.toJson()` `issuer` fields: they dangle — an issuer can name a
 *   module that is no longer in the finished graph.
 * - a chunk `children` set: it describes chunk LOADING parents, not module
 *   membership, so vendor modules reachable from a shared chunk are invisible.
 * - a full `stats.reasons` dump: it is enormous and carries the same dangling
 *   issuer risk as the first point.
 *
 * Registration (both apps, registration only — no other config change):
 *   plugins: [ ..., resolve(__dirname, "../../../scripts/webpack/chart-closure-plugin.cjs") ]
 * Output: `.build/chart-closure/{web-external,web-internal,admin-default}.json`
 *   Never inside `dist/`, never containing an absolute path.
 */

"use strict";

const { createHash } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const SCHEMA_VERSION = 1;
const GENERATOR = "chart-closure-plugin";
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const MANIFEST_DIR = path.join(REPO_ROOT, ".build", "chart-closure");

/** The production seed. A facade entry, so its closure IS the engine cost. */
const SEED_RELATIVE_PATH = "packages/charts/src/index.ts";

/** 370 KiB, fixed by the user. Not derived from any historical measurement. */
const BUDGET_BYTES = 378880;

/** Loaded by the platform, not by the chart engine. Excluded by contract. */
const PLATFORM_PACKAGES = ["react", "react-dom", "scheduler"];

/**
 * Engine families subject to the census. `@antv` is a scope, so `@antv/g2`,
 * `@antv/g`, `@antv/g-canvas` and friends are all covered by one entry.
 * `@ant-design/charts-util` is listed because it is a real chart-engine
 * dependency that previously landed in the `ui` chunk.
 */
const ENGINE_EXACT_PACKAGES = [
  "echarts",
  "zrender",
  "@ant-design/plots",
  "@ant-design/charts-util",
];
const ENGINE_SCOPE_PACKAGES = ["@antv"];

/** The only two apps that may carry a chart closure manifest. */
const SUPPORTED_APPS = new Set(["web", "admin"]);

const MEASUREMENT_STATEMENT =
  "Complete dependency closure of packages/charts/src/index.ts, charged at the " +
  "full actual gzip of every JS chunk that contains at least one non-platform " +
  "closure module. Application route/page modules that merely consume the facade " +
  "(upstream route glue) are NOT part of the seed and are NOT counted here.";

/* ------------------------------------------------------------------ */
/*  Pure helpers. Exported so scripts/test_chart_closure_budget.py can   */
/*  drive them against a synthetic graph without a real webpack build.   */
/* ------------------------------------------------------------------ */

function toPosix(value) {
  return String(value).split(path.sep).join("/");
}

/** Strip a loader query/fragment and express an absolute path repo-relative. */
function toRepoRelative(repoRoot, absolute) {
  if (typeof absolute !== "string" || absolute.length === 0) return null;
  const clean = absolute.split("?")[0].split("#")[0];
  const relative = path.relative(repoRoot, clean);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) return null;
  return toPosix(relative);
}

/**
 * Resolve the npm package a module belongs to from its repo-relative path.
 * pnpm nests a package under the OUTERMOST `node_modules` of the dependent,
 * so the innermost segment wins. Workspace packages carry no `node_modules`.
 */
function packageOfRepoPath(repoRelativePath) {
  if (!repoRelativePath) return null;
  const parts = repoRelativePath.split("/");
  const last = parts.lastIndexOf("node_modules");
  if (last !== -1) {
    const rest = parts.slice(last + 1);
    if (rest.length === 0) return null;
    if (rest[0].startsWith("@")) return rest.length >= 2 ? rest[0] + "/" + rest[1] : rest[0];
    return rest[0];
  }
  if (parts.length >= 2 && parts[0] === "packages" && !parts[1].startsWith(".")) {
    return "@soymutdb/" + parts[1];
  }
  if (parts.length >= 2 && parts[0] === "apps" && !parts[1].startsWith(".")) {
    return "@soymutdb/" + parts[1];
  }
  return null;
}

function isEnginePackage(packageName) {
  if (!packageName) return false;
  if (ENGINE_EXACT_PACKAGES.includes(packageName)) return true;
  return ENGINE_SCOPE_PACKAGES.some(
    (scope) => packageName === scope || packageName.startsWith(scope + "/"),
  );
}

function isPlatformPackage(packageName) {
  return packageName !== null && PLATFORM_PACKAGES.includes(packageName);
}

/**
 * The file behind a module. A `ConcatenatedModule` has no `resource` of its own,
 * so it reports through its `rootModule` — without this a concatenated seed is
 * labelled "unresolved" and looks unattributable.
 */
function resourceOf(module) {
  if (!module) return null;
  if (typeof module.resource === "string") return module.resource;
  const root = module.rootModule;
  if (root && typeof root.resource === "string") return root.resource;
  return null;
}

/**
 * The root module of a ConcatenatedModule. webpack keeps the root OUT of the
 * `modules` array, so it has to be linked explicitly or the seed itself (when it
 * is the concatenation root) belongs to no chunk.
 */
function concatenatedRootModule(module) {
  if (!module || !module.rootModule || module.rootModule === module) return null;
  return typeof module.rootModule.resource === "string" ? module.rootModule : null;
}

/**
 * A `ConcatenatedModule` holds every module folded into it. Tree-shaking
 * means the engine inner modules live here, so a closure that only walked
 * outer modules would attribute the engine to nothing.
 */
function concatenatedInnerModules(module) {
  if (!module) return [];
  const candidates = [module.modules, module._modules];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate.filter((inner) => inner && inner !== module);
    }
  }
  return [];
}

/**
 * Forward closure over the real module graph.
 *
 * Platform modules terminate a branch instead of being traversed: they are
 * never chart engine and are already budgeted by the `react` group.
 */
function computeClosure(moduleGraph, seedModules, classifyPackage) {
  const closure = new Set();
  const platform = new Set();
  const edgeTypes = new Map();
  const queue = [];
  const visited = new Set();

  const admit = (module, edgeType, emitted = true) => {
    if (!module) return;
    if (classifyPackage(module) === "platform") {
      platform.add(module);
      return;
    }
    if (edgeType) edgeTypes.set(edgeType, (edgeTypes.get(edgeType) || 0) + 1);
    if (emitted) closure.add(module);
    if (visited.has(module)) return;
    visited.add(module);
    queue.push(module);
  };

  for (const seed of seedModules) admit(seed, null);

  while (queue.length > 0) {
    const module = queue.pop();
    for (const inner of concatenatedInnerModules(module)) admit(inner, "concatenated");
    let connections = [];
    if (moduleGraph && typeof moduleGraph.getOutgoingConnections === "function") {
      connections = moduleGraph.getOutgoingConnections(module) || [];
    }
    for (const connection of connections) {
      if (!connection) continue;
      const state = typeof connection.getActiveState === "function"
        ? connection.getActiveState(undefined) : true;
      if (state === false) continue;
      // Webpack keeps re-export barrels as transitive-only graph nodes.
      // Traverse their dependencies, but they emit no runtime module.
      admit(connection.module, connectionType(connection), typeof state !== "symbol");
    }
  }

  const dynamicEdges = Array.from(edgeTypes.entries())
    .filter(([kind]) => kind.indexOf("import()") !== -1 || kind.indexOf("dynamic") !== -1)
    .reduce((sum, entry) => sum + entry[1], 0);

  return { closure, platform, edgeTypes, dynamicEdges };
}

/**
 * Edge label for the manifest.
 *
 * `ModuleGraphConnection` in webpack 5.110.3 has NO `dependencyType` property
 * (verified against the real compiler: its keys are originModule,
 * resolvedOriginModule, dependency, resolvedModule, module, weak, conditional,
 * _active, condition, explanations). Reading `connection.dependencyType` silently
 * yields undefined and every edge would be reported as "unknown", so the label is
 * taken from the dependency object itself.
 */
function connectionType(connection) {
  const dependency = connection && connection.dependency;
  if (dependency) {
    if (typeof dependency.type === "string" && dependency.type) return dependency.type;
    if (typeof dependency.category === "string" && dependency.category) {
      return dependency.category;
    }
    if (dependency.constructor && dependency.constructor.name) {
      return dependency.constructor.name;
    }
  }
  return "unknown";
}

/**
 * module -> chunks, built by walking every chunk module iterable.
 * Walking chunks (not `getModuleChunks`) is what makes concatenated inner
 * modules attributable: they are chunk members even though the outer module
 * is the one that owns the chunk.
 */
function buildChunkIndex(chunkGraph, chunks) {
  const byModule = new Map();
  const link = (module, chunk) => {
    if (!module || !chunk) return;
    let list = byModule.get(module);
    if (!list) {
      list = [];
      byModule.set(module, list);
    }
    if (list.indexOf(chunk) === -1) list.push(chunk);
  };
  for (const chunk of chunks || []) {
    let members = [];
    if (chunkGraph && typeof chunkGraph.getChunkModulesIterable === "function") {
      members = chunkGraph.getChunkModulesIterable(chunk) || [];
    }
    for (const member of members) link(member, chunk);
    // Concatenated inner modules are the bulk of a tree-shaken engine, and
    // webpack does NOT expose them through the chunk graph: verified against
    // webpack 5.110.3, an inner module appears in NEITHER
    // getChunkModulesIterable NOR getModuleChunksIterable of the chunk that
    // owns its ConcatenatedModule. They belong to that chunk by construction, so
    // they are expanded here; without this every concatenated engine module is
    // unattributable and the gate reports closureunassigned.
    for (const member of members) {
      for (const inner of concatenatedInnerModules(member)) link(inner, chunk);
      const root = concatenatedRootModule(member);
      if (root) link(root, chunk);
    }
  }
  // Second pass for anything the per-chunk walk missed (defensive: an orphan
  // module still has a module -> chunk mapping in some webpack code paths).
  if (chunkGraph && typeof chunkGraph.getModuleChunksIterable === "function") {
    for (const [module] of byModule) {
      for (const chunk of chunkGraph.getModuleChunksIterable(module) || []) link(module, chunk);
    }
  }
  return byModule;
}

function chunkLabel(chunk, index) {
  const raw = chunk && (chunk.name || chunk.id);
  const label = raw === undefined || raw === null || raw === "" ? null : String(raw);
  return label || "chunk-" + index;
}

function isInitialChunk(chunk) {
  if (!chunk) return false;
  if (typeof chunk.canBeInitial === "function") {
    try {
      return Boolean(chunk.canBeInitial());
    } catch (error) {
      // Conservative: an unknown chunk is treated as non-initial.
    }
  }
  return false;
}

function sha256Hex(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

/** A real Umi app directory, not a directory that merely happens to be named so. */
function isAppDir(directory) {
  try {
    return fs.statSync(path.join(directory, "package.json")).isFile();
  } catch {
    return false;
  }
}

function assetBuffer(asset) {
  if (!asset) return Buffer.alloc(0);
  const source = asset.source !== undefined ? asset.source : asset;
  if (Buffer.isBuffer(source)) return source;
  if (source && typeof source.buffer === "function") return source.buffer();
  if (source && typeof source.source === "function") {
    const raw = source.source();
    return Buffer.isBuffer(raw) ? raw : Buffer.from(String(raw), "utf8");
  }
  return Buffer.from(String(source), "utf8");
}

/**
 * Build the manifest body from a normalised compilation snapshot:
 *   { modules, moduleGraph, chunkGraph, chunks, assets, app, variant,
 *     compilerName, repoRoot, seedRelativePath, assetIndex }
 */
function buildManifest(snapshot) {
  const repoRoot = snapshot.repoRoot || REPO_ROOT;
  const seedRelativePath = snapshot.seedRelativePath || SEED_RELATIVE_PATH;
  const modules = Array.from(snapshot.modules || []);
  const chunks = Array.from(snapshot.chunks || []);
  const errors = [];

  const relativeOf = (module) => toRepoRelative(repoRoot, resourceOf(module));
  const packageOf = (module) => packageOfRepoPath(relativeOf(module));
  const classifyPackage = (module) => {
    const packageName = packageOf(module);
    if (isPlatformPackage(packageName)) return "platform";
    return packageName === null ? "unresolved" : "closure";
  };
  const labelOf = (module, chunkLabelsByModule) => {
    const relative = relativeOf(module);
    if (relative) return relative;
    const assigned = chunkLabelsByModule ? chunkLabelsByModule.get(module) : null;
    if (assigned && assigned.length > 0) return "unresolved:" + assigned[0];
    return "unresolved:module";
  };

  // --- seed ------------------------------------------------------------
  const seedSuffix = "/" + seedRelativePath;
  const seedModules = modules.filter((module) => {
    const relative = relativeOf(module);
    if (relative === seedRelativePath) return true;
    const raw = resourceOf(module);
    return typeof raw === "string" && toPosix(raw.split("?")[0]).endsWith(seedSuffix);
  });
  if (seedModules.length === 0) {
    errors.push({
      check: "seedmissing",
      detail:
        "no compiled module resolves to " +
        seedRelativePath +
        "; the chart entry is not in this compilation",
    });
  }

  // --- closure + chunk attribution ------------------------------------
  const { closure, platform, edgeTypes, dynamicEdges } = computeClosure(
    snapshot.moduleGraph,
    seedModules,
    classifyPackage,
  );
  const chunkIndex = buildChunkIndex(snapshot.chunkGraph, chunks);

  // Every module webpack knows about, concatenated inner modules included.
  const allModules = new Set(modules);
  for (const module of modules) {
    for (const inner of concatenatedInnerModules(module)) allModules.add(inner);
  }

  const chunkLabelsByModule = new Map();
  for (const entry of chunkIndex) {
    chunkLabelsByModule.set(
      entry[0],
      entry[1].map((chunk, index) => chunkLabel(chunk, index)),
    );
  }

  const closureModules = [];
  const unassignedClosureModules = [];
  const closurePackages = new Set();
  for (const module of closure) {
    const assigned = chunkIndex.get(module) || [];
    const packageName = packageOf(module);
    if (packageName) closurePackages.add(packageName);
    if (assigned.length === 0) unassignedClosureModules.push(labelOf(module, chunkLabelsByModule));
    closureModules.push({
      resource: labelOf(module, chunkLabelsByModule),
      package: packageName,
      chunk_count: assigned.length,
      chunks: (chunkLabelsByModule.get(module) || []).slice().sort(),
    });
  }
  closureModules.sort((a, b) => (a.resource < b.resource ? -1 : a.resource > b.resource ? 1 : 0));
  unassignedClosureModules.sort();
  if (unassignedClosureModules.length > 0) {
    errors.push({
      check: "closureunassigned",
      detail: unassignedClosureModules.length + " closure module(s) belong to no emitted chunk",
    });
  }

  // --- concatenation / tree-shaking evidence --------------------------
  let concatenatedModules = 0;
  let concatenatedInnerTotal = 0;
  let concatenatedInnerInClosure = 0;
  let concatenatedInnerUnattributed = 0;
  for (const module of allModules) {
    const inner = concatenatedInnerModules(module);
    if (inner.length === 0) continue;
    concatenatedModules += 1;
    concatenatedInnerTotal += inner.length;
    for (const innerModule of inner) {
      if (!closure.has(innerModule)) continue;
      concatenatedInnerInClosure += 1;
      if ((chunkIndex.get(innerModule) || []).length === 0) concatenatedInnerUnattributed += 1;
    }
  }
  if (concatenatedInnerUnattributed > 0) {
    errors.push({
      check: "closureunassigned",
      detail:
        concatenatedInnerUnattributed + " concatenated inner module(s) in the closure have no chunk",
    });
  }

  // --- engine census over the WHOLE compilation -----------------------
  const censusUnassigned = [];
  let censusModuleCount = 0;
  let censusClosureCount = 0;
  for (const module of allModules) {
    const packageName = packageOf(module);
    if (!isEnginePackage(packageName)) continue;
    const assigned = chunkIndex.get(module) || [];
    if (!assigned.length && snapshot.moduleGraph) {
      const graph = snapshot.moduleGraph;
      if (typeof graph.getUsedExports === "function" && graph.getUsedExports(module, undefined) === false) continue;
      if (typeof graph.getIncomingConnections === "function") {
        const incoming = Array.from(graph.getIncomingConnections(module) || []);
        if (incoming.length && incoming.every((connection) =>
          typeof connection.getActiveState === "function" && connection.getActiveState(undefined) !== true,
        )) continue;
      }
    }
    censusModuleCount += 1;
    if (closure.has(module)) {
      censusClosureCount += 1;
      continue;
    }
    censusUnassigned.push({
      resource: labelOf(module, chunkLabelsByModule),
      package: packageName,
      chunks: (chunkLabelsByModule.get(module) || []).slice().sort(),
    });
  }
  censusUnassigned.sort((a, b) => (a.resource < b.resource ? -1 : a.resource > b.resource ? 1 : 0));
  if (censusUnassigned.length > 0) {
    errors.push({
      check: "unassignedengine",
      detail:
        censusUnassigned.length +
        " engine module(s) are in the build but outside the " +
        seedRelativePath +
        " closure",
    });
  }

  // --- chunks and cost -------------------------------------------------
  const assetIndex = snapshot.assetIndex || new Map();
  const chunkRecords = [];
  let chargedRawBytes = 0;
  let chargedAssetCount = 0;
  let mixedChunkCount = 0;
  let mixedChunkRawBytes = 0;
  let initialRawBytes = 0;
  let lazyRawBytes = 0;
  chunks.forEach((chunk, index) => {
    let members = [];
    if (snapshot.chunkGraph && typeof snapshot.chunkGraph.getChunkModulesIterable === "function") {
      members = Array.from(snapshot.chunkGraph.getChunkModulesIterable(chunk) || []);
    }
    // Cost accounting must see the same module set as the attribution pass.
    // A chunk whose entire chart payload arrived as concatenated inner modules
    // would otherwise look closure-free and be charged nothing.
    for (const member of members.slice()) {
      for (const inner of concatenatedInnerModules(member)) {
        if (!members.includes(inner)) members.push(inner);
      }
    }
    const closureMembers = members.filter((member) => closure.has(member));
    const platformMembers = members.filter((member) => platform.has(member));
    const foreignMembers = members.filter(
      (member) => !closure.has(member) && !platform.has(member),
    );
    const files = Array.from(chunk.files || []).filter((file) => file.endsWith(".js")).sort();
    const charged = closureMembers.length > 0 && files.length > 0;
    const mixed = charged && closureMembers.length < members.length;
    let rawBytes = 0;
    for (const file of files) {
      const asset = assetIndex.get(toPosix(file));
      rawBytes += asset ? asset.raw_bytes : 0;
    }
    const initial = isInitialChunk(chunk);
    if (charged) {
      chargedRawBytes += rawBytes;
      chargedAssetCount += files.length;
      if (initial) initialRawBytes += rawBytes;
      else lazyRawBytes += rawBytes;
      if (mixed) {
        mixedChunkCount += 1;
        mixedChunkRawBytes += rawBytes;
      }
    }
    chunkRecords.push({
      id: chunkLabel(chunk, index),
      name: chunk && chunk.name !== undefined && chunk.name !== null ? String(chunk.name) : null,
      files,
      initial,
      charged,
      mixed,
      chunk_module_count: members.length,
      closure_module_count: closureMembers.length,
      platform_module_count: platformMembers.length,
      foreign_module_count: foreignMembers.length,
      raw_bytes: rawBytes,
    });
  });
  chunkRecords.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));

  // --- asset inventory (complete, hashed) ------------------------------
  const chunkFiles = new Set(chunks.flatMap((chunk) => Array.from(chunk.files || [], toPosix)));
  const assets = Array.from(snapshot.assets || [])
    // The public sw.js is a copied template, subsequently replaced by gen-sw.
    // A real compiled chunk named sw.js must still be recorded and hashed.
    .filter((entry) => !(snapshot.app === "web" && toPosix(entry.name) === "sw.js" &&
      !chunkFiles.has("sw.js")))
    .map((entry) => ({
      path: toPosix(entry.name),
      raw_bytes: entry.raw_bytes,
      sha256: entry.sha256,
      is_js: entry.name.endsWith(".js"),
    }))
    .sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));

  const jsDirs = new Set();
  for (const entry of assets) {
    if (!entry.is_js) continue;
    const slash = entry.path.indexOf("/");
    if (slash !== -1) jsDirs.add(entry.path.slice(0, slash));
  }
  const assetDirs = Array.from(jsDirs).sort();

  const excludedPlatformPackages = new Set();
  let excludedPlatformCount = 0;
  for (const module of platform) {
    excludedPlatformCount += 1;
    const packageName = packageOf(module);
    if (packageName) excludedPlatformPackages.add(packageName);
  }

  return {
    schema_version: SCHEMA_VERSION,
    generator: GENERATOR,
    app: snapshot.app || "unknown",
    variant: snapshot.variant || "unknown",
    compiler_name: snapshot.compilerName || null,
    budget_bytes: BUDGET_BYTES,
    measurement_basis: {
      seed: seedRelativePath,
      seed_scope: "forward-module-graph-from-the-compiled-seed",
      counts_upstream_route_glue: false,
      charge_rule: "whole-js-chunk-actual-gzip",
      proportional_scaling: false,
      estimation: false,
      self_attested_completeness: false,
      statement: MEASUREMENT_STATEMENT,
    },
    platform_exclusions: PLATFORM_PACKAGES.slice(),
    engine_families: ENGINE_EXACT_PACKAGES.concat(
      ENGINE_SCOPE_PACKAGES.map((scope) => scope + "/*"),
    ),
    asset_dirs: assetDirs,
    seed: {
      relative_path: seedRelativePath,
      match_count: seedModules.length,
      matched_modules: seedModules
        .map((module) => labelOf(module, chunkLabelsByModule))
        .sort(),
    },
    closure: {
      module_count: closureModules.length,
      packages: Array.from(closurePackages).sort(),
      edge_types: Object.fromEntries(Array.from(edgeTypes.entries()).sort()),
      dynamic_edge_count: dynamicEdges,
      modules: closureModules,
    },
    concatenation: {
      concatenated_module_count: concatenatedModules,
      inner_module_count: concatenatedInnerTotal,
      inner_modules_in_closure: concatenatedInnerInClosure,
      inner_modules_unattributed: concatenatedInnerUnattributed,
      tree_shaking_observed: concatenatedModules > 0,
    },
    excluded_platform: {
      module_count: excludedPlatformCount,
      packages: Array.from(excludedPlatformPackages).sort(),
    },
    engine_census: {
      module_count: censusModuleCount,
      closure_module_count: censusClosureCount,
      unassigned_count: censusUnassigned.length,
      unassigned: censusUnassigned,
    },
    assets,
    chunks: chunkRecords,
    totals: {
      chunk_count: chunks.length,
      charged_chunk_count: chunkRecords.filter((entry) => entry.charged).length,
      charged_asset_count: chargedAssetCount,
      charged_raw_bytes: chargedRawBytes,
      mixed_chunk_count: mixedChunkCount,
      mixed_chunk_raw_bytes: mixedChunkRawBytes,
      initial_raw_bytes: initialRawBytes,
      lazy_raw_bytes: lazyRawBytes,
    },
    unassigned_closure_modules: unassignedClosureModules,
    errors,
  };
}

/* ------------------------------------------------------------------ */
/*  Webpack / Umi wiring                                                */
/* ------------------------------------------------------------------ */

/**
 * Umi `plugins` takes a path string, so the plugin identifies its own app and
 * variant from the compiler it is attached to.
 */
function resolveTarget(compiler) {
  const candidates = [
    compiler.options && compiler.options.context,
    compiler.context,
  ];
  // `process.cwd()` is deliberately NOT a candidate of its own: webpack already
  // folds it into `compiler.context`, and a repository checkout whose own path
  // happens to end in `/web` must not be mistaken for the portal app.
  // Umi does not pin webpack `context`, so it normally falls back to the cwd
  // turbo/`max build` already set to the app directory. The output path is a
  // second, independent signal: `<appdir>/dist[/<variant>]`.
  const outputPath = compiler.options && compiler.options.output && compiler.options.output.path;
  if (typeof outputPath === "string" && outputPath) {
    let current = path.resolve(outputPath);
    while (path.dirname(current) !== current) {
      candidates.push(current);
      current = path.dirname(current);
    }
  }

  const appDir = candidates
    .filter((value) => typeof value === "string" && value)
    .map((value) => path.resolve(value))
    .find((value) => SUPPORTED_APPS.has(path.basename(value)) && isAppDir(value));
  const app = appDir ? path.basename(appDir) : null;
  if (!app) {
    throw new Error(
      "chart-closure-plugin: cannot identify the app from the compiler " +
        "(context=" +
        String((compiler.options && compiler.options.context) || compiler.context) +
        ", output.path=" +
        String(outputPath) +
        "). Register it only in apps/web and apps/admin.",
    );
  }
  if (app === "web") {
    const variant = String(process.env.VITE_SITE_VARIANT || "external")
      .trim()
      .toLowerCase();
    const resolved = variant === "internal" ? "internal" : "external";
    return { app, variant: resolved, manifestName: "web-" + resolved };
  }
  if (app === "admin") return { app, variant: "default", manifestName: "admin-default" };
  throw new Error(`chart-closure-plugin: unsupported app ${app}`);
}

function readAssets(compilation) {
  const out = [];
  const listed =
    typeof compilation.getAssets === "function" ? compilation.getAssets() : null;
  const entries = listed
    ? listed
    : Object.keys(compilation.assets || {}).map((name) => ({
        name,
        source: compilation.assets[name],
      }));
  for (const entry of entries) {
    const buffer = assetBuffer(entry);
    out.push({
      name: entry.name,
      raw_bytes: buffer.length,
      sha256: sha256Hex(buffer),
    });
  }
  return out;
}

/** Umi plugin entry point. Umi calls this once per app. */
function chartClosureUmiPlugin(api) {
  api.chainWebpack((memo) => {
    memo.plugin("soymutdb-chart-closure").use(ChartClosureWebpackPlugin);
    return memo;
  });
  api.onBuildComplete(({ err }) => {
    if (err) return;
    const target = resolveTarget({ context: api.cwd });
    const filename = path.join(MANIFEST_DIR, target.manifestName + ".json");
    if (!fs.existsSync(filename)) return;
    const manifest = JSON.parse(fs.readFileSync(filename, "utf8"));
    const output = api.paths.absOutputPath;
    // Umi writes its modulepreload helper while producing HTML, after webpack's
    // processAssets hook. Record those exact bytes so the disk inventory stays
    // complete; this platform helper contains no chart modules.
    for (const name of fs.readdirSync(output)) {
      if (!/^preload_helper\.[a-f0-9]+\.js$/.test(name)) continue;
      if (manifest.assets.some((asset) => asset.path === name)) continue;
      const data = fs.readFileSync(path.join(output, name));
      manifest.assets.push({ path: name, raw_bytes: data.length, sha256: sha256Hex(data), is_js: true });
    }
    manifest.assets.sort((a, b) => a.path.localeCompare(b.path));
    fs.writeFileSync(filename, JSON.stringify(manifest, null, 2) + "\n", "utf8");
  });
}

/** The webpack plugin. Exported so tests can drive `buildManifest` directly. */
class ChartClosureWebpackPlugin {
  apply(compiler) {
    const compilerName = compiler.name || null;
    if (compilerName && compilerName !== "client") return;
    const target = resolveTarget(compiler);
    const Compilation = compiler.webpack ? compiler.webpack.Compilation : null;
    const reportStage = Compilation ? Compilation.PROCESS_ASSETS_STAGE_REPORT : undefined;

    compiler.hooks.thisCompilation.tap("ChartClosurePlugin", (compilation) => {
      const tapOptions = reportStage
        ? { name: "ChartClosurePlugin", stage: reportStage }
        : { name: "ChartClosurePlugin" };
      compilation.hooks.processAssets.tap(tapOptions, () => {
        const assets = readAssets(compilation);
        const manifest = buildManifest({
          app: target.app,
          variant: target.variant,
          compilerName,
          repoRoot: REPO_ROOT,
          seedRelativePath: SEED_RELATIVE_PATH,
          modules: Array.from(compilation.modules || []),
          moduleGraph: compilation.moduleGraph,
          chunkGraph: compilation.chunkGraph,
          chunks: Array.from(compilation.chunks || []),
          assets,
          assetIndex: new Map(assets.map((entry) => [toPosix(entry.name), entry])),
        });
        fs.mkdirSync(MANIFEST_DIR, { recursive: true });
        fs.writeFileSync(
          path.join(MANIFEST_DIR, target.manifestName + ".json"),
          JSON.stringify(manifest, null, 2) + "\n",
          "utf8",
        );
        process.stdout.write(
          "[chart-closure] " +
            target.manifestName +
            ": " +
            manifest.closure.module_count +
            " closure module(s), " +
            manifest.totals.charged_chunk_count +
            " charged chunk(s), " +
            manifest.engine_census.module_count +
            " engine module(s) (" +
            manifest.engine_census.unassigned_count +
            " unassigned), " +
            manifest.errors.length +
            " recorded error(s) -> .build/chart-closure/" +
            target.manifestName +
            ".json\n",
        );
      });
    });
  }
}

module.exports = chartClosureUmiPlugin;
module.exports.SCHEMA_VERSION = SCHEMA_VERSION;
module.exports.GENERATOR = GENERATOR;
module.exports.REPO_ROOT = REPO_ROOT;
module.exports.MANIFEST_DIR = MANIFEST_DIR;
module.exports.SEED_RELATIVE_PATH = SEED_RELATIVE_PATH;
module.exports.BUDGET_BYTES = BUDGET_BYTES;
module.exports.PLATFORM_PACKAGES = PLATFORM_PACKAGES;
module.exports.ENGINE_EXACT_PACKAGES = ENGINE_EXACT_PACKAGES;
module.exports.ENGINE_SCOPE_PACKAGES = ENGINE_SCOPE_PACKAGES;
module.exports.MEASUREMENT_STATEMENT = MEASUREMENT_STATEMENT;
module.exports.ChartClosureWebpackPlugin = ChartClosureWebpackPlugin;
module.exports.buildManifest = buildManifest;
module.exports.computeClosure = computeClosure;
module.exports.buildChunkIndex = buildChunkIndex;
module.exports.concatenatedInnerModules = concatenatedInnerModules;
module.exports.packageOfRepoPath = packageOfRepoPath;
module.exports.toRepoRelative = toRepoRelative;
module.exports.isEnginePackage = isEnginePackage;
module.exports.isPlatformPackage = isPlatformPackage;
module.exports.resolveTarget = resolveTarget;
module.exports.sha256Hex = (buffer) => sha256Hex(buffer);
