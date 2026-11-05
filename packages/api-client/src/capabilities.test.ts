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
      version: 3,
      features: { page_builder: true },
      plugins: { jbrowse: plugin() },
      databases: {
        authoritative: "postgresql" as const,
        analytics: "postgresql" as const,
      },
      sequence: {
        available: false,
        engine: null,
        engine_version: null,
        reason: "compiled bio-core wheel is not installed",
        max_inline_sequence: 1_048_576,
        max_pattern: 256,
        max_hits: 1000,
        k_range: [1, 32],
        genetic_codes: [1],
        coordinate_system_internal: "0-based-half-open",
        coordinate_system_public: "1-based-inclusive",
        programs: ["reverse-complement", "match", "align", "stats", "orfs", "translate", "kmers"],
        formats: ["fasta", "fastq", "bed"],
      },
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(capabilitiesApi.get()).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/capabilities");
  });
});
