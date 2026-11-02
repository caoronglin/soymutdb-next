import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { getActiveRelease, getAdminRelease, getAdminReleases } from "@soymutdb/api-client";
import { formatDate, formatNumber } from "@soymutdb/shared/format";
import { Alert, Button, Descriptions, PageContainer, ProCard, ProTable, Space, Tag, Typography, type ProColumns } from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import { readActiveReleaseId, statusTone, toReleaseRow, toReleaseRows, type ReleaseRow } from "./releases/release-rows";

export default function ReleasesPage() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  // `GET /releases` accepts only `status`; it ignores `page`/`page_size` and
  // returns the whole list ordered by `published_at` desc
  // (apps/api/app/api/v1/releases.py::list_releases), so the table paginates
  // client-side and the request carries no pagination the API would honour.
  const query = useQuery({
    queryKey: ["admin", "releases"],
    queryFn: () => getAdminReleases(),
  });
  // The active pointer annotates the list; it is not a page-level dependency,
  // so a failure here degrades to "no badge" rather than an error screen.
  const activeQuery = useQuery({
    queryKey: ["admin", "active-release"],
    queryFn: () => getActiveRelease(),
  });
  // `GET /releases/{release_id}` is served by the API. The route this panel used
  // to call, `GET /releases/{id}/provenance`, is not served by any router
  // (packages/api-client/contract-visibility-baseline.json), so every click used
  // to be a guaranteed 404; the panel now reads the release the API can return.
  const detailQuery = useQuery({
    queryKey: ["admin", "release-detail", selectedId],
    queryFn: () => getAdminRelease(selectedId as string),
    enabled: Boolean(selectedId),
  });
  const activeReleaseId = readActiveReleaseId(activeQuery.data);
  const releases = toReleaseRows(query.data, activeReleaseId);
  const detail = toReleaseRow(detailQuery.data, activeReleaseId);

  // Read-only list: the only action reads one release through a route the API
  // serves. No column opts into ProTable's editor, and no lifecycle write
  // (validate/ready/publish/rollback) is offered here — those live on
  // `POST /admin/releases/{id}/...`, administrator-only and audited server-side.
  const columns: ProColumns<ReleaseRow>[] = [
    {
      title: t("releases.releaseName"),
      key: "release",
      editable: false,
      render: (_value, release) => (
        <Space orientation="vertical" size={2}>
          <Typography.Text code>{release.id}</Typography.Text>
          <Typography.Text code type="secondary">{release.version || release.id}</Typography.Text>
          {release.name ? <Typography.Text type="secondary">{release.name}</Typography.Text> : null}
          {release.isActive ? <Tag color="green">{t("releases.active")}</Tag> : null}
        </Space>
      ),
    },
    {
      title: t("releases.status"),
      key: "status",
      editable: false,
      render: (_value, release) => <Tag color={statusTone(release.status)}>{t(`releases.statuses.${release.status}`, { defaultValue: release.status })}</Tag>,
    },
    {
      title: t("releases.variantCount"),
      key: "variant_count",
      align: "right",
      editable: false,
      render: (_value, release) => formatNumber(release.variantCount),
    },
    {
      title: t("releases.releaseDate"),
      key: "published_at",
      editable: false,
      render: (_value, release) => <Typography.Text>{formatDate(release.publishedAt)}</Typography.Text>,
    },
    {
      title: t("common.actions"),
      key: "actions",
      editable: false,
      render: (_value, release) => (
        <Button
          type="link"
          data-testid={`release-details-${release.id}`}
          onClick={() => setSelectedId(release.id)}
        >
          {t("releases.viewDetails")}
        </Button>
      ),
    },
  ];

  return (
    <PageContainer
      title={t("admin.releases", { defaultValue: "Releases" })}
      subTitle={t("admin.releasesHint", { defaultValue: "Release versions, publication status and database counts." })}
    >
      {query.isPending ? (
        <ProCard loading data-testid="releases-loading" />
      ) : query.isError ? (
        <Alert
          type="error"
          showIcon
          data-testid="releases-error"
          title={t("common.errorDescription")}
          action={<Button size="small" loading={query.isFetching} onClick={() => void query.refetch()} data-testid="releases-retry">{t("common.retry")}</Button>}
        />
      ) : releases.length === 0 ? (
        <ProCard><Typography.Text type="secondary" data-testid="releases-empty">{t("common.noData")}</Typography.Text></ProCard>
      ) : (
        <ProCard>
          <div data-testid="releases-table">
            <ProTable<ReleaseRow>
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
          title={<span data-testid="release-detail-heading">{t("releases.viewDetails")} · <Typography.Text code>{selectedId}</Typography.Text></span>}
          extra={<Button size="small" data-testid="release-detail-close" onClick={() => setSelectedId(null)}>{t("common.close")}</Button>}
        >
          {detailQuery.isPending ? (
            <ProCard loading data-testid="release-detail-loading" />
          ) : detailQuery.isError ? (
            <Alert
              type="error"
              showIcon
              data-testid="release-detail-error"
              title={t("common.errorDescription")}
              action={<Button size="small" loading={detailQuery.isFetching} onClick={() => void detailQuery.refetch()} data-testid="release-detail-retry">{t("common.retry")}</Button>}
            />
          ) : detail === null ? (
            <Typography.Text type="secondary" data-testid="release-detail-empty">{t("common.noData")}</Typography.Text>
          ) : (
            <Descriptions
              size="small"
              column={2}
              data-testid="release-detail-list"
              items={[
                { key: "name", label: t("releases.releaseName"), children: detail.name || "—" },
                { key: "version", label: t("releases.version", { defaultValue: "Version" }), children: detail.version || "—" },
                { key: "status", label: t("releases.status"), children: <Tag color={statusTone(detail.status)}>{t(`releases.statuses.${detail.status}`, { defaultValue: detail.status })}</Tag> },
                { key: "published", label: t("releases.releaseDate"), children: formatDate(detail.publishedAt) },
                { key: "variants", label: t("releases.variantCount"), children: formatNumber(detail.variantCount) },
                { key: "genes", label: t("releases.geneCount"), children: formatNumber(detail.geneCount) },
                { key: "lines", label: t("releases.mutantLineCount"), children: formatNumber(detail.mutantLineCount) },
                { key: "updated", label: t("common.updated"), children: formatDate(detail.updatedAt) },
                ...(detail.isActive ? [{ key: "active", label: t("common.status"), children: <Tag color="green">{t("releases.active")}</Tag> }] : []),
                { key: "description", label: t("releases.description", { defaultValue: "Description" }), span: 2, children: detail.description || "—" },
              ]}
            />
          )}
        </ProCard>
      ) : null}
    </PageContainer>
  );
}
