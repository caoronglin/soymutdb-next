/**
 * Shared news ProForm (B3) — used by both the create (/news/new) and edit
 * (/news/$id) pages. Simple textarea content (no rich-text library per
 * scope), cover URL input, status select, featured/carousel ordering and
 * optional visibility window.
 *
 * Field set mirrors the backend schemas (apps/api/app/schemas/news.py):
 * NewsCreate / NewsUpdate.
 */
import { useTranslation } from "react-i18next";
import { Button, Space } from "antd";
import {
  ProForm,
  ProFormDateTimePicker,
  ProFormDigit,
  ProFormSelect,
  ProFormText,
  ProFormTextArea,
} from "@ant-design/pro-components";
import dayjs from "dayjs";
import type { NewsStatus } from "@soymutdb/api-client";
import FileUpload from "./file-upload";

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
    <ProForm<NewsFormValues>
      onFinish={onSubmit}
      initialValues={initialValues}
      layout="vertical"
      submitter={{
        render: (props) => (
          <Space>
            <Button onClick={onCancel}>{t("admin.news.form.cancel")}</Button>
            <Button
              type="primary"
              loading={submitting}
              onClick={() => props.form?.submit?.()}
            >
              {t("admin.news.form.save")}
            </Button>
          </Space>
        ),
      }}
    >
      <ProFormText
        name="title_en"
        label={t("admin.news.form.titleEn")}
        rules={[{ required: true, message: t("admin.news.form.titleEn") }]}
        fieldProps={{ maxLength: 512 }}
      />
      <ProFormText
        name="title_zh"
        label={t("admin.news.form.titleZh")}
        fieldProps={{ maxLength: 512 }}
      />
      <ProFormText
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
      />
      <ProFormTextArea
        name="content_en"
        label={t("admin.news.form.contentEn")}
        rules={[{ required: true, message: t("admin.news.form.contentEn") }]}
        fieldProps={{ rows: 10 }}
      />
      <ProFormTextArea
        name="content_zh"
        label={t("admin.news.form.contentZh")}
        fieldProps={{ rows: 6 }}
      />
      <ProFormText
        name="category"
        label={t("admin.news.form.category")}
        placeholder={t("admin.news.form.categoryPlaceholder")}
        fieldProps={{ maxLength: 64 }}
      />
      <ProForm.Item
        name="cover_url"
        label={t("admin.news.form.coverUrl")}
        tooltip={t("admin.news.form.coverUrlHelp")}
        extra={t("admin.news.form.coverUrlUploadHint")}
      >
        <FileUpload purpose="news" maxSizeMB={10} accept="image/*" />
      </ProForm.Item>
      <ProFormSelect
        name="status"
        label={t("admin.news.form.status")}
        options={STATUS_OPTIONS}
        rules={[{ required: true }]}
      />
      <ProFormDigit
        name="featured_sort"
        label={t("admin.news.form.featuredSort")}
        tooltip={t("admin.news.form.featuredSortHelp")}
        min={0}
      />
      <ProFormText
        name="carousel_group"
        label={t("admin.news.form.carouselGroup")}
        placeholder={t("admin.news.form.carouselGroupPlaceholder")}
        fieldProps={{ maxLength: 64 }}
      />
      <ProFormDigit name="carousel_sort" label={t("admin.news.form.carouselSort")} min={0} />
      <ProFormDateTimePicker
        name="visible_from"
        label={t("admin.news.form.visibleFrom")}
      />
      <ProFormDateTimePicker
        name="visible_to"
        label={t("admin.news.form.visibleTo")}
      />
    </ProForm>
  );
}
