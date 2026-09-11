/**
 * News management list (B3) — AntD Table with pagination + search + status
 * filter, row actions (edit / delete / preview) and featured reorder.
 *
 * Data source: GET /api/v1/admin/news (researcher+) — sees ALL statuses
 * (draft/published/archived) with optional status_filter, category, and
 * title search. Loading / error / empty states are handled explicitly.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  App,
  Button,
  Form,
  Input,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "../../lib/antd";
import { PlusOutlined } from "@ant-design/icons";
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
 * Map list request params to the backend admin-list query params.
 *
 * Pure function — extracted for unit testing. `status` (filter select)
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

interface NewsListParams {
  current: number;
  pageSize: number;
  title_en?: string;
  category?: string;
  status?: NewsStatus;
}

const DEFAULT_LIST_PARAMS: NewsListParams = {
  current: 1,
  pageSize: 10,
};

export default function NewsListPage() {
  const { t } = useTranslation();
  const { message, modal } = App.useApp();
  const router = useRouter();
  const [searchForm] = Form.useForm<
    Omit<NewsListParams, "current" | "pageSize">
  >();
  const [requestParams, setRequestParams] = useState<NewsListParams>(DEFAULT_LIST_PARAMS);
  const [articles, setArticles] = useState<NewsSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [previewArticle, setPreviewArticle] = useState<{
    id: number | string;
    slug: string;
  } | null>(null);
  const [reorderOpen, setReorderOpen] = useState(false);
  const loadErrorLabel = t("admin.news.messages.loadError");

  useEffect(() => {
    let active = true;

    async function loadArticles() {
      try {
        const data = await listAdminNews(buildAdminNewsQuery(requestParams));
        if (!active) return;
        setArticles(data.items);
        setTotal(data.total);
      } catch (err) {
        if (!active) return;
        setArticles([]);
        setTotal(0);
        message.error(
          `${loadErrorLabel}: ${err instanceof Error ? err.message : String(err)}`,
        );
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadArticles();
    return () => {
      active = false;
    };
  }, [loadErrorLabel, message, reloadVersion, requestParams]);

  const reload = useCallback(() => {
    setLoading(true);
    setReloadVersion((version) => version + 1);
  }, []);

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
            reload();
          } catch (err) {
            message.error(
              `${t("admin.news.messages.deleteError")}: ${err instanceof Error ? err.message : String(err)}`,
            );
          }
        },
      });
    },
    [modal, message, reload, t],
  );

  const columns: TableColumnsType<NewsSummary> = [
    {
      title: t("admin.news.columns.id"),
      dataIndex: "id",
      width: 64,
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
      render: (_, record) =>
        record.published_at ? dayjs(record.published_at).format("YYYY-MM-DD HH:mm") : "—",
    },
    {
      title: t("admin.news.columns.featuredSort"),
      dataIndex: "featured_sort",
      width: 90,
      sorter: (a, b) => a.featured_sort - b.featured_sort,
    },
    {
      title: t("admin.news.columns.actions"),
      key: "option",
      width: 190,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            onClick={() => router.navigate({ to: "/news/$id", params: { id: record.id } })}
          >
            {t("admin.news.actions.edit")}
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => setPreviewArticle({ id: record.id, slug: record.slug })}
          >
            {t("admin.news.actions.preview")}
          </Button>
          <Button
            type="link"
            size="small"
            danger
            onClick={() => confirmDelete(record)}
          >
            {t("admin.news.actions.delete")}
          </Button>
        </Space>
      ),
    },
  ];

  const applyFilters = (values: Omit<NewsListParams, "current" | "pageSize">) => {
    setLoading(true);
    setRequestParams((current) => ({
      ...values,
      current: 1,
      pageSize: current.pageSize,
    }));
  };

  const resetFilters = () => {
    searchForm.resetFields();
    setLoading(true);
    setRequestParams(DEFAULT_LIST_PARAMS);
  };

  return (
    <div className="route-fade-in">
      <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Space>
            <Typography.Text strong>{t("admin.news.title")}</Typography.Text>
          </Space>
          <Space>
            <Button onClick={() => router.navigate({ to: "/news/trash" })}>
              {t("admin.news.trash.title")}
            </Button>
            <Button onClick={() => setReorderOpen(true)}>
              {t("admin.news.actions.reorder")}
            </Button>
            <Button
              type="primary"
              icon={<PlusOutlined />}
              onClick={() => router.navigate({ to: "/news/new" })}
            >
              {t("admin.news.createNew")}
            </Button>
          </Space>
        </div>

        <Form form={searchForm} layout="inline" onFinish={applyFilters}>
          <Form.Item name="title_en" label={t("admin.news.columns.title")}>
            <Input placeholder={t("admin.news.search.placeholder")} />
          </Form.Item>
          <Form.Item name="category" label={t("admin.news.columns.category")}>
            <Input />
          </Form.Item>
          <Form.Item name="status" label={t("admin.news.columns.status")}>
            <Select
              allowClear
              style={{ minWidth: 140 }}
              options={([
                "draft",
                "published",
                "archived",
              ] as const).map((status) => ({
                value: status,
                label: t(`admin.news.status.${status}`),
              }))}
            />
          </Form.Item>
          <Form.Item>
            <Space>
              <Button type="primary" htmlType="submit">
                {t("common.search")}
              </Button>
              <Button htmlType="button" onClick={resetFilters}>
                {t("common.reset")}
              </Button>
            </Space>
          </Form.Item>
        </Form>

        <Table<NewsSummary>
          rowKey="id"
          columns={columns}
          dataSource={articles}
          loading={loading}
          pagination={{
            current: requestParams.current,
            pageSize: requestParams.pageSize,
            total,
            showSizeChanger: true,
            onChange: (current, pageSize) => {
              setLoading(true);
              setRequestParams((params) => ({ ...params, current, pageSize }));
            },
          }}
          locale={{ emptyText: t("admin.news.empty") }}
        />
      </Space>

      <NewsPreviewModal
        open={previewArticle !== null}
        article={previewArticle}
        onClose={() => setPreviewArticle(null)}
      />
      <NewsReorderModal
        open={reorderOpen}
        onClose={() => setReorderOpen(false)}
        onSaved={reload}
      />
    </div>
  );
}
