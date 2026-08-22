import { http } from "./auth";
import {
  adminPluginsApi,
  type AdminPluginResponse,
  type AdminPluginsResponse,
  type PluginManifestMetadata,
} from "./admin-plugins";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPatch = vi.mocked(http.patch);

function plugin(): AdminPluginResponse {
  const manifest: PluginManifestMetadata = {
    manifest_version: 1,
    key: "jbrowse",
    version: "2.17.0",
    api_compatibility: {
      minimum: "2.0.0",
      maximum_exclusive: "3.0.0",
    },
    license: "LGPL-2.1-only",
    config_schema: { type: "object", properties: {} },
    routes: [{ method: "GET", path: "/api/v1/jbrowse/health" }],
    task_queues: [],
    resource_limits: {
      max_concurrency: 4,
      memory_mb: 512,
      timeout_seconds: 30,
    },
    healthcheck: {
      path: "/api/v1/jbrowse/health",
      interval_seconds: 30,
      timeout_seconds: 5,
    },
    assemblies: ["Glycine_max_v4.0"],
    uninstall_semantics: "retain_data",
  };
  return {
    key: "jbrowse",
    status: {
      version: "2.17.0",
      installed: true,
      enabled: true,
      configured: true,
      healthy: true,
      public_url: "https://browser.example.test",
      assemblies: ["Glycine_max_v4.0"],
      reason: null,
    },
    manifest,
  };
}

describe("admin plugins client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPatch.mockReset();
  });

  it("lists the deployment-installed plugin inventory", async () => {
    const response: AdminPluginsResponse = {
      plugins: { jbrowse: plugin() },
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(adminPluginsApi.list()).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/admin/plugins");
  });

  it("reads one plugin without exposing configuration values", async () => {
    const response = plugin();
    mockGet.mockResolvedValueOnce(response);

    await expect(adminPluginsApi.get("jbrowse")).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/admin/plugins/jbrowse");
  });

  it("changes only the server-owned enabled state", async () => {
    const response = plugin();
    response.status.enabled = false;
    mockPatch.mockResolvedValueOnce(response);

    await expect(adminPluginsApi.setEnabled("jbrowse", false)).resolves.toEqual(
      response,
    );
    expect(mockPatch).toHaveBeenCalledWith("/admin/plugins/jbrowse/state", {
      json: { enabled: false },
    });
  });
});
