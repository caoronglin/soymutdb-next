// @vitest-environment jsdom
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import type { PageDefinition } from "@soymutdb/shared";

import { readPageDefinitionBootstrap, pageDefinitionKey, resolveFallbackDefinition } from "../loader";

vi.mock("@soymutdb/api-client", () => ({
  getPageDefinition: vi.fn(),
}));

import { getPageDefinition } from "@soymutdb/api-client";

const SAMPLE: PageDefinition = {
  title_key: "nav.home",
  root: { type: "columns", props: { columns: 1 }, children: [] },
};

function setBootstrap(payload: unknown) {
  const el = document.createElement("script");
  el.id = "rl-page-definition";
  el.type = "application/json";
  el.textContent = JSON.stringify(payload);
  document.head.appendChild(el);
  return el;
}

describe("page-definition loader", () => {
  beforeEach(() => {
    document.head.querySelectorAll("#rl-page-definition").forEach((n) => n.remove());
    vi.mocked(getPageDefinition).mockReset();
  });

  afterEach(() => {
    document.head.querySelectorAll("#rl-page-definition").forEach((n) => n.remove());
  });

  it("reads a valid bootstrap payload", () => {
    const el = setBootstrap({
      route: "/",
      version: 1,
      version_id: "v1",
      definition: SAMPLE,
      generated_at: "2026-01-01T00:00:00Z",
    });
    const boot = readPageDefinitionBootstrap();
    expect(boot?.route).toBe("/");
    expect(boot?.version).toBe(1);
    expect(boot?.definition).toEqual({
      schema_version: 2,
      ...SAMPLE,
      data_sources: [],
      theme_id: "scientific-light",
      layouts: { desktop: {}, tablet: {}, mobile: {} },
    });
    el.remove();
  });

  it("returns null for a missing or malformed bootstrap", () => {
    expect(readPageDefinitionBootstrap()).toBeNull();
    setBootstrap({ route: "/", version: "not-a-number", definition: SAMPLE });
    expect(readPageDefinitionBootstrap()).toBeNull();
  });

  it("rejects a bootstrap whose definition has no root", () => {
    setBootstrap({ route: "/", version: 1, definition: { title_key: "x" } });
    expect(readPageDefinitionBootstrap()).toBeNull();
  });

  it("fails closed instead of using the seed in production mode", () => {
    vi.stubEnv("VITE_DEPLOYMENT_MODE", "production");
    expect(resolveFallbackDefinition("/")).toBeNull();
    vi.unstubAllEnvs();
    expect(resolveFallbackDefinition("/")).not.toBeNull();
  });

  it("exposes a stable route query key", () => {
    expect(pageDefinitionKey("/")).toEqual(["page-definition", "/"]);
    expect(pageDefinitionKey("search")).toEqual(["page-definition", "search"]);
  });
});
