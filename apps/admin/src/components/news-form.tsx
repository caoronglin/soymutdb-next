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
import { Button, DatePicker, Form, Input, InputNumber, Select, Space } from "../lib/antd";
import dayjs from "dayjs";
import type { NewsStatus } from "@soymutdb/api-client";
import FileUpload from "./file-upload";
import { MediaPicker } from "./media-picker";
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
  cover_asset_id?: string;
  cover_alt_text?: string;
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
      <Form.Item name="cover_url" hidden>
        <Input />
      </Form.Item>
      <Form.Item name="cover_asset_id" hidden>
        <Input />
      </Form.Item>
      <Form.Item
        label={t("admin.news.form.coverUrl")}
        tooltip={t("admin.news.form.coverUrlHelp")}
        extra={t("admin.news.form.coverUrlUploadHint")}
      >
        <Form.Item noStyle shouldUpdate>
          {({ getFieldValue, setFieldsValue }) => {
            const coverUrl = getFieldValue("cover_url") as string | undefined;
            const coverAssetId = getFieldValue("cover_asset_id") as string | undefined;
            const coverAltText = getFieldValue("cover_alt_text") as string | undefined;
            return (
              <Space direction="vertical" size="middle" className="w-full">
                <MediaPicker
                  value={coverAssetId}
                  previewUrl={coverUrl}
                  previewAlt={coverAltText}
                  purpose="news"
                  disabled={submitting}
                  onChange={(asset) => {
                    setFieldsValue({
                      cover_asset_id: asset?.id ?? null,
                      cover_url: asset?.public_url ?? null,
                      cover_alt_text: asset?.alt_text ?? null,
                    });
                  }}
                />
                <FileUpload
                  value={coverUrl}
                  purpose="news"
                  maxSizeMB={10}
                  accept="image/jpeg,image/png,image/webp"
                  buttonText={t("admin.media.picker.uploadNew")}
                  onUploaded={(asset) => {
                    setFieldsValue({
                      cover_asset_id: asset.id,
                      cover_url: asset.public_url,
                      cover_alt_text: asset.alt_text ?? null,
                    });
                  }}
                  onChange={(next) => {
                    const url = Array.isArray(next) ? next[0] : next;
                    setFieldsValue({
                      cover_url: url ?? null,
                      ...(url ? {} : { cover_asset_id: null, cover_alt_text: null }),
                    });
                  }}
                />
                <Form.Item
                  name="cover_alt_text"
                  label={t("admin.news.form.coverAltText")}
                  extra={t("admin.news.form.coverAltTextHelp")}
                  rules={[
                    ({ getFieldValue: readField }) => ({
                      validator(_, text) {
                        const assetId = readField("cover_asset_id");
                        if (assetId && !String(text ?? "").trim()) {
                          return Promise.reject(new Error(t("admin.news.form.coverAltTextRequired")));
                        }
                        return Promise.resolve();
                      },
                    }),
                  ]}
                >
                  <Input.TextArea rows={2} maxLength={2000} showCount />
                </Form.Item>
              </Space>
            );
          }}
        </Form.Item>
      </Form.Item>
      <Form.Item
        name="status"
        label={t("admin.news.form.status")}
        rules={[{ required: true }]}
      >
        <Select options={STATUS_OPTIONS.map((opt) => ({ value: opt.value, label: t(`admin.news.status.${opt.value}`) }))} />
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
