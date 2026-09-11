import { describe, expect, it } from "vitest";
import { PAGE_COMPONENT_TYPES } from "@soymutdb/shared";
import {
  getPageBuilderTemplateDefinition,
  PAGE_BUILDER_TEMPLATES,
  resolvePageBuilderTemplates,
} from "./page-builder-templates";

describe("Page Builder templates", () => {
  it("normalizes every template to the shared v2 contract", () => {
    for (const template of PAGE_BUILDER_TEMPLATES) {
      const definition = getPageBuilderTemplateDefinition(template.id);
      expect(definition.schema_version).toBe(2);
      expect(definition.root.type).toBe("columns");
      expect(definition.layouts).toEqual({ desktop: {}, tablet: {}, mobile: {} });
      expect(new Set(definition.data_sources.map((source) => source.id)).size).toBe(
        definition.data_sources.length,
      );
    }
  });

  it("keeps templates inside the server component allowlist", () => {
    const allowed = new Set<string>(PAGE_COMPONENT_TYPES);
    const walk = (node: { type: string; children?: Array<{ type: string; children?: unknown[] }> }) => {
      expect(allowed.has(node.type)).toBe(true);
      for (const child of node.children ?? []) walk(child as { type: string; children?: Array<{ type: string; children?: unknown[] }> });
    };
    for (const template of PAGE_BUILDER_TEMPLATES) walk(template.definition.root);
  });
  it("prefers nonempty API templates over local fallbacks", () => {
    const apiTemplate = {
      key: "server-template",
      label: "Server template",
      description: "Managed by the API",
      definition: PAGE_BUILDER_TEMPLATES[0].definition,
    };
    expect(resolvePageBuilderTemplates([apiTemplate])).toEqual([apiTemplate]);
  });

  it("uses only blank and research fallbacks for empty API results", () => {
    expect(resolvePageBuilderTemplates([]).map((template) => template.key)).toEqual([
      "blank",
      "research",
    ]);
  });

  it("uses fallbacks when the template API is unavailable", () => {
    expect(resolvePageBuilderTemplates(null).map((template) => template.key)).toEqual([
      "blank",
      "research",
    ]);
    expect(resolvePageBuilderTemplates(undefined).map((template) => template.key)).toEqual([
      "blank",
      "research",
    ]);
  });
});
