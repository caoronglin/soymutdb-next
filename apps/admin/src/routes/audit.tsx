import { SnippetsOutlined, DownloadOutlined, FilterOutlined, GlobalOutlined, RiseOutlined, TeamOutlined, DesktopOutlined, FileTextOutlined } from "@ant-design/icons";
import { Badge, Button, Card, Input, Select, Table, Typography } from "@/lib/antd";
import { StatCard } from "../components/stat-card";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { http } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { formatNumber } from "../lib/format";

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

/** Escape a single CSV field per RFC 4180. */
function escapeCsvField(value: string): string {
  if (value.includes(",") || value.includes('"') || value.includes("\n")) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

/** Trigger a client-side file download from a string payload. */
function downloadBlob(content: string, filename: string, mimeType: string): void {
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
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [actionFilter, setActionFilter] = useState("all");
  const [ipFilter, setIpFilter] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [period, setPeriod] = useState<StatsPeriod>("week");
  const [exporting, setExporting] = useState(false);

  const { data, isLoading } = useQuery<{ items: AuditLog[]; total: number }>({
    queryKey: ["admin-audit", page, search, actionFilter, ipFilter, startDate, endDate],
    queryFn: () =>
      http.get("/admin/audit-logs", {
        params: {
          page,
          page_size: 50,
          search,
          action: actionFilter !== "all" ? actionFilter : undefined,
          ip: ipFilter || undefined,
          start_date: startDate || undefined,
          end_date: endDate || undefined,
        },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const { data: stats, isLoading: statsLoading } = useQuery<AuditStats>({
    queryKey: ["admin-audit-stats", period],
    queryFn: () =>
      http.get<AuditStats>("/admin/audit-logs/stats", { params: { period } }),
  });

  const logs = data?.items ?? [];

  // Active users derived from unique actors in the loaded view.
  const activeUsers = useMemo(
    () => new Set(logs.map((l) => l.actor)).size,
    [logs],
  );

  // Top IPs by access count, capped at 10 for the distribution panel.
  const topIps = useMemo(
    () =>
      [...(stats?.ipDistribution ?? [])]
        .sort((a, b) => b.count - a.count)
        .slice(0, 10),
    [stats?.ipDistribution],
  );

  const handleExportCsv = async () => {
    setExporting(true);
    try {
      // Fetch the full filtered list and convert to CSV client-side.
      const res = await http.get<{ items: AuditLog[]; total: number }>(
        "/admin/audit-logs",
        {
          params: {
            page: 1,
            page_size: 10000,
            search,
            action: actionFilter !== "all" ? actionFilter : undefined,
            ip: ipFilter || undefined,
            start_date: startDate || undefined,
            end_date: endDate || undefined,
          },
        },
      );
      const rows = res?.items ?? [];
      const headers = [
        "timestamp",
        "actor",
        "action",
        "resource",
        "resourceId",
        "ipAddress",
        "status",
        "details",
      ];
      const lines = [headers.join(",")];
      for (const l of rows) {
        lines.push(
          [
            l.timestamp,
            l.actor,
            l.action,
            l.resource,
            l.resourceId,
            l.ipAddress,
            l.status,
            l.details ?? "",
          ]
            .map((v) => escapeCsvField(String(v)))
            .join(","),
        );
      }
      downloadBlob(lines.join("\n"), "audit-logs.csv", "text/csv");
    } finally {
      setExporting(false);
    }
  };

  const handleExportPdf = () => {
    // Lightweight PDF export via the browser's print-to-PDF dialog.
    window.print();
  };

  const columns: DataTableColumn<AuditLog>[] = [
    {
      key: "timestamp",
      header: "Timestamp",
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
      header: "Actor",
      sortable: true,
      sortAccessor: (l) => l.actor,
      cell: (l) => <span className="text-sm font-medium">{l.actor}</span>,
    },
    {
      key: "action",
      header: "Action",
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
      header: "Resource",
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
      header: "IP Address",
      cell: (l) => (
        <span className="font-mono text-xs">{l.ipAddress}</span>
      ),
    },
    {
      key: "details",
      header: "Details",
      cell: (l) =>
        l.details ? (
          <span className="text-xs text-muted-foreground" title={l.details}>
            {l.details.length > 60 ? `${l.details.slice(0, 60)}…` : l.details}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4"><div><Typography.Title level={2}>Audit Logs</Typography.Title><Typography.Text type="secondary">Immutable record of all administrative actions. Filter and export for compliance.</Typography.Text></div><div className="flex gap-2"><Button onClick={handleExportCsv} disabled={exporting} icon={<DownloadOutlined />}>{exporting ? "Exporting…" : "Export CSV"}</Button><Button onClick={handleExportPdf} icon={<FileTextOutlined />}>Export PDF</Button></div></div>

      {/* Immutability notice */}
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm text-muted-foreground">
        <SnippetsOutlined className="size-4 shrink-0 text-primary" />
        <span>
          Audit logs are append-only and tamper-evident. Records cannot be modified or deleted.
        </span>
      </div>

      {/* Statistics summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Logins"
          value={formatNumber(stats?.totalLogins ?? 0)}
          icon={<SnippetsOutlined className="size-5" />}
        />
        <StatCard
          label="Total Actions"
          value={formatNumber(stats?.totalActions ?? 0)}
          icon={<RiseOutlined className="size-5" />}
        />
        <StatCard
          label="Unique IPs"
          value={formatNumber(stats?.uniqueIps ?? 0)}
          icon={<GlobalOutlined className="size-5" />}
        />
        <StatCard
          label="Active TeamOutlined"
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
              Top IP Addresses
            </Typography.Title>
            <Badge color="default">
              {stats?.ipDistribution?.length ?? 0} IPs
            </Badge>
          </div>
          <div>
            <Table>
              <thead>
                <tr className="bg-muted/40 hover:bg-muted/40">
                  <th>IP Address</th>
                  <th>City</th>
                  <th className="text-right">Access Count</th>
                </tr>
              </thead>
              <tbody>
                {statsLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <tr key={`ip-skeleton-${i}`}>
                      <td colSpan={3} className="py-3 text-xs text-muted-foreground">
                        Loading…
                      </td>
                    </tr>
                  ))
                ) : topIps.length === 0 ? (
                  <tr>
                    <td colSpan={3} className="py-6 text-center text-sm text-muted-foreground">
                      No IP distribution data for this period.
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
              Stats Period
            </Typography.Title>
          </div>
          <div>
            <p className="mb-3 text-sm text-muted-foreground">
              Control the aggregation window for the summary cards and IP distribution.
            </p>
            <Select value={period} onChange={(v) => setPeriod(v as StatsPeriod)}>


                <Select.Option value="day">Day</Select.Option>
                <Select.Option value="week">Week</Select.Option>
                <Select.Option value="month">Month</Select.Option>

            </Select>
          </div>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <FilterOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by actor, resource, or IP..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-72 pl-8"
          />
        </div>
        <Select value={actionFilter} onChange={setActionFilter}>


            <Select.Option value="all">All Actions</Select.Option>
            <Select.Option value="create">Create</Select.Option>
            <Select.Option value="update">Update</Select.Option>
            <Select.Option value="delete">Delete</Select.Option>
            <Select.Option value="login">Login</Select.Option>
            <Select.Option value="logout">Logout</Select.Option>
            <Select.Option value="export">Export</Select.Option>
            <Select.Option value="role_change">Role Change</Select.Option>

        </Select>
        <div className="relative">
          <GlobalOutlined className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="FilterOutlined by IP address..."
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
            aria-label="Start date"
          />
          <span className="text-xs text-muted-foreground">to</span>
          <Input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className="h-9 w-40"
            aria-label="End date"
          />
        </div>
        <Badge color="default">
          {(data?.total ?? 0).toLocaleString()} records
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
        emptyTitle="No audit records"
        emptyDescription="Audit log entries will appear here as actions are performed."
      />
    </div>
  );
}
