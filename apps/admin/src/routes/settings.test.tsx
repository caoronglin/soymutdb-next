import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const endpoints = [
  "/admin/settings/general",
  "/admin/settings/about",
  "/admin/settings/data",
  "/admin/settings/email",
  "/admin/settings/security",
  "/admin/settings/file_preview",
] as const;

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
    const saveButtons = screen.getAllByRole("button", { name: "Save Changes" });
    expect(saveButtons[5]).toBeEnabled();
    fireEvent.click(saveButtons[5]);

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
      for (const endpoint of endpoints) {
        requests[endpoint].reject(new Error(`${endpoint} unavailable`));
      }
    });

    const errors = await screen.findAllByRole("alert");
    expect(errors).toHaveLength(7);
    expect(errors.map((error) => error.textContent)).toEqual([
      "Unable to load General settings. Refresh the page and try again.",
      "Unable to load About settings. Refresh the page and try again.",
      "Unable to load Data & Storage settings. Refresh the page and try again.",
      "Unable to load Email & Notifications settings. Refresh the page and try again.",
      "Unable to load Security settings. Refresh the page and try again.",
      "Unable to load CDN Configuration settings. Refresh the page and try again.",
      "Unable to load File Preview settings. Refresh the page and try again.",
    ]);

    for (const button of screen.getAllByRole("button", { name: "Save Changes" })) {
      expect(button).toBeDisabled();
    }
  });

  it("keeps every section save action disabled until its configuration has loaded", async () => {
    renderPage();

    const saveButtons = screen.getAllByRole("button", { name: "Save Changes" });
    expect(saveButtons).toHaveLength(7);
    for (const button of saveButtons) {
      expect(button).toBeDisabled();
    }

    await waitFor(() => {
      for (const endpoint of endpoints) {
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
      for (const button of saveButtons) {
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
