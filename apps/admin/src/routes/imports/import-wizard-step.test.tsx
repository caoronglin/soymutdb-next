import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ImportTypeStep, type PersistedImportWizardDraft } from "./import-wizard-step";

vi.mock("@/lib/antd", () => {
  const Select = ({ value, onChange, children, ...props }: { value: string; onChange: (value: string) => void; children: React.ReactNode }) => (
    <select value={value} onChange={(event) => onChange(event.target.value)} {...props}>{children}</select>
  );
  Select.Option = ({ value, children, disabled }: { value: string; children: React.ReactNode; disabled?: boolean }) => (
    <option value={value} disabled={disabled}>{children}</option>
  );
  return { Select };
});

const draft: PersistedImportWizardDraft = {
  schema_version: 1, import_type: "vcf", source_mode: "local", data_set_id: "1",
  filename: "mutants.vcf", object_key: null, module_key: null, release_id: null, checksum: null,
};

describe("ImportTypeStep", () => {
  it("emits a serializable replacement draft without claiming persistence", async () => {
    const onDraftChange = vi.fn();
    render(<ImportTypeStep draft={draft} moduleImportEnabled labelForType={(type) => type} onDraftChange={onDraftChange} />);
    await userEvent.selectOptions(screen.getByLabelText("Import Type"), "gff3");
    expect(onDraftChange).toHaveBeenCalledWith({ ...draft, import_type: "gff3" });
  });

  it("disables the module type when the capability is absent", () => {
    render(<ImportTypeStep draft={draft} moduleImportEnabled={false} labelForType={(type) => type} onDraftChange={vi.fn()} />);
    expect(screen.getByRole("option", { name: "module_tsv" })).toBeDisabled();
  });
});
