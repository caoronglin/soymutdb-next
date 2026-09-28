import { useTranslation } from "react-i18next";
import { ImportPreviewTable } from "../../components/import-preview-table";
import type { ModulePreviewResult } from "../../lib/module-import-upload";

export interface ImportValidationReportProps {
  preview: ModulePreviewResult | { status: "checking" } | null;
}

/**
 * Read-only validation presentation for the wizard. It owns no draft state and
 * deliberately exposes no download action because the existing preview API
 * does not return an error-download URI.
 */
export function ImportValidationReport({ preview }: ImportValidationReportProps) {
  const { t } = useTranslation();
  if (!preview || preview.status === "checking") return null;
  if (preview.status === "unavailable") {
    return <p className="text-xs text-muted-foreground">{preview.reason}</p>;
  }

  return (
    <div className="space-y-2 rounded-md border border-border p-3">
      <p className="text-xs text-muted-foreground">
        {t("admin.ops.validatedRows", { rows: String(preview.rowCount), defaultValue: "Validated {{rows}} rows" })}
        {preview.truncated ? t("admin.ops.onlyFirst100Rows", { defaultValue: "; only the first 100 rows are shown." }) : t("admin.ops.dot", { defaultValue: "." })}
        {" "}{t("admin.ops.previewReadOnly", { defaultValue: "This preview is read-only; edits are not included in the import." })}
      </p>
      {!preview.validation.ok ? (
        <p className="text-xs text-destructive">
          {t("admin.ops.validationErrors", { errors: String(preview.validation.errorCount), defaultValue: "{{errors}} validation errors" })}
          {preview.validation.errors[0] ? `: ${preview.validation.errors[0].message}` : "."}
        </p>
      ) : null}
      {preview.rows.length > 0 && preview.headers.length > 0 ? (
        <ImportPreviewTable
          ariaLabel={t("admin.ops.validatedModulePreview", { defaultValue: "Validated module preview" })}
          columns={preview.headers}
          rows={preview.rows}
          rowKey={(row, index) => `${index}:${String(row.gene_id ?? row.id ?? "row")}`}
          editable={false}
          height={240}
        />
      ) : (
        <p className="text-xs text-muted-foreground">{t("admin.ops.noValidPreviewRows", { defaultValue: "No valid preview rows were found." })}</p>
      )}
    </div>
  );
}
