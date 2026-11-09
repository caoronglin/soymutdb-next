// ABLATION — every routed admin feature page owns a `PageContainer`, and the shell owns none.
//
// Invariant (design §3.1, plan slice A1):
//
// 1. Every page component the router can mount renders inside a `PageContainer`,
//    with its `title`/`subTitle`/`breadcrumb`/`extra` declared there rather than
//    hand-rolled in the page body. The route list is read out of `App.tsx`, not
//    hard-coded, so a page that ships wired but unwrapped fails this guard on
//    arrival instead of quietly reintroducing a second header style.
// 2. Each route is *classified*: it either names the file that owns its
//    `PageContainer`, or it carries a written reason for not having one. A new
//    route that is in neither list is reported, which is what keeps the check
//    from decaying into a list of only the pages somebody remembered.
// 3. The shell does not name the page. The former `PAGE_TITLES` map resolved a
//    title from the pathname and rendered it in `AdminHeader`, which put a
//    second `<h1>` above every wrapped page. One page name, one owner.
//
// Ablation proof: a synthetic route module, an unwrapped page source and a
// re-introduced `PAGE_TITLES` are all asserted to be *reported*, so a green run
// means the check can see a hole rather than passing vacuously.
//
// If this is RED: a page renders its own heading again, or the shell started
// naming pages again, and the console has two authorities for one page name.
import { readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");
const appSource = readFileSync(join(srcRoot, "App.tsx"), "utf8");

/**
 * Comments are stripped before scanning, for the reason
 * `scripts/check_admin_content_architecture.py` gives: these files explain the
 * migration, and a guard that flags the explanation of its own rule is a guard
 * that gets weakened on the first false positive.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

function readSource(path: string): string {
  return stripComments(readFileSync(join(srcRoot, path), "utf8"));
}

/**
 * The route modules `App.tsx` can actually mount, in `lazy(() => import(...))`
 * form: `"./routes/audit"` → `routes/audit`.
 *
 * Read from the router rather than from a list, so renaming or adding a route
 * changes what this guard checks. `imports/index.tsx` re-exports `../imports`,
 * so the module id is the routing truth even when the component is not local.
 */
function routedModules(): string[] {
  return [...appSource.matchAll(/lazy\(\(\) => import\("\.\/(routes\/[^"]+)"\)\)/g)]
    .map((match) => `${match[1]}.tsx`)
    .sort();
}

/**
 * Route modules that deliberately have no `PageContainer`, with the reason.
 *
 * These are not "pages we forgot": they are screens that are not a feature page
 * at all, and wrapping them would add chrome that implies an operator task where
 * there is none.
 */
const NOT_A_FEATURE_PAGE: Record<string, string> = {
  "routes/login.tsx":
    "the sign-in screen — it renders standalone, outside AdminLayout, and has no console behind it to orient",
  "routes/legacy-unavailable.tsx":
    "the ADR-0009 retirement notice — a single `Result` explaining a retired destination, not an operator workflow",
};

/**
 * Route module → the file that renders its `PageContainer`.
 *
 * Not always 1:1. Several routes share one owning component (the five
 * `/settings/*` domains all render `SettingsDomainPage`), which is exactly why
 * the map is written out — a shared owner has to be re-confirmed once, not
 * silently assumed.
 */
const PAGE_CONTAINER_OWNER: Record<string, string> = {
  "routes/index.tsx": "routes/index.tsx",
  "routes/usage-guide.tsx": "routes/usage-guide.tsx",
  "routes/releases.tsx": "routes/releases.tsx",
  "routes/instances.tsx": "routes/instances.tsx",
  "routes/preview-test-data.tsx": "routes/preview-test-data.tsx",
  "routes/imports.tsx": "routes/imports.tsx",
  "routes/imports/new.tsx": "routes/imports/new.tsx",
  "routes/imports/task-detail.tsx": "routes/imports/task-detail.tsx",
  "routes/content.tsx": "routes/content.tsx",
  "routes/media.tsx": "routes/media.tsx",
  "routes/news/index.tsx": "routes/news/index.tsx",
  "routes/news/new.tsx": "routes/news/new.tsx",
  "routes/news/trash.tsx": "routes/news/trash.tsx",
  "routes/news/$id.tsx": "routes/news/$id.tsx",
  "routes/audit.tsx": "routes/audit.tsx",
  "routes/settings.tsx": "routes/settings.tsx",
  "routes/settings/index.tsx": "routes/settings/index.tsx",
  "routes/settings/brand.tsx": "routes/settings/brand.tsx",
  "routes/settings/appearance.tsx": "routes/settings/section-page.tsx",
  "routes/settings/security.tsx": "routes/settings/section-page.tsx",
  "routes/settings/localization.tsx": "routes/settings/section-page.tsx",
  "routes/settings/advanced.tsx": "routes/settings/section-page.tsx",
  "routes/settings/integrations.tsx": "routes/settings/section-page.tsx",
  "routes/features.tsx": "routes/features.tsx",
  "routes/site-control.tsx": "routes/site-control.tsx",
  "routes/page-builder/index.tsx": "routes/page-builder/index.tsx",
  "routes/page-builder/$pageId.tsx": "routes/page-builder/$pageId.tsx",
  "routes/analytics-settings.tsx": "routes/analytics-settings.tsx",
  "routes/publications.tsx": "routes/publications.tsx",
  "routes/table-views.tsx": "routes/table-views.tsx",
  "routes/data-views.tsx": "routes/data-views.tsx",
};

/** Owners that must exist on disk; a stale map entry must not pass vacuously. */
const OWNER_SOURCES = new Map(
  [...new Set(Object.values(PAGE_CONTAINER_OWNER))].map((path) => [path, readSource(path)] as const),
);

/** Route modules that are neither classified nor exempted. */
function unclassifiedRoutes(modules: string[]): string[] {
  return modules.filter(
    (path) => !(path in PAGE_CONTAINER_OWNER) && !(path in NOT_A_FEATURE_PAGE),
  );
}

/** Classified routes whose owning file never renders a `PageContainer`. */
function routesMissingPageContainer(modules: string[]): string[] {
  return modules
    .filter((path) => path in PAGE_CONTAINER_OWNER)
    .filter((path) => !/<PageContainer\b/.test(OWNER_SOURCES.get(PAGE_CONTAINER_OWNER[path]) ?? ""))
    .sort();
}

describe("admin PageContainer coverage (A1)", () => {
  it("finds the routed page modules it depends on", () => {
    // If this fails the guards below are vacuous, which is worse than no guard.
    const modules = routedModules();
    expect(modules.length).toBeGreaterThan(20);
    expect(modules).toContain("routes/audit.tsx");
    expect(modules).toContain("routes/news/$id.tsx");
  });

  it("classifies every routed page as wrapped or deliberately exempt", () => {
    expect(unclassifiedRoutes(routedModules())).toEqual([]);
  });

  it("gives every classified route a page that renders a PageContainer", () => {
    expect(routesMissingPageContainer(routedModules())).toEqual([]);
  });

  it("reads an owner map that points at files that exist", () => {
    for (const [path, source] of OWNER_SOURCES) {
      expect(source.length, relative(srcRoot, join(srcRoot, path))).toBeGreaterThan(0);
    }
    // No exemption may quietly claim a page that does not exist.
    for (const path of Object.keys(NOT_A_FEATURE_PAGE)) {
      expect(() => readFileSync(join(srcRoot, path), "utf8"), path).not.toThrow();
      expect(NOT_A_FEATURE_PAGE[path].length, path).toBeGreaterThan(20);
    }
  });

  it("stops the shell from naming the page a second time", () => {
    // `PAGE_TITLES` + `<AdminHeader title={...}>` gave the console a header that
    // was independent of the page, so the same name appeared in the bar and in
    // the PageContainer, and a route missing from the map showed nothing at all.
    const root = readSource("routes/__root.tsx");
    expect(root).not.toMatch(/PAGE_TITLES/);
    expect(root).not.toMatch(/<AdminHeader\s+title=/);
    // Global navigation controls are shell props; page titles still belong to PageContainer.
    expect(root).toMatch(/<AdminHeader\b[^>]*\/>/);

    const header = readSource("components/admin-header.tsx");
    expect(header).not.toMatch(/title\?:\s*string/);
    expect(header).not.toMatch(/<h1\b/);
  });

  it("detects an unwrapped page, an unclassified route and a re-introduced title (ablation)", () => {
    // 1. A module the router mounts but that is classified nowhere must be
    //    reported. The probe is a real, currently-unmounted module rather than a
    //    synthetic dynamic-import string, because
    //    `scripts/test_ci_job_contracts.py` fails any test file whose dynamic
    //    import text does not resolve — inventing a path here would blind a
    //    second gate to make this one pass.
    const orphan = "routes/content/pages-tab.tsx";
    expect(readSource(orphan).length, orphan).toBeGreaterThan(0);
    expect(unclassifiedRoutes([orphan])).toEqual([orphan]);

    // ...and the extraction the guard depends on still reads the real router,
    // where nothing is unclassified.
    const discovered = [
      ...appSource.matchAll(/lazy\(\(\) => import\("\.\/(routes\/[^"]+)"\)\)/g),
    ].map((match) => `${match[1]}.tsx`);
    expect(discovered.length).toBeGreaterThan(20);
    expect(unclassifiedRoutes(discovered)).toEqual([]);

    // 2. A classified route whose owner lost the wrapper must be reported, and
    //    one that kept it must not.
    const wrapped = readSource("routes/releases.tsx");
    const unwrapped = stripComments('<div className="space-y-6"><Typography.Title level={2}>Releases</Typography.Title></div>');
    expect(routesMissingPageContainer(["routes/releases.tsx"])).toEqual([]);
    expect(/<PageContainer\b/.test(wrapped)).toBe(true);
    expect(/<PageContainer\b/.test(unwrapped)).toBe(false);

    // 3. A re-introduced `PAGE_TITLES` must be caught by the same rule that
    //    catches a hand-rolled header.
    const revertedShell = 'const PAGE_TITLES = { "/": { key: "admin.dashboard.title" } };';
    expect(/PAGE_TITLES/.test(revertedShell)).toBe(true);
    expect(/<AdminHeader\s+title=/.test('<AdminHeader title={title} />')).toBe(true);
    expect(/<AdminHeader\s+title=/.test("<AdminHeader />")).toBe(false);

    // 4. Comment stripping must not blind the scan to its own rule text.
    expect(/<PageContainer\b/.test(stripComments("// <PageContainer> is the rule\nconst x = 1;"))).toBe(false);
  });
});
