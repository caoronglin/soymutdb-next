// @vitest-environment jsdom
// The mount helper is imported first: it registers the @soymutdb/ui-vue mock
// before the view module graph loads it (see mount-portal-view.ts).
import { flushPromises } from "@vue/test-utils";

import { mountPortalView } from "../test/mount-portal-view";

import { getBlastDatabases, getBlastHits, getBlastJobs, getSiteContent } from "@soymutdb/api-client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { setLanguage, t } from "../lib/i18n";
import BlastView from "./BlastView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    getBlastDatabases: vi.fn(),
    getBlastHits: vi.fn(),
    getBlastJobs: vi.fn(),
    getSiteContent: vi.fn(),
    submitBlastJob: vi.fn(),
  };
});

const mockedDatabases = vi.mocked(getBlastDatabases);
const mockedHits = vi.mocked(getBlastHits);
const mockedJobs = vi.mocked(getBlastJobs);
const mockedSiteContent = vi.mocked(getSiteContent);

const HIT = {
  hsp_num: 1,
  subject_id: "Glyma.01G000100",
  subject_title: "hit",
  percent_identity: 99,
  alignment_length: 120,
  mismatches: 1,
  gap_opens: 0,
  query_start: 1,
  query_end: 120,
  subject_start: 1,
  subject_end: 120,
  evalue: 1e-10,
  bit_score: 210,
};

beforeEach(() => {
  setLanguage("en");
  mockedSiteContent.mockReset().mockResolvedValue({});
  mockedDatabases.mockReset().mockResolvedValue([]);
  mockedHits.mockReset().mockResolvedValue({ items: [], total: 0 } as never);
  mockedJobs
    .mockReset()
    .mockResolvedValue({ items: [], page: 1, page_size: 5, total: 0 } as never);
});

/** The label element wrapping one form control (label text, not the control). */
function controlLabel(wrapper: ReturnType<typeof mountPortalView>["wrapper"], testId: string) {
  return wrapper.get(`[data-testid="${testId}"]`).element.parentElement?.textContent ?? "";
}

describe("BlastView editable site content", () => {
  it("renders today's localized labels when no override is stored", async () => {
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    expect(controlLabel(wrapper, "blast-sequence")).toContain(t("blast.inputSequence"));
    expect(controlLabel(wrapper, "blast-database")).toContain(t("blast.database"));
    expect(wrapper.get('[data-testid="blast-submit"]').text()).toBe(t("blast.submit"));
    // Registered-but-previously-unwired keys fall back to their own translation.
    expect(controlLabel(wrapper, "blast-program")).toContain(t("blast.searchType"));
    expect(wrapper.get('[data-testid="blast-database"]').text()).toContain(
      t("blast.databasePlaceholder"),
    );
    expect(wrapper.get('[data-testid="blast-sequence"]').attributes("placeholder")).toBe(
      t("blast.sequencePlaceholder"),
    );
    expect(wrapper.get('[data-testid="blast-hits-empty"]').text()).toBe(t("blast.noJobs"));
    wrapper.unmount();
  });

  it("renders stored overrides for the database/input/submit labels", async () => {
    mockedSiteContent.mockResolvedValue({
      "blast.database": "运营数据库",
      "blast.input": "运营序列输入",
      "blast.submit": "运营提交",
    });
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    expect(controlLabel(wrapper, "blast-database")).toContain("运营数据库");
    expect(controlLabel(wrapper, "blast-sequence")).toContain("运营序列输入");
    expect(wrapper.get('[data-testid="blast-submit"]').text()).toBe("运营提交");
    wrapper.unmount();
  });

  it("renders stored overrides for search type, placeholder and empty-state copy", async () => {
    mockedSiteContent.mockResolvedValue({
      "blast.searchType": "运营检索类型",
      "blast.databasePlaceholder": "运营占位",
      "blast.sequencePlaceholder": "运营序列占位",
      "ui.noResults": "运营空态",
    });
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    expect(controlLabel(wrapper, "blast-program")).toContain("运营检索类型");
    expect(wrapper.get('[data-testid="blast-database"]').text()).toContain("运营占位");
    expect(wrapper.get('[data-testid="blast-sequence"]').attributes("placeholder")).toBe(
      "运营序列占位",
    );
    expect(wrapper.get('[data-testid="blast-hits-empty"]').text()).toBe("运营空态");
    wrapper.unmount();
  });

  it("applies ui.noResults to the no-hits empty state too", async () => {
    mockedJobs.mockResolvedValue({
      items: [{ id: "job-1", name: "j", status: "completed", hit_count: 0 }],
      page: 1,
      page_size: 5,
      total: 1,
    } as never);
    mockedSiteContent.mockResolvedValue({ "ui.noResults": "运营无命中" });
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    await wrapper.get('[data-testid="blast-job-job-1"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="blast-hits-none"]').text()).toBe("运营无命中");
    wrapper.unmount();
  });

  it("renders stored overrides for the hits table headers", async () => {
    mockedJobs.mockResolvedValue({
      items: [{ id: "job-1", name: "j", status: "completed", hit_count: 1 }],
      page: 1,
      page_size: 5,
      total: 1,
    } as never);
    mockedHits.mockResolvedValue({ items: [HIT], total: 1 } as never);
    mockedSiteContent.mockResolvedValue({
      "blast.hitSequenceId": "运营序列ID",
      "blast.hitCoverage": "运营覆盖",
      "blast.hitEValue": "运营E值",
      "blast.hitGeneId": "运营基因ID",
    });
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    await wrapper.get('[data-testid="blast-job-job-1"]').trigger("click");
    await flushPromises();

    const headers = wrapper.get('[data-testid="blast-hits-table"] thead').text();
    expect(headers).toContain("运营序列ID");
    expect(headers).toContain("运营覆盖");
    expect(headers).toContain("运营E值");
    expect(headers).toContain("运营基因ID");
    // The Vue table keeps its own score column and adds React's gene/gbrowse
    // jumps, so the header row carries both.
    expect(headers).toContain(t("blast.hitScore"));
    expect(headers).toContain(t("blast.actions.gbrowse"));

    // The gene cell jumps into the gene-ID search with React's `run` flag, and
    // the gbrowse cell deep-links the hit's locus.
    const geneLink = wrapper.get('[data-testid="blast-hit-gene-0"]');
    expect(geneLink.attributes("href")).toBe(
      `/search/genes?q=${encodeURIComponent(HIT.subject_id)}&run=true`,
    );
    const gbrowse = wrapper.get('[data-testid="blast-hit-gbrowse-0"]');
    expect(gbrowse.attributes("href")).toContain(`loc=${HIT.subject_id}%3A${HIT.subject_start}..${HIT.subject_end}`);
    expect(gbrowse.attributes("rel")).toContain("noopener");
    wrapper.unmount();
  });

  it("uses the ui.loading override for the database placeholder while loading", async () => {
    mockedDatabases.mockReturnValue(new Promise(() => {}) as never);
    mockedSiteContent.mockResolvedValue({ "ui.loading": "运营加载中" });
    const { wrapper } = mountPortalView(BlastView, { path: "/blast" });
    await flushPromises();

    expect(wrapper.get('[data-testid="blast-database"]').text()).toContain("运营加载中");
    wrapper.unmount();
  });
});
