/**
 * Page Builder — list of page definitions.
 *
 * The routes and templates shown here come from the server-owned registry;
 * this screen only creates the definition shell and navigates to the visual
 * editor. Nothing is published until an administrator explicitly publishes
 * from the editor.
 */
import * as React from "react";
import dayjs from "dayjs";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "@tanstack/react-router";
import { useTranslation } from "react-i18next";
import { PlusOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  App,
  Button,
  Form,
  Input,
  Modal,
  PageContainer,
  ProCard,
  ProTable,
  Select,
  Space,
  Tag,
  Typography,
  type ProColumns,
} from "@/lib/antd";
import {
  adminPageBuilderApi,
  type PageDefinitionCreate,
  type PageTemplate,
} from "@soymutdb/api-client";
import type { PageDefinitionStatus, PageDefinitionSummary } from "@soymutdb/shared";
import { emptyDefinition } from "./definition";

const ROUTE_PATTERN = /^\/(?:[a-z0-9][a-z0-9_-]*)(?:\/[a-z0-9_-]+)*$/;
const isRoute = (value: string): boolean => value === "/" || ROUTE_PATTERN.test(value);

const STATUS_COLORS: Record<PageDefinitionStatus, string> = {
  draft: "default",
  preview: "blue",
  requested: "orange",
  published: "green",
};

interface CreateFormValues {
  route: string;
  title_key: string;
  template?: string;
}

export default function PageBuilderListPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [creating, setCreating] = React.useState(false);
  const [form] = Form.useForm<CreateFormValues>();

  const pagesQuery = useQuery({
    queryKey: ["page-builder", "pages"],
    queryFn: () => adminPageBuilderApi.pages(1, 200),
  });
  const templatesQuery = useQuery({
    queryKey: ["page-builder", "templates"],
    queryFn: () => adminPageBuilderApi.templates(),
  });

  const createMutation = useMutation({
    mutationFn: (body: PageDefinitionCreate) => adminPageBuilderApi.create(body),
    onSuccess: (page) => {
      void queryClient.invalidateQueries({ queryKey: ["page-builder", "pages"] });
      setCreating(false);
      form.resetFields();
      message.success(t("admin.pageBuilder.created", { defaultValue: "Page definition created." }));
      void router.navigate({
        to: "/page-builder/$pageId",
        params: { pageId: page.id },
      });
    },
    onError: (error) => {
      message.error(error instanceof Error ? error.message : String(error));
    },
  });

  const templateFor = (key: string | undefined): PageTemplate | undefined =>
    templatesQuery.data?.items.find((template) => template.key === key);

  const submit = async () => {
    const values = await form.validateFields();
    const template = templateFor(values.template);
    const definition = template
      ? template.definition
      : emptyDefinition(values.title_key);
    createMutation.mutate({
      route: values.route,
      title_key: values.title_key,
      definition,
    });
  };

  const columns: ProColumns<PageDefinitionSummary>[] = [
    {
      title: t("admin.pageBuilder.route", { defaultValue: "Route" }),
      dataIndex: "route",
      render: (_, record) => (
        <Typography.Link
          onClick={() =>
            void router.navigate({
              to: "/page-builder/$pageId",
              params: { pageId: record.id },
            })
          }
        >
          <Typography.Text code>{record.route}</Typography.Text>
        </Typography.Link>
      ),
    },
    {
      title: t("admin.pageBuilder.titleKey", { defaultValue: "Title key" }),
      dataIndex: "title_key",
      render: (_, record) => <Typography.Text code>{record.title_key}</Typography.Text>,
    },
    {
      title: t("admin.pageBuilder.version", { defaultValue: "Version" }),
      dataIndex: "latest_version",
      width: 110,
      render: (_, record) => <Tag>v{record.latest_version}</Tag>,
    },
    {
      title: t("admin.pageBuilder.status", { defaultValue: "Status" }),
      dataIndex: "latest_status",
      width: 130,
      render: (_, record) => (
        <Tag color={STATUS_COLORS[record.latest_status]}>{record.latest_status}</Tag>
      ),
    },
    {
      title: t("admin.pageBuilder.updatedAt", { defaultValue: "Updated" }),
      dataIndex: "updated_at",
      width: 190,
      render: (_, record) => dayjs(record.updated_at).format("YYYY-MM-DD HH:mm"),
    },
  ];

  return (
    <PageContainer
      title={t("admin.pageBuilder.title", { defaultValue: "Page Builder" })}
      subTitle={t("admin.pageBuilder.subtitle", {
        defaultValue:
          "Design public pages by dragging registered components. Publish explicitly — drafts are never served.",
      })}
      extra={[
        <Button
          key="refresh"
          icon={<ReloadOutlined />}
          onClick={() => void pagesQuery.refetch()}
          loading={pagesQuery.isFetching}
        >
          {t("common.refresh", { defaultValue: "Refresh" })}
        </Button>,
        <Button key="create" type="primary" icon={<PlusOutlined />} onClick={() => setCreating(true)}>
          {t("admin.pageBuilder.newPage", { defaultValue: "New page" })}
        </Button>,
      ]}
    >
      <ProCard>
        <ProTable<PageDefinitionSummary>
          rowKey="id"
          search={false}
          options={false}
          loading={pagesQuery.isLoading}
          dataSource={pagesQuery.data?.items ?? []}
          columns={columns}
          pagination={{ pageSize: 20, showSizeChanger: false }}
          locale={{
            emptyText: t("admin.pageBuilder.empty", {
              defaultValue: "No page definitions yet. Create one to get started.",
            }),
          }}
        />
      </ProCard>

      <Modal
        title={t("admin.pageBuilder.newPage", { defaultValue: "New page" })}
        open={creating}
        onCancel={() => {
          setCreating(false);
          form.resetFields();
        }}
        onOk={() => void submit()}
        confirmLoading={createMutation.isPending}
        destroyOnHidden
      >
        <Form form={form} layout="vertical" preserve={false}>
          <Form.Item
            name="route"
            label={t("admin.pageBuilder.route", { defaultValue: "Route" })}
            tooltip={t("admin.pageBuilder.routeHelp", {
              defaultValue:
                "Lowercase path such as /downloads or / for the homepage. Reserved prefixes (/admin, /api, /blast, /browser) are rejected by the server.",
            })}
            rules={[
              { required: true, message: "Route is required" },
              {
                validator: (_, value: string | undefined) =>
                  !value || isRoute(value)
                    ? Promise.resolve()
                    : Promise.reject(
                        new Error("Use / for the homepage or a lowercase path like /downloads"),
                      ),
              },
            ]}
          >
            <Input placeholder="/downloads" />
          </Form.Item>
          <Form.Item
            name="title_key"
            label={t("admin.pageBuilder.titleKey", { defaultValue: "Title key" })}
            rules={[{ required: true, message: "Title key is required" }]}
          >
            <Input placeholder="page.downloads.title" />
          </Form.Item>
          <Form.Item
            name="template"
            label={t("admin.pageBuilder.template", { defaultValue: "Start from template" })}
          >
            <Select
              allowClear
              loading={templatesQuery.isLoading}
              placeholder={t("admin.pageBuilder.blankCanvas", {
                defaultValue: "Blank canvas",
              })}
              options={(templatesQuery.data?.items ?? []).map((template) => ({
                value: template.key,
                label: `${template.label}${template.category ? ` · ${template.category}` : ""}`,
              }))}
            />
          </Form.Item>
          <Space direction="vertical" size={0}>
            <Typography.Text type="secondary">
              {t("admin.pageBuilder.draftNote", {
                defaultValue:
                  "A draft v1 is created. Use the editor to add components, preview and publish.",
              })}
            </Typography.Text>
          </Space>
        </Form>
      </Modal>
    </PageContainer>
  );
}