import { http } from "./client";
import {
  capabilitiesApi,
  getPluginAvailability,
  type PluginCapability,
} from "./capabilities";

vi.mock("./client", () => ({
  http: {
    get: vi.fn(),
    put: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);

function plugin(overrides: Partial<PluginCapability> = {}): PluginCapability {
  return {
    version: "1.0.0",
    installed: true,
    enabled: true,
    configured: true,
    healthy: true,
    public_url: "https://plugins.example.test/tool",
    assemblies: ["Glycine_max_v4.0"],
    reason: null,
    ...overrides,
  };
}

describe("plugin capability availability", () => {
  it.each([
    [undefined, "not_installed"],
    [plugin({ installed: false }), "not_installed"],
    [plugin({ enabled: false }), "plugin_disabled"],
    [plugin({ configured: false }), "not_configured"],
    [plugin({ healthy: false, reason: "upstream_timeout" }), "upstream_timeout"],
  ] as const)("rejects an unavailable plugin", (capability, reason) => {
    expect(getPluginAvailability(capability)).toEqual({
      available: false,
      reason,
    });
  });

  it("accepts only an installed, enabled, configured and healthy plugin", () => {
    expect(getPluginAvailability(plugin())).toEqual({
      available: true,
      reason: null,
    });
  });
});

describe("capabilities API", () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it("reads the compatible public capability snapshot", async () => {
    const response = {
      version: 2,
      features: { page_builder: true },
      plugins: { jbrowse: plugin() },
      databases: {
        authoritative: "postgresql" as const,
        analytics: "postgresql" as const,
      },
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(capabilitiesApi.get()).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/capabilities");
  });
});
