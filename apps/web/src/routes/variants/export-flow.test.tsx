import * as React from "react";
import { act, fireEvent, render, screen, cleanup, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * The export chain the portal owns: submit → poll the export record →
 * download through a short-lived signed link.
 *
 * The backend records the export (owner, status, artifact); the portal has
 * to surface that state, otherwise a submitted export is a dead end.
 */

const runtime = vi.hoisted(() => ({
  search: {
    assembly: "1",
    chromosome: "",
    variant_type: "",
    impact: "",
    mutant_line_public_id: "",
    cursor: undefined as string | undefined,
  },
  navigate: vi.fn(),
  sessionId: 1,
  sessionStatus: "authenticated",
  exportQueryEnabled: false,
  isResearcher: true,
  exportStatus: undefined as
    | { status: string; error_message?: string | null }
    | undefined,
  createVariantExport: vi.fn(),
  getVariantExportStatus: vi.fn(),
  getVariantExportDownload: vi.fn(),
}));

vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => runtime.search }),
  useNavigate: () => runtime.navigate,
}));
vi.mock("react-i18next", () => {
  // These boundary tests assert keys; keep their translator stable across renders.
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../../lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("../../lib/session-context", () => ({
  useSession: () => ({ sessionId: runtime.sessionId, status: runtime.sessionStatus }),
}));
vi.mock("../../lib/use-current-user", () => ({
  // The export endpoint requires the researcher capability. The capability is
  // the session's own answer (the server decides); the control only refuses
  // to offer a submission the server would reject.
  useIsResearcher: () => ({ isResearcher: runtime.isResearcher, isLoading: false }),
}));
vi.mock("../../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../../lib/release-scope", () => ({
  // The pinned release is a React value, not a module read: the route
  // has to re-render when an operator publishes a new release.
  useReleaseId: () => "1",
}));
vi.mock("@soymutdb/api-client", () => ({
  getReleaseId: () => "1",
  searchVariants: vi.fn(),
  createVariantExport: (...args: unknown[]) => runtime.createVariantExport(...args),
  getVariantExportStatus: (...args: unknown[]) => runtime.getVariantExportStatus(...args),
  getVariantExportDownload: (...args: unknown[]) => runtime.getVariantExportDownload(...args),
  getAssemblies: vi.fn(),
}));
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: (options: { queryKey: unknown[]; enabled?: boolean }) => {
    if (options.queryKey.includes("assemblies")) {
      return { data: [{ id: 1, name: "Wm82.a4.v1", is_default: true }] };
    }
    if (options.queryKey.includes("export")) {
      runtime.exportQueryEnabled = options.enabled === true;
      return { data: options.enabled ? runtime.exportStatus : undefined };
    }
    return { data: { items: [], has_more: false, next_cursor: null } };
  },
}));

import { Route } from "./index";

const Page = (Route.options as { component: React.ComponentType }).component;

beforeEach(() => {
  runtime.sessionId = 1;
  runtime.sessionStatus = "authenticated";
  runtime.exportQueryEnabled = false;
  runtime.exportStatus = undefined;
  runtime.isResearcher = true;
  runtime.createVariantExport.mockReset();
  runtime.getVariantExportStatus.mockReset();
  runtime.getVariantExportDownload.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

describe("variant export lifecycle", () => {
  it.each(["anonymous", "expired"])("clears exports on %s without a sessionId change", async (status) => {
    runtime.createVariantExport.mockResolvedValue({ export_id: "old-export", message: "old owner" });
    runtime.exportStatus = { status: "succeeded" };
    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await screen.findByTestId("variant-export-download");
    runtime.sessionStatus = status;
    view.rerender(<Page />);
    expect(screen.queryByTestId("variant-export-progress")).toBeNull();
    expect(screen.queryByText("old owner")).toBeNull();
    expect(runtime.exportQueryEnabled).toBe(false);
  });

  it.each(["success", "error"])("ignores late submission %s after logout", async (outcome) => {
    const pending = deferred<{ export_id: string; message: string }>();
    runtime.createVariantExport.mockReturnValue(pending.promise);
    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    runtime.sessionStatus = "anonymous";
    view.rerender(<Page />);
    await act(async () => {
      if (outcome === "success") pending.resolve({ export_id: "old-export", message: "old owner" });
      else pending.reject(new Error("old owner error"));
    });
    expect(screen.queryByTestId("variant-export-status")).toBeNull();
    expect(screen.queryByTestId("variant-export-progress")).toBeNull();
    expect(runtime.exportQueryEnabled).toBe(false);
  });

  it.each(["account switch", "unmount"])("does not open a late download link after %s", async (change) => {
    runtime.createVariantExport.mockResolvedValue({ export_id: "old-export" });
    runtime.exportStatus = { status: "succeeded" };
    const pending = deferred<{ download_url: string }>();
    runtime.getVariantExportDownload.mockReturnValue(pending.promise);
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    fireEvent.click(await screen.findByTestId("variant-export-download"));
    if (change === "account switch") {
      runtime.sessionId = 2;
      view.rerender(<Page />);
    } else {
      view.unmount();
    }
    await act(async () => { pending.resolve({ download_url: "https://minio.test/old-owner" }); });
    expect(clicked).not.toHaveBeenCalled();
  });

  it("does not submit an export for a session without the researcher capability", async () => {
    // The export endpoint requires the researcher capability. Offering the
    // control to a session the server refuses would be a button that can
    // only fail, so the control waits and explains instead.
    runtime.isResearcher = false;
    render(<Page />);
    expect(screen.getByTestId("variant-export-gate")).toBeTruthy();
    const submit = screen.getByTestId("variant-export-submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    fireEvent.click(submit);
    expect(runtime.createVariantExport).not.toHaveBeenCalled();
  });

  it("submits an export and then tracks the submitted record", async () => {
    runtime.createVariantExport.mockResolvedValue({
      export_id: "export-1",
      status: "pending",
      message: "Export job submitted",
    });
    const view = render(<Page />);

    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));

    // The success line is rendered from the resolved response, and the click
    // is what starts that promise: query it asynchronously. Reading it with
    // `getByTestId` immediately after `waitFor(called)` raced the microtask
    // and failed on whichever runner was slow enough to lose.
    expect(runtime.exportStatus).toBeUndefined();
    expect((await screen.findByTestId("variant-export-status")).textContent).toContain(
      "Export job submitted",
    );
    view.unmount();
  });

  it("shows the submitted status even when the request resolves late", async () => {
    // A loaded runner can resolve the request well after the mock call is
    // observed. The status must still appear once the response is applied.
    const pending = deferred<{ export_id: string; status: string; message: string }>();
    runtime.createVariantExport.mockReturnValue(pending.promise);
    const view = render(<Page />);

    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    expect(screen.queryByTestId("variant-export-status")).toBeNull();
    await act(async () => {
      pending.resolve({
        export_id: "export-1",
        status: "pending",
        message: "Export job submitted",
      });
    });

    expect((await screen.findByTestId("variant-export-status")).textContent).toContain(
      "Export job submitted",
    );
    view.unmount();
  });

  it("shows the finished export and downloads it through a signed link", async () => {
    runtime.createVariantExport.mockResolvedValue({
      export_id: "export-1",
      status: "pending",
      message: "Export job submitted",
    });
    runtime.exportStatus = { status: "succeeded" };
    runtime.getVariantExportDownload.mockResolvedValue({
      export_id: "export-1",
      download_url: "https://minio.test/exports/export-1.tsv.gz?sig=abc",
      filename: "export-1.tsv.gz",
      expires_at: "2026-10-22T00:00:00Z",
      expires_in_seconds: 900,
    });
    const clicked: string[] = [];
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this.href);
      });

    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));

    const downloadButton = await screen.findByTestId("variant-export-download");
    fireEvent.click(downloadButton);

    await waitFor(() => expect(runtime.getVariantExportDownload).toHaveBeenCalledWith("export-1"));
    expect(clicked[0]).toContain("https://minio.test/exports/export-1.tsv.gz");
    clickSpy.mockRestore();
    view.unmount();
  });

  it("reports a failed export instead of offering a download", async () => {
    runtime.createVariantExport.mockResolvedValue({
      export_id: "export-1",
      status: "pending",
      message: "Export job submitted",
    });
    runtime.exportStatus = { status: "failed", error_message: "unsupported filter" };

    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));

    expect((await screen.findByTestId("variant-export-error")).textContent).toContain(
      "unsupported filter",
    );
    expect(screen.queryByTestId("variant-export-download")).toBeNull();
    view.unmount();
  });

  it("drops the previous account's export when the session changes", async () => {
    runtime.createVariantExport.mockResolvedValue({
      export_id: "export-1",
      status: "pending",
      message: "Export job submitted",
    });
    runtime.exportStatus = { status: "pending" };

    const view = render(<Page />);
    fireEvent.click(screen.getByRole("button", { name: /variants.export$/ }));
    await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));
    // The same race the success line above was fixed for: `exportId` is set in
    // the same post-`await` block, so the progress block appears a microtask
    // after `waitFor(called)` returns.
    expect(await screen.findByTestId("variant-export-progress")).toBeTruthy();

    // Another account signs in: the previous account's export must not
    // keep being polled.
    runtime.sessionId = 2;
    view.rerender(<Page />);

    await waitFor(() => expect(screen.queryByTestId("variant-export-progress")).toBeNull());
    view.unmount();
  });
});
