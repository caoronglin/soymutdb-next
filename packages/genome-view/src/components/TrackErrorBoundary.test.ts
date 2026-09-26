import { mount } from "@vue/test-utils";
import { defineComponent, h, nextTick } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";
import TrackErrorBoundary from "./TrackErrorBoundary.vue";

const ThrowingTrack = defineComponent({
  name: "ThrowingTrack",
  setup() {
    throw new Error("track exploded");
  },
});

function silenceVueErrors(): void {
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
}

describe("TrackErrorBoundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("catches a child error and shows inline error text", async () => {
    silenceVueErrors();
    const wrapper = mount(TrackErrorBoundary, {
      slots: { default: () => h(ThrowingTrack) },
    });
    await nextTick();
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);
    expect(wrapper.text()).toContain("track exploded");
    expect(wrapper.find("button").text()).toBe("Retry");
  });

  it("emits retry, clears the error and re-renders the slot", async () => {
    silenceVueErrors();
    let shouldThrow = true;
    const FlakyTrack = defineComponent({
      name: "FlakyTrack",
      setup() {
        if (shouldThrow) {
          throw new Error("boom");
        }
        return () => h("div", { class: "recovered" }, "recovered");
      },
    });
    const wrapper = mount(TrackErrorBoundary, {
      slots: { default: () => h(FlakyTrack) },
    });
    await nextTick();
    expect(wrapper.find(".recovered").exists()).toBe(false);
    expect(wrapper.find('[role="alert"]').exists()).toBe(true);

    shouldThrow = false;
    await wrapper.find("button").trigger("click");
    await nextTick();

    expect(wrapper.emitted("retry")).toHaveLength(1);
    expect(wrapper.find('[role="alert"]').exists()).toBe(false);
    expect(wrapper.find(".recovered").text()).toBe("recovered");
  });

  it("uses the title and retryLabel props", async () => {
    silenceVueErrors();
    const wrapper = mount(TrackErrorBoundary, {
      props: { title: "Variant track unavailable", retryLabel: "Try again" },
      slots: { default: () => h(ThrowingTrack) },
    });
    await nextTick();
    expect(wrapper.text()).toContain("Variant track unavailable");
    expect(wrapper.find("button").text()).toBe("Try again");
  });
});