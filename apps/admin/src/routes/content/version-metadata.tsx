import { useTranslation } from "react-i18next";

export interface ContentVersionMetadata {
  edited_by: string | null;
  created_at: string;
}

export function VersionMetadata({ version }: { version: ContentVersionMetadata }) {
  const { t } = useTranslation();
  return (
    <div className="grid gap-3 rounded-lg border border-border bg-muted/30 p-4 text-sm sm:grid-cols-2">
      <div>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("admin.content.editedBy", { defaultValue: "Edited By" })}
        </p>
        <p className="font-medium">{version.edited_by ?? "—"}</p>
      </div>
      <div>
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("admin.content.created", { defaultValue: "Created" })}
        </p>
        <p className="font-medium">{version.created_at}</p>
      </div>
    </div>
  );
}
