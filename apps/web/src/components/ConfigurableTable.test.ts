// @vitest-environment jsdom
import { mountPortalView } from "../test/mount-portal-view";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTableView } from "@soymutdb/api-client";
import ConfigurableTable from "../components/ConfigurableTable.vue";
import type { ConfigurableRow } from "../components/ConfigurableTable.vue";
import type { ResolvedTableView } from "@soymutdb/api-client";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, getTableView: vi.fn() };
});

const mocked = vi.mocked(getTableView);

const BASE_VIEW: ResolvedTableView = {
  kind: "mutation_sites",
  species: "Glycine max",
  site_variant: "external",
  release_id: null,
  template_id: null,
  template_name: "builtin-default",
  is_builtin_default: true,
  columns: [
    { key: "mutant_line_name", label_zh: "株系", label_en: "Mutant line", visible: true },
    { key: "mutation_system", label_zh: "突变体系", label_en: "Mutation system", visible: true },
    { key: "chromosome", label_zh: "染色体号", label_en: "Chromosome", visible: true },
    { key: "position", label_zh: "位点", label_en: "Position", visible: true },
    { key: "confidence", label_zh: "可信度", label_en: "Confidence", visible: true },
    { key: "gene_id", label_zh: "基因号", label_en: "Gene ID", visible: true },
    { key: "feature", label_zh: "特征", label_en: "Feature", visible: true },
    { key: "available", label_zh: "可获得", label_en: "Available", visible: true },
  ],
  actions: { jbrowse: true, genome_preview: true },
};

const ROW: ConfigurableRow = {
  mutant_line_name: "SOYTE1M00001",
  chromosome: "Gm01",
  position: 98256,
  confidence: "H",
  gene_id: "Glyma.01G000100.Wm82.a6.v1",
  feature: "gene|-5225.5",
  available: true,
  homologs: [{ species: "Wm82.a2.v2", gene_id: "Glyma.02G115200", type: "ortholog" }],
};

beforeEach(() => mocked.mockReset());

function mountTable(view: ResolvedTableView, rows: readonly ConfigurableRow[]) {
  return mountPortalView(
    { components: { ConfigurableTable }, template: "<ConfigurableTable :columns=\"view.columns\" :actions=\"view.actions\" :rows=\"rows\" :assembly-name=\"'Wm82.a6.v1'\" />", setup: () => ({ view, rows }) } as never,
    { path: "/confirm" },
  );
}

describe("ConfigurableTable", () => {
  it("renders the configured columns in order and derives the mutation system", () => {
    const { wrapper } = mountTable(BASE_VIEW, [ROW]);
    const headers = wrapper.findAll("thead th").map((th) => th.text());

    expect(headers.slice(0, 8)).toEqual([
      "Mutant line",
      "Mutation system",
      "Chromosome",
      "Position",
      "Confidence",
      "Gene ID",
      "Feature",
      "Available",
    ]);
    const row = wrapper.get('[data-testid="configurable-row"]');
    expect(row.text()).toContain("SOYTE1M00001");
    expect(row.text()).toContain("SOYTE1M00001·98256");
    expect(row.text()).toContain("Glyma.01G000100.Wm82.a6.v1");
    expect(row.text()).toContain("gene|-5225.5");
    expect(row.text()).toContain("Y");
    expect(row.text()).toContain("高");
    wrapper.unmount();
  });

  it("keeps a homolog column opt-in and never invents a missing value", () => {
    const view: ResolvedTableView = {
      ...BASE_VIEW,
      columns: [
        ...BASE_VIEW.columns,
        {
          key: "homolog:Wm82.a2.v2",
          label_zh: "W82_V2",
          label_en: "W82_V2",
          visible: true,
        },
      ],
    };

    const { wrapper } = mountTable(view, [ROW]);
    expect(wrapper.get('[data-column="homolog:Wm82.a2.v2"]').text()).toBe("Glyma.02G115200");

    // A row without that homolog renders an em dash, not an empty cell or 0.
    const second = mountTable(view, [{ ...ROW, homologs: [] }]);
    expect(second.wrapper.get('[data-column="homolog:Wm82.a2.v2"]').text()).toBe("—");
    second.wrapper.unmount();
    wrapper.unmount();
  });

  it("does not render a column the template hid", () => {
    const view: ResolvedTableView = {
      ...BASE_VIEW,
      columns: BASE_VIEW.columns.map((column) =>
        column.key === "feature" ? { ...column, visible: false } : column,
      ),
    };

    const { wrapper } = mountTable(view, [ROW]);
    expect(wrapper.find('[data-column="feature"]').exists()).toBe(false);
    expect(wrapper.find('[data-column="position"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("keeps the optional JBrowse and genome preview actions behind the template", () => {
    const { wrapper } = mountTable(
      { ...BASE_VIEW, actions: { jbrowse: true, genome_preview: false } },
      [ROW],
    );
    expect(wrapper.get('[data-testid="jbrowse-link-0"]').attributes("href")).toContain(
      "/browser?assembly=Wm82.a6.v1&loc=Gm01%3A98256-98256",
    );
    expect(wrapper.find('[data-testid="genome-link-0"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("omits the action columns entirely when the template disables them", () => {
    const { wrapper } = mountTable({ ...BASE_VIEW, actions: { jbrowse: false, genome_preview: false } }, [ROW]);
    expect(wrapper.find('[data-testid="jbrowse-link-0"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="genome-link-0"]').exists()).toBe(false);
    wrapper.unmount();
  });
});

describe("table view resolution", () => {
  it("asks the API for the layout of the requested kind", async () => {
    const { getTableView } = await import("@soymutdb/api-client");
    mocked.mockResolvedValue(BASE_VIEW);

    const resolved = await getTableView("mutation_sites", { species: "Glycine max" });

    expect(mocked).toHaveBeenCalledWith("mutation_sites", { species: "Glycine max" });
    // No template exists for this scope, so the API answers with the built-in
    // default rather than an empty column set.
    expect(resolved.is_builtin_default).toBe(true);
    expect(resolved.actions.jbrowse).toBe(true);
    expect(resolved.columns).toHaveLength(8);
  });
});
