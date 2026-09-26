import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";
import LocusSearch from "./LocusSearch.vue";

describe("LocusSearch", () => {
  it("disables submit until there is a non-blank value", async () => {
    const wrapper = mount(LocusSearch, { props: { modelValue: "   " } });
    expect(wrapper.find("button").attributes("disabled")).toBeDefined();
    await wrapper.setProps({ modelValue: "chr01:1-1000" });
    expect(wrapper.find("button").attributes("disabled")).toBeUndefined();
  });

  it("emits update:modelValue on input and submit on form submission", async () => {
    const wrapper = mount(LocusSearch, { props: { modelValue: "chr01" } });
    const input = wrapper.find("input");
    await input.setValue("chr01:1-1000");
    expect(wrapper.emitted("update:modelValue")?.at(-1)).toEqual(["chr01:1-1000"]);

    await wrapper.setProps({ modelValue: "  chr01:1-1000  " });
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("submit")?.at(-1)).toEqual(["chr01:1-1000"]);
  });

  it("does not submit a blank value", async () => {
    const wrapper = mount(LocusSearch, { props: { modelValue: "   " } });
    await wrapper.find("form").trigger("submit");
    expect(wrapper.emitted("submit")).toBeUndefined();
  });
});
