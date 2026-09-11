import { describe, expect, it } from "vitest";
import { buildAuditLogFilterParams } from "./audit-params";

describe("buildAuditLogFilterParams", () => {
  it("maps UI filters to the audit API contract", () => {
    expect(
      buildAuditLogFilterParams({
        search: "  editor  ",
        action: "login",
        ipAddress: " 192.0.2.10 ",
        startDate: "2026-01-01",
        endDate: "2026-01-31",
      }),
    ).toEqual({
      search: "editor",
      action: "login",
      ip_address: "192.0.2.10",
      start_date: "2026-01-01",
      end_date: "2026-01-31",
    });
  });

  it("omits empty values and the all-actions sentinel", () => {
    expect(
      buildAuditLogFilterParams({
        search: "  ",
        action: "all",
        ipAddress: "  ",
        startDate: "",
        endDate: "",
      }),
    ).toEqual({
      search: undefined,
      action: undefined,
      ip_address: undefined,
      start_date: undefined,
      end_date: undefined,
    });
  });
});
