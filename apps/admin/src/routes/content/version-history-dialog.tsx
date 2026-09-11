import { EyeOutlined, HistoryOutlined, RedoOutlined } from "@ant-design/icons";
import * as React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { http } from "@soymutdb/api-client";
import { Button, Modal, Typography } from "@/lib/antd";
import { ConfirmDialog } from "../../components/confirm-dialog";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { contentKeys } from "./query-keys";
import type { StaticPage, VersionHistoryDialogProps } from "./pages-tab";

export interface ContentVersion { id: string; page_id: string; version: number; title_en: string; title_zh: string | null; content_en: string; content_zh: string | null; summary: string | null; edited_by: string | null; edit_comment: string | null; created_at: string; }
export interface VersionDetailProps { version: ContentVersion; onBack: () => void; }
export interface VersionHistoryDialogComponentProps extends VersionHistoryDialogProps { VersionDetail: React.ComponentType<VersionDetailProps>; }

function getErrorMessage(err: unknown, t: (key: string, options?: Record<string, unknown>) => string): string {
  if (err instanceof Error) return err.message;
  return t("admin.content.unknownError", { defaultValue: "An unknown error occurred" });
}

export function VersionHistoryDialog({ page, open, onOpenChange, VersionDetail }: VersionHistoryDialogComponentProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [viewing, setViewing] = React.useState<ContentVersion | null>(null);
  const [restoreTarget, setRestoreTarget] =
    React.useState<ContentVersion | null>(null);

  const { data, isLoading } = useQuery<ContentVersion[]>({
    queryKey: contentKeys.pageVersions(page.id),
    queryFn: async () => {
      const res = await http.get<
        ContentVersion[] | { items: ContentVersion[] }
      >(`/admin/content/pages/${page.id}/versions`);
      return Array.isArray(res) ? res : res.items;
    },
    enabled: open,
  });

  const restoreMutation = useMutation({
    mutationFn: (version: number) =>
      http.post(
        `/admin/content/pages/${page.id}/versions/${version}/restore`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: contentKeys.all });
      queryClient.invalidateQueries({
        queryKey: contentKeys.pageVersions(page.id),
      });
      setRestoreTarget(null);
      setViewing(null);
    },
  });

  React.useEffect(() => {
    if (!open) {
      setViewing(null);
      setRestoreTarget(null);
    }
  }, [open]);

  const versions = data ?? [];

  const versionColumns: DataTableColumn<ContentVersion>[] = [
    {
      key: "version",
      header: t("admin.content.colVersion", { defaultValue: "Version" }),
      sortable: true,
      sortAccessor: (v) => v.version,
      cell: (v) => (
        <span className="font-mono text-sm font-medium">v{v.version}</span>
      ),
    },
    {
      key: "title_en",
      header: t("admin.content.colTitle", { defaultValue: "Title" }),
      sortable: true,
      sortAccessor: (v) => v.title_en,
      cell: (v) => (
        <div className="min-w-0">
          <p className="truncate font-medium">{v.title_en}</p>
          {v.title_zh ? (
            <p className="truncate text-xs text-muted-foreground">
              {v.title_zh}
            </p>
          ) : null}
        </div>
      ),
    },
    {
      key: "edit_comment",
      header: t("admin.content.colComment", { defaultValue: "Comment" }),
      cell: (v) => (
        <span className="text-sm text-muted-foreground">
          {v.edit_comment ?? "—"}
        </span>
      ),
    },
    {
      key: "edited_by",
      header: t("admin.content.colEditedBy", { defaultValue: "Edited By" }),
      sortable: true,
      sortAccessor: (v) => v.edited_by ?? "",
      cell: (v) => <span className="text-sm">{v.edited_by ?? "—"}</span>,
    },
    {
      key: "created_at",
      header: t("admin.content.colCreated", { defaultValue: "Created" }),
      sortable: true,
      sortAccessor: (v) => v.created_at,
      cell: (v) => (
        <span className="text-sm text-muted-foreground">{v.created_at}</span>
      ),
    },
    {
      key: "actions",
      header: t("admin.content.colActions", { defaultValue: "Actions" }),
      align: "right",
      cell: (v) => (
        <div className="flex items-center justify-end gap-1">
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setViewing(v)}
            title={t("admin.content.view", { defaultValue: "View" })}
            aria-label={t("admin.content.viewVersionContent", { defaultValue: "View version content" })}
          >
            <EyeOutlined className="size-3.5" />
          </Button>
          <Button
            type="text"
            size="small"
            className="size-8 p-0"
            onClick={() => setRestoreTarget(v)}
            title={t("admin.content.restore", { defaultValue: "Restore" })}
            aria-label={t("admin.content.restoreVersion", { defaultValue: "Restore version" })}
            disabled={v.version === page.current_version}
          >
            <RedoOutlined className="size-3.5" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <Modal open={open} onCancel={() => onOpenChange(false)}>
      <div className="max-h-[90vh] max-w-4xl overflow-y-auto">
        <div>
          <Typography.Title level={5} className="flex items-center gap-2">
            <HistoryOutlined className="size-5" />
            {t("admin.content.versionHistoryTitle", { defaultValue: "Version History" })}
          </Typography.Title>
          <Typography.Text type="secondary">
            <span className="font-medium text-foreground">{page.title_en}</span>
            {" · "}{t("admin.content.currentVersionLine", { defaultValue: "current version v{{version}}", version: page.current_version })}
          </Typography.Text>
        </div>

        {viewing ? (
          <VersionDetail version={viewing} onBack={() => setViewing(null)} />
        ) : (
          <DataTable
            columns={versionColumns}
            data={versions}
            rowKey={(v) => v.id}
            loading={isLoading}
            emptyTitle={t("admin.content.noVersionsFound", { defaultValue: "No versions found" })}
            emptyDescription={t("admin.content.noVersionsFoundDesc", { defaultValue: "Versions are created automatically when a page is edited." })}
          />
        )}

        <div>
          <Button type="default" onClick={() => onOpenChange(false)}>
            {t("admin.content.close", { defaultValue: "Close" })}
          </Button>
        </div>
      </div>

      {restoreTarget && (
        <ConfirmDialog
          open={Boolean(restoreTarget)}
          onOpenChange={(open) => !open && setRestoreTarget(null)}
          title={t("admin.content.restoreVersionTitle", { defaultValue: "Restore Version" })}
          description={t("admin.content.restoreVersionConfirm", { defaultValue: 'Restore page "{{title}}" to version v{{version}}? This creates a new version with the content of v{{version}}.', title: page.title_en, version: restoreTarget.version })}
          confirmLabel={t("admin.content.restore", { defaultValue: "Restore" })}
          severity="destructive"
          onConfirm={() => restoreMutation.mutate(restoreTarget.version)}
          loading={restoreMutation.isPending}
        >
          {restoreMutation.error ? (
            <p className="text-sm text-destructive" role="alert">
              {getErrorMessage(restoreMutation.error, t)}
            </p>
          ) : null}
        </ConfirmDialog>
      )}
    </Modal>
  );
}
