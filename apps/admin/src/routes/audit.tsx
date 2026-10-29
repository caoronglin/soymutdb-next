import { SnippetsOutlined, DownloadOutlined, FilterOutlined, GlobalOutlined, RiseOutlined, TeamOutlined, DesktopOutlined, FileTextOutlined, WarningOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Skeleton, App, Badge, Button, Input, PageContainer, ProCard, ProTable, Select, Typography, type ProColumns } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { PRO_LIST_SHELL } from "../components/pro-table-shell";
import { formatNumber } from "../lib/format";
import { buildAuditLogFilterParams } from "../lib/audit-params";

interface AuditLog {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  resource: string;
  resourceId: string;
  ipAddress: string;
  userAgent: string;
  status: "success" | "failure";
  /**
   * Structured audit metadata. The API sends a JSON object for actions that
   * carry structured context (`{ login_at, username }` for a login) and a plain
   * string for legacy rows, so both shapes have to be accepted here.
   */
  details: AuditDetails | null;
}

type AuditDetails = string | Record<string, unknown>;

/**
 * Render `details` as text.
 *
 * React refuses an object child outright (error #31, "Objects are not valid as
 * a React child"), which took the whole audit page down; and the previous
 * `details.length` / `details.slice` calls are string methods that a structured
 * value does not have. Flattening to a single line keeps the table compact and
 * the `title` tooltip still shows the full payload.
 */
function formatAuditDetails(details: AuditDetails | null): string {
  if (details === null || details === undefined) return "";
  if (typeof details === "string") return details;
  try {
    return JSON.stringify(details);
  } catch {
    // Cyclic or non-serialisable payloads must not break the page.
    return String(details);
  }
}

interface AuditStats {
  loginTrend: { date: string; count: number }[];
  actionDistribution: { action: string; count: number }[];
  ipDistribution: { ip: string; count: number; city: string | null }[];
  totalLogins: number;
  totalActions: number;
  uniqueIps: number;
}

type StatsPeriod = "day" | "week" | "month";

const EMPTY_AUDIT_LOGS: AuditLog[] = [];
const EMPTY_IP_DISTRIBUTION: AuditStats["ipDistribution"] = [];

/** Rows per page of the audit list; shared by the request and the pager. */
const AUDIT_PAGE_SIZE = 50;

/**
 * The raw filter values that scope an audit-log request.
 *
 * They are kept as one object (and not as five separate states) because a
 * filter change and the page reset that belongs to it have to be applied
 * together: the page number belongs to the filter scope it was counted for.
 */
interface AuditFilterScope {
  search: string;
  action: string;
  ipAddress: string;
  startDate: string;
  endDate: string;
}

const EMPTY_FILTER_SCOPE: AuditFilterScope = {
  search: "",
  action: "all",
  ipAddress: "",
  startDate: "",
  endDate: "",
};

/** The filter scope plus the page of that scope the operator is looking at. */
interface AuditQueryState {
  scope: AuditFilterScope;
  page: number;
}

/** Trigger a client-side file download from a server response. */
function downloadBlob(content: BlobPart, filename: string, mimeType: string): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export default function AuditPage() {
  const { t } = useTranslation();
  const { message } = App.useApp();
  const [queryState, setQueryState] = useState<AuditQueryState>({
    scope: EMPTY_FILTER_SCOPE,
    page: 1,
  });
  const { scope, page } = queryState;
  const [period, setPeriod] = useState<StatsPeriod>("week");
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  /**
   * Apply a filter change and restart the result set at page 1.
   *
   * The scope and the page are one state, so the new filter and the reset
   * page reach the query in the same update. An effect that reset the page
   * afterwards would first render (and request) the *previous* page with the
   * new filter — a request for a page the filtered result set may not have,
   * which is what makes the compliance screen claim "no audit records".
   */
  const updateScope = useCallback((patch: Partial<AuditFilterScope>) => {
    setQueryState((prev) => ({ scope: { ...prev.scope, ...patch }, page: 1 }));
  }, []);

  /** Move to another page of the current scope; the scope itself is unchanged. */
  const changePage = useCallback((nextPage: number) => {
    setQueryState((prev) =>
      prev.page === nextPage ? prev : { ...prev, page: nextPage },
    );
  }, []);

  const filterParams = useMemo(
    () =>
      buildAuditLogFilterParams({
        search: scope.search,
        action: scope.action,
        ipAddress: scope.ipAddress,
        startDate: scope.startDate,
        endDate: scope.endDate,
      }),
    [scope.search, scope.action, scope.ipAddress, scope.startDate, scope.endDate],
  );

  const { data, isLoading, isError: logsFailed, refetch: refetchLogs } = useQuery<{ items: AuditLog[]; total: number }>({
    queryKey: ["admin-audit", page, scope.search, scope.action, scope.ipAddress, scope.startDate, scope.endDate],
    queryFn: () =>
      http.get("/admin/audit-logs", {
        params: {
          page,
          page_size: AUDIT_PAGE_SIZE,
          ...filterParams,
        },
      }),
  });

  /**
   * A page that the filtered result set does not have must never be shown as
   * an empty log: the records exist, they are simply on another page. The
   * count comes from the server and is not adjusted here.
   */
  const total = data?.total ?? 0;
  const lastPage = Math.max(1, Math.ceil(total / AUDIT_PAGE_SIZE));
  const pageBeyondResult =
    data != null && data.total > 0 && data.items.length === 0 && page > lastPage;
  useEffect(() => {
    if (!pageBeyondResult) return;
    setQueryState((prev) =>
      prev.page === lastPage ? prev : { ...prev, page: lastPage },
    );
  }, [pageBeyondResult, lastPage]);

  const {
    data: stats,
    isLoading: statsLoading,
    isError: statsFailed,
    refetch: refetchStats,
  } = useQuery<AuditStats>({
    queryKey: ["admin-audit-stats", period],
    queryFn: () =>
      http.get<AuditStats>("/admin/audit-logs/stats", { params: { period } }),
  });

  const logs = data?.items ?? EMPTY_AUDIT_LOGS;
  const ipDistribution = stats?.ipDistribution ?? EMPTY_IP_DISTRIBUTION;

  // Active users derived from unique actors in the loaded view.
  const activeUsers = useMemo(
    () => new Set(logs.map((l) => l.actor)).size,
    [logs],
  );

  // Top IPs by access count, capped at 10 for the distribution panel.
  const topIps = useMemo(
    () =>
      [...ipDistribution]
        .sort((a, b) => b.count - a.count)
        .slice(0, 10),
    [ipDistribution],
  );

  /**
   * Columns for the IP distribution panel.
   *
   * This table used to be an antd `Table` fed hand-written `<thead>`/`<tbody>`
   * children. Its data, the top-10 cap and both of its messages are unchanged;
   * what moved is the loading presentation, which now comes from ProTable's own
   * `loading` state instead of five hand-drawn placeholder rows, and the header
   * styling, which ProTable owns. The empty state keeps the exact same string.
   */
  const ipColumns: ProColumns<AuditStats["ipDistribution"][number]>[] = [
    {
      title: t("admin.audit.ipAddress", { defaultValue: "IP Address" }),
      dataIndex: "ip",
      key: "ip",
      editable: false,
      render: (ip) => <span className="font-mono text-xs">{ip}</span>,
    },
    {
      title: t("admin.audit.city", { defaultValue: "City" }),
      dataIndex: "city",
      key: "city",
      editable: false,
      render: (_value, row) => <span className="text-sm text-muted-foreground">{row.city ?? "—"}</span>,
    },
    {
      title: t("admin.audit.accessCount", { defaultValue: "Access Count" }),
      dataIndex: "count",
      key: "count",
      align: "right",
      editable: false,
      render: (_value, row) => (
        <span className="inline-block">
          <Badge color="default">{row.count.toLocaleString()}</Badge>
        </span>
      ),
    },
  ];

  const handleExportCsv = async () => {
    setExporting(true);
    setExportError(null);
    try {
      // Let the API stream the complete result in bounded batches instead of
      // materialising an arbitrary 10,000-row JSON response in the browser.
      const blob = await http.download("/admin/audit-logs/export", {
        params: filterParams,
      });
      downloadBlob(blob, "audit-logs.csv", "text/csv");
    } catch (error) {
      // Without this the rejection escaped as an unhandled promise and the
      // operator only saw the button return to its idle state.
      const reason = error instanceof Error ? error.message : String(error);
      setExportError(reason);
      message.error(
        t("admin.audit.exportFailed", { defaultValue: "The CSV export failed." }),
      );
    } finally {
      setExporting(false);
    }
  };

  const handleExportPdf = () => {
    // Lightweight PDF export via the browser's print-to-PDF dialog.
    window.print();
  };

  const columns = useMemo<DataTableColumn<AuditLog>[]>(() => [
    {
      key: "timestamp",
      header: t("admin.audit.timestamp", { defaultValue: "Timestamp" }),
      sortable: true,
      sortAccessor: (l) => l.timestamp,
      cell: (l) => (
        <span className="font-mono text-xs text-muted-foreground">
          {l.timestamp}
        </span>
      ),
    },
    {
      key: "actor",
      header: t("admin.audit.actor", { defaultValue: "Actor" }),
      sortable: true,
      sortAccessor: (l) => l.actor,
      cell: (l) => <span className="text-sm font-medium">{l.actor}</span>,
    },
    {
      key: "action",
      header: t("admin.audit.action", { defaultValue: "Action" }),
      sortable: true,
      sortAccessor: (l) => l.action,
      cell: (l) => (
        <Badge color={l.status === "success" ? "default" : "destructive"}>
          {l.action}
        </Badge>
      ),
    },
    {
      key: "resource",
      header: t("admin.audit.resource", { defaultValue: "Resource" }),
      sortable: true,
      sortAccessor: (l) => l.resource,
      cell: (l) => (
        <div>
          <p className="text-sm">{l.resource}</p>
          <p className="font-mono text-xs text-muted-foreground">{l.resourceId}</p>
        </div>
      ),
    },
    {
      key: "ipAddress",
      header: t("admin.audit.ipAddress", { defaultValue: "IP Address" }),
      cell: (l) => (
        <span className="font-mono text-xs">{l.ipAddress}</span>
      ),
    },
    {
      key: "details",
      header: t("admin.audit.details", { defaultValue: "Details" }),
      cell: (l) => {
        const text = formatAuditDetails(l.details);
        return text ? (
          <span className="text-xs text-muted-foreground" title={text}>
            {text.length > 60 ? `${text.slice(0, 60)}…` : text}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        );
      },
    },
  ], [t]);

  return (
    <PageContainer
      title={t("admin.audit.title", { defaultValue: "Audit Logs" })}
      subTitle={t("admin.audit.subtitle", { defaultValue: "Immutable record of all administrative actions. Filter and export for compliance." })}
      extra={[
        <div key="export" className="flex gap-2"><Button onClick={handleExportCsv} disabled={exporting} icon={<DownloadOutlined />}>{exporting ? t("admin.audit.exporting", { defaultValue: "Exporting…" }) : t("admin.audit.exportCsv", { defaultValue: "Export CSV" })}</Button><Button onClick={handleExportPdf} icon={<FileTextOutlined />}>{t("admin.audit.exportPdf", { defaultValue: "Export PDF" })}</Button></div>,
      ]}
    >
      <div className="space-y-6">

        {/* Immutability notice */}
        <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm text-muted-foreground">
          <SnippetsOutlined className="size-4 shrink-0 text-primary" />
          <span>
            {t("admin.audit.appendOnlyNote", { defaultValue: "Audit logs are append-only and tamper-evident. Records cannot be modified or deleted." })}
          </span>
        </div>

        {/* Statistics summary cards. A failed statistics request must not be
            rendered as a set of zeros: "0 logins" reads as a fact about the
            deployment, so an unknown value is shown as a dash instead. */}
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            label={t("admin.audit.totalLogins", { defaultValue: "Total Logins" })}
            value={statsFailed || !stats ? "—" : formatNumber(stats?.totalLogins ?? 0)}
            icon={<SnippetsOutlined className="size-5" />}
          />
          <StatCard
            label={t("admin.audit.totalActions", { defaultValue: "Total Actions" })}
            value={statsFailed || !stats ? "—" : formatNumber(stats?.totalActions ?? 0)}
            icon={<RiseOutlined className="size-5" />}
          />
          <StatCard
            label={t("admin.audit.uniqueIps", { defaultValue: "Unique IPs" })}
            value={statsFailed || !stats ? "—" : formatNumber(stats?.uniqueIps ?? 0)}
            icon={<GlobalOutlined className="size-5" />}
          />
          <StatCard
            label={t("admin.audit.activeUsers", { defaultValue: "Active Users" })}
            value={logsFailed || !data ? "—" : formatNumber(activeUsers)}
            icon={<TeamOutlined className="size-5" />}
          />
        </div>

        {statsFailed ? (
          <div
            role="alert"
            data-testid="audit-stats-error"
            className="flex items-center gap-2 rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <WarningOutlined className="size-4" />
            <span className="flex-1">
              {t("admin.audit.statsLoadError", { defaultValue: "Audit statistics could not be loaded." })}
            </span>
            <Button size="small" onClick={() => void refetchStats()}>
              {t("common.retry", { defaultValue: "Retry" })}
            </Button>
          </div>
        ) : null}

        {/* IP distribution + period selector */}
        <div className="grid gap-4 lg:grid-cols-3">
          <ProCard className="lg:col-span-2">
            <div className="flex-row items-center justify-between space-y-0">
              <Typography.Title level={5} className="flex items-center gap-2 text-base">
                <DesktopOutlined className="size-4 text-primary" />
                {t("admin.audit.topIpsTitle", { defaultValue: "Top IP Addresses" })}
              </Typography.Title>
              <Badge color="default">
                {t("admin.audit.topIpsCount", { count: stats?.ipDistribution?.length ?? 0, defaultValue: "{{count}} IPs" })}
              </Badge>
            </div>
            <div>
              {statsFailed ? (
                <p
                  role="alert"
                  data-testid="audit-ip-distribution-error"
                  className="text-sm text-destructive"
                >
                  {t("admin.audit.statsLoadError", { defaultValue: "Audit statistics could not be loaded." })}
                </p>
              ) : statsLoading ? <Skeleton active /> : (
                <ProTable<AuditStats["ipDistribution"][number]>
                  {...PRO_LIST_SHELL}
                  rowKey="ip"
                  size="small"
                  columns={ipColumns}
                  dataSource={topIps}
                  loading={statsLoading}
                  pagination={false}
                  locale={{
                    emptyText: t("admin.audit.noIpData", { defaultValue: "No IP distribution data for this period." }),
                  }}
                />
              )}
            </div>
          </ProCard>

          {/* Period selector for stats */}
          <ProCard>
            <div>
              <Typography.Title level={5} className="flex items-center gap-2 text-base">
                <RiseOutlined className="size-4 text-primary" />
                {t("admin.audit.statsPeriodTitle", { defaultValue: "Stats Period" })}
              </Typography.Title>
            </div>
            <div>
              <p className="mb-3 text-sm text-muted-foreground">
                {t("admin.audit.statsPeriodDesc", { defaultValue: "Control the aggregation window for the summary cards and IP distribution." })}
              </p>
              <Select
                value={period}
                onChange={(v) => setPeriod(v as StatsPeriod)}
                options={[
                  { value: "day", label: t("admin.audit.periodDay", { defaultValue: "Day" }) },
                  { value: "week", label: t("admin.audit.periodWeek", { defaultValue: "Week" }) },
                  { value: "month", label: t("admin.audit.periodMonth", { defaultValue: "Month" }) },
                ]}
              />
            </div>
          </ProCard>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="relative">
            <FilterOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={t("admin.audit.searchPlaceholder", { defaultValue: "Search by actor, resource, or IP..." })}
              value={scope.search}
              onChange={(e) => updateScope({ search: e.target.value })}
              className="h-9 w-72 pl-8"
            />
          </div>
          <Select
            value={scope.action}
            onChange={(v) => updateScope({ action: v })}
            options={[
              { value: "all", label: t("admin.audit.actionAll", { defaultValue: "All Actions" }) },
              { value: "create", label: t("admin.audit.actionCreate", { defaultValue: "Create" }) },
              { value: "update", label: t("admin.audit.actionUpdate", { defaultValue: "Update" }) },
              { value: "delete", label: t("admin.audit.actionDelete", { defaultValue: "Delete" }) },
              { value: "login", label: t("admin.audit.actionLogin", { defaultValue: "Login" }) },
              { value: "logout", label: t("admin.audit.actionLogout", { defaultValue: "Logout" }) },
              { value: "export", label: t("admin.audit.actionExport", { defaultValue: "Export" }) },
              { value: "role_change", label: t("admin.audit.actionRoleChange", { defaultValue: "Role Change" }) },
            ]}
          />
          <div className="relative">
            <GlobalOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder={t("admin.audit.ipFilterPlaceholder", { defaultValue: "Filter by IP address..." })}
              value={scope.ipAddress}
              onChange={(e) => updateScope({ ipAddress: e.target.value })}
              className="h-9 w-44 pl-8"
            />
          </div>
          <div className="flex items-center gap-1.5">
            <Input
              type="date"
              value={scope.startDate}
              onChange={(e) => updateScope({ startDate: e.target.value })}
              className="h-9 w-40"
              aria-label={t("admin.audit.startDateLabel", { defaultValue: "Start date" })}
            />
            <span className="text-xs text-muted-foreground">{t("admin.audit.dateRangeSeparator", { defaultValue: "to" })}</span>
            <Input
              type="date"
              value={scope.endDate}
              onChange={(e) => updateScope({ endDate: e.target.value })}
              className="h-9 w-40"
              aria-label={t("admin.audit.endDateLabel", { defaultValue: "End date" })}
            />
          </div>
          <Badge color="default">
            {logsFailed || !data
              ? "—"
              : t("admin.audit.recordsCount", { count: total, defaultValue: "{{count}} records" })}
          </Badge>
        </div>

        {exportError ? (
          <div
            role="alert"
            data-testid="audit-export-error"
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive"
          >
            <p>
              {t("admin.audit.exportFailed", { defaultValue: "The CSV export failed." })}
            </p>
            <p className="mt-1 text-xs">
              {t("common.errorReason", {
                reason: exportError,
                defaultValue: "Server response: {{reason}}",
              })}
            </p>
          </div>
        ) : null}

        {logsFailed ? (
          /* A failed request is not an empty log. The compliance screen must
             never claim that nothing happened because the transport failed. */
          <div
            role="alert"
            data-testid="audit-load-error"
            className="rounded-lg border border-destructive/40 bg-destructive/10 p-4 text-sm text-destructive"
          >
            <p className="font-medium">
              {t("admin.audit.loadError", { defaultValue: "The audit log could not be loaded." })}
            </p>
            <p className="mt-1">
              {t("admin.audit.loadErrorDesc", {
                defaultValue: "The request failed, so the records below are unknown rather than empty. Retry to load them.",
              })}
            </p>
            <Button className="mt-3" size="small" onClick={() => void refetchLogs()}>
              {t("common.retry", { defaultValue: "Retry" })}
            </Button>
          </div>
        ) : isLoading || pageBeyondResult ? <Skeleton active /> : (
          <DataTable
            columns={columns}
            data={logs}
            rowKey={(l) => l.id}
            loading={isLoading}
            page={page}
            pageSize={AUDIT_PAGE_SIZE}
            total={total}
            onPageChange={changePage}
            emptyTitle={t("admin.audit.emptyTitle", { defaultValue: "No audit records" })}
            emptyDescription={t("admin.audit.emptyDescription", { defaultValue: "Audit log entries will appear here as actions are performed." })}
          />
        )}
      </div>
    </PageContainer>
  );
}
