import { http } from "./auth";
import {
  adminSettingsApi,
  type SettingsDocumentResponse,
  type SettingsHistoryResponse,
  type SettingsSchemaResponse,
} from "./admin-settings";

vi.mock("./auth", () => ({
  http: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
  },
}));

const mockGet = vi.mocked(http.get);
const mockPost = vi.mocked(http.post);
const mockPatch = vi.mocked(http.patch);

describe("typed admin settings client", () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPost.mockReset();
    mockPatch.mockReset();
  });

  it("reads the non-secret registry schema", async () => {
    const response: SettingsSchemaResponse = {
      version: 1,
      sections: {
        email: {
          fields: {
            enabled: {
              kind: "boolean",
              default: true,
              permission: "administrator",
              scope: "global",
              hot_reload: true,
              redaction: "none",
              requires_approval: false,
              allowed_values: [],
              allowed_url_hosts: [],
              minimum: null,
              maximum: null,
              max_length: 5,
            },
          },
        },
      },
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(adminSettingsApi.schema()).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/admin/settings/schema");
  });

  it("reads a typed document with the optimistic-lock version", async () => {
    const response: SettingsDocumentResponse = {
      section: "email",
      version: 3,
      values: { enabled: true, port: 587 },
    };
    mockGet.mockResolvedValueOnce(response);

    await expect(adminSettingsApi.get("email")).resolves.toEqual(response);
    expect(mockGet).toHaveBeenCalledWith("/admin/settings/email/document");
  });

  it("validates and normalizes without persisting", async () => {
    const response = {
      section: "email",
      valid: true as const,
      values: { enabled: true },
    };
    mockPost.mockResolvedValueOnce(response);

    await expect(
      adminSettingsApi.validate("email", { enabled: true }),
    ).resolves.toEqual(response);
    expect(mockPost).toHaveBeenCalledWith("/admin/settings/validate", {
      json: { section: "email", values: { enabled: true } },
    });
  });

  it("PATCHes only when the expected version matches", async () => {
    const response: SettingsDocumentResponse = {
      section: "email",
      version: 4,
      values: { enabled: false },
    };
    mockPatch.mockResolvedValueOnce(response);

    await expect(
      adminSettingsApi.patch("email", 3, { enabled: false }),
    ).resolves.toEqual(response);
    expect(mockPatch).toHaveBeenCalledWith("/admin/settings/email", {
      json: { expected_version: 3, values: { enabled: false } },
    });
  });

  it("reads bounded history and rolls back as a new version", async () => {
    const history: SettingsHistoryResponse = {
      section: "email",
      current_version: 4,
      items: [],
    };
    mockGet.mockResolvedValueOnce(history);
    mockPost.mockResolvedValueOnce({
      section: "email",
      version: 5,
      values: { enabled: true },
    });

    await expect(adminSettingsApi.history("email", 25)).resolves.toEqual(history);
    expect(mockGet).toHaveBeenCalledWith("/admin/settings/email/history", {
      params: { limit: 25 },
    });

    await adminSettingsApi.rollback("email", {
      expected_version: 4,
      target_version: 1,
      reason: "Restore known-good mail settings",
    });
    expect(mockPost).toHaveBeenCalledWith("/admin/settings/email/rollback", {
      json: {
        expected_version: 4,
        target_version: 1,
        reason: "Restore known-good mail settings",
      },
    });
  });
});
