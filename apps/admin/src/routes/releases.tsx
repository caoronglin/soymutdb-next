import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, RotateCcw, CheckCircle2, Archive } from "lucide-react";
import { http, getReleases, type ReleaseSummary } from "@soymutdb/api-client";
import { Button, Card, CardContent, CardHeader, CardTitle, Input, Badge } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { StatusBadge, type ReleaseStatus, canTransition } from "../components/status-badge";
import { ConfirmDialog } from "../components/confirm-dialog";

interface ReleaseRow extends Omit<ReleaseSummary, "status"> {
  status: ReleaseStatus;
}

interface ConfirmAction {
  release: ReleaseRow;
  action: "activate" | "rollback" | "archive";
}

export default function ReleasesPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [confirmAction, setConfirmAction] = useState<ConfirmAction | null>(null);

  const { data: releases, isLoading } = useQuery({
    queryKey: ["admin-releases", page],
    queryFn: () => getReleases({ page, page_size: 20 }),
  });

  const transitionMutation = useMutation({
    mutationFn: async (params: { releaseId: string; action: string }) => {
      return http.post(`/admin/releases/${params.releaseId}/${params.action}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-releases"] });
      setConfirmAction(null);
    },
  });

  const rows: ReleaseRow[] = (releases ?? []).map((r) => ({
    ...r,
    status: (r.status === "active"
      ? "active"
      : r.status === "deprecated"
        ? "archived"
        : r.status === "pending"
          ? "draft"
          : "archived") as ReleaseStatus,
  }));

  const filteredRows = search
    ? rows.filter((r) =>
        r.name.toLowerCase().includes(search.toLowerCase()),
      )
    : rows;

  const handleConfirm = useCallback(() => {
    if (!confirmAction) return;
    transitionMutation.mutate({
      releaseId: confirmAction.release.id,
      action: confirmAction.action,
    });
  }, [confirmAction, transitionMutation]);

  const columns: DataTableColumn<ReleaseRow>[] = [
    {
      key: "name",
      header: "Release",
      sortable: true,
      sortAccessor: (r) => r.name,
      cell: (r) => (
        <div>
          <p className="font-medium">{r.name}</p>
          <p className="text-xs text-muted-foreground">{r.assembly_name}</p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (r) => r.status,
      cell: (r) => <StatusBadge status={r.status} type="release" />,
    },
    {
      key: "variant_count",
      header: "Variants",
      sortable: true,
      sortAccessor: (r) => r.variant_count,
      cell: (r) => (
        <span className="font-mono text-sm">
          {r.variant_count.toLocaleString()}
        </span>
      ),
    },
    {
      key: "gene_count",
      header: "Genes",
      sortable: true,
      sortAccessor: (r) => r.gene_count,
      cell: (r) => (
        <span className="font-mono text-sm">
          {r.gene_count.toLocaleString()}
        </span>
      ),
    },
    {
      key: "release_date",
      header: "Release Date",
      sortable: true,
      sortAccessor: (r) => r.release_date ?? "",
      cell: (r) => (
        <span className="text-sm text-muted-foreground">
          {r.release_date ?? "—"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (r) => (
        <div className="flex items-center justify-end gap-1">
          {canTransition(r.status, "active") && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmAction({ release: r, action: "activate" })}
            >
              <CheckCircle2 className="size-3.5" />
              Activate
            </Button>
          )}
          {r.status === "active" && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmAction({ release: r, action: "rollback" })}
            >
              <RotateCcw className="size-3.5" />
              Rollback
            </Button>
          )}
          {canTransition(r.status, "archived") && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setConfirmAction({ release: r, action: "archive" })}
            >
              <Archive className="size-3.5" />
              Archive
            </Button>
          )}
        </div>
      ),
    },
  ];

  const actionConfig: Record<
    ConfirmAction["action"],
    { title: string; description: string; label: string; severity: "destructive" | "critical"; phrase: string }
  > = {
    activate: {
      title: "Activate Release",
      description:
        "Activating this release will make it the current production release. All public queries will be served from this release. This action requires four-eyes approval.",
      label: "Activate Release",
      severity: "critical",
      phrase: "ACTIVATE",
    },
    rollback: {
      title: "Rollback Release",
      description:
        "Rolling back will revert to the previous active release. This is a high-risk operation that may affect data consistency. Requires four-eyes approval.",
      label: "Rollback Release",
      severity: "critical",
      phrase: "ROLLBACK",
    },
    archive: {
      title: "Archive Release",
      description:
        "Archiving this release will make it read-only and unavailable for new queries. Existing data is preserved. This action can be reversed by an administrator.",
      label: "Archive Release",
      severity: "destructive",
      phrase: "ARCHIVE",
    },
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Release Management</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage data releases through the lifecycle: Draft → Importing → Validating → Active → Archived.
          </p>
        </div>
        <Button>
          <Plus className="size-4" />
          New Release
        </Button>
      </div>

      {/* State machine diagram */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Release Lifecycle</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {(["draft", "importing", "validating", "active", "archived"] as ReleaseStatus[]).map(
              (status, i, arr) => (
                <div key={status} className="flex items-center gap-2">
                  <StatusBadge status={status} type="release" />
                  {i < arr.length - 1 && (
                    <span className="text-muted-foreground">→</span>
                  )}
                </div>
              ),
            )}
          </div>
        </CardContent>
      </Card>

      {/* Search */}
      <div className="flex items-center gap-3">
        <Input
          placeholder="Search releases..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Badge variant="secondary">
          {filteredRows.length} release{filteredRows.length === 1 ? "" : "s"}
        </Badge>
      </div>

      {/* Table */}
      <DataTable
        columns={columns}
        data={filteredRows}
        rowKey={(r) => r.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={filteredRows.length}
        onPageChange={setPage}
        emptyTitle="No releases found"
        emptyDescription="Create a new release to get started."
      />

      {/* Confirm dialog */}
      {confirmAction && (
        <ConfirmDialog
          open={Boolean(confirmAction)}
          onOpenChange={(open) => !open && setConfirmAction(null)}
          title={actionConfig[confirmAction.action].title}
          description={actionConfig[confirmAction.action].description}
          confirmLabel={actionConfig[confirmAction.action].label}
          severity={actionConfig[confirmAction.action].severity}
          confirmPhrase={actionConfig[confirmAction.action].phrase}
          onConfirm={handleConfirm}
          loading={transitionMutation.isPending}
        >
          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <p className="text-xs text-muted-foreground">Release</p>
            <p className="font-medium">{confirmAction.release.name}</p>
            <p className="mt-1 text-xs text-muted-foreground">
              {confirmAction.release.variant_count.toLocaleString()} variants ·{" "}
              {confirmAction.release.gene_count.toLocaleString()} genes
            </p>
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}
