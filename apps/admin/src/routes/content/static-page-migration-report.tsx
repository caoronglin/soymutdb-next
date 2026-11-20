import { EyeOutlined } from "@ant-design/icons";
import * as React from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import {
  Alert,
  Button,
  ProCard,
  ProTable,
  Space,
  Tag,
  Typography,
  type ProColumns,
} from "@/lib/antd";
import { PRO_LIST_SHELL } from "../../components/pro-table-shell";

interface MigrationItem {
  static_page_id: number;
  slug: string;
  route: string;
  outcome: "created" | "skipped" | "invalid";
  error_code: string | null;
  message: string | null;
}

interface MigrationReport {
  dry_run: true;
  created: number;
  skipped: number;
  invalid: number;
  items: MigrationItem[];
}

const OUTCOME_COLOR: Record<MigrationItem["outcome"], string> = {
  created: "green",
  skipped: "default",
  invalid: "red",
};

/**
 * `editable: false` on every column is load-bearing, not decoration: this is a
 * dry-run report (design §3.4 — "只读页面不得出现可编辑控件"). ProTable's cell
 * editor is opt-in per column, and this page is the one place where an edit
 * affordance would be actively wrong — the report is a snapshot of a validation
 * run, not a record the operator may change.
 *
 * Column titles were hardcoded English before this: the report sits inside a
 * zh-locale console, so the header row stayed English while everything around
 * it was translated. `buildMigrationColumns` takes `t` for that reason.
 */
function buildMigrationColumns(
  t: ReturnType<typeof useTranslation>["t"],
): ProColumns<MigrationItem>[] {
  return [
    {
      title: t("admin.content.migrationColumnSlug", { defaultValue: "Legacy slug" }),
      dataIndex: "slug",
      key: "slug",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.slug}</span>,
    },
    {
      title: t("admin.content.migrationColumnRoute", { defaultValue: "Draft route" }),
      dataIndex: "route",
      key: "route",
      editable: false,
      render: (_, row) => <span className="font-mono text-xs">{row.route}</span>,
    },
    {
      title: t("admin.content.migrationColumnOutcome", { defaultValue: "Result" }),
      dataIndex: "outcome",
      key: "outcome",
      width: 120,
      editable: false,
      render: (_, row) => (
        <Tag color={OUTCOME_COLOR[row.outcome]}>
          {t(`admin.content.migrationOutcome.${row.outcome}`, { defaultValue: row.outcome })}
        </Tag>
      ),
    },
    {
      title: t("admin.content.migrationColumnMessage", { defaultValue: "Message" }),
      dataIndex: "message",
      key: "message",
      editable: false,
      render: (_, row) => (
        <Typography.Text type={row.message ? undefined : "secondary"}>
          {row.message ?? t("admin.content.migrationReady", { defaultValue: "Ready for a draft migration." })}
        </Typography.Text>
      ),
    },
  ];
}

export function StaticPageMigrationReport() {
  const { t } = useTranslation();
  const migrationColumns = React.useMemo(() => buildMigrationColumns(t), [t]);
  const preview = useMutation({
    mutationFn: () =>
      http.post<MigrationReport>("/admin/content/pages/migrate-to-page-builder/dry-run", { json: {} }),
  });

  const report = preview.data;
  return (
    <ProCard className="border-dashed">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Typography.Title level={5} className="mb-1 text-sm">
            {t("admin.content.migrationTitle")}
          </Typography.Title>
          <Typography.Paragraph className="mb-0 text-sm text-muted-foreground">
            {t("admin.content.migrationBody")}
          </Typography.Paragraph>
        </div>
        <Button
          icon={<EyeOutlined className="size-4" />}
          loading={preview.isPending}
          onClick={() => preview.mutate()}
        >
          {t("admin.content.previewMigration")}
        </Button>
      </div>

      {preview.isError ? (
        <Alert
          className="mt-3"
          type="error"
          showIcon
          title={t("admin.content.migrationPreviewError", {
            defaultValue: "Unable to load the migration preview. Try again later.",
          })}
        />
      ) : null}

      {report ? (
        <Space className="mt-4 w-full" orientation="vertical" size={12} aria-live="polite">
          <Typography.Text type="secondary">
            {t("admin.content.migrationSummary", {
              created: report.created,
              skipped: report.skipped,
              invalid: report.invalid,
              defaultValue: "Dry run: {{created}} ready, {{skipped}} already mapped, {{invalid}} needs review.",
            })}
          </Typography.Text>
          <ProTable<MigrationItem>
            {...PRO_LIST_SHELL}
            size="small"
            bordered
            rowKey="static_page_id"
            columns={migrationColumns}
            dataSource={report.items}
            pagination={false}
            scroll={{ x: "max-content" }}
          />
        </Space>
      ) : null}
    </ProCard>
  );
}

