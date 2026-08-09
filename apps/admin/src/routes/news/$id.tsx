/**
 * Edit news article (B3) — loads the full detail (via the preview-token
 * dance, since B1 has no `GET /admin/news/{id}`), pre-fills the ProForm and
 * PUTs on save. Preview button mints a fresh token and shows the public URL.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, Card, Space, Spin, Typography } from "antd";
import { EyeOutlined } from "@ant-design/icons";
import { useParams, useRouter } from "@tanstack/react-router";
import {
  getAdminNewsDetail,
  updateNews,
  type NewsDetail,
} from "@soymutdb/api-client";
import { NewsForm, type NewsFormValues } from "../../components/news-form";
import { NewsPreviewModal } from "../../components/news-preview-modal";

function toFormValues(detail: NewsDetail): Partial<NewsFormValues> {
  return {
    title_en: detail.title_en,
    title_zh: detail.title_zh ?? undefined,
    content_en: detail.content_en,
    content_zh: detail.content_zh ?? undefined,
    slug: detail.slug,
    category: detail.category ?? undefined,
    cover_url: detail.cover_url ?? undefined,
    status: detail.status,
    featured_sort: detail.featured_sort,
    carousel_group: detail.carousel_group ?? undefined,
    carousel_sort: detail.carousel_sort,
    // visible_from / visible_to are NOT returned by the backend detail
    // schema (B1 gap) — cannot prefill; kept empty in the edit form.
  };
}

export default function NewsEditPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const params = useParams({ strict: false });
  const newsId = params.id as string | undefined;

  const [detail, setDetail] = useState<NewsDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);

  useEffect(() => {
    if (!newsId) return;
    let disposed = false;
    setLoading(true);
    setError(null);
    getAdminNewsDetail(newsId)
      .then((data) => {
        if (!disposed) setDetail(data);
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [newsId]);

  const handleSubmit = async (values: NewsFormValues) => {
    if (!newsId) return;
    setSubmitting(true);
    try {
      await updateNews(newsId, {
        title_en: values.title_en,
        title_zh: values.title_zh || null,
        content_en: values.content_en,
        content_zh: values.content_zh || null,
        slug: values.slug,
        category: values.category || null,
        cover_url: values.cover_url || null,
        featured_sort: values.featured_sort ?? 0,
        carousel_group: values.carousel_group || null,
        carousel_sort: values.carousel_sort ?? 0,
        status: values.status ?? "draft",
        visible_from: values.visible_from ? values.visible_from.toISOString() : null,
        visible_to: values.visible_to ? values.visible_to.toISOString() : null,
      });
      message.success(t("admin.news.messages.saveSuccess"));
      router.navigate({ to: "/news" });
    } catch (err) {
      message.error(
        `${t("admin.news.messages.saveError")}: ${err instanceof Error ? err.message : String(err)}`,
      );
      setSubmitting(false);
    }
  };

  const goBack = () => router.navigate({ to: "/news" });

  if (loading) {
    return (
      <div className="route-fade-in flex justify-center py-24">
        <Spin tip={t("admin.news.loading")}>
          <div className="h-24 w-64" />
        </Spin>
      </div>
    );
  }

  if (error || !detail) {
    return (
      <div className="route-fade-in mx-auto max-w-3xl">
        <Card>
          <Typography.Paragraph type="danger">
            {error ?? t("admin.news.empty")}
          </Typography.Paragraph>
          <Button onClick={goBack}>{t("admin.news.backToList")}</Button>
        </Card>
      </div>
    );
  }

  return (
    <div className="route-fade-in mx-auto max-w-3xl">
      <Card
        title={
          <Space>
            <span>{t("admin.news.edit")}</span>
            <Typography.Text type="secondary" className="text-sm">
              #{detail.id}
            </Typography.Text>
          </Space>
        }
        extra={
          <Button icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)}>
            {t("admin.news.actions.preview")}
          </Button>
        }
      >
        <NewsForm
          key={detail.id}
          initialValues={toFormValues(detail)}
          onSubmit={handleSubmit}
          onCancel={goBack}
          submitting={submitting}
        />
      </Card>

      <NewsPreviewModal
        open={previewOpen}
        article={{ id: detail.id, slug: detail.slug }}
        onClose={() => setPreviewOpen(false)}
      />
    </div>
  );
}
