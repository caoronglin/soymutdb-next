import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FeaturesPage from "./features";

// The shared double keeps a stable `t` identity and interpolates `{{placeholders}}`:
// an unmocked i18next leaves raw keys/templates in the DOM, which reads as a product bug.
// See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

const { adminGetMock, getMock, updateMock } = vi.hoisted(() => ({
  adminGetMock: vi.fn(),
  getMock: vi.fn(),
  updateMock: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => ({
  capabilitiesApi: {
    adminGet: adminGetMock,
    get: getMock,
    adminUpdate: updateMock,
  },
  getPluginAvailability: (plugin: any) => {
    if (!plugin?.installed) return { available: false, reason: "not_installed" };
    if (!plugin.enabled) return { available: false, reason: "plugin_disabled" };
    if (!plugin.configured) return { available: false, reason: "not_configured" };
    if (!plugin.healthy) return { available: false, reason: plugin.reason ?? "plugin_unhealthy" };
    return { available: true, reason: null };
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <FeaturesPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  adminGetMock.mockReset();
  getMock.mockReset();
  updateMock.mockReset();
});

describe("FeaturesPage explicit capability state", () => {
  it("announces feature and plugin loading without presenting either as disabled", () => {
    adminGetMock.mockReturnValue(new Promise(() => {}));
    getMock.mockReturnValue(new Promise(() => {}));
    renderPage();

    expect(screen.getByText("Loading feature flags…")).toBeInTheDocument();
    expect(screen.getByText("Loading plugin status…")).toBeInTheDocument();
    expect(screen.queryByText("plugin_disabled")).not.toBeInTheDocument();
  });

  it("shows a plugin request failure separately from a disabled feature", async () => {
    adminGetMock.mockResolvedValue({
      version: 2,
      features: [{
        key: "imports.module_tsv",
        enabled: false,
        default: true,
        public: true,
        description: "Module imports",
        disable_behavior: "reject_new_requests",
      }],
    });
    getMock.mockRejectedValue(new Error("offline"));
    renderPage();

    expect(await screen.findByRole("alert", { name: "Plugin status unavailable" })).toHaveTextContent(
      "Unable to load plugin status.",
    );
    expect(screen.getByRole("button", { name: "Enable imports.module_tsv" })).toHaveTextContent(
      "Disabled",
    );
  });

  it("renders a server-owned plugin lifecycle reason", async () => {
    adminGetMock.mockResolvedValue({ version: 2, features: [] });
    getMock.mockResolvedValue({
      version: 2,
      features: {},
      plugins: {
        jbrowse: {
          installed: true,
          enabled: false,
          configured: true,
          healthy: true,
          reason: null,
        },
      },
      databases: { authoritative: "postgresql", analytics: "clickhouse" },
    });
    renderPage();

    expect(await screen.findByText("plugin_disabled")).toBeInTheDocument();
  });
});
