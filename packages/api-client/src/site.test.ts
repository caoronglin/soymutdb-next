import { authRequest, http } from "./auth";
import { request } from "./client";
import {
  getAdminSiteBranding,
  getSiteBranding,
  getSiteContent,
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

  it("asks for the full content map by default", async () => {
    mockPublicRequest.mockResolvedValueOnce({ "hero.title": "Default" });

    await getSiteContent("external");

    expect(mockPublicRequest).toHaveBeenCalledWith("/site/content", {
      params: { variant: "external" },
      auth: false,
    });
  });

  it("can ask for overrides only, so a locale default is not clobbered", async () => {
    mockPublicRequest.mockResolvedValueOnce({ "hero.title": "运营改过的标题" });

    const content = await getSiteContent("external", { onlyOverrides: true });

    expect(mockPublicRequest).toHaveBeenCalledWith("/site/content", {
      params: { variant: "external", only_overrides: true },
      auth: false,
    });
    expect(content).toEqual({ "hero.title": "运营改过的标题" });
  });

  it("keeps the internal content read on the authenticated transport", async () => {
    mockAuthRequest.mockResolvedValueOnce({});

    await getSiteContent("internal", { onlyOverrides: true });

    expect(mockAuthRequest).toHaveBeenCalledWith("/site/content", {
      params: { variant: "internal", only_overrides: true },
    });
    expect(mockPublicRequest).not.toHaveBeenCalled();
  });
});
