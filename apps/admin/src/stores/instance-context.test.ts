import { beforeEach, describe, expect, it } from "vitest";

import { createPinia, setActivePinia } from "pinia";

import { useAdminInstanceContext } from "./instance-context";

beforeEach(() => {
  setActivePinia(createPinia());
});

describe("admin instance context", () => {
  it("defaults to no explicit selection (the local instance)", () => {
    const store = useAdminInstanceContext();
    expect(store.selectedCode).toBeNull();
  });

  it("keeps the selection in module memory for the session", () => {
    const store = useAdminInstanceContext();
    store.select("peer-cn");
    expect(store.selectedCode).toBe("peer-cn");
  });

  it("returns to the default when the selection is cleared", () => {
    const store = useAdminInstanceContext();
    store.select("peer-cn");
    store.select(null);
    expect(store.selectedCode).toBeNull();
  });
});
