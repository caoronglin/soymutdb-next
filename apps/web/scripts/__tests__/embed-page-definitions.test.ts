import { execFile } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { afterEach, describe, expect, it, vi } from "vitest";
import { embedPublishedDefinitions, routeToFile } from "../embed-page-definitions";

const workspaces: string[] = [];
function fixtureDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "soymutdb-ssg-"));
  workspaces.push(dir);
  writeFileSync(join(dir, "index.html"), "<html><head></head><body>SPA</body></html>");
  return dir;
}
afterEach(() => {
  while (workspaces.length) rmSync(workspaces.pop()!, { recursive: true, force: true });
});

const execFileAsync = promisify(execFile);
const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");
const SCRIPT = resolve(REPOSITORY_ROOT, "apps/web/scripts/embed-page-definitions.ts");
const TSX_LOADER = resolve(REPOSITORY_ROOT, "apps/web/node_modules/tsx/dist/loader.mjs");

async function runCliFixture(routes: unknown): Promise<{ distDir: string; requests: string[] }> {
  const directory = fixtureDir();
  const requestLog = join(directory, "requests.log");
  const fetchMock = join(directory, "fetch-mock.mjs");
  writeFileSync(fetchMock, [
    'import { appendFileSync } from "node:fs";',
    'globalThis.fetch = async function(input) {',
    '  appendFileSync(process.env.MOCK_REQUEST_LOG, String(input) + "\\n");',
    '  return new Response(process.env.MOCK_RESPONSE_BODY, { status: 200, headers: { "content-type": "application/json" } });',
    '};',
  ].join("\n"));
  await execFileAsync(process.execPath, ["--import", TSX_LOADER, SCRIPT], {
    cwd: directory,
    env: {
      ...process.env,
      SOYMUTDB_API_URL: "https://fixture.invalid",
      SOYMUTDB_DIST_DIR: directory,
      NODE_ENV: "production",
      MOCK_REQUEST_LOG: requestLog,
      MOCK_RESPONSE_BODY: JSON.stringify(routes),
      NODE_OPTIONS: `--import=${fetchMock}`,
    },
  });
  return {
    distDir: directory,
    requests: readFileSync(requestLog, "utf-8").trim().split("\n").filter(Boolean),
  };
}

describe("published PageDefinition SSG embedding", () => {
  it("consumes a mocked published-routes manifest into nested release files", async () => {
    const distDir = fixtureDir();
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify([
      { route: "/", version: 1, status: "published", definition: { root: { type: "columns" } } },
      { route: "/about-us/team", version: 2, status: "published", definition: { root: { type: "columns" } } },
      { route: "/draft", version: 3, status: "draft", definition: { root: { type: "columns" } } },
      { route: "/../escape", version: 4, status: "published", definition: { root: { type: "columns" } } },
    ]), { status: 200 })) as unknown as typeof fetch;

    await expect(embedPublishedDefinitions({
      apiBase: "https://fixture.invalid",
      distDir,
      production: true,
      fetchImpl,
    })).resolves.toBe(2);

    expect(fetchImpl).toHaveBeenCalledWith(
      "https://fixture.invalid/api/v1/page-definitions/published-routes",
      expect.any(Object),
    );
    expect(readFileSync(join(distDir, "about-us", "team", "index.html"), "utf-8")).toContain('"route":"/about-us/team"');
    expect(readFileSync(join(distDir, "about-us", "team", "index.html"), "utf-8")).toContain('"status":"published"');
    expect(() => readFileSync(join(distDir, "escape", "index.html"))).toThrow();
  });

  it("runs the production CLI against a local mocked HTTP fixture", async () => {
    const { distDir, requests } = await runCliFixture([
      { route: "/field-guide", version: 9, status: "published", definition: { root: { type: "columns" } } },
      { route: "/not-live", version: 10, status: "draft", definition: { root: { type: "columns" } } },
    ]);
    expect(requests).toEqual(["https://fixture.invalid/api/v1/page-definitions/published-routes"]);
    const html = readFileSync(join(distDir, "field-guide", "index.html"), "utf-8");
    expect(html).toContain("rl-page-definition");
    expect(html).toContain('"route":"/field-guide"');
    expect(html).toContain('"status":"published"');
    expect(() => readFileSync(join(distDir, "not-live", "index.html"))).toThrow();
  });

  it("maps only safe route segments to artifact paths", () => {
    expect(routeToFile("/")).toBe("index.html");
    expect(routeToFile("/about-us/team")).toBe(join("about-us", "team", "index.html"));
    for (const unsafe of ["about", "/../escape", "/a//b", "/a_b", "/a?x=1"]) {
      expect(routeToFile(unsafe)).toBeNull();
    }
  });

  it("keeps an offline SPA shell when the manifest cannot be fetched", async () => {
    const distDir = fixtureDir();
    const fetchImpl = vi.fn(async () => { throw new Error("offline"); }) as unknown as typeof fetch;
    await expect(embedPublishedDefinitions({ apiBase: "https://fixture.invalid", distDir, production: true, fetchImpl })).resolves.toBe(0);
    expect(readFileSync(join(distDir, "index.html"), "utf-8")).toContain("SPA");
  });
});
