import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Button,
  Empty,
  Input,
  Modal,
  Pagination,
  Skeleton,
  Space,
  Tag,
  Typography,
} from "../lib/antd";
import { CheckOutlined, PictureOutlined, SearchOutlined } from "@ant-design/icons";
import { listMediaAssets, type MediaAsset } from "@soymutdb/api-client";

export interface MediaPickerProps {
  value?: string | null;
  previewUrl?: string | null;
  previewAlt?: string | null;
  purpose?: string;
  disabled?: boolean;
  onChange?: (asset: MediaAsset | null) => void;
}

const PAGE_SIZE = 12;

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

function assetLabel(asset: MediaAsset): string {
  return asset.alt_text || asset.original_filename;
}

export function MediaPicker({
  value,
  previewUrl,
  previewAlt,
  purpose = "news",
  disabled,
  onChange,
}: MediaPickerProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [reloadToken, setReloadToken] = useState(0);
  const [items, setItems] = useState<MediaAsset[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMediaAssets({
      search: search.trim() || undefined,
      purpose,
      status: "ready",
      page,
      page_size: PAGE_SIZE,
    })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, page, purpose, reloadToken, search]);

  const selectAsset = (asset: MediaAsset) => {
    onChange?.(asset);
    setOpen(false);
  };

  return (
    <div className="space-y-3">
      {previewUrl ? (
        <div className="flex items-start gap-4 rounded-lg border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900/50">
          <img
            src={previewUrl}
            alt={previewAlt || t("admin.media.picker.selectedImage")}
            className="h-20 w-28 rounded-md object-cover"
          />
          <div className="min-w-0 flex-1">
            <Typography.Text strong>{t("admin.media.picker.selectedImage")}</Typography.Text>
            <Typography.Paragraph ellipsis={{ rows: 2 }} className="mb-2 mt-1 text-xs" type="secondary">
              {previewAlt || t("admin.media.picker.noAltText")}
            </Typography.Paragraph>
            <Space size="small">
              <Button size="small" onClick={() => setOpen(true)} disabled={disabled}>
                {t("admin.media.picker.change")}
              </Button>
              <Button size="small" danger onClick={() => onChange?.(null)} disabled={disabled}>
                {t("admin.media.picker.remove")}
              </Button>
            </Space>
          </div>
        </div>
      ) : (
        <Button
          icon={<PictureOutlined />}
          onClick={() => setOpen(true)}
          disabled={disabled}
          className="w-full sm:w-auto"
        >
          {t("admin.media.picker.choose")}
        </Button>
      )}

      <Modal
        title={t("admin.media.picker.title")}
        open={open}
        onCancel={() => setOpen(false)}
        footer={null}
        width={860}
        destroyOnClose
      >
        <div className="space-y-4">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            value={search}
            placeholder={t("admin.media.picker.searchPlaceholder")}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
          {error ? (
            <Alert
              type="error"
              showIcon
              title={t("admin.media.picker.loadError")}
              description={error}
              action={<Button onClick={() => setReloadToken((token) => token + 1)}>{t("admin.media.picker.retry")}</Button>}
            />
          ) : loading ? (
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {Array.from({ length: PAGE_SIZE }, (_, index) => (
                <Skeleton active key={index} paragraph={{ rows: 2 }} />
              ))}
            </div>
          ) : items.length === 0 ? (
            <Empty description={t("admin.media.picker.empty")} />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                {items.map((asset) => {
                  const selected = asset.id === value;
                  return (
                    <button
                      type="button"
                      key={asset.id}
                      aria-pressed={selected}
                      aria-label={assetLabel(asset)}
                      onClick={() => selectAsset(asset)}
                      className={[
                        "group overflow-hidden rounded-lg border text-left transition",
                        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500",
                        selected
                          ? "border-blue-500 ring-2 ring-blue-200 dark:ring-blue-900"
                          : "border-slate-200 hover:border-blue-300 dark:border-slate-700 dark:hover:border-blue-700",
                      ].join(" ")}
                    >
                      <div className="relative aspect-[4/3] bg-slate-100 dark:bg-slate-800">
                        <img
                          src={asset.public_url}
                          alt={assetLabel(asset)}
                          loading="lazy"
                          className="h-full w-full object-cover"
                        />
                        {selected ? (
                          <span className="absolute right-2 top-2 rounded-full bg-blue-600 p-1 text-white">
                            <CheckOutlined />
                          </span>
                        ) : null}
                      </div>
                      <div className="space-y-1 p-2">
                        <Typography.Text ellipsis={{ tooltip: asset.original_filename }} className="block text-xs">
                          {asset.original_filename}
                        </Typography.Text>
                        <Typography.Text type="secondary" className="block text-[11px]">
                          {asset.width && asset.height ? asset.width + " × " + asset.height + " · " : ""}
                          {formatBytes(asset.size_bytes)}
                        </Typography.Text>
                        {!asset.alt_text && !asset.is_decorative ? (
                          <Tag color="warning">{t("admin.media.picker.missingAlt")}</Tag>
                        ) : null}
                      </div>
                    </button>
                  );
                })}
              </div>
              {total > PAGE_SIZE ? (
                <div className="flex justify-end">
                  <Pagination
                    current={page}
                    pageSize={PAGE_SIZE}
                    total={total}
                    showSizeChanger={false}
                    onChange={setPage}
                  />
                </div>
              ) : null}
            </>
          )}
        </div>
      </Modal>
    </div>
  );
}
