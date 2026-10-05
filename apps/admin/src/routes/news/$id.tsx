/**
 * Edit news article (B3) — loads the full detail (via the preview-token
 * dance, since B1 has no `GET /admin/news/{id}`), pre-fills the ProForm and
 * PUTs on save. Preview button mints a fresh token and shows the public URL.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Button, PageContainer, ProCard, Spin, Typography } from "../../lib/antd";
import { EyeOutlined } from "@ant-design/icons";
import { useParams, useRouter } from "@tanstack/react-router";
import dayjs from "dayjs";
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
    cover_asset_id: detail.cover_asset_id ?? undefined,
    cover_alt_text: detail.cover_alt_text ?? undefined,
    status: detail.status,
    featured_sort: detail.featured_sort,
    carousel_group: detail.carousel_group ?? undefined,
    carousel_sort: detail.carousel_sort,
    // visible_from / visible_to are returned by the backend detail schema
    // since D4 — pre-fill the visibility window in the edit form.
    visible_from: detail.visible_from ? dayjs(detail.visible_from) : null,
    visible_to: detail.visible_to ? dayjs(detail.visible_to) : null,
    source_platform: detail.source_platform ?? null,
    source_url: detail.source_url ?? null,
    source_published_at: detail.source_published_at ?? null,
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
        cover_asset_id: values.cover_asset_id || null,
        cover_alt_text: values.cover_alt_text || null,
        featured_sort: values.featured_sort ?? 0,
        carousel_group: values.carousel_group || null,
        carousel_sort: values.carousel_sort ?? 0,
        status: values.status ?? "draft",
        visible_from: values.visible_from ? values.visible_from.toISOString() : null,
        visible_to: values.visible_to ? values.visible_to.toISOString() : null,
        ...(values.source_preview_token
          ? { source_preview_token: values.source_preview_token }
          : values.clear_source_provenance
            ? { clear_source_provenance: true }
            : {}),
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
      <PageContainer>
        <div className="route-fade-in mx-auto max-w-3xl">
          <ProCard>
            <Typography.Paragraph type="danger">
              {error ?? t("admin.news.empty")}
            </Typography.Paragraph>
            <Button onClick={goBack}>{t("admin.news.backToList")}</Button>
          </ProCard>
        </div>
      </PageContainer>
    );
  }

  return (
    <PageContainer
      title={t("admin.news.edit")}
      subTitle={`#${detail.id}`}
      extra={[
        <Button key="preview" icon={<EyeOutlined />} onClick={() => setPreviewOpen(true)}>
          {t("admin.news.actions.preview")}
        </Button>,
      ]}
    >
      <div className="route-fade-in mx-auto max-w-3xl">
        <ProCard>
          <NewsForm
            key={detail.id}
            initialValues={toFormValues(detail)}
            onSubmit={handleSubmit}
            onCancel={goBack}
            submitting={submitting}
          />
        </ProCard>

        <NewsPreviewModal
          open={previewOpen}
          article={{ id: detail.id, slug: detail.slug }}
          onClose={() => setPreviewOpen(false)}
        />
      </div>
    </PageContainer>
  );
}
