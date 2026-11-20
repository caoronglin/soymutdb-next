/**
 * Downloads route — data file catalog fetched from API, grouped by category.
 *
 * Features:
 * - API-driven file list (no hardcoded data)
 * - Grouped display by category (variants, genes, assemblies, tracks)
 * - Download via pre-signed URLs
 * - Preview button opening file-preview-dialog (unified viewer with
 *   same-group file switching)
 * - Size badges with "too large" indicator
 */
import type * as React from "react";
import { useState } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../lib/site-content-react";
import {
  DatabaseOutlined as Database,
  DeploymentUnitOutlined as Dna,
  DownloadOutlined as Download,
  EyeOutlined as Eye,
  FileProtectOutlined as FileCheck2,
  FileTextOutlined as FileText,
  PartitionOutlined as Layers,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Modal,
  Select,
  Skeleton,
  Table,
  Tag,
  Typography,
  type TableColumnsType,
} from "@/lib/antd";
import { FadeUp, Stagger } from "../components/route-motion";
import { getDownloadFiles, getDownloadUrl } from "@soymutdb/api-client";
import type { DownloadFile } from "@soymutdb/api-client";
import { ExportQueryCard } from "../components/export-query-card";
import { SequenceFormatConverter } from "../components/sequence-format-converter";
import { FilePreviewDialog } from "../components/file-viewer/file-preview-dialog";
import type { PreviewFile } from "../components/file-viewer/file-preview-dialog";
import { VariantExportControls } from "../components/variant-export-controls";
import { safeExternalUrl } from "../lib/url-safety";
import { REMOTE_PREVIEW_CONFIG } from "../lib/remote-preview";
import { assembliesQueryOptions } from "../lib/query-options";
import { assemblyOptionLabel } from "../lib/assembly-selection";
import { SITE_VARIANT } from "../lib/site-variant";
import { useReleaseId } from "../lib/release-scope";

export const Route = createFileRoute("/downloads")({
  component: DownloadsComponent,
});

const CATEGORY_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  variants: Dna,
  genes: Layers,
  assemblies: Database,
  tracks: FileText,
};

const CATEGORY_LABEL_KEYS: Record<string, string> = {
  variants: "downloads.variants",
  genes: "downloads.genes",
  assemblies: "downloads.assemblies",
  tracks: "downloads.tracks",
};

const MAX_PREVIEW_SIZE = 10 * 1024 * 1024; // 10 MB

function formatFileSize(bytes: number | null): string {
  if (bytes === null || bytes === 0) return "N/A";
  const units = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  const size = bytes / Math.pow(1024, i);
  return `${size.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr).toISOString().slice(0, 10);
  } catch {
    return dateStr;
  }
}

function shortChecksum(sha256: string | null): string {
  // A legacy file has no digest. Rendering "not recorded" instead of a
  // truncated string is what keeps it from being mistaken for a verified
  // checksum; an empty string would be the same lie in a quieter form.
  return sha256 ? sha256.slice(0, 12) : "—";
}

/** Sequence formats the converter can read. */
const SEQUENCE_EXTENSIONS = [".fa", ".fasta", ".fna", ".fas"];

function isSequenceFile(file: DownloadFile): boolean {
  const lowered = file.name.toLowerCase();
  return SEQUENCE_EXTENSIONS.some((extension) => lowered.endsWith(extension));
}

function getFileFormat(name: string): string {
  const parts = name.toLowerCase().split(".");
  if (parts.length < 2) return "Unknown";
  const last = parts[parts.length - 1];
  if (last === "gz" || last === "bz2" || last === "zip") {
    return parts.length > 2 ? parts[parts.length - 2].toUpperCase() : last.toUpperCase();
  }
  return last.toUpperCase();
}

function DownloadsComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const [preview, setPreview] = useState<{ files: PreviewFile[]; index: number } | null>(null);
  // Conversion fetches the file body into the page, so it is bounded by the
  // same size cap the preview uses and only offered for sequence formats.
  const [convert, setConvert] = useState<{ file: DownloadFile; text: string } | null>(null);

  const { data: files, isLoading, error, refetch } = useQuery({
    queryKey: ["downloads"],
    queryFn: () => getDownloadFiles(),
    staleTime: 60_000,
  });

  // The custom export is bound to exactly one assembly namespace: an export
  // that could span v4 and v5 would mix coordinate systems in one artifact.
  // The catalogue supplies the options; the default assembly is the one the
  // release itself publishes, so the common case needs no interaction.
  // The pinned release is read reactively: a module read captured a
  // snapshot that no release switch could invalidate, so the catalogue and
  // the export would keep answering for a release the tab no longer follows.
  const releaseId = useReleaseId();
  const assembliesQuery = useQuery(
    assembliesQueryOptions({ releaseId, siteVariant: SITE_VARIANT }),
  );
  const assemblies = assembliesQuery.data ?? [];
  const [exportAssemblyId, setExportAssemblyId] = useState<string | undefined>(undefined);
  const exportAssembly = exportAssemblyId
    ? assemblies.find((assembly) => String(assembly.id) === exportAssemblyId)
    : assemblies.find((assembly) => assembly.is_default);

  const handleDownload = async (file: DownloadFile) => {
    // Both the signed URL and the stored location are server data: only an
    // http(s) target may reach window.open, or a poisoned row becomes a
    // script/exfiltration vector. A rejected target opens nothing.
    const openSafe = (candidate: string | undefined) => {
      const url = safeExternalUrl(candidate);
      if (url) window.open(url, "_blank", "noopener,noreferrer");
    };
    try {
      const { url } = await getDownloadUrl(file.id);
      openSafe(url);
    } catch {
      // Fallback: the catalogue's own location, still scheme-checked.
      openSafe(file.file_url);
    }
  };

  const handlePreview = async (file: DownloadFile) => {
    // Offer the whole group for in-dialog switching (same-category files).
    const group = groups.find((g) => g.files.some((f) => f.id === file.id));
    const groupFiles = group?.files ?? [file];

    // A remote preview hands the artifact to a third party, so only a
    // time-limited signed location may enter it. If signing fails the
    // catalogue location is kept; the preview policy then keeps it local.
    const entries = await Promise.all(
      groupFiles.map(async (f) => {
        let url = safeExternalUrl(f.file_url) ?? "";
        try {
          const signed = await getDownloadUrl(f.id);
          url = safeExternalUrl(signed.url) ?? url;
        } catch {
          // Fall through with the catalogue location.
        }
        return {
          name: f.name,
          url,
          size: f.file_size ?? 0,
          format: getFileFormat(f.name),
          // The catalogue lists only files of the resolved published release.
          visibility: "public" as const,
        };
      }),
    );
    setPreview({
      files: entries,
      index: groupFiles.findIndex((f) => f.id === file.id),
    });
  };

  // Group files by category
  const groups = groupByCategory(files ?? []);

  // antd's native table replaces the hand-rolled <table>: same columns, but it
  // inherits the theme's header/row/hover tokens and the responsive scroll.
  /**
   * Fetch a sequence artifact and open the converter.
   *
   * The body is read here rather than in the component so the 10 MB cap and the
   * "no paths, only text" rule stay next to the existing preview policy.
   */
  const handleConvert = async (file: DownloadFile) => {
    if (!isSequenceFile(file)) return;
    if (file.file_size !== null && file.file_size > MAX_PREVIEW_SIZE) return;
    try {
      const response = await fetch(file.file_url);
      if (!response.ok) throw new Error(String(response.status));
      setConvert({ file, text: await response.text() });
    } catch {
      setConvert({ file, text: "" });
    }
  };

  const downloadColumns: TableColumnsType<DownloadFile> = [
    {
      title: get("downloads.fileName", t("downloads.fileName")),
      dataIndex: "name",
      key: "name",
      render: (_, file) => <span className="font-mono text-xs">{file.name}</span>,
    },
    {
      title: get("downloads.format", t("downloads.format")),
      key: "format",
      width: 110,
      render: (_, file) => (
        <Tag variant="outlined" className="font-mono text-[10px]">
          {getFileFormat(file.name)}
        </Tag>
      ),
    },
    {
      title: get("downloads.fileSize", t("downloads.fileSize")),
      key: "size",
      width: 130,
      render: (_, file) => {
        const oversize = file.file_size !== null && file.file_size > 1024 * 1024 * 1024;
        return (
          <span
            className={`font-mono text-xs tabular-nums ${oversize ? "text-warning-foreground" : ""}`}
          >
            {formatFileSize(file.file_size)}
          </span>
        );
      },
    },
    {
      title: get("downloads.lastUpdated", t("downloads.lastUpdated")),
      key: "created_at",
      width: 150,
      render: (_, file) => <span className="font-mono text-xs">{formatDate(file.created_at)}</span>,
    },
    {
      title: get("downloads.checksum", t("downloads.checksum")),
      key: "sha256",
      width: 150,
      render: (_, file) => (
        <span
          className="font-mono text-xs"
          data-testid={`download-checksum-${file.id}`}
          title={file.sha256 ?? ""}
        >
          {shortChecksum(file.sha256)}
        </span>
      ),
    },
    {
      title: get("downloads.license", t("downloads.license")),
      key: "license",
      width: 120,
      render: (_, file) => (
        <span className="text-xs" data-testid={`download-license-${file.id}`}>
          {file.license ?? "—"}
        </span>
      ),
    },
    {
      title: get("downloads.generatedAt", t("downloads.generatedAt")),
      key: "generated_at",
      width: 150,
      render: (_, file) => (
        <span className="font-mono text-xs">
          {file.generated_at ? formatDate(file.generated_at) : "—"}
        </span>
      ),
    },
    {
      title: t("common.actions"),
      key: "actions",
      align: "right",
      width: 190,
      render: (_, file) => {
        const tooLarge = file.file_size !== null && file.file_size > MAX_PREVIEW_SIZE;
        return (
          <div className="flex items-center justify-end gap-1">
            {tooLarge ? (
              <Tag className="text-[10px]">{get("downloads.too_large", t("downloads.too_large"))}</Tag>
            ) : (
              <>
                {/* Only a sequence artifact can be converted, and only when it
                    is small enough to read into the page. */}
                {isSequenceFile(file) ? (
                  <Button
                    type="text"
                    size="small"
                    onClick={() => void handleConvert(file)}
                    data-testid={`download-convert-${file.id}`}
                  >
                    {get("downloads.convert.action", t("downloads.convert.action"))}
                  </Button>
                ) : null}
                <Button type="text" size="small" onClick={() => handlePreview(file)}>
                  <Eye className="size-3.5" aria-hidden />
                  <span className="hidden sm:inline">
                    {get("downloads.preview", t("downloads.preview"))}
                  </span>
                </Button>
              </>
            )}
            <Button
              type="text"
              size="small"
              aria-label={get("downloads.download", t("downloads.download"))}
              onClick={() => handleDownload(file)}
            >
              <Download className="size-4" aria-hidden />
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{get("downloads.title", t("downloads.title"))}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {get("downloads.subtitle", t("downloads.subtitle"))}
        </h1>
      </FadeUp>

      {isLoading && (
        <div className="mt-10 space-y-4">
          <Skeleton className="h-32 w-full rounded-xl" />
          <Skeleton className="h-32 w-full rounded-xl" />
          <Skeleton className="h-32 w-full rounded-xl" />
        </div>
      )}

      {error && (
        <Alert
          className="mt-10"
          data-testid="downloads-error"
          type="error"
          showIcon
          title={t("downloads.loadError")}
          action={
            <Button
              size="small"
              data-testid="downloads-retry"
              onClick={() => void refetch()}
            >
              {t("common.retry")}
            </Button>
          }
        />
      )}

      {!isLoading && !error && groups.length === 0 && (
        <div data-testid="downloads-empty" className="mt-10">
          <Empty description={t("downloads.empty")}>
            <Link to="/search" className="text-sm font-medium text-primary hover:underline">
              {t("home.databaseSearch")} →
            </Link>
          </Empty>
        </div>
      )}

      <Stagger className="mt-10 grid gap-4">
        {groups.map((group) => {
          const Icon = group.icon;
          return (
            <Card key={group.id}>
              <div>
                <Typography.Title className="flex items-center gap-2">
                  <span className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
                    <Icon className="size-5" aria-hidden />
                  </span>
                  {get(group.titleKey, t(group.titleKey))}
                </Typography.Title>
                <Typography.Text>
                  {group.files.length} {t("common.items")}
                </Typography.Text>
              </div>
              <Table<DownloadFile>
                rowKey="id"
                size="small"
                dataSource={group.files}
                pagination={false}
                scroll={{ x: 720 }}
                onRow={(file) =>
                  ({ "data-testid": `download-row-${file.id}` }) as React.HTMLAttributes<HTMLElement>
                }
                columns={downloadColumns}
              />
            </Card>
          );
        })}
      </Stagger>

      <Card className="mt-6 border-dashed">
        <div className="flex flex-wrap items-center gap-4 p-6">
          <div className="flex size-10 items-center justify-center rounded-lg bg-accent text-accent-foreground">
            <FileCheck2 className="size-5" aria-hidden />
          </div>
          <div className="flex-1">
            <p className="font-medium">{t("downloads.customExportTitle")}</p>
            <p className="text-sm text-muted-foreground">
              {t("downloads.customExportDescription")}
            </p>
          </div>
          <div className="w-full sm:w-64">
            <label
              className="mb-1 block text-xs text-muted-foreground"
              htmlFor="download-export-assembly"
            >
              {t("variants.assembly")}
            </label>
            <Select
              id="download-export-assembly"
              data-testid="download-export-assembly"
              value={exportAssembly ? String(exportAssembly.id) : undefined}
              onChange={(value) => setExportAssemblyId(String(value))}
              loading={assembliesQuery.isLoading}
              disabled={assembliesQuery.isError || assemblies.length === 0}
              placeholder={t("search.genes.assemblyPlaceholder")}
              options={assemblies.map((assembly) => ({
                value: String(assembly.id),
                label: assemblyOptionLabel(assembly),
              }))}
            />
          </div>
        </div>
        <div className="px-6 pb-6">
          <VariantExportControls
            assemblyKey={exportAssembly?.name ?? ""}
            submitLabel={t("common.submit")}
          />
        </div>
      </Card>

      <ExportQueryCard
        assemblies={assemblies}
        defaultAssemblyId={exportAssembly ? String(exportAssembly.id) : undefined}
      />

      {convert ? (
        <Modal
          open
          title={convert.file.name}
          footer={null}
          width={720}
          onCancel={() => setConvert(null)}
          data-testid="download-convert-dialog"
        >
          <SequenceFormatConverter
            text={convert.text}
            sourceFormat="fasta"
            fileName={convert.file.name}
          />
        </Modal>
      ) : null}

      {preview && (
        <FilePreviewDialog
          files={preview.files}
          initialIndex={preview.index}
          open={Boolean(preview)}
          remotePreview={REMOTE_PREVIEW_CONFIG}
          onOpenChange={(open: boolean) => {
            if (!open) setPreview(null);
          }}
        />
      )}
    </div>
  );
}

interface DownloadGroup {
  id: string;
  titleKey: string;
  icon: React.ComponentType<{ className?: string }>;
  files: DownloadFile[];
}

function groupByCategory(files: DownloadFile[]): DownloadGroup[] {
  const grouped = new Map<string, DownloadFile[]>();

  for (const file of files) {
    const cat = file.category ?? "other";
    if (!grouped.has(cat)) {
      grouped.set(cat, []);
    }
    grouped.get(cat)!.push(file);
  }

  // Order: variants, genes, assemblies, tracks, then others
  const order = ["variants", "genes", "assemblies", "tracks"];
  const ordered: DownloadGroup[] = [];

  for (const cat of order) {
    const catFiles = grouped.get(cat);
    if (catFiles) {
      ordered.push({
        id: cat,
        titleKey: CATEGORY_LABEL_KEYS[cat] ?? `downloads.${cat}`,
        icon: CATEGORY_ICONS[cat] ?? FileText,
        files: catFiles,
      });
      grouped.delete(cat);
    }
  }

  // Remaining categories
  for (const [cat, catFiles] of grouped) {
    ordered.push({
      id: cat,
      titleKey: `downloads.${cat}`,
      icon: FileText,
      files: catFiles,
    });
  }

  return ordered;
}
