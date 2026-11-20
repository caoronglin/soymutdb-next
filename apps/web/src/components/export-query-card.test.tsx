// @vitest-environment jsdom
import * as React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

/**
 * The query builder is the "no SQL" entry point to the one export pipeline.
 * Two properties matter more than the form's shape: the assembly it submits is
 * the resolved *name* (a numeric id would be a namespace the worker cannot
 * scope), and a visitor the API would refuse never gets to submit. A card
 * that renders but silently drops a filter would hand back an artifact the
 * downloader did not ask for.
 */

const runtime = vi.hoisted(() => ({
  submitExportQuery: vi.fn(),
  isResearcher: true,
}));

vi.mock("react-i18next", async () => (await import("../test/mocks")).mockTranslation);
vi.mock("../lib/use-current-user", () => ({
  useIsResearcher: () => ({ isResearcher: runtime.isResearcher, isLoading: false }),
}));
vi.mock("@soymutdb/api-client", () => ({
  submitExportQuery: (...args: unknown[]) => runtime.submitExportQuery(...args),
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
    "data-testid": testId,
  }: {
    value?: string;
    onChange?: (value: string) => void;
    options?: { value: string; label: string }[];
    "data-testid"?: string;
  }) => (
    <select
      data-testid={testId}
      value={value ?? ""}
      onChange={(event) => onChange?.(event.target.value)}
    >
      {(options ?? []).map((option) => (
        <option key={option.value} value={option.value}>{option.label}</option>
      ))}
    </select>
  ),
  Typography: {
    Text: ({ children, ...props }: React.HTMLAttributes<HTMLSpanElement>) => (
      <span {...props}>{children}</span>
    ),
  },
}));

import { ExportQueryCard } from "./export-query-card";

const ASSEMBLIES = [
  { id: 7, name: "Wm82.a4.v1", is_default: true },
  { id: 9, name: "Wm82.a2.v1", is_default: false },
];

beforeEach(() => {
  runtime.isResearcher = true;
  runtime.submitExportQuery = vi.fn(async () => ({
    export_id: "export-1",
    status: "pending",
    message: "submitted",
    format: "tsv",
    applied_filters: {},
  }));
});
afterEach(() => cleanup());

it("submits the assembly name, not its numeric id", async () => {
  render(<ExportQueryCard assemblies={ASSEMBLIES} />);

  fireEvent.click(screen.getByTestId("export-query-submit"));

  await waitFor(() => expect(runtime.submitExportQuery).toHaveBeenCalledTimes(1));
  const payload = runtime.submitExportQuery.mock.calls[0][0];
  // The worker scopes its SQL by assembly key; an id here would export a
  // namespace the release does not publish.
  expect(payload.filters.assembly).toBe("Wm82.a4.v1");
  await waitFor(() =>
    expect(screen.getByTestId("export-query-success").textContent).toContain("export-1")
  );
});

it("sends only the filters the operator actually set", async () => {
  render(<ExportQueryCard assemblies={ASSEMBLIES} />);

  fireEvent.click(screen.getByTestId("export-query-submit"));

  await waitFor(() => expect(runtime.submitExportQuery).toHaveBeenCalledTimes(1));
  const payload = runtime.submitExportQuery.mock.calls[0][0];
  // Empty controls must not be sent as empty strings: the API validates
  // values, and "" for a chromosome is a constraint, not an absence.
  expect(Object.keys(payload.filters)).toEqual(["assembly"]);
});

it("does not submit for a visitor the API would refuse", async () => {
  runtime.isResearcher = false;
  render(<ExportQueryCard assemblies={ASSEMBLIES} />);

  const submit = screen.getByTestId("export-query-submit");
  expect(submit.hasAttribute("disabled")).toBe(true);
  fireEvent.click(submit);
  await waitFor(() => expect(runtime.submitExportQuery).not.toHaveBeenCalled());
});

it("reports a refused submission instead of pretending it succeeded", async () => {
  runtime.submitExportQuery = vi.fn(async () => {
    throw new Error("Unsupported query filter(s): go_term");
  });
  render(<ExportQueryCard assemblies={ASSEMBLIES} />);

  fireEvent.click(screen.getByTestId("export-query-submit"));

  await waitFor(() =>
    expect(screen.getByTestId("export-query-error").textContent).toContain("go_term")
  );
  expect(screen.queryByTestId("export-query-success")).toBeNull();
});
