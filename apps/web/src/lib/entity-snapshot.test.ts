import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { describe, expect, it } from "vitest";

import {
  ENTITY_SNAPSHOT_SCHEMA_VERSION,
  EntitySnapshotError,
  assertEntitySnapshotRelease,
  normalizeEntitySnapshot,
  planEntityDocuments,
} from "./entity-snapshot";
import { injectStaticContent } from "./static-content-render";

const GENE = {
  kind: "gene",
  public_id: "Glyma.01G000100",
  symbol: "GLYMA01G000100",
  assembly_id: "1",
  assembly_name: "Wm82.a4.v1",
  release_id: 7,
  chromosome: "chr01",
  start: 100,
  end: 200,
  strand: "+",
  title: "Glyma.01G000100 — Gene — SoyMutDB",
  description: "A released gene record.",
};

function snapshot(entities: unknown[] = [GENE], overrides: Record<string, unknown> = {}) {
  return {
    schema_version: ENTITY_SNAPSHOT_SCHEMA_VERSION,
    generated_at: "2026-01-01T00:00:00Z",
    site_variant: "external",
    entities,
    ...overrides,
  };
}

describe("normalizeEntitySnapshot", () => {
  it("keeps only the whitelisted public fields", () => {
    const normalized = normalizeEntitySnapshot({
      ...snapshot([{ ...GENE, internal_id: "INT-1", status: "draft", extra: { x: 1 } }]),
    });
    expect(normalized.entities).toHaveLength(1);
    expect(normalized.entities[0]).toEqual(GENE);
    // The persistence key and workflow state are never copied into a published
    // document, whatever the upstream payload carried.
    expect(Object.keys(normalized.entities[0])).not.toContain("internal_id");
    expect(Object.keys(normalized.entities[0])).not.toContain("status");
  });

  it("fails closed on an unknown schema, variant or kind", () => {
    expect(() => normalizeEntitySnapshot(snapshot([GENE], { schema_version: 2 }))).toThrow(
      EntitySnapshotError,
    );
    expect(() => normalizeEntitySnapshot(snapshot([GENE], { site_variant: "internal" }))).toThrow(
      EntitySnapshotError,
    );
    expect(() => normalizeEntitySnapshot(snapshot([{ ...GENE, kind: "mutant" }]))).toThrow(
      EntitySnapshotError,
    );
  });

  it("refuses an identifier that could escape its document directory", () => {
    for (const publicId of ["../secrets", "a/b", ".hidden", "", "Glyma 01"]) {
      expect(() =>
        normalizeEntitySnapshot(snapshot([{ ...GENE, public_id: publicId }])),
      ).toThrow(EntitySnapshotError);
    }
  });

  it("refuses coordinates that are not a 1-based inclusive interval", () => {
    expect(() => normalizeEntitySnapshot(snapshot([{ ...GENE, start: 0 }]))).toThrow(
      EntitySnapshotError,
    );
    expect(() => normalizeEntitySnapshot(snapshot([{ ...GENE, start: 200, end: 100 }]))).toThrow(
      EntitySnapshotError,
    );
    expect(() => normalizeEntitySnapshot(snapshot([{ ...GENE, start: 1.5 }]))).toThrow(
      EntitySnapshotError,
    );
  });

  it("refuses a repeated entity instead of writing one document twice", () => {
    expect(() => normalizeEntitySnapshot(snapshot([GENE, GENE]))).toThrow(/repeats/);
  });

  it("accepts an empty entity list as the fail-closed default", () => {
    expect(normalizeEntitySnapshot(snapshot([])).entities).toEqual([]);
  });
});

describe("assertEntitySnapshotRelease", () => {
  it("requires every entry to belong to the release the build pins", () => {
    const normalized = normalizeEntitySnapshot(snapshot());
    expect(() => assertEntitySnapshotRelease(normalized, 7)).not.toThrow();
    // An unpinned build publishes whatever the snapshot says.
    expect(() => assertEntitySnapshotRelease(normalized, undefined)).not.toThrow();
    expect(() => assertEntitySnapshotRelease(normalized, 8)).toThrow(/release_id=7/);
  });
});

describe("planEntityDocuments", () => {
  it("materialises one document per entity, with a real body", () => {
    const documents = planEntityDocuments(normalizeEntitySnapshot(snapshot()));
    expect(documents).toHaveLength(1);
    const [document] = documents;
    expect(document.path).toBe("/genes/Glyma.01G000100");
    expect(document.templatePath).toBe("/genes/:geneId");
    expect(document.relativePath).toBe("genes/Glyma.01G000100/index.html");
    expect(document.title).toBe(GENE.title);
    expect(document.description).toBe(GENE.description);

    // First-paint content: identifier, coordinates, strand, assembly, release.
    expect(document.mainHtml).toContain("<h1");
    expect(document.mainHtml).toContain("Glyma.01G000100");
    expect(document.mainHtml).toContain("chr01:100–200");
    expect(document.mainHtml).toContain("Wm82.a4.v1 (id 1)");
    expect(document.mainHtml).toContain(">7<");
    // Never the no-JS apology: this document has content of its own.
    expect(document.mainHtml).not.toContain("enable JavaScript");
  });

  it("states coordinates with separators and no locale dependency", () => {
    const [document] = planEntityDocuments(
      normalizeEntitySnapshot(snapshot([{ ...GENE, chromosome: "chr02", start: 20450, end: 21890 }])),
    );
    expect(document.mainHtml).toContain("chr02:20,450–21,890");
  });

  it("links back through the deployment base path", () => {
    const [rootDocument] = planEntityDocuments(normalizeEntitySnapshot(snapshot()));
    expect(rootDocument.mainHtml).toContain('href="/genes"');
    const [subPathDocument] = planEntityDocuments(normalizeEntitySnapshot(snapshot()), {
      basePath: "/soymutdb-next/",
    });
    expect(subPathDocument.mainHtml).toContain('href="/soymutdb-next/genes"');
  });

  it("escapes every value it writes into the document", () => {
    const [document] = planEntityDocuments(
      normalizeEntitySnapshot(
        snapshot([{ ...GENE, symbol: "<script>alert(1)</script>", description: 'A & "B"' }]),
      ),
    );
    expect(document.mainHtml).not.toContain("<script>");
    expect(document.mainHtml).toContain("&lt;script&gt;");
    expect(document.mainHtml).toContain("A &amp; &quot;B&quot;");
  });

  it("emits nothing for an empty snapshot, so no record page is prerendered", () => {
    expect(planEntityDocuments(normalizeEntitySnapshot(snapshot([])))).toEqual([]);
  });
});

/**
 * The one invariant that keeps a prerendered record from being read twice.
 *
 * `generate-static-routes.ts` writes the entity body into the built shell with
 * `injectStaticContent()`, i.e. *inside* `#root`. The portal then boots with
 * `ReactDOM.createRoot` (Umi's client renderer), which takes that node over and
 * discards its children on the first commit. So a JS client sees the app's own
 * back-link once, and a no-JS client sees the static one once — never both.
 *
 * The test mounts a stand-in for the route's own back-link exactly the way the
 * real boot does (createRoot over the same container), so a static body moved
 * outside `#root` — the sibling placement the shell fallback uses — fails here
 * with two `a[href="/genes"]` instead of one.
 */
describe("prerendered entity document + mounted app", () => {
  const SHELL =
    '<!doctype html><html><head><title>Glyma.01G000100 — Gene — SoyMutDB</title></head>' +
    '<body><div id="root"></div></body></html>';

  it("shows exactly one back-link navigation before and after the app mounts", async () => {
    const [record] = planEntityDocuments(normalizeEntitySnapshot(snapshot()));
    const parsed = new DOMParser().parseFromString(
      injectStaticContent(SHELL, record.mainHtml, ""),
      "text/html",
    );
    const container = parsed.getElementById("root")!;
    document.body.append(document.adoptNode(container));

    // No-JS client: the static body is the page, with its real facts.
    expect(container.querySelectorAll("[data-rl-static='entity']")).toHaveLength(1);
    expect(container.querySelectorAll('a[href="/genes"]')).toHaveLength(1);
    expect(container.textContent).toContain("Glyma.01G000100");
    expect(container.textContent).toContain("chr01:100–200");
    expect(container.textContent).toContain("Wm82.a4.v1");

    // JS client: the same container is handed to createRoot, like the boot.
    (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
    let root: Root | undefined;
    await act(async () => {
      root = createRoot(container);
      root.render(
        React.createElement(
          "nav",
          { "data-testid": "spa-back" },
          React.createElement("a", { href: "/genes" }, "← Gene search"),
        ),
      );
    });

    expect(container.querySelectorAll("[data-rl-static='entity']")).toHaveLength(0);
    // One navigation: the app's. The static body did not survive beside it.
    expect(document.querySelectorAll('a[href="/genes"]')).toHaveLength(1);
    expect(document.querySelectorAll(".rl-entity-back")).toHaveLength(0);

    await act(async () => root?.unmount());
    container.remove();
  });
});
