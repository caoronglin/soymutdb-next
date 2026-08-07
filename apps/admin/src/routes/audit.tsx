import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ScrollText,
  Download,
  Filter,
  Globe,
  Activity,
  Users,
  Monitor,
  FileText,
} from "lucide-react";
import { http } from "@soymutdb/api-client";
import {
  Button,
  Input,
  Badge,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { StatCard, formatNumber } from "@soymutdb/ui";

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
        <Badge variant={l.status === "success" ? "default" : "destructive"}>
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
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Audit Logs</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Immutable record of all administrative actions. Filter and export for compliance.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleExportCsv} disabled={exporting}>
            <Download className="size-4" />
            {exporting ? "Exporting…" : "Export CSV"}
          </Button>
          <Button variant="outline" onClick={handleExportPdf}>
            <FileText className="size-4" />
            Export PDF
          </Button>
        </div>
      </div>

      {/* Immutability notice */}
      <div className="flex items-center gap-2 rounded-lg border border-border bg-muted/30 px-4 py-2.5 text-sm text-muted-foreground">
        <ScrollText className="size-4 shrink-0 text-primary" />
        <span>
          Audit logs are append-only and tamper-evident. Records cannot be modified or deleted.
        </span>
      </div>

      {/* Statistics summary cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Total Logins"
          value={formatNumber(stats?.totalLogins ?? 0)}
          icon={<ScrollText className="size-5" />}
        />
        <StatCard
          label="Total Actions"
          value={formatNumber(stats?.totalActions ?? 0)}
          icon={<Activity className="size-5" />}
        />
        <StatCard
          label="Unique IPs"
          value={formatNumber(stats?.uniqueIps ?? 0)}
          icon={<Globe className="size-5" />}
        />
        <StatCard
          label="Active Users"
          value={typeof activeUsers === "number" ? formatNumber(activeUsers) : activeUsers}
          icon={<Users className="size-5" />}
        />
      </div>

      {/* IP distribution + period selector */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <CardTitle className="flex items-center gap-2 text-base">
              <Monitor className="size-4 text-primary" />
              Top IP Addresses
            </CardTitle>
            <Badge variant="secondary">
              {stats?.ipDistribution?.length ?? 0} IPs
            </Badge>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead>IP Address</TableHead>
                  <TableHead>City</TableHead>
                  <TableHead className="text-right">Access Count</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {statsLoading ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <TableRow key={`ip-skeleton-${i}`}>
                      <TableCell colSpan={3} className="py-3 text-xs text-muted-foreground">
                        Loading…
                      </TableCell>
                    </TableRow>
                  ))
                ) : topIps.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="py-6 text-center text-sm text-muted-foreground">
                      No IP distribution data for this period.
                    </TableCell>
                  </TableRow>
                ) : (
                  topIps.map((row) => (
                    <TableRow key={row.ip}>
                      <TableCell>
                        <span className="font-mono text-xs">{row.ip}</span>
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {row.city ?? "—"}
                      </TableCell>
                      <TableCell className="text-right">
                        <Badge variant="outline">{row.count.toLocaleString()}</Badge>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Period selector for stats */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Activity className="size-4 text-primary" />
              Stats Period
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-muted-foreground">
              Control the aggregation window for the summary cards and IP distribution.
            </p>
            <Select value={period} onValueChange={(v) => setPeriod(v as StatsPeriod)}>
              <SelectTrigger className="h-9 w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="day">Day</SelectItem>
                <SelectItem value="week">Week</SelectItem>
                <SelectItem value="month">Month</SelectItem>
              </SelectContent>
            </Select>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative">
          <Filter className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by actor, resource, or IP..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="h-9 w-72 pl-8"
          />
        </div>
        <Select value={actionFilter} onValueChange={setActionFilter}>
          <SelectTrigger className="h-9 w-44">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Actions</SelectItem>
            <SelectItem value="create">Create</SelectItem>
            <SelectItem value="update">Update</SelectItem>
            <SelectItem value="delete">Delete</SelectItem>
            <SelectItem value="login">Login</SelectItem>
            <SelectItem value="logout">Logout</SelectItem>
            <SelectItem value="export">Export</SelectItem>
            <SelectItem value="role_change">Role Change</SelectItem>
          </SelectContent>
        </Select>
        <div className="relative">
          <Globe className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Filter by IP address..."
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
        <Badge variant="secondary">
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
