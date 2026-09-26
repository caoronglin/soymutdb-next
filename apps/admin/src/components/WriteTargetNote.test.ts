// @vitest-environment jsdom
import { QueryClient, VueQueryPlugin } from "@tanstack/vue-query";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listSpeciesInstances } from "@soymutdb/api-client";

import { useAdminInstanceContext } from "../stores/instance-context";
import WriteTargetNote from "./WriteTargetNote.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, listSpeciesInstances: vi.fn() };
});

const INSTANCES = {
  items: [
    {
      id: 1,
      code: "local",
      name: "Local",
      is_local: true,
      api_base_url: "http://127.0.0.1:8030",
    },
    {
      id: 2,
      code: "peer-cn",
      name: "Peer CN",
      is_local: false,
      api_base_url: "https://peer.example",
    },
  ],
};

function mountNote() {
  const pinia = createPinia();
  setActivePinia(pinia);
  return mount(WriteTargetNote, {
    global: {
      plugins: [
        pinia,
        [
          VueQueryPlugin,
          { queryClient: new QueryClient({ defaultOptions: { queries: { retry: false } } }) },
        ],
      ],
    },
  });
}

beforeEach(() => {
  vi.mocked(listSpeciesInstances).mockReset().mockResolvedValue(INSTANCES as never);
});

describe("WriteTargetNote (P1-07)", () => {
  it("names the local write target by default", async () => {
    const wrapper = mountNote();
    await flushPromises();

    const note = wrapper.get('[data-testid="write-target-local"]');
    expect(note.text()).toContain("Local (local)");
    expect(note.text()).toContain("127.0.0.1:8030");
    expect(wrapper.find('[data-testid="write-target-remote"]').exists()).toBe(false);
    wrapper.unmount();
  });

  it("warns that a selected remote instance is registration-only", async () => {
    const wrapper = mountNote();
    await flushPromises();
    useAdminInstanceContext().select("peer-cn");
    await flushPromises();

    const note = wrapper.get('[data-testid="write-target-remote"]');
    expect(note.text()).toContain("Peer CN (peer-cn)");
    expect(note.text()).toContain("Local (local)");
    expect(note.text()).toContain("registration-only");
    wrapper.unmount();
  });
});
