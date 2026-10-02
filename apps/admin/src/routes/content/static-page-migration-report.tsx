import { EyeOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import {
  Alert,
  Button,
  Card,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";

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

const migrationColumns: TableColumnsType<MigrationItem> = [
  {
    title: "Legacy slug",
    dataIndex: "slug",
    key: "slug",
    render: (_, row) => <span className="font-mono text-xs">{row.slug}</span>,
  },
  {
    title: "Draft route",
    dataIndex: "route",
    key: "route",
    render: (_, row) => <span className="font-mono text-xs">{row.route}</span>,
  },
  {
    title: "Result",
    dataIndex: "outcome",
    key: "outcome",
    width: 120,
    render: (_, row) => <Tag color={OUTCOME_COLOR[row.outcome]}>{row.outcome}</Tag>,
  },
  {
    title: "Message",
    dataIndex: "message",
    key: "message",
    render: (_, row) => (
      <Typography.Text type={row.message ? undefined : "secondary"}>
        {row.message ?? "Ready for a draft migration."}
      </Typography.Text>
    ),
  },
];

export function StaticPageMigrationReport() {
  const preview = useMutation({
    mutationFn: () =>
      http.post<MigrationReport>("/admin/content/pages/migrate-to-page-builder/dry-run", { json: {} }),
  });

  const report = preview.data;
  return (
    <Card className="border-dashed">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Typography.Title level={5} className="mb-1 text-sm">
            Page Builder migration preview
          </Typography.Title>
          <Typography.Paragraph className="mb-0 text-sm text-muted-foreground">
            This preview only validates legacy pages and reports draft candidates. It never creates, publishes, or changes source pages.
          </Typography.Paragraph>
        </div>
        <Button
          icon={<EyeOutlined className="size-4" />}
          loading={preview.isPending}
          onClick={() => preview.mutate()}
        >
          Preview migration
        </Button>
      </div>

      {preview.isError ? (
        <Alert
          className="mt-3"
          type="error"
          showIcon
          title="Unable to load the migration preview. Try again later."
        />
      ) : null}

      {report ? (
        <Space className="mt-4 w-full" orientation="vertical" size={12} aria-live="polite">
          <Typography.Text type="secondary">
            Dry run: {report.created} ready, {report.skipped} already mapped, {report.invalid} needs
            review.
          </Typography.Text>
          <Table<MigrationItem>
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
    </Card>
  );
}

