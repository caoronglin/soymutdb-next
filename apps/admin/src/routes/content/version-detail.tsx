import { useTranslation } from "react-i18next";
import { Button, ProDescriptions } from "@/lib/antd";
import { VersionMetadata } from "./version-metadata";
import type { ContentVersion } from "./version-history-dialog";

export interface VersionDetailProps { version: ContentVersion; onBack: () => void; }

/** The free-form body fields keep their own block rendering inside the cell. */
function contentBlock(body: string) {
  return (
    <pre className="max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-border bg-muted/30 p-3 font-mono text-xs">
      {body}
    </pre>
  );
}

/**
 * A single content version, described field by field.
 *
 * This replaces five hand-written label/value blocks (design §3.3). Which fields
 * appear, in what order, and the exact styling of the content bodies are all
 * unchanged — `title_zh`, `summary` and `content_zh` were conditional before and
 * stay conditional, expressed as column entries that render `null`.
 */
export function VersionDetail({ version, onBack }: VersionDetailProps) {
  const { t } = useTranslation();

  /*
   * The optional fields are filtered out of the schema rather than rendered as
   * empty rows: a column whose `render` returns `null` still emits its label, and
   * the previous markup omitted the label *and* the value together. Building the
   * list conditionally is what keeps the two behaviours identical.
   */
  const columns = [
    {
      title: t("admin.content.titleEnglish", { defaultValue: "Title (English)" }),
      dataIndex: "title_en",
    },
    ...(version.title_zh
      ? [
          {
            title: t("admin.content.titleChinese", { defaultValue: "Title (Chinese)" }),
            dataIndex: "title_zh",
          },
        ]
      : []),
    ...(version.summary
      ? [
          {
            title: t("admin.content.summary", { defaultValue: "Summary" }),
            dataIndex: "summary",
          },
        ]
      : []),
    {
      title: t("admin.content.contentEnglish", { defaultValue: "Content (English)" }),
      key: "content_en",
      render: (_value: unknown, row: ContentVersion) => contentBlock(row.content_en),
    },
    ...(version.content_zh
      ? [
          {
            title: t("admin.content.contentChinese", { defaultValue: "Content (Chinese)" }),
            dataIndex: "content_zh",
            render: (_value: unknown, row: ContentVersion) => contentBlock(row.content_zh ?? ""),
          },
        ]
      : []),
  ];

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

      <ProDescriptions<ContentVersion>
        bordered
        column={1}
        size="small"
        dataSource={version}
        columns={columns}
      />
    </div>
  );
}
