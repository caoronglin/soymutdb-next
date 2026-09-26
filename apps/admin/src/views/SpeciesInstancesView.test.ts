// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Imported first so the @soymutdb/ui-vue mock is registered before the view
// module graph resolves its imports (see ../test/support).
import { mountAdminView } from "../test/support";

import {
  checkSpeciesInstanceHealth,
  createSpeciesInstance,
  deleteSpeciesInstance,
  listSpeciesInstances,
  updateSpeciesInstance,
  type SpeciesInstance,
} from "@soymutdb/api-client";
import SpeciesInstancesView from "./SpeciesInstancesView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    listSpeciesInstances: vi.fn(),
    createSpeciesInstance: vi.fn(),
    updateSpeciesInstance: vi.fn(),
    deleteSpeciesInstance: vi.fn(),
    checkSpeciesInstanceHealth: vi.fn(),
  };
});

const LOCAL: SpeciesInstance = {
  id: 1,
  code: "local",
  name: "Local SoyMutDB",
  species: "Glycine max",
  api_base_url: "http://localhost:8010/api/v1",
  jbrowse_base_url: null,
  portal_base_url: null,
  site_url: null,
  is_enabled: true,
  is_local: true,
  connection_state: "healthy",
  last_checked_at: "2026-09-26T08:00:00Z",
  last_error_at: null,
  is_stale: false,
  remote_management: "local",
  notes: null,
  created_at: "2026-09-25T00:00:00Z",
  updated_at: "2026-09-25T00:00:00Z",
};

const REMOTE: SpeciesInstance = {
  ...LOCAL,
  id: 2,
  code: "peer-cn",
  name: "Peer instance",
  api_base_url: "https://peer.example.org/api/v1",
  portal_base_url: "https://peer.example.org",
  site_url: "https://peer.example.org",
  is_local: false,
  connection_state: "unhealthy",
  last_checked_at: "2026-09-26T07:00:00Z",
  last_error_at: "2026-09-26T07:00:00Z",
  remote_management: "registration_only",
};

const mockedList = vi.mocked(listSpeciesInstances);

beforeEach(() => {
  mockedList.mockReset().mockResolvedValue({ items: [LOCAL, REMOTE], total: 2 });
  vi.mocked(createSpeciesInstance).mockReset();
  vi.mocked(updateSpeciesInstance).mockReset();
  vi.mocked(deleteSpeciesInstance).mockReset();
  vi.mocked(checkSpeciesInstanceHealth).mockReset();
});

describe("SpeciesInstancesView", () => {
  it("lists registered instances and shows each connection state", async () => {
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    expect(mockedList).toHaveBeenCalled();
    const rows = wrapper.findAll('[data-testid="instance-row"]');
    expect(rows).toHaveLength(2);
    expect(rows[0]!.text()).toContain("Local SoyMutDB");
    expect(rows[1]!.text()).toContain("peer.example.org");
    wrapper.unmount();
  });

  it("never offers removal for the local instance", async () => {
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    expect((wrapper.get('[data-testid="instance-delete-1"]').element as HTMLButtonElement).disabled)
      .toBe(true);
    expect((wrapper.get('[data-testid="instance-delete-2"]').element as HTMLButtonElement).disabled)
      .toBe(false);
    wrapper.unmount();
  });

  it("registers a new instance with its code and portal URL", async () => {
    vi.mocked(createSpeciesInstance).mockResolvedValue(LOCAL);
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    await wrapper.get('[data-testid="instances-new"]').trigger("click");
    await wrapper.get('[data-testid="instance-code"]').setValue("peer-eu");
    await wrapper.get('[data-testid="instance-name"]').setValue("Peer EU");
    await wrapper.get('[data-testid="instance-api-url"]').setValue("https://peer-eu.example.org/api/v1");
    await wrapper.get('[data-testid="instance-site-url"]').setValue("https://peer-eu.example.org");
    await wrapper.get('[data-testid="instance-editor"] form').trigger("submit");
    await flushPromises();

    expect(vi.mocked(createSpeciesInstance)).toHaveBeenCalledWith(
      expect.objectContaining({
        code: "peer-eu",
        name: "Peer EU",
        api_base_url: "https://peer-eu.example.org/api/v1",
        site_url: "https://peer-eu.example.org",
      }),
    );
    wrapper.unmount();
  });

  it("probes a registered peer through the health endpoint", async () => {
    vi.mocked(checkSpeciesInstanceHealth).mockResolvedValue({
      id: 2,
      code: "peer-cn",
      connection_state: "healthy",
      checked_at: "2026-09-26T09:00:00Z",
      last_checked_at: "2026-09-26T09:00:00Z",
      last_error_at: null,
      is_stale: false,
      error_code: null,
      remote_management: "registration_only",
    });
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    await wrapper.get('[data-testid="instance-check-2"]').trigger("click");
    await flushPromises();

    expect(vi.mocked(checkSpeciesInstanceHealth)).toHaveBeenCalledWith(2);
    wrapper.unmount();
  });

  it("requires an explicit confirmation before deleting a registration", async () => {
    vi.mocked(deleteSpeciesInstance).mockResolvedValue(undefined);
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    await wrapper.get('[data-testid="instance-delete-2"]').trigger("click");
    expect(wrapper.find('[data-testid="instance-delete-confirm"]').exists()).toBe(true);
    expect(vi.mocked(deleteSpeciesInstance)).not.toHaveBeenCalled();

    await wrapper.get('[data-testid="instance-delete-confirm-button"]').trigger("click");
    await flushPromises();

    expect(vi.mocked(deleteSpeciesInstance)).toHaveBeenCalledWith(2);
    wrapper.unmount();
  });

  it("shows the current target and switches it without writing to the registry", async () => {
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    expect(wrapper.get('[data-testid="instances-current"]').text()).toContain("Local SoyMutDB");
    expect(wrapper.find('[data-testid="instances-remote-disabled"]').exists()).toBe(false);

    await wrapper.get('[data-testid="instance-select-2"]').trigger("click");
    await flushPromises();

    expect(wrapper.get('[data-testid="instances-current"]').text()).toContain("Peer instance");
    expect(wrapper.find('[data-testid="instances-remote-disabled"]').exists()).toBe(true);
    // Selecting a target is console UI state; it never mutates the registry.
    expect(vi.mocked(updateSpeciesInstance)).not.toHaveBeenCalled();
    expect(vi.mocked(createSpeciesInstance)).not.toHaveBeenCalled();
    wrapper.unmount();
  });

  it("keeps remote registrations read-only in the console's own wording", async () => {
    const { wrapper } = mountAdminView(SpeciesInstancesView, { path: "/instances" });
    await flushPromises();

    await wrapper.get('[data-testid="instances-new"]').trigger("click");
    // A new registration starts as a remote (non-local) row, so the
    // registration-only notice is visible until the local flag is checked.
    expect(wrapper.get('[data-testid="instance-remote-hint"]').text()).toContain("registration-only");
    await wrapper.get('[data-testid="instance-local"]').setValue(true);
    expect(wrapper.find('[data-testid="instance-remote-hint"]').exists()).toBe(false);
    await wrapper.get('[data-testid="instance-local"]').setValue(false);
    expect(wrapper.get('[data-testid="instance-remote-hint"]').text()).toContain("registration-only");
    wrapper.unmount();
  });
});
