import { SnippetsOutlined, DownloadOutlined, FilterOutlined, GlobalOutlined, RiseOutlined, TeamOutlined, DesktopOutlined, FileTextOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { Badge, Button, Card, Input, Select, Table, Typography } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../components/data-table";
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
  details: string | null;
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
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [ipFilter, setIpFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [period, setPeriod] = useState<StatsPeriod>("week");
  const [exporting, setExporting] = useState(false);
  const filterParams = useMemo(
    () =>
      buildAuditLogFilterParams({
        search,
        action: actionFilter,
        ipAddress: ipFilter,
        startDate,
        endDate,
      }),
    [search, actionFilter, ipFilter, startDate, endDate],
  );

  const { data, isLoading } = useQuery<{ items: AuditLog[]; total: number }>({
    queryKey: ["admin-audit", page, search, actionFilter, ipFilter, startDate, endDate],
    queryFn: () =>
      http.get("/admin/audit-logs", {
        params: {
          page,
          page_size: 50,
          ...filterParams,
        },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const { data: stats, isLoading: statsLoading } = useQuery<AuditStats>({
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

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      // Let the API stream the complete result in bounded batches instead of
      // materialising an arbitrary 10,000-row JSON response in the browser.
      const blob = await http.download("/admin/audit-logs/export", {
        params: filterParams,
      });
      downloadBlob(blob, "audit-logs.csv", "text/csv");
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
      cell: (l) =>
        l.details ? (
          <span className="text-xs text-muted-foreground" title={l.details}>
            {l.details.length > 60 ? `${l.details.slice(0, 60)}…` : l.details}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ], [t]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><Typography.Title level={2}>{t("admin.audit.title", { defaultValue: "Audit Logs" })}</Typography.Title><Typography.Text type="secondary">{t("admin.audit.subtitle", { defaultValue: "Immutable record of all administrative actions. Filter and export for compliance." })}</Typography.Text></div><div className="flex gap-2"><Button onClick={handleExportCsv} disabled={exporting} icon={<DownloadOutlined />}>{exporting ? t("admin.audit.exporting", { defaultValue: "Exporting…" }) : t("admin.audit.exportCsv", { defaultValue: "Export CSV" })}</Button><Button onClick={handleExportPdf} icon={<FileTextOutlined />}>{t("admin.audit.exportPdf", { defaultValue: "Export PDF" })}</Button></div></div>

      {/* Immutability notice */}
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm text-muted-foreground">
        <SnippetsOutlined className="size-4 shrink-0 text-primary" />
        <span>
          {t("admin.audit.appendOnlyNote", { defaultValue: "Audit logs are append-only and tamper-evident. Records cannot be modified or deleted." })}
        </span>
      </div>

      {/* Statistics summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label={t("admin.audit.totalLogins", { defaultValue: "Total Logins" })}
          value={formatNumber(stats?.totalLogins ?? 0)}
          icon={<SnippetsOutlined className="size-5" />}
        />
        <StatCard
          label={t("admin.audit.totalActions", { defaultValue: "Total Actions" })}
          value={formatNumber(stats?.totalActions ?? 0)}
          icon={<RiseOutlined className="size-5" />}
        />
        <StatCard
          label={t("admin.audit.uniqueIps", { defaultValue: "Unique IPs" })}
          value={formatNumber(stats?.uniqueIps ?? 0)}
          icon={<GlobalOutlined className="size-5" />}
        />
        <StatCard
          label={t("admin.audit.activeUsers", { defaultValue: "Active Users" })}
          value={typeof activeUsers === "number" ? formatNumber(activeUsers) : activeUsers}
          icon={<TeamOutlined className="size-5" />}
        />
      </div>

      {/* IP distribution + period selector */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
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
            <Table>
              <thead>
                <tr className="bg-muted/40 hover:bg-muted/40">
                  <th>{t("admin.audit.ipAddress", { defaultValue: "IP Address" })}</th>
                  <th>{t("admin.audit.city", { defaultValue: "City" })}</th>
                  <th className="text-right">{t("admin.audit.accessCount", { defaultValue: "Access Count" })}</th>
                </tr>
              </thead>
              <tbody>
                {statsLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={`ip-skeleton-${i}`}>
                      <td colSpan={3} className="py-3 text-xs text-muted-foreground">
                        {t("admin.audit.loading", { defaultValue: "Loading…" })}
                      </td>
                    </tr>
                  ))
                ) : topIps.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-6 text-center text-sm text-muted-foreground">
                      {t("admin.audit.noIpData", { defaultValue: "No IP distribution data for this period." })}
                    </td>
                  </tr>
                ) : (
                  topIps.map((row) => (
                    <tr key={row.ip}>
                      <td>
                        <span className="font-mono text-xs">{row.ip}</span>
                      </td>
                      <td className="text-sm text-muted-foreground">
                        {row.city ?? "—"}
                      </td>
                      <td className="text-right">
                        <Badge color="default">{row.count.toLocaleString()}</Badge>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </Table>
          </div>
        </Card>

        {/* Period selector for stats */}
        <Card>
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
            <Select value={period} onChange={(v) => setPeriod(v as StatsPeriod)}>


                <Select.Option value="day">{t("admin.audit.periodDay", { defaultValue: "Day" })}</Select.Option>
                <Select.Option value="week">{t("admin.audit.periodWeek", { defaultValue: "Week" })}</Select.Option>
                <Select.Option value="month">{t("admin.audit.periodMonth", { defaultValue: "Month" })}</Select.Option>

            </Select>
          </div>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <FilterOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("admin.audit.searchPlaceholder", { defaultValue: "Search by actor, resource, or IP..." })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-72 pl-8"
          />
        </div>
        <Select value={actionFilter} onChange={setActionFilter}>


            <Select.Option value="all">{t("admin.audit.actionAll", { defaultValue: "All Actions" })}</Select.Option>
            <Select.Option value="create">{t("admin.audit.actionCreate", { defaultValue: "Create" })}</Select.Option>
            <Select.Option value="update">{t("admin.audit.actionUpdate", { defaultValue: "Update" })}</Select.Option>
            <Select.Option value="delete">{t("admin.audit.actionDelete", { defaultValue: "Delete" })}</Select.Option>
            <Select.Option value="login">{t("admin.audit.actionLogin", { defaultValue: "Login" })}</Select.Option>
            <Select.Option value="logout">{t("admin.audit.actionLogout", { defaultValue: "Logout" })}</Select.Option>
            <Select.Option value="export">{t("admin.audit.actionExport", { defaultValue: "Export" })}</Select.Option>
            <Select.Option value="role_change">{t("admin.audit.actionRoleChange", { defaultValue: "Role Change" })}</Select.Option>

        </Select>
        <div className="relative">
          <GlobalOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder={t("admin.audit.ipFilterPlaceholder", { defaultValue: "Filter by IP address..." })}
            value={ipFilter}
            onChange={(e) => setIpFilter(e.target.value)}
            className="h-9 w-44 pl-8"
          />
        </div>
        <div className="flex items-center gap-1.5">
          <Input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className="h-9 w-40"
            aria-label={t("admin.audit.startDateLabel", { defaultValue: "Start date" })}
          />
          <span className="text-xs text-muted-foreground">{t("admin.audit.dateRangeSeparator", { defaultValue: "to" })}</span>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="h-9 w-40"
            aria-label={t("admin.audit.endDateLabel", { defaultValue: "End date" })}
          />
        </div>
        <Badge color="default">
          {t("admin.audit.recordsCount", { count: data?.total ?? 0, defaultValue: "{{count}} records" })}
        </Badge>
      </div>

      <DataTable
        columns={columns}
        data={logs}
        rowKey={(l) => l.id}
        loading={isLoading}
        page={page}
        pageSize={50}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle={t("admin.audit.emptyTitle", { defaultValue: "No audit records" })}
        emptyDescription={t("admin.audit.emptyDescription", { defaultValue: "Audit log entries will appear here as actions are performed." })}
      />
    </div>
  );
}
