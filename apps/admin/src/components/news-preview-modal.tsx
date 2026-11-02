/**
 * News preview modal (B3) — mints a 15-min HMAC preview token and shows the
 * public preview URL with "copy link" + "open preview" actions.
 *
 * Contract: GET /api/v1/admin/news/{id}/preview-token → { preview, exp, url }.
 * The token unlocks the draft on the public detail page without login:
 *   {public_url}/news/{slug}?preview={token}&exp={exp}
 * `public_url` must be the explicit VITE_PUBLIC_URL portal origin; never infer it.
 */
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, App, Button, Input, Modal, Space, Typography } from "../lib/antd";
import {
  CopyOutlined,
  LinkOutlined,
  LoadingOutlined,
} from "@ant-design/icons";
import { getPreviewToken } from "@soymutdb/api-client";
import { requireDeploymentOrigin } from "@soymutdb/shared/deployment";

/** Resolve the public web origin (deploy-time override for admin hosting). */
function publicSiteUrl(): string | null {
  try {
    const configured = import.meta.env.VITE_PUBLIC_URL;
    const origin = requireDeploymentOrigin(configured, "Public site");
    // Localhost is an explicit exception in the shared deployment policy.
    // Keep the portal's configured base path (e.g. a GitHub Pages project).
    if (!/^https?:\/\//.test(origin)) return null;
    const basePath = new URL(configured!).pathname.replace(/\/+$/, "");
    return `${origin}${basePath}`;
  } catch {
    return null;
  }
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
  const [token, setToken] = useState<{
    preview: string; exp: number; articleId: number | string; slug: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const portalBaseUrl = publicSiteUrl();
  const articleId = article?.id;
  const slug = article?.slug;

  // A prop change renders before the effect can clear the previous token.
  // Bind it to its article so that render cannot expose a mismatched link.
  const previewUrl = open && portalBaseUrl && token && token.articleId === articleId && token.slug === slug
    ? `${portalBaseUrl}/news/${encodeURIComponent(token.slug)}?${new URLSearchParams({ preview: token.preview, exp: String(token.exp) })}`
    : null;

  useEffect(() => {
    setToken(null);
    setError(null);
    setLoading(false);
    if (!open || !portalBaseUrl || articleId == null || slug == null) return;
    let disposed = false;
    setLoading(true);
    getPreviewToken(articleId)
      .then((res) => {
        if (!disposed) setToken({ preview: res.preview, exp: res.exp, articleId, slug });
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
  }, [open, articleId, slug, portalBaseUrl]);

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
          <Button
            icon={<LinkOutlined />}
            href={previewUrl ?? undefined}
            disabled={!previewUrl}
            target="_blank"
            rel="noreferrer"
          >
            {t("admin.news.preview.openPreview")}
          </Button>
        </Space>
      }
    >
      <Alert
        type="info"
        showIcon
        title={t("admin.news.preview.note")}
        style={{ marginBottom: 16 }}
      />
      {!portalBaseUrl ? (
        <Alert
          type="warning"
          showIcon
          title={t("admin.news.preview.originMissing")}
          description={t("admin.news.preview.originMissingHint")}
        />
      ) : loading ? (
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
