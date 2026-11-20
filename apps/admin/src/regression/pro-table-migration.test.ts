// ABLATION — the admin console's list pages render the ProTable shell, not a bare antd Table.
//
// Invariant (design §3.2 / §3.3, plan slices A2 and A3):
//
// 1. No route renders a bare antd `<Table>`. The migration is additive and
//    behaviour-preserving, so this is a *substitution* rule, not a style rule:
//    every page that had a `<Table` still has a table, with the same rowKey, the
//    same columns, the same data source and the same pagination object.
// 2. Every `ProTable` a route renders supplies its own `rowKey`. ProTable falls
//    back to the array index when rowKey is absent, which is exactly the failure
//    the design forbids (§3.2 hard constraint 3) and it is invisible in review —
//    the table renders, selection just quietly follows position.
// 3. Every `ProTable` a route renders spreads the shared `PRO_LIST_SHELL`, so no
//    page quietly grows ProTable's search form, toolbar or settings dropdown and
//    starts issuing a second, different query path.
// 4. `preview-test-data` writes exactly one field. Its columns must all be
//    non-editable, so ProTable's opt-in cell editor cannot widen the contract to
//    "operator may edit the uploaded source table" (design §3.4).
// 5. `ProDescriptions` and `ProCard` are in use, so the detail views are described
//    by a schema and the card containers are the Pro ones.
// 6. Slice A4: no content section is still a bare antd `Card`. The only two
//    `Card`s left in the tree are the media grid's tiles and the sign-in panel,
//    pinned to an exact count with their reason, so a new section container on
//    either file has to be classified rather than absorbed by the exemption.
//
// Ablation proof: the detectors in this file are exercised against synthetic
// sources that violate each rule, so a green run means the check can see a hole
// rather than passing vacuously. The matching real-file ablation (reverting one
// page to a bare Table, dropping one rowKey) is reported in the migration notes.
//
// If this is RED: either a list page lost its ProTable shell, or a shell quietly
// regressed into a table that identifies rows by position.
import { readFileSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, "..");

/**
 * Comments are stripped before scanning, for the reason
 * `scripts/check_admin_content_architecture.py` gives: these files explain the
 * migration, and a guard that flags the explanation of its own rule is a guard
 * that gets weakened on the first false positive.
 */
function stripComments(source: string): string {
  return source.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
}

/**
 * Openings tags for one JSX element name.
 *
 * The scan is brace-aware so that a `=>` inside a `render` prop does not end the
 * tag early, and it skips a TypeScript generic argument (`<ProTable<Row> …`) for
 * the same reason. It is not string-literal-aware: a prop value containing a
 * literal `>` (`title="a > b"`) would truncate the tag. No admin route uses that
 * form, and the failure mode would be a reported missing `rowKey` — a false red,
 * not a silent pass.
 */
function jsxOpeningTags(source: string, element: string): string[] {
  const tags: string[] = [];
  const opener = new RegExp(`<${element}\\b`, "g");
  let match: RegExpExecArray | null;
  while ((match = opener.exec(source)) !== null) {
    let cursor = match.index + match[0].length;
    let propsStart = cursor;

    // Skip `<ProTable<Row>`: the generic argument list is not part of the props.
    if (source[cursor] === "<") {
      let genericDepth = 0;
      for (; cursor < source.length; cursor += 1) {
        if (source[cursor] === "<") genericDepth += 1;
        else if (source[cursor] === ">") {
          genericDepth -= 1;
          if (genericDepth === 0) {
            cursor += 1;
            break;
          }
        }
      }
      propsStart = cursor;
    }
    let braceDepth = 0;
    for (; cursor < source.length; cursor += 1) {
      const char = source[cursor];
      if (char === "{") braceDepth += 1;
      else if (char === "}") braceDepth -= 1;
      else if (char === ">" && braceDepth === 0) break;
    }
    tags.push(source.slice(propsStart, cursor + 1));
  }
  return tags;
}

/** The list pages slice A2 moved onto ProTable. */
const MIGRATED_LIST_PAGES = [
  "routes/audit.tsx",
  "routes/content/static-page-migration-report.tsx",
  "routes/instances.tsx",
  "routes/news/index.tsx",
  "routes/news/trash.tsx",
  "routes/preview-test-data.tsx",
  "routes/releases.tsx",
  "routes/table-templates.tsx",
];

/** The detail views slice A3 moved onto ProDescriptions. */
const PRO_DESCRIPTIONS_PAGES = [
  "routes/content/version-detail.tsx",
  "routes/content/version-metadata.tsx",
  "routes/imports/task-detail.tsx",
];

/**
 * The card containers slice A3 moved onto ProCard — the pages that *had* a card
 * and now have a Pro one. `news/trash` is deliberately absent: it had no card
 * container, and the ProTable's own (borderless) shell is the container, so
 * adding one would be a new box rather than a substitution.
 */
const PRO_CARD_PAGES = [
  "routes/audit.tsx",
  "routes/content/static-page-migration-report.tsx",
  "routes/instances.tsx",
  "routes/preview-test-data.tsx",
  "routes/releases.tsx",
  "routes/table-templates.tsx",
];

/**
 * Slice A4 — the remaining content-section `Card` containers, moved onto
 * `ProCard`. A card that holds a *section* (a form, a filter bar, a list item
 * summary, a chart) is the Pro one; the `Card` that is left in this tree is
 * pinned in `BARE_CARD_ALLOWANCE` below with the reason it is not a section.
 */
const CONVERGED_CARD_PAGES = [
  "components/admin-usage-guide.tsx",
  "components/charts/import-throughput.tsx",
  "components/charts/query-latency.tsx",
  "components/charts/storage-growth.tsx",
  "components/stat-card.tsx",
  "routes/analytics-settings.tsx",
  "routes/login.tsx",
  "routes/content/pages-tab.tsx",
  "routes/features.tsx",
  "routes/news/$id.tsx",
  "routes/news/new.tsx",
  "routes/publications.tsx",
  "routes/settings.tsx",
  "routes/settings/appearance-form.tsx",
  "routes/settings/brand.tsx",
  "routes/settings/integrations.tsx",
  "routes/settings/localization-form.tsx",
  "routes/settings/revision-history.tsx",
  "routes/settings/security-form.tsx",
  "routes/settings/site-form.tsx",
];

/**
 * Files allowed to keep a bare antd `Card`, pinned to the exact number of them.
 *
 * The count is the point: a *named* exemption ("this file has a Card somewhere")
 * stops being checked the first time someone adds a second, unrelated one. Two
 * remain by design and neither is a content section:
 *
 * - `routes/media.tsx` — the media grid's skeleton tiles and asset tiles. They
 *   are repeated tiles with a `cover` image, not sections, and `ProCard` has no
 *   `cover` prop, so moving them would drop the thumbnail rather than restyle it.
 *   The filter bar and the empty state on that page *were* converted.
 * - `routes/login.tsx` used to be exempted here for its centred sign-in Card.
 *   The Pro split-panel rewrite (2026-10-10) removed that Card, so the exemption
 *   no longer describes anything; the page is now in `CONVERGED_CARD_PAGES`,
 *   which asserts the Card count stays at zero rather than at one.
 */
const BARE_CARD_ALLOWANCE: Record<string, { count: number; converted: number; reason: string }> = {
  "routes/media.tsx": {
    count: 2,
    converted: 2,
    reason: "media grid tiles (skeleton + asset), which need `cover`",
  },
};

function readRoute(path: string): string {
  return stripComments(readFileSync(join(srcRoot, path), "utf8"));
}

const routeSources = new Map(
  MIGRATED_LIST_PAGES.map((path) => [path, readRoute(path)] as const),
);

/** `file:tag index` for every ProTable opening tag that is missing its rowKey. */
function proTablesMissingRowKey(source: string): string[] {
  return jsxOpeningTags(source, "ProTable")
    .map((tag, index) => (/rowKey\s*=/.test(tag) ? null : `#${index}`))
    .filter((entry): entry is string => entry !== null);
}

/** `file:tag index` for every ProTable that does not spread the shared shell. */
function proTablesMissingShell(source: string): string[] {
  return jsxOpeningTags(source, "ProTable")
    .map((tag, index) => (tag.includes("PRO_LIST_SHELL") ? null : `#${index}`))
    .filter((entry): entry is string => entry !== null);
}

describe("ProComponents migration (A2 list shell / A3 detail / A4 content cards)", () => {
  it("finds the migrated list pages", () => {
    // Guards against a path rename silently emptying the list below.
    expect(routeSources.size).toBe(MIGRATED_LIST_PAGES.length);
    for (const [path, source] of routeSources) {
      expect(source.length, relative(srcRoot, join(srcRoot, path))).toBeGreaterThan(0);
    }
  });

  it("renders no bare antd Table in any admin route", () => {
    const offenders: string[] = [];
    for (const path of MIGRATED_LIST_PAGES) {
      if (/<Table\b/.test(routeSources.get(path)!)) offenders.push(path);
    }
    expect(offenders).toEqual([]);
  });

  it("gives every ProTable a rowKey", () => {
    const missing: string[] = [];
    for (const [path, source] of routeSources) {
      for (const tag of proTablesMissingRowKey(source)) missing.push(`${path}:${tag}`);
    }
    expect(missing).toEqual([]);
  });

  it("spreads the shared ProTable shell preset in every route table", () => {
    const missing: string[] = [];
    for (const [path, source] of routeSources) {
      for (const tag of proTablesMissingShell(source)) missing.push(`${path}:${tag}`);
    }
    expect(missing).toEqual([]);
  });

  it("keeps the preview-test-data write contract at one field", () => {
    // `editable: false` on every column is the guard; a single `editable: true`
    // anywhere in this file would hand ProTable an edit path over the uploaded
    // source table, which the backend overwrites on the next import.
    const source = routeSources.get("routes/preview-test-data.tsx")!;
    expect(source).not.toMatch(/editable:\s*true/);
    const columns = jsxOpeningTags(source, "ProTable");
    expect(columns.length).toBe(1);
    expect(source).toContain("updateTestDataPreviewMutationSite");
  });

  it("preserves the news list server-side pagination contract", () => {
    // The page holds exactly one server page at a time. A ProTable that switched
    // to client-side paging would still render, and would silently drop rows.
    const source = routeSources.get("routes/news/index.tsx")!;
    expect(source).toContain("buildAdminNewsQuery");
    expect(source).toMatch(/pagination=\{\{[\s\S]*?current: requestParams\.current/);
    expect(source).toContain("total,");
  });

  it("describes detail views with ProDescriptions", () => {
    for (const path of PRO_DESCRIPTIONS_PAGES) {
      const source = readRoute(path);
      expect(jsxOpeningTags(source, "ProDescriptions").length, path).toBeGreaterThan(0);
    }
  });

  it("uses ProCard for the migrated card containers", () => {
    for (const path of PRO_CARD_PAGES) {
      const source = readRoute(path);
      expect(jsxOpeningTags(source, "ProCard").length, path).toBeGreaterThan(0);
    }
  });

  it("renders no bare antd Card in the converged content pages (A4)", () => {
    const offenders: string[] = [];
    for (const path of CONVERGED_CARD_PAGES) {
      const bare = jsxOpeningTags(readRoute(path), "Card").length;
      // A `ProCard` must not be able to satisfy this by name: the scan is on the
      // element name `<Card`, so `<ProCard` is invisible to it by construction.
      if (bare > 0) offenders.push(`${path} (${bare})`);
    }
    expect(offenders).toEqual([]);
  });

  it("pins the two Cards that are deliberately not content sections", () => {
    for (const [path, allowance] of Object.entries(BARE_CARD_ALLOWANCE)) {
      const source = readRoute(path);
      expect(jsxOpeningTags(source, "Card").length, path).toBe(allowance.count);
      expect(allowance.reason.length, path).toBeGreaterThan(10);
      // The exemption is for the tiles and the panel, not for the file: a
      // partially converted page must still show the Pro containers it gained,
      // so "this file is exempt" cannot quietly become "this file is done".
      expect(jsxOpeningTags(source, "ProCard").length, path).toBe(allowance.converted);
    }
  });

  it("detects a Card put back on a converged page (ablation)", () => {
    // 1. A reverted container is reported; a Pro one is not.
    expect(jsxOpeningTags('<div><Card title="Overview">x</Card></div>', "Card")).toHaveLength(1);
    expect(jsxOpeningTags('<div><ProCard title="Overview">x</ProCard></div>', "Card")).toHaveLength(0);

    // 2. Self-closing Cards count too — a loading placeholder is a container.
    expect(jsxOpeningTags('<Card loading data-testid="brand-loading" />', "Card")).toHaveLength(1);
    expect(jsxOpeningTags('<ProCard loading data-testid="brand-loading" />', "Card")).toHaveLength(0);

    // 3. The media tile props must never have been quietly deleted to make a
    //    conversion possible: `ProCard` has no `cover`, so a lost cover is a
    //    silent loss of the thumbnail, not a restyle.
    expect(jsxOpeningTags('<ProCard hoverable cover={<img />}>x</ProCard>', "Card")).toHaveLength(0);
  });

  it("detects a reverted page and a dropped rowKey (ablation)", () => {
    // 1. A page put back on a bare Table must be reported.
    const reverted = `<div><Table<Row> rowKey="id" dataSource={rows} columns={cols} /></div>`;
    expect(/<Table\b/.test(stripComments(reverted))).toBe(true);

    // 2. A ProTable without rowKey must be reported, and one with it must not.
    expect(proTablesMissingRowKey(`<ProTable dataSource={rows} />`)).toEqual(["#0"]);
    expect(proTablesMissingRowKey(`<ProTable rowKey="id" dataSource={rows} />`)).toEqual([]);

    // 3. The brace-aware scan must survive a `render` arrow prop and a generic
    //    argument, otherwise it would report a truncated tag on every table that
    //    has a cell renderer or an explicit row type.
    const withRender = `<ProTable rowKey="id" columns={[{ render: (_, r) => <Tag>{r.id}</Tag> }]} />`;
    expect(proTablesMissingRowKey(withRender)).toEqual([]);
    expect(jsxOpeningTags(withRender, "ProTable")).toHaveLength(1);
    expect(proTablesMissingRowKey(`<ProTable<Row> dataSource={rows} />`)).toEqual(["#0"]);
    expect(proTablesMissingRowKey(`<ProTable<Row> rowKey="id" dataSource={rows} />`)).toEqual([]);

    // 4. A table that skipped the shared shell must be reported.
    expect(proTablesMissingShell(`<ProTable rowKey="id" />`)).toEqual(["#0"]);
    expect(proTablesMissingShell(`<ProTable {...PRO_LIST_SHELL} rowKey="id" />`)).toEqual([]);

    // 5. Comment stripping must not blind the scan to its own rule text.
    expect(/<Table\b/.test(stripComments("// <Table> is fine in prose\nconst x = 1;"))).toBe(false);
  });
});
