/**
 * News preview modal (B3) — mints a 15-min HMAC preview token and shows the
 * public preview URL with "copy link" + "open preview" actions.
 *
 * Contract: GET /api/v1/admin/news/{id}/preview-token → { preview, exp, url }.
 * The token unlocks the draft on the public detail page without login:
 *   {public_url}/news/{slug}?preview={token}&exp={exp}
 * `public_url` = VITE_PUBLIC_URL (web build origin) or the admin origin.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Input, Modal, Space, Typography } from "antd";
import {
  CopyOutlined,
  LinkOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { getPreviewToken } from "@soymutdb/api-client";

/** Resolve the public web origin (deploy-time override for admin hosting). */
function publicSiteUrl(): string {
  const configured = import.meta.env.VITE_PUBLIC_URL as string | undefined;
  if (configured) return configured.replace(/\/+$/, "");
  if (typeof window !== "undefined") return window.location.origin;
  return "";
}

export interface NewsPreviewModalProps {
  open: boolean;
  /** Article id (used to mint the token) and slug (for the public URL). */
  article: { id: number | string; slug: string } | null;
  onClose: () => void;
}

export function NewsPreviewModal({ open, article, onClose }: NewsPreviewModalProps) {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [token, setToken] = useState<{ preview: string; exp: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const previewUrl = article && token
    ? `${publicSiteUrl()}/news/${encodeURIComponent(article.slug)}?preview=${encodeURIComponent(token.preview)}&exp=${token.exp}`
    : null;

  useEffect(() => {
    if (!open || !article) return;
    let disposed = false;
    setLoading(true);
    setError(null);
    setToken(null);
    getPreviewToken(article.id)
      .then((res) => {
        if (!disposed) setToken({ preview: res.preview, exp: res.exp });
      })
      .catch((err: unknown) => {
        if (!disposed) {
          setError(err instanceof Error ? err.message : String(err));
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [open, article]);

  const copyLink = useCallback(async () => {
    if (!previewUrl) return;
    try {
      await navigator.clipboard.writeText(previewUrl);
      message.success(t("admin.news.preview.copied"));
    } catch {
      message.error(t("admin.news.messages.saveError"));
    }
  }, [previewUrl, message, t]);

  return (
    <Modal
      open={open}
      title={t("admin.news.preview.title")}
      onCancel={onClose}
      footer={
        <Space>
          <Button onClick={onClose}>{t("admin.news.form.cancel")}</Button>
          <Button
            type="primary"
            icon={<CopyOutlined />}
            disabled={!previewUrl}
            onClick={copyLink}
          >
            {t("admin.news.preview.copyLink")}
          </Button>
          {previewUrl ? (
            <Button
              icon={<LinkOutlined />}
              href={previewUrl}
              target="_blank"
              rel="noreferrer"
            >
              {t("admin.news.preview.openPreview")}
            </Button>
          ) : null}
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        message={t("admin.news.preview.note")}
        style={{ marginBottom: 16 }}
      />
      {loading ? (
        <Typography.Text type="secondary">
          <LoadingOutlined /> {t("admin.news.preview.loading")}
        </Typography.Text>
      ) : error ? (
        <Typography.Text type="danger">{error}</Typography.Text>
      ) : previewUrl ? (
        <Input readOnly value={previewUrl} />
      ) : null}
    </Modal>
  );
}
