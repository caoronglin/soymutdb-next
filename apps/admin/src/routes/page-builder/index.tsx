/**
 * Page Builder index: list page definitions with a create form.
 */

import { PartitionOutlined, PlusOutlined, LoadingOutlined } from "@ant-design/icons";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { Badge, Button, Card, Input, Select, Table, Typography } from "@/lib/antd";
import { AdminUsageGuide } from "../../components/admin-usage-guide";
import { pageBuilderApi } from "../../lib/page-builder-api";
import {
  getPageBuilderTemplateDefinition,
  resolvePageBuilderTemplates,
} from "../../lib/page-builder-templates";

export default function PageBuilderIndexPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [route, setRoute] = useState("");
  const [titleKey, setTitleKey] = useState("");
  const [templateId, setTemplateId] = useState<string>("research");
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);

  const { data: templateData } = useQuery({
    queryKey: ["page-builder", "templates"],
    queryFn: () => pageBuilderApi.listTemplates(),
    retry: false,
  });
  const templates = resolvePageBuilderTemplates(templateData?.items);

  const { data, isLoading } = useQuery({
    queryKey: ["page-builder", "pages", page],
    queryFn: () => pageBuilderApi.list({ page, page_size: 20 }),
    placeholderData: (previous) => previous ?? { items: [], total: 0, page, page_size: 20 },
  });

  const createMutation = useMutation({
    mutationFn: () =>
      pageBuilderApi.create({
        route,
        title_key: titleKey,
        definition:
          templates.find((template) => template.key === templateId)?.definition ??
          getPageBuilderTemplateDefinition("research"),
      }),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
      setRoute("");
      setTitleKey("");
      setError(null);
      // Navigate to the new editor through the router rather than assigning to
      // `window.location` (mutating a global inside a component is rejected by
      // the react-hooks/immutability lint rule and bypasses route preloading).
      navigate({ to: "/page-builder/$pageId", params: { pageId: created.id } });
    },
    onError: (err: unknown) => {
      const e = err as { message?: string };
      setError(e?.message ?? t("admin.builder.createFailed", { defaultValue: "Failed to create page." }));
    },
  });

  const selectedTemplate = templates.find((template) => template.key === templateId) ?? templates[0];

  return (
    <div className="space-y-6 p-6">
      <div><Typography.Title level={2}>{t("admin.builder.title", { defaultValue: "Page Builder" })}</Typography.Title><Typography.Text type="secondary"><PartitionOutlined /> {t("admin.builder.subtitle", { defaultValue: "Versioned, schema-validated page definitions" })}</Typography.Text></div>
      <AdminUsageGuide
        items={[
          {
            key: "template",
            title: t("admin.usage.builderTitle", { defaultValue: "Page template workflow" }),
            steps: [
              t("admin.usage.builderStep1", { defaultValue: "Choose a bounded template that matches the page purpose." }),
              t("admin.usage.builderStep2", { defaultValue: "Create the page, then edit components through the server registry." }),
              t("admin.usage.builderStep3", { defaultValue: "Preview and fix responsive layout before saving a draft." }),
              t("admin.usage.builderStep4", { defaultValue: "Publish only after the version and API data sources are verified." }),
            ],
            api: ["GET /admin/page-builder/registry", "POST /admin/page-builder/pages", "PUT /admin/page-builder/pages/{id}/draft", "POST /admin/page-builder/pages/{id}/publish-request"],
            tables: ["page_definitions", "page_definition_versions", "outbox_events"],
            note: t("admin.usage.builderNote", { defaultValue: "The server registry validates component props and the outbox starts the publication pipeline." }),
          },
        ]}
      />
      <Card title={t("admin.builder.createPage", { defaultValue: "Create a page" })}>
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[220px] flex-1 space-y-1.5 sm:flex-none">
            <Typography.Text>{t("admin.builder.routeLabel", { defaultValue: "Route" })}</Typography.Text>
            <Input value={route} onChange={(e) => setRoute(e.target.value)} placeholder="/about-us" />
          </div>
          <div className="min-w-[220px] flex-1 space-y-1.5 sm:flex-none">
            <Typography.Text>{t("admin.builder.titleKeyLabel", { defaultValue: "Title key" })}</Typography.Text>
            <Input value={titleKey} onChange={(e) => setTitleKey(e.target.value)} placeholder="nav.about" />
          </div>
          <div className="min-w-[240px] flex-1 space-y-1.5 sm:flex-none">
            <Typography.Text>{t("admin.builder.templateLabel", { defaultValue: "Starting template" })}</Typography.Text>
            <Select
              value={templateId}
              options={templates.map((template) => ({
                value: template.key,
                label: template.label,
              }))}
              onChange={setTemplateId}
              className="w-full"
            />
            <Typography.Text type="secondary" className="block text-xs">
              {selectedTemplate?.description ?? "Start with a bounded, responsive page structure."}
            </Typography.Text>
          </div>
          <Button type="primary" onClick={() => createMutation.mutate()} disabled={createMutation.isPending || !route || !titleKey} icon={createMutation.isPending ? <LoadingOutlined /> : <PlusOutlined />}>{t("admin.builder.create", { defaultValue: "Create" })}</Button>
        </div>
        {error ? <Typography.Paragraph type="danger" className="mt-3">{error}</Typography.Paragraph> : null}
      </Card>
      <Card title={t("admin.builder.pages", { defaultValue: "Pages" })}>
        <Table
          loading={isLoading}
          rowKey="id"
          dataSource={data?.items ?? []}
          locale={{ emptyText: t("admin.builder.noPages", { defaultValue: "No pages yet." }) }}
          pagination={{
             current: data?.page ?? page,
             pageSize: data?.page_size ?? 20,
             total: data?.total ?? 0,
             showSizeChanger: false,
             onChange: (nextPage) => setPage(nextPage),
           }}
           columns={[
            { title: t("admin.builder.colRoute", { defaultValue: "Route" }), dataIndex: "route", render: (value) => <span className="font-mono text-sm">{value}</span> },
            { title: t("admin.builder.colTitleKey", { defaultValue: "Title key" }), dataIndex: "title_key" },
            { title: t("admin.builder.colLatestVersion", { defaultValue: "Latest version" }), dataIndex: "latest_version" },
            { title: t("admin.builder.colStatus", { defaultValue: "Status" }), dataIndex: "latest_status", render: (value) => <Badge color="default">{value}</Badge> },
            { title: t("admin.builder.colAction", { defaultValue: "Action" }), key: "action", align: "right", render: (_, page) => <Link to="/page-builder/$pageId" params={{ pageId: page.id }}><Button size="small">{t("admin.builder.edit", { defaultValue: "Edit" })}</Button></Link> },
          ]}
        />
      </Card>
    </div>
  );
}
