import { Select } from "@/lib/antd";

export const IMPORT_WIZARD_TYPES = [
  "vcf", "gff3", "fasta", "blast_db", "seed_data",
  "expression_csv", "homolog_csv", "module_tsv",
] as const;

export type ImportWizardType = (typeof IMPORT_WIZARD_TYPES)[number];

/**
 * Serializable state boundary for a future persisted wizard draft. Files are
 * deliberately represented by metadata/object references, never a File object.
 * Persistence is owned by the future draft API; this component does not claim
 * to save drafts locally or remotely.
 */
export interface PersistedImportWizardDraft {
  schema_version: 1;
  import_type: ImportWizardType;
  source_mode: "local" | "s3";
  data_set_id: string;
  filename: string;
  object_key: string | null;
  module_key: string | null;
  release_id: string | null;
  checksum: string | null;
}

export interface ImportTypeStepProps {
  draft: PersistedImportWizardDraft;
  moduleImportEnabled: boolean;
  labelForType: (type: ImportWizardType) => string;
  onDraftChange: (next: PersistedImportWizardDraft) => void;
}

/** First real wizard step, reusable by both the legacy modal and `/imports/new`. */
export function ImportTypeStep({ draft, moduleImportEnabled, labelForType, onDraftChange }: ImportTypeStepProps) {
  return (
    <div className="space-y-1.5">
      <label htmlFor="import-type">Import Type</label>
      <Select
        id="import-type"
        aria-label="Import Type"
        value={draft.import_type}
        onChange={(value) => onDraftChange({ ...draft, import_type: value as ImportWizardType })}
      >
        {IMPORT_WIZARD_TYPES.map((type) => (
          <Select.Option key={type} value={type} disabled={type === "module_tsv" && !moduleImportEnabled}>
            {labelForType(type)}
          </Select.Option>
        ))}
      </Select>
    </div>
  );
}
