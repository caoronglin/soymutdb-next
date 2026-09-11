import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ImportSourceStep } from "./import-source-step";
import type { PersistedImportWizardDraft } from "./import-wizard-step";

vi.mock("@/lib/antd", () => {
  const Select = ({ value, onChange, children, ...props }: { value: string; onChange: (value: string) => void; children: React.ReactNode }) => <select value={value} onChange={(event) => onChange(event.target.value)} {...props}>{children}</select>;
  Select.Option = ({ value, children, disabled }: { value: string; children: React.ReactNode; disabled?: boolean }) => <option value={value} disabled={disabled}>{children}</option>;
  return { Select, Input: (props: React.InputHTMLAttributes<HTMLInputElement>) => <input {...props} /> };
});

const draft: PersistedImportWizardDraft = { schema_version: 1, import_type: "vcf", source_mode: "s3", data_set_id: "1", filename: "old.vcf", object_key: "s3://bucket/old.vcf", module_key: null, release_id: null, checksum: null };

describe("ImportSourceStep", () => {
  it("emits serializable S3 metadata changes", () => {
    const onDraftChange = vi.fn();
    render(<ImportSourceStep draft={draft} localUploadEnabled selectedFile={null} uploading={false} uploadProgress={0} onDraftChange={onDraftChange} onFileSelect={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("S3 File Path"), { target: { value: "s3://bucket/new.vcf" } });
    expect(onDraftChange).toHaveBeenCalledWith({ ...draft, object_key: "s3://bucket/new.vcf" });
  });

  it("keeps browser files transient while emitting their serializable filename", () => {
    const onDraftChange = vi.fn();
    const onFileSelect = vi.fn();
    render(<ImportSourceStep draft={{ ...draft, source_mode: "local" }} localUploadEnabled selectedFile={null} uploading={false} uploadProgress={0} onDraftChange={onDraftChange} onFileSelect={onFileSelect} />);
    const file = new File(["vcf"], "new.vcf", { type: "text/plain" });
    fireEvent.change(screen.getByLabelText("File"), { target: { files: [file] } });
    expect(onFileSelect).toHaveBeenCalledWith(file);
    expect(onDraftChange).toHaveBeenCalledWith(expect.objectContaining({ filename: "new.vcf", object_key: null }));
  });
});
