import { execFile } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";

import {
  isProductionDeploymentMode,
  resolveDeploymentMode,
} from "../../src/lib/deployment";
import { requireReleaseId, writeReleaseManifest } from "../release-manifest";

const execFileAsync = promisify(execFile);
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

const temporaryDirectories: string[] = [];

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    rmSync(directory, { recursive: true, force: true });
  }
});

function readRepositoryFile(path: string): string {
  return readFileSync(resolve(REPOSITORY_ROOT, path), "utf8");
}

function joinTmp(prefix: string): string {
  return join(tmpdir(), `${prefix}${Math.random().toString(36).slice(2)}`);
}

describe("production deployment mode resolution", () => {
  it("resolves VITE_DEPLOYMENT_MODE=production to the strict production mode", () => {
    expect(resolveDeploymentMode("production")).toBe("production");
    expect(resolveDeploymentMode("PRODUCTION")).toBe("production");
    expect(isProductionDeploymentMode("production")).toBe(true);
  });

  it("does not treat demo/minimal/standard/undefined as production", () => {
    expect(isProductionDeploymentMode("demo")).toBe(false);
    expect(isProductionDeploymentMode("minimal")).toBe(false);
    expect(isProductionDeploymentMode("standard")).toBe(false);
    expect(isProductionDeploymentMode(undefined)).toBe(false);
    // Unknown values still resolve to standard (not silently production).
    expect(resolveDeploymentMode("production-ish")).toBe("standard");
  });
});

describe("SSG / sample generation fail-closed contract", () => {
  it("ssg-build must fail closed when the release API is unavailable in production", () => {
    const source = readRepositoryFile("apps/web/scripts/ssg-build.ts");
    expect(source).toContain("isProductionDeploymentMode");
    expect(source).toContain(
      "Production SSG build requires a reachable release API",
    );
    expect(source).toMatch(/PRODUCTION_MODE && !apiAvailable/);
    expect(source).toContain(
      "refusing to emit a demo/fallback artifact",
    );
  });

  it("generate-samples must refuse demo fixtures in production", () => {
    const source = readRepositoryFile("apps/web/scripts/generate-samples.ts");
    expect(source).toContain("isProductionDeploymentMode");
    expect(source).toContain("DEMO_MODE");
    expect(source).toMatch(/PRODUCTION_MODE && \(DEMO_MODE \|\|/);
    expect(source).toContain("refusing to emit demo fixtures into a production artifact");
    // Demode-only fixture sourcing must be gated on DEMO_MODE, never on
    // production.
    expect(source).toMatch(/const variants = DEMO_MODE \? FALLBACK_VARIANTS : await fetchVariantsFromApi\(\)/);
  });
});

describe("release manifest contract", () => {
  it("requireReleaseId rejects a missing/invalid release id (production must be tagged)", () => {
    expect(() => requireReleaseId({})).toThrow(/SOYMUTDB_RELEASE_ID/);
    expect(() => requireReleaseId({ SOYMUTDB_RELEASE_ID: "abc" })).toThrow();
    expect(requireReleaseId({ SOYMUTDB_RELEASE_ID: "42" })).toBe(42);
  });

  it("writeReleaseManifest emits manifest.json + SHA256SUMS over the tree", () => {
    const dir = mkdtempSync(joinTmp("rel-manifest-"));
    temporaryDirectories.push(dir);
    writeFileSync(resolve(dir, "a.js"), "hello");
    // Nested file: the release manifest walker must handle a subdirectory of
    // the tree, so create the directory first (writeFileSync does not mkdir).
    mkdirSync(resolve(dir, "assets"), { recursive: true });
    writeFileSync(resolve(dir, "assets/b.css"), "world");

    const out = writeReleaseManifest(dir, 7);

    expect(existsSync(out.manifestPath)).toBe(true);
    expect(existsSync(out.sha256Path)).toBe(true);
    const manifest = JSON.parse(readFileSync(out.manifestPath, "utf8"));
    expect(manifest.release_id).toBe(7);
    expect(manifest.application).toBe("soymutdb-next");
    expect(Object.keys(manifest.files).sort()).toEqual(["a.js", "assets/b.css"]);
    const sums = readFileSync(out.sha256Path, "utf8");
    expect(sums).toMatch(/^[0-9a-f]{64}  a\.js$/m);
    expect(sums).toMatch(/^[0-9a-f]{64}  assets\/b\.css$/m);
  });
});

describe("production artifact scan script", () => {
  it("exists at scripts/check-production-artifact.sh and is executable", () => {
    const path = resolve(REPOSITORY_ROOT, "scripts/check-production-artifact.sh");
    expect(existsSync(path)).toBe(true);
    const mode = statSync(path).mode;
    expect(mode & 0o111).toBeTruthy();
  });

  it("rejects placeholder/demo markers in strict mode", async () => {
    const dir = mkdtempSync(joinTmp("prod-scan-fail-"));
    temporaryDirectories.push(dir);
    writeFileSync(resolve(dir, "index.html"), "<html>api.example.com</html>");
    writeFileSync(resolve(dir, "sample.html"), "SMDB-00001 Demo fixture");

    await expect(
      execFileAsync("bash", [
        resolve(REPOSITORY_ROOT, "scripts/check-production-artifact.sh"),
        dir,
      ]),
    ).rejects.toMatchObject({ code: 1 });
  });

  it("passes a clean release artifact, and permits demo fixtures with --allow-demo", async () => {
    const clean = mkdtempSync(joinTmp("prod-scan-clean-"));
    temporaryDirectories.push(clean);
    writeFileSync(resolve(clean, "index.html"), "<html>soymutdb release</html>");
    writeFileSync(resolve(clean, "app.js"), "const b='http://localhost:5175';");

    const ok = await execFileAsync("bash", [
      resolve(REPOSITORY_ROOT, "scripts/check-production-artifact.sh"),
      clean,
    ]);
    expect(ok.stdout).toContain("OK");

    const demo = mkdtempSync(joinTmp("prod-scan-demo-"));
    temporaryDirectories.push(demo);
    writeFileSync(resolve(demo, "sample.html"), "SMDB-00001 Demo fixture");

    // Strict mode must reject demo fixtures.
    await expect(
      execFileAsync("bash", [
        resolve(REPOSITORY_ROOT, "scripts/check-production-artifact.sh"),
        demo,
      ]),
    ).rejects.toMatchObject({ code: 1 });

    // --allow-demo permits the demo markers (used for the gh-pages demo artifact).
    const demoOk = await execFileAsync("bash", [
      resolve(REPOSITORY_ROOT, "scripts/check-production-artifact.sh"),
      demo,
      "--allow-demo",
    ]);
    expect(demoOk.stdout).toContain("OK");
  });
});

describe("build pipeline & env hashing contract", () => {
  it("appends the release-manifest step to the web build chain", () => {
    const pkg = readRepositoryFile("apps/web/package.json");
    expect(pkg).toMatch(/scripts\/release-manifest\.ts/);
  });

  it("hashes SOYMUTDB_RELEASE_ID for the frontend build", () => {
    const turbo = readRepositoryFile("turbo.json");
    expect(turbo).toContain("SOYMUTDB_RELEASE_ID");
  });

  it("pins browser API requests to the artifact release", () => {
    const buildSites = readRepositoryFile("apps/web/scripts/build-sites.ts");
    const main = readRepositoryFile("apps/web/src/main.tsx");
    expect(buildSites).toContain(
      "VITE_SOYMUTDB_RELEASE_ID: process.env.SOYMUTDB_RELEASE_ID",
    );
    expect(main).toContain(
      "setReleaseId(import.meta.env.VITE_SOYMUTDB_RELEASE_ID)",
    );
  });

  it("admin vite config supports VITE_BASE_URL", async () => {
    const source = readRepositoryFile("apps/admin/vite.config.ts");
    expect(source).toContain("loadEnv");
    expect(source).toContain("normalizeBasePath");
    expect(source).toContain("env.VITE_BASE_URL");
  });

  it("jbrowse vite config is base-aware", () => {
    const source = readRepositoryFile("apps/jbrowse/vite.config.ts");
    expect(source).toContain("env.VITE_BASE_URL");
    expect(source).toContain("base:");
  });
});
