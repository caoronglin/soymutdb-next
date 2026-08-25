/**
 * Page Builder index: list page definitions with a create form.
 */

import { PartitionOutlined, PlusOutlined, LoadingOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { Badge, Button, Card, Input, Table, Typography } from "@/lib/antd";
import {
  normalizePageDefinition,
  type PageDefinitionV2,
} from "@soymutdb/shared";
import { pageBuilderApi } from "../../lib/page-builder-api";

function defaultDefinition(): PageDefinitionV2 {
  return normalizePageDefinition({
    root: {
      type: "columns",
      props: { columns: 1 },
      children: [{ type: "rich_text", props: { content: "<p>New page</p>" } }],
    },
  })!;
}

export default function PageBuilderIndexPage() {
  const queryClient = useQueryClient();
  const [route, setRoute] = useState("");
  const [titleKey, setTitleKey] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["page-builder", "pages"],
    queryFn: () => pageBuilderApi.list({ page: 1, page_size: 100 }),
    placeholderData: { items: [], total: 0, page: 1, page_size: 100 },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      pageBuilderApi.create({
        route,
        title_key: titleKey,
        definition: defaultDefinition(),
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
      setRoute("");
      setTitleKey("");
      setError(null);
      // Navigate to the new editor.
      window.location.hash = `#/page-builder/${created.id}`;
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setError(e?.message ?? "Failed to create page.");
    },
  });

  return (
    <div className="space-y-6 p-6">
      <div><Typography.Title level={2}>Page Builder</Typography.Title><Typography.Text type="secondary"><PartitionOutlined /> Versioned, schema-validated page definitions</Typography.Text></div>
      <Card title="Create a page">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5"><Typography.Text>Route</Typography.Text><Input value={route} onChange={(e) => setRoute(e.target.value)} placeholder="/about-us" className="w-64" /></div>
          <div className="space-y-1.5"><Typography.Text>Title key</Typography.Text><Input value={titleKey} onChange={(e) => setTitleKey(e.target.value)} placeholder="nav.about" className="w-64" /></div>
          <Button type="primary" onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !route || !titleKey} icon={createMutation.isPending ? <LoadingOutlined /> : <PlusOutlined />}>Create</Button>
        </div>
        {error ? <Typography.Paragraph type="danger" className="mt-3">{error}</Typography.Paragraph> : null}
      </Card>
      <Card title="Pages">
        <Table
          loading={isLoading}
          rowKey="id"
          dataSource={data?.items ?? []}
          locale={{ emptyText: "No pages yet." }}
          columns={[
            { title: "Route", dataIndex: "route", render: (value) => <span className="font-mono text-sm">{value}</span> },
            { title: "Title key", dataIndex: "title_key" },
            { title: "Latest version", dataIndex: "latest_version" },
            { title: "Status", dataIndex: "latest_status", render: (value) => <Badge color="default">{value}</Badge> },
            { title: "Action", key: "action", align: "right", render: (_, page) => <Link to="/page-builder/$pageId" params={{ pageId: page.id }}><Button size="small">Edit</Button></Link> },
          ]}
        />
      </Card>
    </div>
  );
}
