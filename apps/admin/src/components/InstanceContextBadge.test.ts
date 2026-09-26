// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mountAdminView } from "../test/support";

import { listSpeciesInstances, type SpeciesInstance } from "@soymutdb/api-client";
import InstanceContextBadge from "./InstanceContextBadge.vue";
import { useAdminInstanceContext } from "../stores/instance-context";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, listSpeciesInstances: vi.fn() };
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
  last_checked_at: null,
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
  name: "Peer CN",
  api_base_url: "https://peer.example.org",
  is_local: false,
  remote_management: "registration_only",
};

const mockedList = vi.mocked(listSpeciesInstances);

beforeEach(() => {
  mockedList.mockReset().mockResolvedValue({ items: [LOCAL, REMOTE], total: 2 });
});

describe("InstanceContextBadge", () => {
  it("shows the local instance, release and API host by default", async () => {
    const { wrapper } = mountAdminView(InstanceContextBadge, { path: "/" });
    await flushPromises();

    expect(wrapper.get('[data-testid="instance-context-instance"]').text()).toContain(
      "Local SoyMutDB",
    );
    expect(wrapper.get('[data-testid="instance-context-release"]').text()).toContain("Release");
    expect(wrapper.get('[data-testid="instance-context-server"]').text()).toContain(
      "localhost:8010",
    );
    expect(wrapper.find('[data-testid="instance-context-remote"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("marks a selected remote registration as registration-only", async () => {
    const { wrapper, pinia } = mountAdminView(InstanceContextBadge, { path: "/" });
    await flushPromises();

    setActivePinia(pinia);
    useAdminInstanceContext().select("peer-cn");
    await flushPromises();

    expect(wrapper.get('[data-testid="instance-context-instance"]').text()).toContain("Peer CN");
    expect(wrapper.get('[data-testid="instance-context-server"]').text()).toContain(
      "peer.example.org",
    );
    expect(wrapper.find('[data-testid="instance-context-remote"]').exists()).toBe(true);
    wrapper.unmount();
  });

  it("falls back to the local instance when the stored code is not registered", async () => {
    const { wrapper, pinia } = mountAdminView(InstanceContextBadge, { path: "/" });
    await flushPromises();

    setActivePinia(pinia);
    useAdminInstanceContext().select("removed-peer");
    await flushPromises();

    expect(wrapper.get('[data-testid="instance-context-instance"]').text()).toContain(
      "Local SoyMutDB",
    );
    wrapper.unmount();
  });
});
