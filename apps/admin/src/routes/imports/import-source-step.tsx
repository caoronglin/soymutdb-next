import { Input, Select } from "@/lib/antd";
import type { PersistedImportWizardDraft } from "./import-wizard-step";

export interface ImportSourceStepProps {
  draft: PersistedImportWizardDraft;
  localUploadEnabled: boolean;
  selectedFile: File | null;
  uploading: boolean;
  uploadProgress: number;
  onDraftChange: (next: PersistedImportWizardDraft) => void;
  onFileSelect: (file: File) => void;
}

/**
 * Real source/file selection step. It emits only serializable source metadata
 * through `onDraftChange`; the browser File stays transient and is handed to
 * the established upload flow through `onFileSelect`.
 */
export function ImportSourceStep({
  draft, localUploadEnabled, selectedFile, uploading, uploadProgress, onDraftChange, onFileSelect,
}: ImportSourceStepProps) {
  const local = draft.source_mode === "local";
  return (
    <>
      <div className="space-y-1.5">
        <label htmlFor="import-mode">Source</label>
        <Select
          id="import-mode"
          aria-label="Source"
          value={draft.source_mode}
          onChange={(value) => onDraftChange({ ...draft, source_mode: value as "local" | "s3" })}
        >
          <Select.Option value="local" disabled={!localUploadEnabled}>Local file</Select.Option>
          <Select.Option value="s3">S3 URI (advanced)</Select.Option>
        </Select>
      </div>

      {local ? (
        <div className="space-y-1.5">
          <label htmlFor="import-local-file">File</label>
          <input
            id="import-local-file"
            type="file"
            accept=".txt,.tsv,.csv,.xlsx,.vcf,.gff3,.fasta"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (!file) return;
              onFileSelect(file);
              onDraftChange({ ...draft, filename: file.name, object_key: null });
              event.currentTarget.value = "";
            }}
          />
          {selectedFile ? <p className="text-xs text-muted-foreground">{selectedFile.name} · {formatBytes(selectedFile.size)}</p> : null}
          {uploading ? <UploadProgress value={uploadProgress} /> : null}
        </div>
      ) : (
        <>
          <div className="space-y-1.5">
            <label htmlFor="import-filename">Filename</label>
            <Input
              id="import-filename"
              value={draft.filename}
              onChange={(event) => onDraftChange({ ...draft, filename: event.target.value })}
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="import-filepath">S3 File Path</label>
            <Input
              id="import-filepath"
              placeholder="s3://bucket-name/path/to/file.csv"
              value={draft.object_key ?? ""}
              onChange={(event) => onDraftChange({ ...draft, object_key: event.target.value || null })}
            />
            <p className="text-xs text-muted-foreground">The S3 URI where the file has already been uploaded.</p>
          </div>
        </>
      )}
    </>
  );
}

function UploadProgress({ value }: { value: number }) {
  return (
    <div className="space-y-1" role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-primary transition-all" style={{ width: value + "%" }} />
      </div>
      <p className="text-xs text-muted-foreground">Uploading… {value}%</p>
    </div>
  );
}

function formatBytes(size: number): string {
  if (size < 1024) return size + " B";
  if (size < 1024 * 1024) return (size / 1024).toFixed(1) + " KB";
  return (size / (1024 * 1024)).toFixed(1) + " MB";
}
