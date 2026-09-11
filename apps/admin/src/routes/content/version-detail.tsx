import { useTranslation } from "react-i18next";
import { Button } from "@/lib/antd";
import { VersionMetadata } from "./version-metadata";
import type { ContentVersion } from "./version-history-dialog";

export interface VersionDetailProps { version: ContentVersion; onBack: () => void; }

export function VersionDetail({ version, onBack }: VersionDetailProps) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Button type="text" size="small" onClick={onBack}>
          {t("admin.content.backToList", { defaultValue: "Back to list" })}
        </Button>
        <span className="font-mono text-sm font-medium">v{version.version}</span>
        {version.edit_comment ? (
          <span className="text-sm text-muted-foreground">
            · {version.edit_comment}
          </span>
        ) : null}
      </div>

      <VersionMetadata version={version} />

      <div className="space-y-1.5">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("admin.content.titleEnglish", { defaultValue: "Title (English)" })}
        </p>
        <p className="font-medium">{version.title_en}</p>
      </div>
      {version.title_zh ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("admin.content.titleChinese", { defaultValue: "Title (Chinese)" })}
          </p>
          <p className="font-medium">{version.title_zh}</p>
        </div>
      ) : null}
      {version.summary ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("admin.content.summary", { defaultValue: "Summary" })}
          </p>
          <p className="text-sm">{version.summary}</p>
        </div>
      ) : null}
      <div className="space-y-1.5">
        <p className="text-xs uppercase tracking-wide text-muted-foreground">
          {t("admin.content.contentEnglish", { defaultValue: "Content (English)" })}
        </p>
        <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
          {version.content_en}
        </pre>
      </div>
      {version.content_zh ? (
        <div className="space-y-1.5">
          <p className="text-xs uppercase tracking-wide text-muted-foreground">
            {t("admin.content.contentChinese", { defaultValue: "Content (Chinese)" })}
          </p>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
            {version.content_zh}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
