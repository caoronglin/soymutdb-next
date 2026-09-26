import { http } from "./auth";
import { checkSpeciesInstanceHealth } from "./table-views";

vi.mock("./auth", () => ({ http: { get: vi.fn() } }));

const mockGet = vi.mocked(http.get);

describe("species instance health client contract", () => {
  beforeEach(() => mockGet.mockReset());

  it("requests one registered instance health snapshot", async () => {
    const health = {
      id: 7,
      code: "maize",
      connection_state: "unconfigured" as const,
      checked_at: "2026-09-26T10:00:00Z",
      last_checked_at: null,
      last_error_at: null,
      is_stale: true,
      error_code: "trust_not_configured",
      remote_management: "registration_only" as const,
    };
    mockGet.mockResolvedValueOnce(health);

    await expect(checkSpeciesInstanceHealth(7)).resolves.toEqual(health);
    expect(mockGet).toHaveBeenCalledWith("/admin/species-instances/7/health");
  });
});
