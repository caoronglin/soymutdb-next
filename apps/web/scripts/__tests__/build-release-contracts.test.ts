import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

const REPOSITORY_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "../../../..");

function readRepositoryFile(path: string): string {
  return readFileSync(resolve(REPOSITORY_ROOT, path), "utf8");
}

function readJson(path: string): Record<string, unknown> {
  return JSON.parse(readRepositoryFile(path)) as Record<string, unknown>;
}

describe("root command contracts", () => {
  it("targets scripts that exist in the selected workspaces", () => {
    const rootPackage = readJson("package.json") as {
      scripts: Record<string, string>;
    };

    expect(rootPackage.scripts["dev:admin"]).toBe(
      "pnpm --filter @soymutdb/admin dev",
    );
    expect(rootPackage.scripts["build:ssg"]).toBe(
      "pnpm --filter @soymutdb/web ssg:build",
    );
  });
});

describe("Turbo build environment contract", () => {
  it("hashes every environment variable that changes a frontend build", () => {
    const turbo = readJson("turbo.json") as {
      globalEnv?: string[];
      tasks: { build: { env?: string[] } };
    };
    const hashedBuildEnv = new Set([
      ...(turbo.globalEnv ?? []),
      ...(turbo.tasks.build.env ?? []),
    ]);

    expect([...hashedBuildEnv]).toEqual(
      expect.arrayContaining([
        "CI",
        "CONTENT_SNAPSHOT_URL",
        "NODE_ENV",
        "SITE_BASE_URL",
        "SOYMUTDB_API_URL",
        "SOYMUTDB_FETCH_TIMEOUT",
        "SOYMUTDB_SITE_URL",
        "VITE_API_BASE_URL",
        "VITE_BASE_URL",
        "VITE_CLOUDFLARE_ANALYTICS_TOKEN",
        "VITE_DEMO_MODE",
        "VITE_DEPLOYMENT_MODE",
        "VITE_JBROWSE_BASE_URL",
        "VITE_JBROWSE_DATA_URL",
        "VITE_JBROWSE_URL",
        "VITE_PUBLIC_URL",
        "VITE_SW_ENABLED",
      ]),
    );
  });
});

describe("SSG route contracts", () => {
  it("builds the canonical browser route and retains a legacy redirect", () => {
    const source = readRepositoryFile("apps/web/scripts/ssg-build.ts");
    const pagesSource = source.match(/const PAGES = \[([\s\S]*?)\];/)?.[1] ?? "";
    const pages = [...pagesSource.matchAll(/"([^"]+)"/g)].map((match) => match[1]);

    expect(pages).toContain("browser");
    expect(pages).not.toContain("browse");
    expect(source).toContain('writeLegacyRedirect("browse", "browser"');
  });

  it("uses /browser in generated links and sitemap entries", () => {
    const samples = readRepositoryFile("apps/web/scripts/generate-samples.ts");
    const fallback = readRepositoryFile("apps/web/scripts/fallback-data.ts");

    expect(samples).toContain('"browser"');
    expect(samples).not.toMatch(/\["", "about", "browse",/);
    expect(fallback).toContain('sampleAppUrl(basePath, "browser")');
    expect(fallback).not.toContain('href="/browser"');
    expect(fallback).not.toContain('href="/browse"');
  });
});

describe("SSG-to-SPA ownership contract", () => {
  const originalEnvironment = {
    VITE_API_BASE_URL: process.env.VITE_API_BASE_URL,
    VITE_BASE_URL: process.env.VITE_BASE_URL,
    VITE_JBROWSE_BASE_URL: process.env.VITE_JBROWSE_BASE_URL,
  };

  let template: typeof import("../base-template");

  beforeAll(async () => {
    process.env.VITE_API_BASE_URL = "http://localhost:8000";
    process.env.VITE_JBROWSE_BASE_URL = "http://localhost:5175";
    process.env.VITE_BASE_URL = "/portal/";
    vi.resetModules();
    template = await import("../base-template");
  });

  afterAll(() => {
    for (const [name, value] of Object.entries(originalEnvironment)) {
      if (value === undefined) delete process.env[name];
      else process.env[name] = value;
    }
  });

  const assets = {
    jsEntry: "assets/app.js",
    cssEntry: "assets/app.css",
    preloads: [],
    fontPreloads: [],
  };

  it("keeps generated HTML outside an empty React root", () => {
    const html = template.renderBaseTemplate({
      title: "Static fallback",
      description: "Static fallback",
      widgetsHtml: "<article>Build-time HTML</article>",
      assets,
    });

    expect(html).toContain(
      '<div id="ssg-content" data-render-owner="static"><article>Build-time HTML</article></div>',
    );
    expect(html).toContain('<div id="root" hidden></div>');
    expect(html).not.toContain('<div id="root"><article>Build-time HTML</article>');
  });

  it("can emit a standalone page when no SPA route exists", () => {
    const options = {
      title: "Standalone sample",
      description: "Standalone sample",
      widgetsHtml: "<article>Sample</article>",
      assets,
      spaEntrypoint: false,
    };
    const html = template.renderBaseTemplate(options);

    expect(html).toContain('<div id="ssg-content" data-render-owner="static">');
    expect(html).not.toContain('id="root"');
    expect(html).not.toContain("assets/app.js");
    expect(html).toContain("<script>\n// Widget loader:");
  });

  it("prevents JSON-LD script breakout and escapes URL attributes", () => {
    const html = template.renderBaseTemplate({
      title: "Structured data",
      description: "Structured data",
      canonical: 'https://db.example.org/sample?value="unsafe"&next=1',
      jsonLd: { description: "</script><script>window.pwned=1</script>" },
      assets,
    });

    expect(html).not.toContain("</script><script>window.pwned=1</script>");
    expect(html).toContain(
      "\\u003c/script\\u003e\\u003cscript\\u003ewindow.pwned=1\\u003c/script\\u003e",
    );
    expect(html).toContain(
      'href="https://db.example.org/sample?value=&quot;unsafe&quot;&amp;next=1"',
    );
  });

  it("renders a base-aware compatibility redirect", () => {
    const module = template as typeof template & {
      renderRedirectTemplate?: (targetPath: string) => string;
    };

    expect(module.renderRedirectTemplate).toBeTypeOf("function");
    if (!module.renderRedirectTemplate) return;

    const html = module.renderRedirectTemplate("browser");
    expect(html).toContain("/portal/browser");
    expect(html).toContain("window.location.search");
    expect(html).toContain("window.location.hash");
  });

  it("keeps fallback HTML visible until the React tree commits", async () => {
    const runtimeUrl = new URL("../ssg-runtime.ts", import.meta.url).href;
    const runtime = (await import(/* @vite-ignore */ runtimeUrl)) as {
      prepareSsgHandoff: (
        root: HTMLElement,
        document: Document,
      ) => () => void;
    };
    const staticContent = {
      remove: vi.fn(),
    } as unknown as HTMLElement;
    const root = { hidden: false } as HTMLElement;
    const documentStub = {
      getElementById: vi.fn((id: string) =>
        id === "ssg-content" ? staticContent : null,
      ),
    } as unknown as Document;

    const completeHandoff = runtime.prepareSsgHandoff(root, documentStub);
    expect(root.hidden).toBe(true);
    expect(staticContent.remove).not.toHaveBeenCalled();

    completeHandoff();
    completeHandoff();
    expect(staticContent.remove).toHaveBeenCalledOnce();
    expect(root.hidden).toBe(false);
  });
});
