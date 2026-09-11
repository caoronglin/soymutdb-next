import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportValidationReport } from "./import-validation-report";

vi.mock("../../components/import-preview-table", () => ({
  ImportPreviewTable: ({ rows }: { rows: unknown[] }) => <div data-testid="preview-table">{rows.length} rows</div>,
}));

// This component interpolates its default:
//
//   t("admin.ops.validationErrors", {
//     errors: String(count),
//     defaultValue: "{{errors}} validation errors",
//   })
//
// and the test asserts "1 validation errors". Without an initialised i18next,
// `t` returns `defaultValue` verbatim, so the DOM contains the literal
// `{{errors}} validation errors`. The shared double substitutes placeholders the
// way i18next does, and keeps a stable `t` identity. See src/test/mocks.ts.
vi.mock("react-i18next", async () => (await import("../../test/mocks")).mockTranslation);

describe("ImportValidationReport", () => {
  it("keeps unavailable preview reasons visible", () => {
    render(<ImportValidationReport preview={{ status: "unavailable", reason: "Inspection service unavailable" }} />);
    expect(screen.getByText("Inspection service unavailable")).toBeInTheDocument();
  });

  it("renders validation semantics and the read-only result table", () => {
    render(<ImportValidationReport preview={{
      status: "available", headers: ["gene_id"], rows: [{ gene_id: "Gm01" }], rowCount: 1, truncated: false, checksumSha256: "a",
      validation: { ok: false, errorCount: 1, errors: [{ code: "bad_value", row: 1, message: "Invalid value" }] },
    }} />);
    expect(screen.getByText(/1 validation errors/)).toHaveTextContent("Invalid value");
    expect(screen.getByTestId("preview-table")).toHaveTextContent("1 rows");
    expect(screen.queryByRole("button", { name: /download/i })).not.toBeInTheDocument();
  });
});
