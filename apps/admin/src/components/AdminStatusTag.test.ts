// @vitest-environment jsdom
import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

vi.mock("@soymutdb/ui-vue", () => ({
  Tag: {
    props: ["color"],
    template: '<span :data-color="color"><slot /></span>',
  },
}));

import AdminStatusTag from "./AdminStatusTag.vue";

/**
 * One tone vocabulary for backend statuses. The text must stay the server's own
 * token by default — a new backend status has to render, not disappear — while
 * an explicit label wins when the token needs localising.
 */
describe("AdminStatusTag", () => {
  it("shows the server status verbatim with a mapped tone", () => {
    const wrapper = mount(AdminStatusTag, { props: { status: "published" } });
    expect(wrapper.text()).toBe("published");
    expect(wrapper.get("span").attributes("data-color")).toBe("green");
  });

  it("falls back to a neutral tone for an unknown status but still renders it", () => {
    const wrapper = mount(AdminStatusTag, { props: { status: "quarantined" } });
    expect(wrapper.text()).toBe("quarantined");
    expect(wrapper.get("span").attributes("data-color")).toBe("default");
  });

  it("lets a localised label replace the machine token", () => {
    const wrapper = mount(AdminStatusTag, {
      props: { status: "unhealthy", label: "Unreachable" },
    });
    expect(wrapper.text()).toBe("Unreachable");
    expect(wrapper.get("span").attributes("data-color")).toBe("red");
  });

  it("matches tone case-insensitively", () => {
    const wrapper = mount(AdminStatusTag, { props: { status: "FAILED" } });
    expect(wrapper.get("span").attributes("data-color")).toBe("red");
  });
});
