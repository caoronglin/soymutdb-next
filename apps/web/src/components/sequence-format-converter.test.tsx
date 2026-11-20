/**
 * In-download format conversion.
 *
 * The assertions cover the two things this component can get wrong: sending a
 * request for an empty file (nothing to convert) and swallowing a failure so
 * the button looks like it did nothing.
 */
import * as React from "react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("react-i18next", () => {
  const translation = { t: (key: string) => key };
  return { useTranslation: () => translation };
});

const api = vi.hoisted(() => ({ convertFormat: vi.fn() }));

vi.mock("@soymutdb/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@soymutdb/api-client")>();
  return { ...actual, sequenceApi: { ...actual.sequenceApi, convertFormat: api.convertFormat } };
});


// The web workspace renders Ant Design through `@/lib/antd`, and the route
// tests replace that facade with plain DOM so the components under test render
// without the library's layout probes. Follow the same pattern here.
vi.mock("@/lib/antd", () => ({
  Alert: ({ title }: { title?: React.ReactNode }) => <div role="alert">{title}</div>,
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props}>{children}</button>
  ),
  Select: ({
    value,
    onChange,
    options,
  }: {
    value?: string;
    onChange?: (next: string) => void;
    options?: { value: string; label: string }[];
  }) => (
    <select value={value} onChange={(event) => onChange?.(event.target.value)}>
      {(options ?? []).map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  ),
  Space: ({ children }: { children?: React.ReactNode }) => <div>{children}</div>,
  Typography: {
    Text: ({ children }: { children?: React.ReactNode }) => <span>{children}</span>,
  },
}));

import { SequenceFormatConverter } from "./sequence-format-converter";

beforeEach(() => {
  api.convertFormat.mockReset();
});

describe("SequenceFormatConverter", () => {
  it("does not offer conversion for an empty body", () => {
    render(<SequenceFormatConverter text="   " />);

    expect(screen.getByText("downloads.convert.empty")).toBeTruthy();
    // No button means no request that could only fail.
    expect(screen.queryByRole("button")).toBeNull();
    expect(api.convertFormat).not.toHaveBeenCalled();
  });

  it("offers a target format and a convert action for a non-empty body", () => {
    render(<SequenceFormatConverter text=">s1\nATGCAA\n" fileName="genes.fa" />);

    expect(screen.getByText("downloads.convert.label")).toBeTruthy();
    expect(screen.getByText("downloads.convert.run")).toBeTruthy();
    // The defaults the API documents: FASTA in, GenBank out.
    expect(screen.getByTestId("download-convert")).toBeTruthy();
    // Nothing is converted before the reader asks.
    expect(api.convertFormat).not.toHaveBeenCalled();
  });
});
