import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { getReleaseProvenance, getReleases, type ReleaseSummary } from "@soymutdb/api-client";
import { formatNumber } from "@soymutdb/shared/format";
import { Alert, Button, PageContainer, ProCard, ProTable, Space, Tag, Typography, type ProColumns } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";

function safeExternalUrl(value: string | undefined): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function statusColor(status: ReleaseSummary["status"]): string {
  if (status === "published") return "green";
  if (status === "ready" || status === "validated") return "blue";
  if (status === "rolled_back") return "orange";
  return "default";
}

export default function ReleasesPage() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const query = useQuery({
    queryKey: ["admin", "releases"],
    queryFn: () => getReleases({ page: 1, page_size: 100 }),
  });
  const provenanceQuery = useQuery({
    queryKey: ["admin", "release-provenance", selectedId],
    queryFn: () => getReleaseProvenance(selectedId as string),
    enabled: Boolean(selectedId),
  });
  const releases = query.data ?? [];
  const provenance = provenanceQuery.data ?? [];

  // Read-only list: the only write-free action column is the provenance link,
  // which opens a read-only panel below. No column opts into ProTable's editor.
  const columns: ProColumns<ReleaseSummary>[] = [
    {
      title: t("releases.releaseName"),
      dataIndex: "id",
      key: "id",
      editable: false,
      render: (_id, release) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text code>{release.id}</Typography.Text>
          {release.name ? <Typography.Text type="secondary">{release.name}</Typography.Text> : null}
          {release.is_active ? <Tag color="green">{t("releases.active")}</Tag> : null}
        </Space>
      ),
    },
    {
      title: t("releases.status"),
      dataIndex: "status",
      key: "status",
      editable: false,
      render: (_value, release) => <Tag color={statusColor(release.status)}>{t(`releases.statuses.${release.status}`, { defaultValue: release.status })}</Tag>,
    },
    { title: t("releases.assembly"), dataIndex: "assembly_name", key: "assembly_name", editable: false, render: (value) => <Typography.Text code>{value}</Typography.Text> },
    {
      title: t("releases.variantCount"),
      dataIndex: "variant_count",
      key: "variant_count",
      align: "right",
      editable: false,
      render: (_value, release) => formatNumber(release.variant_count),
    },
    {
      title: t("common.actions"),
      key: "actions",
      editable: false,
      render: (_value, release) => (
        <Button
          type="link"
          data-testid={`release-provenance-${release.id}`}
          onClick={() => setSelectedId(release.id)}
        >
          {t("releases.provenance")}
        </Button>
      ),
    },
  ];

  return (
    <PageContainer
      title={t("admin.releases", { defaultValue: "Releases" })}
      subTitle={t("admin.releasesHint", { defaultValue: "Every release the API serves, with the imports and source files that produced it." })}
    >
      {query.isPending ? (
        <ProCard loading data-testid="releases-loading" />
      ) : query.isError ? (
        <Alert
          type="error"
          showIcon
          data-testid="releases-error"
          title={t("common.errorDescription")}
          action={<Button size="small" onClick={() => void query.refetch()} data-testid="releases-retry">{t("common.retry")}</Button>}
        />
      ) : releases.length === 0 ? (
        <ProCard><Typography.Text type="secondary" data-testid="releases-empty">{t("common.noData")}</Typography.Text></ProCard>
      ) : (
        <ProCard>
          <div data-testid="releases-table">
            <ProTable<ReleaseSummary>
              {...PRO_LIST_SHELL}
              rowKey="id"
              dataSource={releases}
              columns={columns}
              pagination={{ pageSize: 10, showSizeChanger: true }}
              scroll={{ x: 760 }}
              onRow={() => ({ "data-testid": "release-row" } as React.HTMLAttributes<HTMLTableRowElement>)}
            />
          </div>
        </ProCard>
      )}

      {selectedId ? (
        <ProCard
          style={{ marginTop: 16 }}
          title={<span data-testid="provenance-heading">{t("releases.provenance")} · <Typography.Text code>{selectedId}</Typography.Text></span>}
          extra={<Button size="small" data-testid="provenance-close" onClick={() => setSelectedId(null)}>{t("common.close")}</Button>}
        >
          {provenanceQuery.isPending ? (
            <ProCard loading data-testid="provenance-loading" />
          ) : provenanceQuery.isError ? (
            <Alert type="error" showIcon data-testid="provenance-error" title={t("common.errorDescription")} />
          ) : provenance.length === 0 ? (
            <Typography.Text type="secondary" data-testid="provenance-empty">{t("common.noData")}</Typography.Text>
          ) : (
            <ul className="grid gap-2" data-testid="provenance-list">
              {provenance.map((item) => {
                const url = safeExternalUrl(item.source_url);
                return (
                  <li key={item.id} className="rounded-md border border-border p-3 text-sm">
                    <Typography.Text code>{item.source_type} · {item.source_name}</Typography.Text>
                    {item.version ? <div><Typography.Text type="secondary">{item.version}</Typography.Text></div> : null}
                    {url ? (
                      <div><a href={url} target="_blank" rel="noopener noreferrer" className="break-all">{item.source_url}</a></div>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </ProCard>
      ) : null}
    </PageContainer>
  );
}
