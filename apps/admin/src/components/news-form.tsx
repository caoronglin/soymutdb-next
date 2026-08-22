/**
 * Shared news form (B3) — used by both the create (/news/new) and edit
 * (/news/$id) pages. Rich-text content (E1 RichEditor, HTML value), cover
 * URL input, status select, featured/carousel ordering and optional
 * visibility window.
 *
 * Field set mirrors the backend schemas (apps/api/app/schemas/news.py):
 * NewsCreate / NewsUpdate.
 */
import { useTranslation } from "react-i18next";
import { Button, DatePicker, Form, Input, InputNumber, Select, Space } from "antd";
import dayjs from "dayjs";
import type { NewsStatus } from "@soymutdb/api-client";
import FileUpload from "./file-upload";
import { RichEditor } from "./rich-editor/rich-editor";

/** Form values (Dayjs for the two datetime fields). */
export interface NewsFormValues {
  title_en: string;
  title_zh?: string;
  content_en: string;
  content_zh?: string;
  slug: string;
  category?: string;
  cover_url?: string;
  status: NewsStatus;
  featured_sort: number;
  carousel_group?: string;
  carousel_sort: number;
  visible_from?: dayjs.Dayjs | null;
  visible_to?: dayjs.Dayjs | null;
}

export interface NewsFormProps {
  /** Initial values (edit page passes the fetched detail). */
  initialValues?: Partial<NewsFormValues>;
  /** Form submit handler — receives serialized payload. */
  onSubmit: (values: NewsFormValues) => void;
  /** Cancel / back navigation. */
  onCancel: () => void;
  /** Disable submit while the request is in flight. */
  submitting?: boolean;
}

const STATUS_OPTIONS: { label: string; value: NewsStatus }[] = [
  { label: "draft", value: "draft" },
  { label: "published", value: "published" },
  { label: "archived", value: "archived" },
];

export function NewsForm({
  initialValues,
  onSubmit,
  onCancel,
  submitting,
}: NewsFormProps) {
  const { t } = useTranslation();

  return (
    <Form<NewsFormValues>
      onFinish={(values) => onSubmit(values)}
      initialValues={initialValues}
      layout="vertical"
    >
      <Form.Item
        name="title_en"
        label={t("admin.news.form.titleEn")}
        rules={[{ required: true, message: t("admin.news.form.titleEn") }]}
      >
        <Input maxLength={512} />
      </Form.Item>
      <Form.Item
        name="title_zh"
        label={t("admin.news.form.titleZh")}
      >
        <Input maxLength={512} />
      </Form.Item>
      <Form.Item
        name="slug"
        label={t("admin.news.form.slug")}
        tooltip={t("admin.news.form.slugHelp")}
        rules={[
          { required: true, message: t("admin.news.form.slug") },
          {
            pattern: /^[a-z0-9]+(?:-[a-z0-9]+)*$/,
            message: t("admin.news.form.slugHelp"),
          },
        ]}
      >
        <Input />
      </Form.Item>
      <Form.Item
        name="content_en"
        label={t("admin.news.form.contentEn")}
        rules={[{ required: true, message: t("admin.news.form.contentEn") }]}
      >
        <RichEditor placeholder={t("admin.editor.placeholder")} />
      </Form.Item>
      <Form.Item
        name="content_zh"
        label={t("admin.news.form.contentZh")}
      >
        <RichEditor placeholder={t("admin.editor.placeholder")} />
      </Form.Item>
      <Form.Item
        name="category"
        label={t("admin.news.form.category")}
      >
        <Input
          maxLength={64}
          placeholder={t("admin.news.form.categoryPlaceholder")}
        />
      </Form.Item>
      <Form.Item
        name="cover_url"
        label={t("admin.news.form.coverUrl")}
        tooltip={t("admin.news.form.coverUrlHelp")}
        extra={t("admin.news.form.coverUrlUploadHint")}
      >
        <FileUpload purpose="news" maxSizeMB={10} accept="image/*" />
      </Form.Item>
      <Form.Item
        name="status"
        label={t("admin.news.form.status")}
        rules={[{ required: true }]}
      >
        <Select options={STATUS_OPTIONS} />
      </Form.Item>
      <Form.Item
        name="featured_sort"
        label={t("admin.news.form.featuredSort")}
        tooltip={t("admin.news.form.featuredSortHelp")}
      >
        <InputNumber min={0} />
      </Form.Item>
      <Form.Item
        name="carousel_group"
        label={t("admin.news.form.carouselGroup")}
      >
        <Input
          maxLength={64}
          placeholder={t("admin.news.form.carouselGroupPlaceholder")}
        />
      </Form.Item>
      <Form.Item name="carousel_sort" label={t("admin.news.form.carouselSort")}>
        <InputNumber min={0} />
      </Form.Item>
      <Form.Item
        name="visible_from"
        label={t("admin.news.form.visibleFrom")}
      >
        <DatePicker showTime />
      </Form.Item>
      <Form.Item
        name="visible_to"
        label={t("admin.news.form.visibleTo")}
      >
        <DatePicker showTime />
      </Form.Item>
      <Form.Item>
        <Space>
          <Button htmlType="button" onClick={onCancel}>
            {t("admin.news.form.cancel")}
          </Button>
          <Button type="primary" htmlType="submit" loading={submitting}>
            {t("admin.news.form.save")}
          </Button>
        </Space>
      </Form.Item>
    </Form>
  );
}
