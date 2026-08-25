/**
 * New news article (B3) — same ProForm as the edit page, POST on save.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { App, Card } from "../../lib/antd";
import { useRouter } from "@tanstack/react-router";
import { createNews } from "@soymutdb/api-client";
import { NewsForm, type NewsFormValues } from "../../components/news-form";

export default function NewsNewPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (values: NewsFormValues) => {
    setSubmitting(true);
    try {
      await createNews({
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

  return (
    <div className="route-fade-in mx-auto max-w-3xl">
      <Card title={t("admin.news.createNew")}>
        <NewsForm
          initialValues={{ status: "draft", featured_sort: 0, carousel_sort: 0 }}
          onSubmit={handleSubmit}
          onCancel={() => router.navigate({ to: "/news" })}
          submitting={submitting}
        />
      </Card>
    </div>
  );
}
