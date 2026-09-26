import { authRequest, http } from "./auth";
import { request } from "./client";
import {
  getAdminSiteBranding,
  getSiteBranding,
  patchAdminSiteBranding,
} from "./site";

vi.mock("./auth", () => ({
  authRequest: vi.fn(),
  http: { get: vi.fn(), patch: vi.fn() },
}));
vi.mock("./client", () => ({ request: vi.fn() }));

const mockAuthRequest = vi.mocked(authRequest);
const mockPublicRequest = vi.mocked(request);
const mockGet = vi.mocked(http.get);
const mockPatch = vi.mocked(http.patch);

describe("site branding client contract", () => {
  beforeEach(() => {
    mockAuthRequest.mockReset();
    mockPublicRequest.mockReset();
    mockGet.mockReset();
    mockPatch.mockReset();
  });

  it("reads public branding with an explicit external variant", async () => {
    const brand = {
      variant: "external" as const,
      name_zh: "大豆数据库",
      name_en: "SoyMutDB",
      icon_url: null,
    };
    mockPublicRequest.mockResolvedValueOnce(brand);

    await expect(getSiteBranding()).resolves.toEqual(brand);
    expect(mockPublicRequest).toHaveBeenCalledWith("/site/branding", {
      params: { variant: "external" },
      auth: false,
    });
  });

  it("keeps internal brand reads authenticated and private by variant", async () => {
    mockAuthRequest.mockResolvedValueOnce({
      variant: "internal",
      name_zh: "内部站",
      name_en: "Internal",
      icon_url: null,
    });

    await getSiteBranding("internal");
    expect(mockAuthRequest).toHaveBeenCalledWith("/site/branding", {
      params: { variant: "internal" },
    });
  });

  it("uses versioned admin brand GET and PATCH contracts", async () => {
    const document = {
      variant: "external" as const,
      version: 2,
      values: { name_zh: "大豆数据库", name_en: "SoyMutDB", icon_url: null },
    };
    mockGet.mockResolvedValueOnce(document);
    mockPatch.mockResolvedValueOnce({ ...document, version: 3 });

    await getAdminSiteBranding("external");
    expect(mockGet).toHaveBeenCalledWith("/admin/settings/site-brand", {
      params: { variant: "external" },
    });
    await patchAdminSiteBranding("external", 2, { icon_url: null });
    expect(mockPatch).toHaveBeenCalledWith("/admin/settings/site-brand", {
      params: { variant: "external" },
      json: { expected_version: 2, values: { icon_url: null } },
    });
  });
});
