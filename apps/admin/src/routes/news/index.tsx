/**
 * News management list (B3) — ProTable with pagination + search + status
 * filter, row actions (edit / delete / preview) and featured reorder.
 *
 * Data source: GET /api/v1/admin/news (researcher+) — sees ALL statuses
 * (draft/published/archived) with optional status_filter, category, and
 * title search.  Loading / error / empty states are handled by ProTable's
 * built-in request lifecycle.
 */
import { useCallback, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Space, Tag, Typography } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { ProTable, type ActionType, type ProColumns } from "@ant-design/pro-components";
import { useRouter } from "@tanstack/react-router";
import dayjs from "dayjs";
import {
  deleteNews,
  listAdminNews,
  type AdminNewsListParams,
  type NewsStatus,
  type NewsSummary,
} from "@soymutdb/api-client";
import { NewsPreviewModal } from "../../components/news-preview-modal";
import { NewsReorderModal } from "../../components/news-reorder-modal";

const STATUS_COLORS: Record<NewsStatus, string> = {
  draft: "default",
  published: "success",
  archived: "warning",
};

/**
 * Map ProTable request params to the backend admin-list query params.
 *
 * Pure function — extracted for unit testing. `status` (valueEnum select)
 * maps to `status_filter`; `title_en` (search input) maps to the backend
 * `search` (ILIKE); `category` passes through; `current`/`pageSize` map to
 * `page`/`page_size`. Empty/undefined values are dropped so the backend
 * defaults apply.
 */
export function buildAdminNewsQuery(params: {
  current?: number;
  pageSize?: number;
  title_en?: string;
  category?: string;
  status?: NewsStatus | string;
}): AdminNewsListParams {
  const query: AdminNewsListParams = {
    page: params.current ?? 1,
    page_size: params.pageSize ?? 10,
  };
  if (params.status) query.status_filter = params.status as NewsStatus;
  if (params.category) query.category = params.category;
  if (params.title_en) query.search = params.title_en;
  return query;
}

export default function NewsListPage() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const router = useRouter();
  const actionRef = useRef<ActionType>(null);
  const [previewArticle, setPreviewArticle] = useState<{
    id: number | string;
    slug: string;
  } | null>(null);
  const [reorderOpen, setReorderOpen] = useState(false);

  const statusEnum = useCallback(
    () => ({
      draft: { text: t("admin.news.status.draft") },
      published: { text: t("admin.news.status.published") },
      archived: { text: t("admin.news.status.archived") },
    }),
    [t],
  );

  const confirmDelete = useCallback(
    (record: NewsSummary) => {
      modal.confirm({
        title: t("admin.news.deleteConfirm.title"),
        content: t("admin.news.deleteConfirm.content", {
          title: record.title_en,
        }),
        okText: t("admin.news.deleteConfirm.okText"),
        okButtonProps: { danger: true },
        onOk: async () => {
          try {
            await deleteNews(record.id);
            message.success(t("admin.news.messages.deleteSuccess"));
            actionRef.current?.reload();
          } catch (err) {
            message.error(
              `${t("admin.news.messages.deleteError")}: ${err instanceof Error ? err.message : String(err)}`,
            );
          }
        },
      });
    },
    [modal, message, t],
  );

  const columns: ProColumns<NewsSummary>[] = [
    {
      title: t("admin.news.columns.id"),
      dataIndex: "id",
      width: 64,
      search: false,
    },
    {
      title: t("admin.news.columns.title"),
      dataIndex: "title_en",
      ellipsis: true,
      render: (_, record) =>
        record.title_zh ? (
          <span>
            {record.title_en} <span className="text-muted-foreground">/ {record.title_zh}</span>
          </span>
        ) : (
          record.title_en
        ),
    },
    {
      title: t("admin.news.columns.category"),
      dataIndex: "category",
      width: 140,
      render: (_, record) => record.category ?? "—",
    },
    {
      title: t("admin.news.columns.status"),
      dataIndex: "status",
      width: 110,
      valueType: "select",
      valueEnum: statusEnum(),
      render: (_, record) => (
        <Tag color={STATUS_COLORS[record.status]}>
          {t(`admin.news.status.${record.status}`)}
        </Tag>
      ),
    },
    {
      title: t("admin.news.columns.publishedAt"),
      dataIndex: "published_at",
      width: 170,
      search: false,
      render: (_, record) =>
        record.published_at ? dayjs(record.published_at).format("YYYY-MM-DD HH:mm") : "—",
    },
    {
      title: t("admin.news.columns.featuredSort"),
      dataIndex: "featured_sort",
      width: 90,
      search: false,
      sorter: (a, b) => a.featured_sort - b.featured_sort,
    },
    {
      title: t("admin.news.columns.actions"),
      valueType: "option",
      key: "option",
      width: 190,
      render: (_, record) => [
        <Button
          key="edit"
          type="link"
          size="small"
          onClick={() => router.navigate({ to: "/news/$id", params: { id: record.id } })}
        >
          {t("admin.news.actions.edit")}
        </Button>,
        <Button
          key="preview"
          type="link"
          size="small"
          onClick={() => setPreviewArticle({ id: record.id, slug: record.slug })}
        >
          {t("admin.news.actions.preview")}
        </Button>,
        <Button
          key="delete"
          type="link"
          size="small"
          danger
          onClick={() => confirmDelete(record)}
        >
          {t("admin.news.actions.delete")}
        </Button>,
      ],
    },
  ];

  return (
    <div className="route-fade-in">
      <ProTable<NewsSummary>
        headerTitle={
          <Space>
            <Typography.Text strong>{t("admin.news.title")}</Typography.Text>
          </Space>
        }
        actionRef={actionRef}
        rowKey="id"
        columns={columns}
        search={{
          labelWidth: "auto",
        }}
        request={async (params) => {
          try {
            const data = await listAdminNews(buildAdminNewsQuery(params));
            return { data: data.items, total: data.total, success: true };
          } catch (err) {
            message.error(
              `${t("admin.news.messages.loadError")}: ${err instanceof Error ? err.message : String(err)}`,
            );
            return { data: [], total: 0, success: false };
          }
        }}
        pagination={{ defaultPageSize: 10, showSizeChanger: true }}
        toolBarRender={() => [
          <Button key="reorder" onClick={() => setReorderOpen(true)}>
            {t("admin.news.actions.reorder")}
          </Button>,
          <Button
            key="create"
            type="primary"
            icon={<PlusOutlined />}
            onClick={() => router.navigate({ to: "/news/new" })}
          >
            {t("admin.news.createNew")}
          </Button>,
        ]}
        locale={{ emptyText: t("admin.news.empty") }}
      />

      <NewsPreviewModal
        open={previewArticle !== null}
        article={previewArticle}
        onClose={() => setPreviewArticle(null)}
      />
      <NewsReorderModal
        open={reorderOpen}
        onClose={() => setReorderOpen(false)}
        onSaved={() => actionRef.current?.reload()}
      />
    </div>
  );
}