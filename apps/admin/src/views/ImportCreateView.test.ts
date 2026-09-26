// @vitest-environment jsdom
import { flushPromises } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adminImportsApi } from "@soymutdb/api-client";

import { mountAdminView } from "../test/support";
import ImportCreateView from "./ImportCreateView.vue";

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return {
    ...actual,
    adminImportsApi: { ...actual.adminImportsApi, create: vi.fn() },
  };
});

beforeEach(() => {
  vi.mocked(adminImportsApi.create)
    .mockReset()
    .mockResolvedValue({ id: 7, filename: "variants.vcf", type: "vcf", status: "queued" } as never);
});

describe("ImportCreateView (P1-06)", () => {
  it("creates an import with an idempotency key and navigates to its detail", async () => {
    const { wrapper, router } = mountAdminView(ImportCreateView, { path: "/imports/new" });
    await flushPromises();

    await wrapper.get('[data-testid="import-create-filename"]').setValue("variants.vcf");
    await wrapper.get('[data-testid="import-create-object-key"]').setValue("s3://bucket/v.vcf");
    await wrapper.get("form").trigger("submit.prevent");
    await flushPromises();

    expect(vi.mocked(adminImportsApi.create)).toHaveBeenCalledTimes(1);
    const payload = vi.mocked(adminImportsApi.create).mock.calls[0][0];
    expect(payload.filename).toBe("variants.vcf");
    expect(payload.type).toBe("vcf");
    expect(payload.object_key).toBe("s3://bucket/v.vcf");
    expect(payload.idempotency_key).toBeTruthy();
    expect(router.currentRoute.value.path).toBe("/imports/7");
    wrapper.unmount();
  });
});
