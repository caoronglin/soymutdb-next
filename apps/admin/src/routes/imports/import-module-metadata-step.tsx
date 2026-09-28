import { Button, Input } from "@/lib/antd";

export interface ImportModuleMetadataStepProps {
  sourceMode: "local" | "s3";
  releaseId: string;
  moduleKey: string;
  checksum: string;
  localFileSelected: boolean;
  previewChecking: boolean;
  onReleaseIdChange: (value: string) => void;
  onModuleKeyChange: (value: string) => void;
  onChecksumChange: (value: string) => void;
  onPreview: () => void;
}

/**
 * Module-only metadata and preview trigger. It remains controlled by the
 * legacy submit state so validation/submission semantics and draft ownership
 * do not change.
 */
export function ImportModuleMetadataStep({
  sourceMode, releaseId, moduleKey, checksum, localFileSelected, previewChecking,
  onReleaseIdChange, onModuleKeyChange, onChecksumChange, onPreview,
}: ImportModuleMetadataStepProps) {
  return (
    <>
      <div className="space-y-1.5">
        <label htmlFor="import-release-id">Release ID</label>
        <Input id="import-release-id" type="number" min="1" inputMode="numeric" value={releaseId} onChange={(event) => onReleaseIdChange(event.target.value)} />
        <p className="text-xs text-muted-foreground">Required. Module rows are immutable within one existing release.</p>
      </div>
      <div className="space-y-1.5">
        <label htmlFor="import-module-key">Module Key</label>
        <Input id="import-module-key" placeholder="genes" value={moduleKey} onChange={(event) => onModuleKeyChange(event.target.value)} />
        <p className="text-xs text-muted-foreground">Server-owned schema key. Supports .tsv / .txt / .csv / .xlsx.</p>
      </div>
      {sourceMode === "s3" ? (
        <div className="space-y-1.5">
          <label htmlFor="import-checksum">Checksum</label>
          <Input id="import-checksum" value={checksum} onChange={(event) => onChecksumChange(event.target.value)} />
        </div>
      ) : null}
      <div className="space-y-1.5">
        <Button htmlType="button" type="default" size="small" disabled={!localFileSelected} onClick={onPreview}>
          {previewChecking ? "Checking…" : "Preview"}
        </Button>
      </div>
    </>
  );
}
