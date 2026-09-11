import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./settings";

const { getMock, putMock, cdnGetMock, cdnPatchMock } = vi.hoisted(() => ({
  getMock: vi.fn(),
  putMock: vi.fn(),
  cdnGetMock: vi.fn(),
  cdnPatchMock: vi.fn(),
}));

// The shared double keeps a stable `t` identity: an inline
// `() => ({ t: ... })` returns a new function per render and makes any
// component with `t` in an effect dependency loop forever. See test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);

vi.mock("@soymutdb/api-client", () => ({
  http: {
    get: getMock,
    put: putMock,
  },
  adminSettingsApi: {
    get: cdnGetMock,
    patch: cdnPatchMock,
  },
}));

vi.mock("../components/confirm-dialog", () => ({
  ConfirmDialog: ({ open, title, description }: any) =>
    open ? (
      <div role="dialog">
        <p>{title}</p>
        <p>{description}</p>
      </div>
    ) : null,
}));

vi.mock("../components/rich-editor/rich-editor", () => ({
  RichEditor: ({ value, onChange }: any) => (
    <textarea value={value} onChange={(event) => onChange(event.target.value)} />
  ),
}));

type Deferred = {
  promise: Promise<unknown>;
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
};

function deferred(): Deferred {
  let resolve!: (value: unknown) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<unknown>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

/**
 * Every section the page loads over `http.get`. Sections that carry site
 * content are variant-scoped (`<base>_<variant>`); the page defaults to the
 * `external` variant. `cdn` is excluded because it loads through
 * `adminSettingsApi.get("cdn")` and is asserted separately.
 */
const endpoints = [
  "/admin/settings/general",
  "/admin/settings/about_external",
  "/admin/settings/home_external",
  "/admin/settings/data",
  "/admin/settings/email",
  "/admin/settings/security",
  "/admin/settings/file_preview",
  "/admin/settings/footer_external",
  "/admin/settings/content_external",
] as const;

// The page renders one save action per section; keep this in sync with the
// section list in `settings.tsx`.
const SECTION_COUNT = 10;

/**
 * Sections that surface a load-error alert when their request fails. `cdn`
 * resolves through `adminSettingsApi.get` and `content` only loads once the
 * schema query returns fields, so neither is part of this failure scenario.
 */
const LOAD_ERROR_SECTIONS = 8;

/**
 * `content_external` is only requested after the schema query returns fields.
 * With no schema mocked it is never fetched, so rejecting its deferred would
 * leave an unhandled rejection and make the whole run exit non-zero.
 */
const SECTION_ENDPOINTS = endpoints.filter(
  (endpoint) => endpoint !== "/admin/settings/content_external",
);

let requests: Record<(typeof endpoints)[number], Deferred>;

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  getMock.mockReset();
  putMock.mockReset();
  cdnGetMock.mockReset();
  cdnPatchMock.mockReset();
  putMock.mockResolvedValue({});
  cdnPatchMock.mockResolvedValue({ section: "cdn", version: 2, values: { enabled: true, url: "https://cdn.example/echarts.js" } });
  requests = Object.fromEntries(endpoints.map((endpoint) => [endpoint, deferred()])) as Record<
    (typeof endpoints)[number],
    Deferred
  >;
  getMock.mockImplementation((endpoint: string) => requests[endpoint as keyof typeof requests]?.promise ?? Promise.resolve({}));
  cdnGetMock.mockResolvedValue({ section: "cdn", version: 1, values: { enabled: true, url: "https://cdn.example/echarts.js" } });
});

describe("SettingsPage save protection", () => {
  it("does not render retired GSAP or Lenis CDN fields", () => {
    renderPage();

    expect(screen.queryByLabelText("GSAP CDN URL")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Lenis CDN URL")).not.toBeInTheDocument();
  });

  it("uses the backend CDN contract without retired motion engines", async () => {
    renderPage();
    await act(async () => {
      for (const endpoint of endpoints) {
        requests[endpoint].resolve({});
      }
      await Promise.resolve();
    });

    const echartsInput = screen.getByLabelText("ECharts CDN URL");
    await waitFor(() =>
      expect(echartsInput).toHaveValue("https://cdn.example/echarts.js"),
    );
    // Resolve the CDN card's own save action structurally instead of trusting a
    // positional index, which silently retargets when a section is added.
    const cdnUrlInput = screen.getByLabelText("ECharts CDN URL");
    const cdnCard = cdnUrlInput.closest(".ant-card");
    expect(cdnCard).not.toBeNull();
    const cdnSave = within(cdnCard as HTMLElement).getByRole("button", {
      name: "Save Changes",
    });
    expect(cdnSave).toBeEnabled();
    fireEvent.click(cdnSave);

    await waitFor(() => {
      expect(cdnPatchMock).toHaveBeenCalledWith("cdn", 1, {
        enabled: true,
        url: "https://cdn.example/echarts.js",
      });
    });
  });

  it("announces every failed configuration load accessibly", async () => {
    renderPage();

    act(() => {
      for (const endpoint of SECTION_ENDPOINTS) {
        requests[endpoint].reject(new Error(`${endpoint} unavailable`));
      }
    });

    const errors = await screen.findAllByRole("alert");
    expect(errors).toHaveLength(LOAD_ERROR_SECTIONS);
    expect(errors.map((error) => error.textContent)).toEqual([
      "Unable to load General settings. Refresh the page and try again.",
      "Unable to load About settings. Refresh the page and try again.",
      "Unable to load Homepage welcome settings. Refresh the page and try again.",
      "Unable to load Data & Storage settings. Refresh the page and try again.",
      "Unable to load Email & Notifications settings. Refresh the page and try again.",
      "Unable to load Security settings. Refresh the page and try again.",
      "Unable to load File Preview settings. Refresh the page and try again.",
      "Unable to load Footer settings. Refresh the page and try again.",
    ]);

    // A section whose load failed must not offer a save action. Only the CDN
    // section resolved successfully in this scenario, so it is excluded.
    const cdnUrlInput = screen.getByLabelText("ECharts CDN URL");
    const cdnCard = cdnUrlInput.closest(".ant-card");
    for (const button of screen.getAllByRole("button", { name: "Save Changes" })) {
      if (cdnCard?.contains(button)) continue;
      expect(button).toBeDisabled();
    }
  });

  it("keeps every section save action disabled until its configuration has loaded", async () => {
    renderPage();

    const saveButtons = screen.getAllByRole("button", { name: "Save Changes" });
    expect(saveButtons).toHaveLength(SECTION_COUNT);
    for (const button of saveButtons) {
      expect(button).toBeDisabled();
    }

    await waitFor(() => {
      // `content_external` only loads once the schema query yields fields, so it
      // is excluded from the request assertions here.
      for (const endpoint of endpoints) {
        if (endpoint === "/admin/settings/content_external") continue;
        expect(getMock).toHaveBeenCalledWith(endpoint);
      }
      expect(cdnGetMock).toHaveBeenCalledWith("cdn");
    });

    act(() => {
      for (const endpoint of endpoints) {
        requests[endpoint].resolve({});
      }
    });

    await waitFor(() => {
      // The content section stays disabled until its schema arrives; every
      // other section becomes actionable once its configuration resolves.
      for (const button of saveButtons) {
        if (button === saveButtons[SECTION_COUNT - 2]) continue;
        expect(button).toBeEnabled();
      }
    });
  });

  it("does not show a success confirmation when saving a section fails", async () => {
    renderPage();
    act(() => {
      for (const endpoint of endpoints) {
        requests[endpoint].resolve({});
      }
    });

    const saveButtons = screen.getAllByRole("button", { name: "Save Changes" });
    await waitFor(() => expect(saveButtons[0]).toBeEnabled());

    putMock.mockRejectedValueOnce(new Error("network unavailable"));
    fireEvent.click(saveButtons[0]);

    await waitFor(() => expect(putMock).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
