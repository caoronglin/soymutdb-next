// @vitest-environment jsdom
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The export lifecycle's polling window.
 *
 * An export is a background job, so a long preparation is legitimate. But a
 * record that never reaches a final state must not keep the portal polling
 * forever: the visitor would watch an endless "preparing" line for a job
 * that may never resolve. The window closes, the portal says so, and the
 * visitor decides whether to look again.
 */

const runtime = vi.hoisted(() => ({
  queryOptions: null as null | { refetchInterval?: (query: unknown) => number | false },
  data: undefined as { status: string } | undefined,
  isError: false,
  createVariantExport: vi.fn(),
  getVariantExportStatus: vi.fn(),
  getVariantExportDownload: vi.fn(),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: (options: { refetchInterval?: (query: unknown) => number | false }) => {
    runtime.queryOptions = options;
    return { data: runtime.data, isError: runtime.isError, refetch: vi.fn() };
  },
}));
vi.mock("../lib/session-context", () => ({
  useSession: () => ({ sessionId: 1, status: "authenticated" }),
}));
vi.mock("@soymutdb/api-client", () => ({
  createVariantExport: (...args: unknown[]) => runtime.createVariantExport(...args),
  getVariantExportStatus: (...args: unknown[]) => runtime.getVariantExportStatus(...args),
  getVariantExportDownload: (...args: unknown[]) => runtime.getVariantExportDownload(...args),
}));

import { useVariantExport } from "./use-variant-export";

const pendingQuery = { state: { data: { status: "pending" }, status: "success" } };

beforeEach(() => {
  runtime.queryOptions = null;
  runtime.data = { status: "pending" };
  runtime.isError = false;
  runtime.createVariantExport.mockReset().mockResolvedValue({ export_id: "export-1" });
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-29T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

it("polls while the export is in flight and stops when the window closes", async () => {
  const { result } = renderHook(() =>
    useVariantExport({ assemblyKey: "Wm82.a4.v1", pollDeadlineMs: 1000 }),
  );

  expect(runtime.queryOptions?.refetchInterval?.(pendingQuery)).toBe(3000);

  await act(async () => {
    await result.current.requestExport();
  });
  expect(result.current.exportId).toBe("export-1");
  expect(result.current.pollExpired).toBe(false);
  expect(runtime.queryOptions?.refetchInterval?.(pendingQuery)).toBe(3000);

  // The window closes: the portal stops polling and says so.
  await act(async () => {
    vi.advanceTimersByTime(2000);
  });
  expect(result.current.pollExpired).toBe(true);
  expect(runtime.queryOptions?.refetchInterval?.(pendingQuery)).toBe(false);
});

it("stops polling as soon as the export reaches a final state", async () => {
  const { result } = renderHook(() =>
    useVariantExport({ assemblyKey: "Wm82.a4.v1", pollDeadlineMs: 1000 }),
  );

  await act(async () => {
    await result.current.requestExport();
  });

  runtime.data = { status: "succeeded" };
  const finished = { state: { data: { status: "succeeded" }, status: "success" } };
  expect(runtime.queryOptions?.refetchInterval?.(finished)).toBe(false);
  expect(result.current.pollExpired).toBe(false);
});

it("reports a status lookup failure as a terminal state, not endless pending", async () => {
  const { result } = renderHook(() =>
    useVariantExport({ assemblyKey: "Wm82.a4.v1", pollDeadlineMs: 1000 }),
  );

  await act(async () => {
    await result.current.requestExport();
  });
  expect(result.current.statusUnavailable).toBe(false);

  // The record is gone (expired, or it belongs to another account): the
  // lookup stops polling, so the portal has to say the state is unknown
  // instead of leaving "preparing" on screen for the rest of the window.
  runtime.isError = true;
  runtime.data = undefined;
  const failed = { state: { data: undefined, status: "error" } };
  expect(runtime.queryOptions?.refetchInterval?.(failed)).toBe(false);

  await act(async () => {
    vi.advanceTimersByTime(1000);
  });
  expect(result.current.statusUnavailable).toBe(true);
  expect(result.current.exportStatus).toBeUndefined();
});
