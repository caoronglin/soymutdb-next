// @vitest-environment jsdom
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The downloads catalogue offers a custom export. The control used to be a
 * button without a handler: the card promised an async export job and the
 * page had nothing to submit. These cases pin the two properties that make
 * it a real control: the submission is bound to one assembly namespace, and
 * a visitor the server would refuse is offered the sign-in path instead of a
 * button that always fails.
 */

const runtime = vi.hoisted(() => ({
  files: [] as unknown[],
  assemblies: [
    { id: 1, name: "Wm82.a4.v1", version: "v4", is_default: true },
    { id: 2, name: "Wm82.a2.v1", version: "v5", is_default: false },
  ],
  isResearcher: true,
  sessionStatus: "authenticated" as string,
  createVariantExport: vi.fn(),
  getVariantExportStatus: vi.fn(),
  getVariantExportDownload: vi.fn(),
}));

vi.mock("../lib/release-scope", () => ({
  // The pinned release is a React value, not a module read: the route
  // has to re-render when an operator publishes a new release.
  useReleaseId: () => "1",
}));
vi.mock("@tanstack/react-router", () => ({
  createFileRoute: () => (options: unknown) => ({ options, useSearch: () => ({}) }),
  useNavigate: () => vi.fn(),
}));
vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});
vi.mock("../lib/site-content-react", () => ({
  useSiteContent: () => ({ get: (_key: string, fallback: string) => fallback }),
}));
vi.mock("../components/route-motion", () => ({
  FadeUp: ({ children }: { children: React.ReactNode }) => children,
  Stagger: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("../components/file-viewer/file-preview-dialog", () => ({
  FilePreviewDialog: () => null,
}));
vi.mock("../lib/session-context", () => ({
  useSession: () => ({ sessionId: 1, status: runtime.sessionStatus }),
}));
vi.mock("../lib/use-current-user", () => ({
  useIsResearcher: () => ({ isResearcher: runtime.isResearcher, isLoading: false }),
}));
vi.mock("@tanstack/react-query", () => ({
  queryOptions: (options: unknown) => options,
  useQuery: (options: { queryKey: unknown[]; enabled?: boolean }) => {
    if (options.queryKey.includes("assemblies")) {
      return { data: runtime.assemblies, isLoading: false, isError: false };
    }
    if (options.queryKey.includes("export")) {
      return { data: options.enabled ? { status: "pending" } : undefined };
    }
    return { data: runtime.files, isLoading: false, isError: false };
  },
}));
vi.mock("@soymutdb/api-client", () => ({
  getDownloadFiles: async () => runtime.files,
  getDownloadUrl: async () => ({ url: "https://minio.test/file" }),
  getReleaseId: () => "1",
  createVariantExport: (...args: unknown[]) => runtime.createVariantExport(...args),
  getVariantExportStatus: (...args: unknown[]) => runtime.getVariantExportStatus(...args),
  getVariantExportDownload: (...args: unknown[]) => runtime.getVariantExportDownload(...args),
  submitExportQuery: async () => ({ export_id: "query-export-1", status: "pending", message: "submitted", format: "tsv", applied_filters: {} }),
}));
vi.mock("@/lib/antd", () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Select: ({
    value,
    onChange,
    options,
    id,
    "data-testid": testId,
  }: {
    value?: string;
    onChange?: (value: string) => void;
    options?: { value: string; label: string }[];
    id?: string;
    "data-testid"?: string;
  }) => (
    <select
      id={id}
      data-testid={testId ?? "download-export-assembly"}
      value={value ?? ""}
      onChange={(event) => onChange?.(event.target.value)}
    >
      {(options ?? []).map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  ),
  Skeleton: () => null,
  Table: ({ dataSource, columns }: {
    dataSource?: unknown[];
    columns?: { key?: string; render?: (_: unknown, row: unknown) => React.ReactNode }[];
  }) => (
    <table>
      <tbody>
        {(dataSource ?? []).map((row, index) => (
          <tr key={index}>
            {(columns ?? []).map((col) => (
              <td key={col.key}>{col.render ? col.render(undefined, row) : null}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  ),
  Tag: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Typography: {
    Title: ({ children, ...props }: React.HTMLAttributes<HTMLHeadingElement>) => (
      <h2 {...props}>{children}</h2>
    ),
    Paragraph: ({ children, ...props }: React.HTMLAttributes<HTMLParagraphElement>) => (
      <p {...props}>{children}</p>
    ),
    Text: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
      <span {...props}>{children}</span>
    ),
  },
}));

import { Route } from "./downloads";

const Page = (Route as unknown as { options: { component: React.ComponentType } }).options.component;

beforeEach(() => {
  vi.clearAllMocks();
  runtime.files = [];
  runtime.isResearcher = true;
  runtime.sessionStatus = "authenticated";
  runtime.createVariantExport.mockResolvedValue({ export_id: "export-1", message: "submitted" });
  runtime.getVariantExportStatus.mockResolvedValue({ status: "pending" });
  runtime.getVariantExportDownload.mockResolvedValue({ download_url: "https://minio.test/e" });
});

afterEach(cleanup);

it("submits a custom export bound to the selected assembly namespace", async () => {
  render(<Page />);
  const submit = screen.getByTestId("variant-export-submit");
  fireEvent.click(submit);
  await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));
  const body = runtime.createVariantExport.mock.calls[0][0] as {
    filters: { assembly: string };
  };
  // The default assembly of the release is the scope of an export that did
  // not choose one; an export may never span two coordinate namespaces.
  expect(body.filters.assembly).toBe("Wm82.a4.v1");
});

it("rebinds the export when another assembly is selected", async () => {
  render(<Page />);
  fireEvent.change(screen.getByTestId("download-export-assembly"), {
    target: { value: "2" },
  });
  fireEvent.click(screen.getByTestId("variant-export-submit"));
  await waitFor(() => expect(runtime.createVariantExport).toHaveBeenCalledTimes(1));
  const body = runtime.createVariantExport.mock.calls[0][0] as {
    filters: { assembly: string };
  };
  expect(body.filters.assembly).toBe("Wm82.a2.v1");
});

it("offers the sign-in path instead of a submission the server would refuse", async () => {
  runtime.isResearcher = false;
  render(<Page />);
  expect(screen.getByTestId("variant-export-gate")).toBeTruthy();
  const submit = screen.getByTestId("variant-export-submit") as HTMLButtonElement;
  expect(submit.disabled).toBe(true);
  fireEvent.click(submit);
  expect(runtime.createVariantExport).not.toHaveBeenCalled();
});

it("renders provenance columns and never shows a fake digest for a legacy file", async () => {
  runtime.files = [{
    id: "7",
    name: "legacy.tsv.gz",
    description: null,
    file_url: "https://minio.test/legacy.tsv.gz",
    file_size: 1024,
    category: "variants",
    download_count: 0,
    created_at: "2026-01-01T00:00:00Z",
    sha256: null,
    license: null,
    generated_at: null,
    source_ref: null,
  }];
  render(<Page />);
  await waitFor(() => expect(screen.getByTestId("download-checksum-7")).toBeTruthy());
  // A legacy file must not be presented as a verified checksum: no digest,
  // no empty string that a reader could mistake for a value.
  expect(screen.getByTestId("download-checksum-7").textContent).toBe("—");
  expect(screen.getByTestId("download-checksum-7").getAttribute("title")).toBe("");
  expect(screen.getByTestId("download-license-7").textContent).toBe("—");
});

it("shows the query builder empty state when the release has no assemblies", async () => {
  runtime.assemblies = [];
  render(<Page />);
  expect(screen.getByTestId("export-query-empty")).toBeTruthy();
  expect(screen.queryByTestId("export-query-form")).toBeNull();
});
