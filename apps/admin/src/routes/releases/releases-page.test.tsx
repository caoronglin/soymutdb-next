import * as React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ReleasesPage from "../releases";

// The shared double, imported inside the factory: `vi.mock` is hoisted above
// the imports, so a factory closing over a top-level import hits the TDZ.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

/**
 * The antd facade is doubled; the page, its column definitions and its query
 * wiring are not. Each double renders what the page hands it — children,
 * `data-testid`, `color`, `disabled`, and one cell per column through the
 * column's own `render` — so every assertion below still exercises
 * `releases.tsx` rather than the double.
 */
vi.mock("@/lib/antd", () => {
  type Props = Record<string, unknown> & { children?: React.ReactNode };
  const testid = (props: Props) => props["data-testid"] as string | undefined;
  return {
    PageContainer: (props: Props) => (
      <section>
        <h1>{props.title as React.ReactNode}</h1>
        <p>{props.subTitle as React.ReactNode}</p>
        {props.children}
      </section>
    ),
    ProCard: (props: Props) => (
      <div data-testid={testid(props)} data-loading={String(Boolean(props.loading))}>
        {props.title as React.ReactNode}
        {props.children}
        {props.extra as React.ReactNode}
      </div>
    ),
    Alert: (props: Props) => (
      <div role="alert" data-testid={testid(props)}>
        {props.title as React.ReactNode}
        {props.action as React.ReactNode}
      </div>
    ),
    Button: (props: Props) => (
      <button type="button" data-testid={testid(props)} disabled={Boolean(props.loading)} onClick={props.onClick as () => void}>
        {props.children}
      </button>
    ),
    Tag: (props: Props) => (
      <span data-color={props.color as string | undefined}>{props.children}</span>
    ),
    Space: (props: Props) => <div>{props.children}</div>,
    Input: (props: Props) => (
      <input
        aria-label={props["aria-label"] as string | undefined}
        placeholder={props.placeholder as string | undefined}
        value={props.value as string | undefined}
        onChange={props.onChange as React.ChangeEventHandler<HTMLInputElement>}
      />
    ),
    Select: (props: Props) => {
      const options = props.options as Array<{ value: string; label: React.ReactNode }> | undefined;
      return (
        <select
          aria-label={props["aria-label"] as string | undefined}
          value={props.value as string | undefined}
          onChange={(event) => (props.onChange as (value: string) => void)?.(event.target.value)}
        >
          {options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      );
    },
    Typography: {
      Text: (props: Props) => (
        <span data-code={String(Boolean(props.code))} data-text-type={props.type as string | undefined}>
          {props.children}
        </span>
      ),
    },
    Descriptions: (props: Props) => {
      const items = props.items as Array<{ key: string; label?: React.ReactNode; children?: React.ReactNode }> | undefined;
      return (
        <dl data-testid={testid(props)}>
          {items?.map((item) => (
            <React.Fragment key={item.key}>
              <dt>{item.label}</dt>
              <dd>{item.children}</dd>
            </React.Fragment>
          ))}
        </dl>
      );
    },
    ProTable: (props: Props) => {
      const columns = props.columns as Array<{ key?: string; render?: (value: unknown, row: Record<string, unknown>, index: number) => React.ReactNode }> | undefined;
      const dataSource = props.dataSource as Array<Record<string, unknown>> | undefined;
      const rowKey = (props.rowKey as string | undefined) ?? "id";
      return (
        <table>
          <tbody>
            {dataSource?.map((row, index) => (
              <tr key={String(row[rowKey])} data-testid="release-row">
                {columns?.map((column) => (
                  <td key={String(column.key)}>{column.render?.(row[String(column.key)], row, index)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      );
    },
  };
});

const client = vi.hoisted(() => ({
  getAdminReleases: vi.fn(),
  getActiveRelease: vi.fn(),
  getAdminRelease: vi.fn(),
  // Kept in the double on purpose: a regression that reintroduces the call
  // fails as an assertion ("must not be called") instead of a confusing
  // "not a function" crash inside the page.
  getReleaseProvenance: vi.fn(),
}));

vi.mock("@soymutdb/api-client", () => client);

const PUBLISHED = {
  id: "7",
  version: "v5.0.0",
  name: "Glycine max v5",
  description: "Soybean reference 5",
  variant_count: 1234,
  gene_count: 56,
  mutant_line_count: 7,
  status: "published",
  published_at: "2026-10-02T08:30:00Z",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-10-02T08:30:00Z",
};

const DRAFT = {
  ...PUBLISHED,
  id: "3",
  version: "v5.1.0-rc1",
  status: "draft",
  published_at: null,
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ReleasesPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  client.getAdminReleases.mockReset().mockResolvedValue([PUBLISHED, DRAFT]);
  client.getActiveRelease
    .mockReset()
    .mockResolvedValue({ release_id: "7", version: "v5.0.0", published_at: "2026-10-02T08:30:00Z" });
  client.getAdminRelease.mockReset().mockResolvedValue(PUBLISHED);
  client.getReleaseProvenance.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("admin release list contract", () => {
  it("requests the list without pagination the endpoint ignores", async () => {
    renderPage();
    await screen.findByTestId("releases-table");
    // `list_releases` accepts only `status`; `page`/`page_size` were sent and dropped.
    expect(client.getAdminReleases).toHaveBeenCalledWith();
  });

  it("renders the fields the API returns and badges the active release", async () => {
    renderPage();
    const rows = await screen.findAllByTestId("release-row");
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain("v5.0.0");
    expect(rows[0].textContent).toContain("Glycine max v5");
    // `published_at` is the release date. The old Assembly column had no field
    // behind it and rendered empty on every row.
    expect(rows[0].textContent).toContain("Oct 2, 2026");
    // `stableT` returns the key when a translation is missing, so `releases.active`
    // is what the badge reads here and in the app when the locale lacks the key.
    expect(screen.getByText("releases.active")).toBeTruthy();
    expect(rows[0].textContent).toContain("releases.active");
    expect(rows[1].textContent).not.toContain("releases.active");
    // An unpublished release has no date, and must not print a broken one.
    expect(rows[1].textContent).toContain("—");
  });

  it("reads the row action from a route the API serves, never the unserved provenance route", async () => {
    renderPage();
    fireEvent.click(await screen.findByTestId("release-details-7"));
    await screen.findByTestId("release-detail-list");
    expect(client.getAdminRelease).toHaveBeenCalledWith("7");
    expect(client.getReleaseProvenance).not.toHaveBeenCalled();
    expect(screen.getByTestId("release-detail-heading").textContent).toContain("7");
    expect(screen.getByTestId("release-detail-list").textContent).toContain("Soybean reference 5");
  });

  it("keeps the list readable when the active-release pointer fails", async () => {
    client.getActiveRelease.mockRejectedValue(new Error("no pointer"));
    renderPage();
    await screen.findByTestId("releases-table");
    expect(screen.queryByText("releases.active")).toBeNull();
    expect(screen.getAllByTestId("release-row")).toHaveLength(2);
  });
});

describe("admin release failure recovery", () => {
  it("recovers a failed release-detail request through the retry action", async () => {
    client.getAdminRelease.mockRejectedValueOnce(new Error("upstream 503"));
    renderPage();
    fireEvent.click(await screen.findByTestId("release-details-7"));

    await screen.findByTestId("release-detail-error");
    expect(client.getAdminRelease).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("release-detail-retry"));
    await screen.findByTestId("release-detail-list");
    expect(client.getAdminRelease).toHaveBeenCalledTimes(2);
  });

  it("recovers a failed list request through the retry action", async () => {
    client.getAdminReleases.mockRejectedValueOnce(new Error("upstream 503"));
    renderPage();

    await screen.findByTestId("releases-error");
    fireEvent.click(screen.getByTestId("releases-retry"));

    await screen.findByTestId("releases-table");
    await waitFor(() => expect(screen.getAllByTestId("release-row")).toHaveLength(2));
  });
});
