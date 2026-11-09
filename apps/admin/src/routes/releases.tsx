import * as React from "react";
import { useQuery } from "@tanstack/react-query";
import { ReloadOutlined } from "@ant-design/icons";
import { getActiveRelease, getAdminRelease, getAdminReleases } from "@soymutdb/api-client";
import { formatDate, formatNumber } from "@soymutdb/shared/format";
import {
  Alert,
  Button,
  Descriptions,
  Input,
  PageContainer,
  ProCard,
  ProTable,
  Select,
  Space,
  Tag,
  Typography,
  type ProColumns,
} from "@/lib/antd";
import { useTranslation } from "react-i18next";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import { readActiveReleaseId, statusTone, toReleaseRow, toReleaseRows, type ReleaseRow } from "./releases/release-rows";

const STATUS_ORDER = ["published", "ready", "validated", "draft", "rolled_back"] as const;

function SummaryCard({ label, value, hint }: { label: React.ReactNode; value: React.ReactNode; hint?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card px-4 py-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      {hint ? <p className="mt-0.5 truncate text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export default function ReleasesPage() {
  const { t } = useTranslation();
  const [selectedId, setSelectedId] = React.useState<string | null>(null);
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<string>("all");
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
  const releases = React.useMemo(() => toReleaseRows(query.data, activeReleaseId), [query.data, activeReleaseId]);
  const detail = toReleaseRow(detailQuery.data, activeReleaseId);

  const statuses = React.useMemo(() => {
    const present = new Set(releases.map((release) => release.status));
    return STATUS_ORDER.filter((status) => present.has(status));
  }, [releases]);

  const filtered = React.useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    return releases.filter((release) => {
      if (statusFilter !== "all" && release.status !== statusFilter) return false;
      if (!needle) return true;
      return [release.id, release.name, release.version]
        .filter(Boolean)
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle);
    });
  }, [releases, search, statusFilter]);

  const activeRelease = releases.find((release) => release.isActive) ?? null;
  const publishedCount = releases.filter((release) => release.status === "published").length;
  const draftCount = releases.filter((release) => release.status === "draft").length;

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
      render: (_value, release) => <Tag color={statusTone(release.status)}>{t(`releaseStatus.${release.status}`, { defaultValue: release.status })}</Tag>,
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
      extra={
        <Button
          icon={<ReloadOutlined aria-hidden />}
          loading={query.isFetching}
          onClick={() => void query.refetch()}
          data-testid="releases-refresh"
        >
          {t("common.refresh", { defaultValue: "Refresh" })}
        </Button>
      }
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
        <ProCard data-testid="releases-empty">
          <div className="flex flex-col items-center gap-3 py-10 text-center">
            <Typography.Title level={5} style={{ margin: 0 }}>
              {t("admin.releasesEmpty.title", { defaultValue: "No releases yet" })}
            </Typography.Title>
            <Typography.Text type="secondary" style={{ maxWidth: 520 }}>
              {t("admin.releasesEmpty.description", {
                defaultValue:
                  "A release groups the data imported for one assembly version. Create one from the import workflow, then publish it to serve it on the public site.",
              })}
            </Typography.Text>
            <Space>
              <Button type="primary" href="#/imports">
                {t("admin.releasesEmpty.openImports", { defaultValue: "Open imports" })}
              </Button>
              <Button href="#/site-control">
                {t("admin.releasesEmpty.openSiteControl", { defaultValue: "Site control" })}
              </Button>
            </Space>
          </div>
        </ProCard>
      ) : (
        <>
          <div data-testid="releases-summary" className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <SummaryCard
              label={t("admin.releasesSummary.total", { defaultValue: "Total releases" })}
              value={formatNumber(releases.length)}
            />
            <SummaryCard
              label={t("admin.releasesSummary.published", { defaultValue: "Published" })}
              value={formatNumber(publishedCount)}
            />
            <SummaryCard
              label={t("admin.releasesSummary.draft", { defaultValue: "Drafts" })}
              value={formatNumber(draftCount)}
            />
            <SummaryCard
              label={t("admin.releasesSummary.active", { defaultValue: "Active release" })}
              value={activeRelease ? activeRelease.version || activeRelease.id : "—"}
              hint={
                activeRelease
                  ? t("admin.releasesSummary.activeVariants", {
                      defaultValue: "{{count}} variants served",
                      count: formatNumber(activeRelease.variantCount),
                    })
                  : t("admin.releasesSummary.noActive", { defaultValue: "No active release pointer" })
              }
            />
          </div>

          <ProCard>
            <div data-testid="releases-table">
              <div className="mb-3 flex flex-wrap items-center gap-2">
                <Input
                  allowClear
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder={t("admin.releasesFilter.search", { defaultValue: "Search by name, version, or ID" })}
                  aria-label={t("admin.releasesFilter.search", { defaultValue: "Search by name, version, or ID" })}
                  style={{ maxWidth: 320 }}
                />
                <Select
                  value={statusFilter}
                  onChange={setStatusFilter}
                  aria-label={t("admin.releasesFilter.status", { defaultValue: "Filter by status" })}
                  style={{ width: 180 }}
                  options={[
                    { value: "all", label: t("common.all", { defaultValue: "All" }) },
                    ...statuses.map((status) => ({
                      value: status,
                      label: t(`releaseStatus.${status}`, { defaultValue: status }),
                    })),
                  ]}
                />
                <Typography.Text type="secondary" className="text-xs">
                  {t("admin.releasesFilter.matching", {
                    defaultValue: "{{shown}} / {{total}} matching",
                    shown: formatNumber(filtered.length),
                    total: formatNumber(releases.length),
                  })}
                </Typography.Text>
              </div>
              {filtered.length === 0 ? (
                <div className="py-10 text-center" data-testid="releases-filtered-empty">
                  <Typography.Text type="secondary">
                    {t("admin.releasesFilter.empty", { defaultValue: "No releases match the current filters." })}
                  </Typography.Text>
                </div>
              ) : (
                <ProTable<ReleaseRow>
                  {...PRO_LIST_SHELL}
                  rowKey="id"
                  dataSource={filtered}
                  columns={columns}
                  pagination={{ pageSize: 10, showSizeChanger: true }}
                  scroll={{ x: 760 }}
                  onRow={() => ({ "data-testid": "release-row" } as React.HTMLAttributes<HTMLTableRowElement>)}
                />
              )}
            </div>
          </ProCard>
        </>
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
                { key: "status", label: t("releases.status"), children: <Tag color={statusTone(detail.status)}>{t(`releaseStatus.${detail.status}`, { defaultValue: detail.status })}</Tag> },
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