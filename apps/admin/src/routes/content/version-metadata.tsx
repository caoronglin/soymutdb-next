import { useTranslation } from "react-i18next";
import { ProDescriptions } from "@/lib/antd";

export interface ContentVersionMetadata {
  edited_by: string | null;
  created_at: string;
}

/**
 * The two provenance fields of a content version.
 *
 * This used to be a hand-written two-column grid of label/value `<div>`s. The
 * fields, their order and the "—" for a missing editor are unchanged; the markup
 * is now a description schema (design §3.3).
 */
export function VersionMetadata({ version }: { version: ContentVersionMetadata }) {
  const { t } = useTranslation();
  return (
    <ProDescriptions<ContentVersionMetadata>
      bordered
      column={2}
      dataSource={version}
      columns={[
        {
          title: t("admin.content.editedBy", { defaultValue: "Edited By" }),
          dataIndex: "edited_by",
          render: (_value, row) => row.edited_by ?? "—",
        },
        {
          title: t("admin.content.created", { defaultValue: "Created" }),
          dataIndex: "created_at",
        },
      ]}
    />
  );
}
