import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  App,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Select,
  Skeleton,
  Space,
  Switch,
  Tag,
  Typography,
} from "../lib/antd";
import {
  CopyOutlined,
  DeleteOutlined,
  EditOutlined,
  PictureOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  archiveMediaAsset,
  listMediaAssets,
  updateMediaAsset,
  type MediaAsset,
} from "@soymutdb/api-client";
import FileUpload from "../components/file-upload";

const PAGE_SIZE = 24;
const PURPOSE_OPTIONS = ["news", "editor", "about"] as const;
type AssetStatus = "ready" | "archived";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
}

export default function MediaPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [items, setItems] = useState<MediaAsset[]>([]);
  const [search, setSearch] = useState("");
  const [purpose, setPurpose] = useState<string | undefined>();
  const uploadPurpose = purpose ?? "news";
  const [assetStatus, setAssetStatus] = useState<AssetStatus>("ready");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);
  const [editing, setEditing] = useState<MediaAsset | null>(null);
  const [editValues, setEditValues] = useState({
    alt_text: "",
    caption: "",
    credit: "",
    is_decorative: false,
  });
  const [saving, setSaving] = useState(false);
  const [archiving, setArchiving] = useState<MediaAsset | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    listMediaAssets({
      search: search.trim() || undefined,
      purpose,
      status: assetStatus,
      page,
      page_size: PAGE_SIZE,
    })
      .then((response) => {
        if (cancelled) return;
        setItems(response.items);
        setTotal(response.total);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [assetStatus, page, purpose, reload, search]);

  const resetToFirstPage = () => setPage(1);

  const openEditor = (asset: MediaAsset) => {
    setEditing(asset);
    setEditValues({
      alt_text: asset.alt_text ?? "",
      caption: asset.caption ?? "",
      credit: asset.credit ?? "",
      is_decorative: asset.is_decorative,
    });
  };

  const saveMetadata = async () => {
    if (!editing) return;
    setSaving(true);
    try {
      const updated = await updateMediaAsset(editing.id, {
        alt_text: editValues.alt_text.trim() || null,
        caption: editValues.caption.trim() || null,
        credit: editValues.credit.trim() || null,
        is_decorative: editValues.is_decorative,
      });
      setItems((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      setEditing(null);
      message.success(t("admin.media.messages.updated"));
    } catch (reason) {
      message.error(
        t("admin.media.messages.updateError") + ": " + (reason instanceof Error ? reason.message : String(reason)),
      );
    } finally {
      setSaving(false);
    }
  };

  const confirmArchive = async () => {
    if (!archiving) return;
    try {
      await archiveMediaAsset(archiving.id);
      setItems((current) => current.filter((item) => item.id !== archiving.id));
      setTotal((current) => Math.max(0, current - 1));
      message.success(t("admin.media.messages.archived"));
    } catch (reason) {
      message.error(
        t("admin.media.messages.archiveError") + ": " + (reason instanceof Error ? reason.message : String(reason)),
      );
    } finally {
      setArchiving(null);
    }
  };

  const copyUrl = async (url: string) => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard API unavailable");
      await navigator.clipboard.writeText(url);
      message.success(t("admin.media.messages.copied"));
    } catch {
      message.error(t("admin.media.messages.copyError"));
    }
  };

  const handleUploaded = (asset: MediaAsset) => {
    setReload((value) => value + 1);
    openEditor(asset);
    message.success(t("admin.media.messages.uploaded"));
  };

  return (
    <div className="route-fade-in space-y-6">
      <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
        <div>
          <Typography.Title level={2} className="!mb-1">
            {t("admin.media.title")}
          </Typography.Title>
          <Typography.Paragraph type="secondary" className="!mb-0 max-w-2xl">
            {t("admin.media.description")}
          </Typography.Paragraph>
        </div>
        <FileUpload
          value={undefined}
          purpose={uploadPurpose}
          accept="image/jpeg,image/png,image/webp"
          maxSizeMB={10}
          buttonText={t("admin.media.upload")}
          onUploaded={handleUploaded}
        />
      </div>

      <Card>
        <div className="flex flex-col gap-3 lg:flex-row">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            value={search}
            placeholder={t("admin.media.searchPlaceholder")}
            onChange={(event) => {
              setSearch(event.target.value);
              resetToFirstPage();
            }}
            className="lg:max-w-md"
          />
          <Select
            allowClear
            value={purpose}
            placeholder={t("admin.media.filterPurpose")}
            options={PURPOSE_OPTIONS.map((value) => ({
              value,
              label: t("admin.media.purposes." + value),
            }))}
            onChange={(value) => {
              setPurpose(value);
              resetToFirstPage();
            }}
            className="w-full lg:w-48"
          />
          <Select
            value={assetStatus}
            options={[
              { value: "ready", label: t("admin.media.status.ready") },
              { value: "archived", label: t("admin.media.status.archived") },
            ]}
            onChange={(value: AssetStatus) => {
              setAssetStatus(value);
              resetToFirstPage();
            }}
            className="w-full lg:w-48"
          />
        </div>
      </Card>

      {error ? (
        <Alert
          type="error"
          showIcon
          message={t("admin.media.loadError")}
          description={error}
          action={<Button onClick={() => setReload((value) => value + 1)}>{t("admin.media.retry")}</Button>}
        />
      ) : loading ? (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
          {Array.from({ length: 12 }, (_, index) => (
            <Card key={index} styles={{ body: { padding: 12 } }}>
              <Skeleton.Image active className="!h-36 !w-full" />
              <Skeleton active paragraph={{ rows: 2 }} className="mt-3" />
            </Card>
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card>
          <Empty
            image={<PictureOutlined className="text-4xl text-slate-300" />}
            description={t("admin.media.empty")}
          >
            <FileUpload
              value={undefined}
              purpose={uploadPurpose}
              accept="image/jpeg,image/png,image/webp"
              maxSizeMB={10}
              buttonText={t("admin.media.uploadFirst")}
              onUploaded={handleUploaded}
            />
          </Empty>
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6">
            {items.map((asset) => (
              <Card
                key={asset.id}
                hoverable
                styles={{ body: { padding: 12 } }}
                cover={
                  <div className="relative aspect-[4/3] overflow-hidden bg-slate-100 dark:bg-slate-800">
                    <img
                      src={asset.public_url}
                      alt={asset.alt_text || asset.original_filename}
                      loading="lazy"
                      className="h-full w-full object-cover"
                    />
                    {asset.status === "archived" ? (
                      <Tag className="absolute left-2 top-2" color="default">
                        {t("admin.media.status.archived")}
                      </Tag>
                    ) : null}
                  </div>
                }
              >
                <div className="space-y-2">
                  <Typography.Text ellipsis={{ tooltip: asset.original_filename }} className="block text-xs">
                    {asset.original_filename}
                  </Typography.Text>
                  <Typography.Text type="secondary" className="block text-[11px]">
                    {asset.width && asset.height ? asset.width + " × " + asset.height + " · " : ""}
                    {formatBytes(asset.size_bytes)}
                  </Typography.Text>
                  <div className="flex items-center justify-between gap-2">
                    <Typography.Text type="secondary" className="text-[11px]">
                      {t("admin.media.usage", { count: asset.usage_count })}
                    </Typography.Text>
                    {!asset.alt_text && !asset.is_decorative ? (
                      <Tag color="warning">{t("admin.media.missingAlt")}</Tag>
                    ) : null}
                  </div>
                  <Space size="small">
                    <Button size="small" icon={<EditOutlined />} aria-label={t("admin.media.editMetadata")} onClick={() => openEditor(asset)} />
                    <Button size="small" icon={<CopyOutlined />} aria-label={t("admin.media.copyUrl")} onClick={() => copyUrl(asset.public_url)} />
                    {asset.status === "ready" ? (
                      <Button size="small" danger icon={<DeleteOutlined />} aria-label={t("admin.media.archive")} onClick={() => setArchiving(asset)} />
                    ) : null}
                  </Space>
                </div>
              </Card>
            ))}
          </div>
          {total > PAGE_SIZE ? (
            <div className="flex justify-center">
              <Button.Group>
                <Button disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>{t("admin.media.previous")}</Button>
                <Button disabled>{page + " / " + Math.max(1, Math.ceil(total / PAGE_SIZE))}</Button>
                <Button disabled={page >= Math.ceil(total / PAGE_SIZE)} onClick={() => setPage((value) => value + 1)}>{t("admin.media.next")}</Button>
              </Button.Group>
            </div>
          ) : null}
        </>
      )}

      <Modal
        title={t("admin.media.editTitle")}
        open={editing !== null}
        onCancel={() => setEditing(null)}
        onOk={saveMetadata}
        confirmLoading={saving}
        okText={t("admin.media.saveMetadata")}
      >
        <Space direction="vertical" size="middle" className="w-full">
          <Input.TextArea
            rows={3}
            maxLength={2000}
            showCount
            value={editValues.alt_text}
            placeholder={t("admin.media.altPlaceholder")}
            onChange={(event) => setEditValues((current) => ({ ...current, alt_text: event.target.value }))}
          />
          <Input.TextArea
            rows={2}
            maxLength={2000}
            value={editValues.caption}
            placeholder={t("admin.media.captionPlaceholder")}
            onChange={(event) => setEditValues((current) => ({ ...current, caption: event.target.value }))}
          />
          <Input
            maxLength={512}
            value={editValues.credit}
            placeholder={t("admin.media.creditPlaceholder")}
            onChange={(event) => setEditValues((current) => ({ ...current, credit: event.target.value }))}
          />
          <Space>
            <Switch
              checked={editValues.is_decorative}
              onChange={(checked) => setEditValues((current) => ({ ...current, is_decorative: checked }))}
            />
            <Typography.Text>{t("admin.media.decorative")}</Typography.Text>
          </Space>
          {editing ? (
            <Typography.Text type="secondary">
              {t("admin.media.usageDetail", { count: editing.usage_count })}
            </Typography.Text>
          ) : null}
        </Space>
      </Modal>

      <Modal
        title={t("admin.media.archiveTitle")}
        open={archiving !== null}
        onCancel={() => setArchiving(null)}
        onOk={confirmArchive}
        okButtonProps={{ danger: true }}
        okText={t("admin.media.archive")}
      >
        <Typography.Paragraph>{t("admin.media.archiveConfirm")}</Typography.Paragraph>
        {archiving && archiving.usage_count > 0 ? (
          <Alert type="warning" showIcon message={t("admin.media.archiveInUse", { count: archiving.usage_count })} />
        ) : null}
      </Modal>
    </div>
  );
}
