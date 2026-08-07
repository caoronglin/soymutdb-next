import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Database, Server, Activity } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Badge, Card, CardContent, PageHeader, StatCard } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { StatusBadge, type TaskStatus } from "../components/status-badge";

interface BlastDatabase {
  id: string;
  name: string;
  type: "nucleotide" | "protein";
  description: string;
  sequenceCount: number;
  totalLength: number;
  isActive: boolean;
  lastUpdated: string;
}

interface BlastJobRow {
  id: string;
  user: string;
  program: string;
  database: string;
  status: TaskStatus;
  hitCount: number | null;
  duration: number | null;
  submittedAt: string;
}

export default function BlastPage() {
  const [tab, setTab] = useState<"databases" | "jobs">("databases");

  const { data: dbData, isLoading: dbLoading } = useQuery<{ items: BlastDatabase[]; total: number }>({
    queryKey: ["admin-blast-databases"],
    queryFn: () => http.get("/admin/blast/databases"),
    placeholderData: { items: [], total: 0 },
  });

  const { data: jobData, isLoading: jobLoading } = useQuery<{ items: BlastJobRow[]; total: number }>({
    queryKey: ["admin-blast-jobs"],
    queryFn: () => http.get("/admin/blast/jobs", { params: { page_size: 20 } }),
    placeholderData: { items: [], total: 0 },
  });

  const dbColumns: DataTableColumn<BlastDatabase>[] = [
    {
      key: "name",
      header: "Database",
      sortable: true,
      sortAccessor: (d) => d.name,
      cell: (d) => (
        <div className="flex items-center gap-2">
          <Database className="size-4 text-primary" />
          <div>
            <p className="font-medium">{d.name}</p>
            <p className="text-xs text-muted-foreground">{d.description}</p>
          </div>
        </div>
      ),
    },
    {
      key: "type",
      header: "Type",
      sortable: true,
      sortAccessor: (d) => d.type,
      cell: (d) => (
        <Badge variant={d.type === "protein" ? "default" : "secondary"}>
          {d.type}
        </Badge>
      ),
    },
    {
      key: "sequenceCount",
      header: "Sequences",
      sortable: true,
      sortAccessor: (d) => d.sequenceCount,
      cell: (d) => (
        <span className="font-mono text-sm">{d.sequenceCount.toLocaleString()}</span>
      ),
    },
    {
      key: "totalLength",
      header: "Total Length",
      sortable: true,
      sortAccessor: (d) => d.totalLength,
      cell: (d) => (
        <span className="font-mono text-sm">{d.totalLength.toLocaleString()}</span>
      ),
    },
    {
      key: "isActive",
      header: "Status",
      cell: (d) => (
        <Badge variant={d.isActive ? "success" : "secondary"}>
          {d.isActive ? "Active" : "Inactive"}
        </Badge>
      ),
    },
    {
      key: "lastUpdated",
      header: "Updated",
      sortable: true,
      sortAccessor: (d) => d.lastUpdated,
      cell: (d) => (
        <span className="text-sm text-muted-foreground">{d.lastUpdated}</span>
      ),
    },
  ];

  const jobColumns: DataTableColumn<BlastJobRow>[] = [
    {
      key: "user",
      header: "User",
      sortable: true,
      sortAccessor: (j) => j.user,
      cell: (j) => <span className="text-sm">{j.user}</span>,
    },
    {
      key: "program",
      header: "Program",
      sortable: true,
      sortAccessor: (j) => j.program,
      cell: (j) => <Badge variant="outline">{j.program}</Badge>,
    },
    {
      key: "database",
      header: "Database",
      cell: (j) => <span className="text-sm">{j.database}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (j) => j.status,
      cell: (j) => <StatusBadge status={j.status} type="task" />,
    },
    {
      key: "hitCount",
      header: "Hits",
      cell: (j) => (
        <span className="font-mono text-sm">
          {j.hitCount?.toLocaleString() ?? "—"}
        </span>
      ),
    },
    {
      key: "duration",
      header: "Duration",
      cell: (j) => (
        <span className="font-mono text-sm">
          {j.duration ? `${j.duration}s` : "—"}
        </span>
      ),
    },
    {
      key: "submittedAt",
      header: "Submitted",
      sortable: true,
      sortAccessor: (j) => j.submittedAt,
      cell: (j) => (
        <span className="text-sm text-muted-foreground">{j.submittedAt}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="BLAST Management"
        description="Manage BLAST databases and monitor search jobs."
      />

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Databases", value: dbData?.total ?? 0, icon: Database },
          { label: "Active Jobs", value: jobData?.items.filter((j) => j.status === "running").length ?? 0, icon: Activity },
          { label: "Total Jobs", value: jobData?.total ?? 0, icon: Search },
          { label: "Avg Duration", value: "—", icon: Server },
        ].map((s) => (
          <StatCard key={s.label} label={s.label} value={s.value} icon={<s.icon className="size-5" />} />
        ))}
      </div>

      {/* Tab switcher */}
      <div className="flex items-center gap-1 border-b border-border">
        {(["databases", "jobs"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "databases" ? "Databases" : "Jobs"}
          </button>
        ))}
      </div>

      {tab === "databases" ? (
        <DataTable
          columns={dbColumns}
          data={dbData?.items ?? []}
          rowKey={(d) => d.id}
          loading={dbLoading}
          emptyTitle="No BLAST databases"
          emptyDescription="Create a database to enable BLAST searches."
        />
      ) : (
        <DataTable
          columns={jobColumns}
          data={jobData?.items ?? []}
          rowKey={(j) => j.id}
          loading={jobLoading}
          emptyTitle="No BLAST jobs"
          emptyDescription="Submitted BLAST jobs will appear here."
        />
      )}
    </div>
  );
}
