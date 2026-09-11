import {
  normalizePageDefinition,
  type CompatiblePageDefinition,
  type PageDefinitionV2,
} from "@soymutdb/shared";

export type PageBuilderTemplateId = "blank" | "research" | "dataExplorer" | "helpCenter";

export interface PageBuilderTemplate {
  id: PageBuilderTemplateId;
  labelKey: string;
  descriptionKey: string;
  definition: PageDefinitionV2;
}

function createDefinition(
  root: PageDefinitionV2["root"],
  options: Pick<PageDefinitionV2, "theme_id" | "data_sources"> = {
    theme_id: "scientific-light",
    data_sources: [],
  },
): PageDefinitionV2 {
  return normalizePageDefinition({
    root,
    theme_id: options.theme_id,
    data_sources: options.data_sources,
  })!;
}

export const PAGE_BUILDER_TEMPLATES: readonly PageBuilderTemplate[] = [
  {
    id: "blank",
    labelKey: "admin.builder.templateBlank",
    descriptionKey: "admin.builder.templateBlankDesc",
    definition: createDefinition({
      type: "columns",
      props: { columns: 1 },
      children: [
        {
          type: "rich_text",
          props: { content: "<h1>New page</h1><p>Start with a clear purpose and one primary action.</p>" },
        },
      ],
    }),
  },
  {
    id: "research",
    labelKey: "admin.builder.templateResearch",
    descriptionKey: "admin.builder.templateResearchDesc",
    definition: createDefinition(
      {
        type: "columns",
        props: { columns: 1 },
        children: [
          {
            type: "notice",
            props: {
              kind: "info",
              content: "Use this page to introduce a research topic, evidence, and the next tool action.",
            },
          },
          {
            type: "rich_text",
            props: {
              content: "<h1>Research overview</h1><p>Summarize the biological question, scope, and release used by this page.</p>",
            },
          },
          {
            type: "columns",
            props: { columns: 2 },
            children: [
              {
                type: "resource_cards",
                props: {
                  heading: "Explore resources",
                  cards: [
                    { title: "Gene search", description: "Find a gene or locus.", href: "/search/genes" },
                    { title: "Genome browser", description: "Inspect genomic context.", href: "/search/gbrowse" },
                  ],
                },
              },
              { type: "news_list", props: { limit: 4 } },
            ],
          },
          { type: "divider", props: {} },
          {
            type: "tool_entries",
            props: { entries: ["Gene ID", "Physical Location", "JBrowse 2", "BLAST"] },
          },
        ],
      },
      {
        theme_id: "scientific-light",
        data_sources: [
          { id: "published-news", kind: "news", config: { scope: "published", limit: 4 } },
          { id: "published-resources", kind: "resource_catalog", config: { scope: "published" } },
        ],
      },
    ),
  },
  {
    id: "dataExplorer",
    labelKey: "admin.builder.templateDataExplorer",
    descriptionKey: "admin.builder.templateDataExplorerDesc",
    definition: createDefinition(
      {
        type: "columns",
        props: { columns: 1 },
        children: [
          {
            type: "notice",
            props: {
              kind: "info",
              content: "Keep the query entry point above result context and state the active data scope.",
            },
          },
          { type: "assembly_select", props: { default_assembly: "Wm82v4.0" } },
          { type: "gene_search_form", props: { title: "Search by gene ID" } },
          { type: "location_search_form", props: { title: "Search by physical location" } },
          {
            type: "data_table",
            props: { columns: ["Gene ID", "Species", "Variant count", "Updated"] },
          },
        ],
      },
      {
        theme_id: "compact-data",
        data_sources: [
          { id: "gene-catalog", kind: "gene_catalog", config: { scope: "published" } },
          { id: "variant-summary", kind: "variant_summary", config: { scope: "active_release" } },
        ],
      },
    ),
  },
  {
    id: "helpCenter",
    labelKey: "admin.builder.templateHelpCenter",
    descriptionKey: "admin.builder.templateHelpCenterDesc",
    definition: createDefinition({
      type: "columns",
      props: { columns: 1 },
      children: [
        {
          type: "rich_text",
          props: {
            content: "<h1>Help center</h1><p>Give operators and researchers a short path from question to answer.</p>",
          },
        },
        {
          type: "tabs",
          props: { tabs: ["Getting started", "Data policy", "Contact"] },
          children: [
            { type: "rich_text", props: { content: "<h2>Getting started</h2><p>Choose a tool, select an assembly, and inspect the result state.</p>" } },
            { type: "rich_text", props: { content: "<h2>Data policy</h2><p>Published data is release-bound and traceable to its source.</p>" } },
            { type: "rich_text", props: { content: "<h2>Contact</h2><p>Provide a maintained support channel and response expectations.</p>" } },
          ],
        },
        {
          type: "notice",
          props: { kind: "warning", content: "Do not place credentials, private endpoints, or executable HTML in page content." },
        },
      ],
    }),
  },
];

export interface ResolvedPageBuilderTemplate {
  key: string;
  label: string;
  description: string | null;
  definition: CompatiblePageDefinition;
}

export function resolvePageBuilderTemplates(
  apiTemplates: readonly ResolvedPageBuilderTemplate[] | null | undefined,
): readonly ResolvedPageBuilderTemplate[] {
  if (apiTemplates?.length) return apiTemplates;
  return PAGE_BUILDER_TEMPLATES
    .filter((template) => template.id === "blank" || template.id === "research")
    .map((template) => ({
      key: template.id,
      label: template.id,
      description: null,
      definition: template.definition,
    }));
}

export function getPageBuilderTemplate(id: PageBuilderTemplateId): PageBuilderTemplate {
  return PAGE_BUILDER_TEMPLATES.find((template) => template.id === id) ?? PAGE_BUILDER_TEMPLATES[0];
}

export function getPageBuilderTemplateDefinition(id: PageBuilderTemplateId): PageDefinitionV2 {
  return getPageBuilderTemplate(id).definition;
}
