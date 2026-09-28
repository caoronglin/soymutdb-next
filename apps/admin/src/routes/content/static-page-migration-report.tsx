import { EyeOutlined } from "@ant-design/icons";
import { useMutation } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { Button, Card, Typography } from "@/lib/antd";

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
        <p role="alert" className="mt-3 text-sm text-destructive">
          Unable to load the migration preview. Try again later.
        </p>
      ) : null}

      {report ? (
        <div className="mt-4 space-y-3" aria-live="polite">
          <p className="text-sm">
            Dry run: {report.created} ready, {report.skipped} already mapped, {report.invalid} needs review.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b text-muted-foreground">
                  <th className="p-2">Legacy slug</th>
                  <th className="p-2">Draft route</th>
                  <th className="p-2">Result</th>
                  <th className="p-2">Message</th>
                </tr>
              </thead>
              <tbody>
                {report.items.map((item) => (
                  <tr key={item.static_page_id} className="border-b last:border-0">
                    <td className="p-2 font-mono">{item.slug}</td>
                    <td className="p-2 font-mono">{item.route}</td>
                    <td className="p-2">{item.outcome}</td>
                    <td className="p-2 text-muted-foreground">{item.message ?? "Ready for a draft migration."}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </Card>
  );
}

