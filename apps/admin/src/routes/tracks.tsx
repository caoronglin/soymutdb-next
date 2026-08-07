import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Layers, Plus, RefreshCw, Globe, GlobeLock } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Button, Input, Badge, PageHeader } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { StatusBadge, type TaskStatus } from "../components/status-badge";
import { ConfirmDialog } from "../components/confirm-dialog";

interface TrackRow {
  id: string;
  name: string;
  type: string;
  category: string[];
  assembly: string;
  fileSize: number;
  status: TaskStatus;
  isPublic: boolean;
  updatedAt: string;
}

export default function TracksPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [toggleTarget, setToggleTarget] = useState<TrackRow | null>(null);

  const { data, isLoading } = useQuery<{ items: TrackRow[]; total: number }>({
    queryKey: ["admin-tracks", page, search],
    queryFn: () =>
      http.get("/admin/tracks", {
        params: { page, page_size: 20, search },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const toggleMutation = useMutation({
    mutationFn: async (params: { trackId: string; isPublic: boolean }) => {
      return http.patch(`/admin/tracks/${params.trackId}/visibility`, {
        json: { is_public: params.isPublic },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-tracks"] });
      setToggleTarget(null);
    },
  });

  const tracks = data?.items ?? [];

  const columns: DataTableColumn<TrackRow>[] = [
    {
      key: "name",
      header: "Track",
      sortable: true,
      sortAccessor: (t) => t.name,
      cell: (t) => (
        <div className="flex items-center gap-2">
          <Layers className="size-4 text-primary" />
          <div>
            <p className="font-medium">{t.name}</p>
            <p className="text-xs text-muted-foreground">{t.type}</p>
          </div>
        </div>
      ),
    },
    {
      key: "category",
      header: "Category",
      cell: (t) => (
        <div className="flex flex-wrap gap-1">
          {t.category.map((c) => (
            <Badge key={c} variant="secondary" className="text-xs">
              {c}
            </Badge>
          ))}
        </div>
      ),
    },
    {
      key: "assembly",
      header: "Assembly",
      sortable: true,
      sortAccessor: (t) => t.assembly,
      cell: (t) => <span className="text-sm">{t.assembly}</span>,
    },
    {
      key: "fileSize",
      header: "Size",
      sortable: true,
      sortAccessor: (t) => t.fileSize,
      cell: (t) => (
        <span className="font-mono text-sm">
          {(t.fileSize / 1024 / 1024).toFixed(1)} MB
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (t) => t.status,
      cell: (t) => <StatusBadge status={t.status} type="task" />,
    },
    {
      key: "isPublic",
      header: "Visibility",
      sortable: true,
      sortAccessor: (t) => (t.isPublic ? "1" : "0"),
      cell: (t) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setToggleTarget(t)}
          className="gap-1.5"
        >
          {t.isPublic ? (
            <>
              <Globe className="size-3.5 text-primary" />
              <span className="text-xs">Public</span>
            </>
          ) : (
            <>
              <GlobeLock className="size-3.5 text-muted-foreground" />
              <span className="text-xs">Private</span>
            </>
          )}
        </Button>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: () => (
        <Button variant="ghost" size="sm">
          <RefreshCw className="size-3.5" />
          Reindex
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Track Management"
        description="Manage JBrowse 2 genome browser tracks and data files."
        actions={
          <Button>
            <Plus className="size-4" />
            New Track
          </Button>
        }
      />

      <Input
        placeholder="Search tracks..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-xs"
      />

      <DataTable
        columns={columns}
        data={tracks}
        rowKey={(t) => t.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle="No tracks found"
        emptyDescription="Add a track to configure the genome browser."
      />

      {toggleTarget && (
        <ConfirmDialog
          open={Boolean(toggleTarget)}
          onOpenChange={(open) => !open && setToggleTarget(null)}
          title={toggleTarget.isPublic ? "Make Track Private" : "Make Track Public"}
          description={
            toggleTarget.isPublic
              ? `Making "${toggleTarget.name}" private will hide it from public users. Existing shared links to this track will stop working.`
              : `Making "${toggleTarget.name}" public will expose it to all users, including unauthenticated visitors. Ensure the data is ready for public release.`
          }
          confirmLabel={toggleTarget.isPublic ? "Make Private" : "Make Public"}
          severity={toggleTarget.isPublic ? "default" : "destructive"}
          onConfirm={() =>
            toggleMutation.mutate({
              trackId: toggleTarget.id,
              isPublic: !toggleTarget.isPublic,
            })
          }
          loading={toggleMutation.isPending}
        />
      )}
    </div>
  );
}
