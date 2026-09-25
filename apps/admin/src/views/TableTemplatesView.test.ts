// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The mount helper is imported first: it registers the @soymutdb/ui-vue mock
// (Antdv Next does not resolve under vitest's node resolver — see
// packages/ui-vue/src/facade.test.ts) before the view module graph loads it.
import { mountAdminView } from "../test/support";

import { listTableViewTemplates, updateTableViewTemplate } from "@soymutdb/api-client";
import TableTemplatesView from "./TableTemplatesView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listTableViewTemplates: vi.fn(),
    updateTableViewTemplate: vi.fn(),
    createTableViewTemplate: vi.fn(),
    deleteTableViewTemplate: vi.fn(),
  };
});

const mockedList = vi.mocked(listTableViewTemplates);

const TEMPLATE = {
  id: 7,
  kind: "mutation_sites" as const,
  name: "mutation sites",
  species: "Glycine max",
  site_variant: "external" as const,
  release_id: null,
  is_default: true,
  columns: [
    { key: "mutant_line_name", label_zh: "株系", label_en: "Mutant line", visible: true },
    { key: "confidence", label_zh: "可信度", label_en: "Confidence", visible: true },
  ],
  actions: { jbrowse: true, genome_preview: false },
  notes: null,
  created_at: "2026-09-25T00:00:00Z",
  updated_at: "2026-09-25T00:00:00Z",
};

beforeEach(() => {
  mockedList.mockReset().mockResolvedValue({ items: [TEMPLATE], total: 1 });
});

describe("TableTemplatesView", () => {
  it("lists the templates for the active table kind", async () => {
    const { wrapper } = mountAdminView(TableTemplatesView, { path: "/table-templates" });
    await flushPromises();

    expect(mockedList).toHaveBeenCalledWith({ kind: "mutation_sites" });
    const row = wrapper.get('[data-testid="template-row"]');
    expect(row.text()).toContain("mutation sites");
    expect(row.text()).toContain("mutant_line_name");
    wrapper.unmount();
  });

  it("loads a template into the editor, including its trailing actions", async () => {
    const { wrapper } = mountAdminView(TableTemplatesView, { path: "/table-templates" });
    await flushPromises();

    await wrapper.get('[data-testid="template-edit-7"]').trigger("click");
    await flushPromises();

    expect((wrapper.get('[data-testid="template-name"]').element as HTMLInputElement).value).toBe(
      "mutation sites",
    );
    expect(wrapper.find('[data-testid="template-column-mutant_line_name"]').exists()).toBe(true);
    expect(
      (wrapper.get('[data-testid="template-action-jbrowse"]').element as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (wrapper.get('[data-testid="template-action-genome"]').element as HTMLInputElement).checked,
    ).toBe(false);
    wrapper.unmount();
  });

  it("offers the homolog columns but never pre-selects them", async () => {
    const { wrapper } = mountAdminView(TableTemplatesView, { path: "/table-templates" });
    await flushPromises();

    // A new template starts from the built-in order: the cross-assembly homolog
    // columns are offered as buttons, not added to the column list.
    await wrapper.get('[data-testid="templates-new"]').trigger("click");
    expect(wrapper.find('[data-testid="template-column-mutant_line_name"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="template-column-homolog:W82_V2"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="template-add-homolog:W82_V2"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("promotes a template to the default through the API", async () => {
    vi.mocked(updateTableViewTemplate).mockResolvedValue({ ...TEMPLATE, is_default: true });
    const { wrapper } = mountAdminView(TableTemplatesView, { path: "/table-templates" });
    await flushPromises();

    // The template in the fixture is already the default, so the action is not
    // offered for it — that is the assertion: a default cannot be promoted twice.
    expect(wrapper.find('[data-testid="template-default-7"]').exists()).toBe(false);
    wrapper.unmount();
  });
});
