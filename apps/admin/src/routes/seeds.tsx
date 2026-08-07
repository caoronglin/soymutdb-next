import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Sprout, Package, Truck, CheckCircle2, XCircle } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Button, Badge, Card, CardContent } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";

interface SeedRequest {
  id: string;
  user: string;
  email: string;
  institution: string;
  mutantLine: string;
  accession: string;
  quantity: number;
  status: "pending" | "under_review" | "approved" | "denied" | "preparing" | "shipped" | "delivered" | "cancelled";
  requestedAt: string;
  trackingNumber: string | null;
}

interface SeedStock {
  id: string;
  accession: string;
  mutantLine: string;
  quantityAvailable: number;
  availability: "available" | "limited" | "unavailable";
  lastInventoryDate: string;
}

export default function SeedsPage() {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"requests" | "inventory">("requests");
  const [actionTarget, setActionTarget] = useState<{
    request: SeedRequest;
    action: "approve" | "deny";
  } | null>(null);

  const { data: reqData, isLoading: reqLoading } = useQuery<{ items: SeedRequest[]; total: number }>({
    queryKey: ["admin-seed-requests"],
    queryFn: () => http.get("/admin/seeds/requests", { params: { page_size: 20 } }),
    placeholderData: { items: [], total: 0 },
  });

  const { data: stockData, isLoading: stockLoading } = useQuery<{ items: SeedStock[]; total: number }>({
    queryKey: ["admin-seed-stock"],
    queryFn: () => http.get("/admin/seeds/stock", { params: { page_size: 20 } }),
    placeholderData: { items: [], total: 0 },
  });

  const actionMutation = useMutation({
    mutationFn: async (params: { requestId: string; action: string }) => {
      return http.patch(`/admin/seeds/requests/${params.requestId}`, {
        json: { status: params.action },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-seed-requests"] });
      setActionTarget(null);
    },
  });

  const statusVariant = (status: SeedRequest["status"]) => {
    switch (status) {
      case "approved":
      case "delivered":
        return "success" as const;
      case "denied":
      case "cancelled":
        return "destructive" as const;
      case "shipped":
      case "preparing":
        return "default" as const;
      default:
        return "warning" as const;
    }
  };

  const reqColumns: DataTableColumn<SeedRequest>[] = [
    {
      key: "user",
      header: "Requester",
      sortable: true,
      sortAccessor: (r) => r.user,
      cell: (r) => (
        <div>
          <p className="font-medium">{r.user}</p>
          <p className="text-xs text-muted-foreground">{r.email}</p>
          <p className="text-xs text-muted-foreground">{r.institution}</p>
        </div>
      ),
    },
    {
      key: "accession",
      header: "Accession",
      sortable: true,
      sortAccessor: (r) => r.accession,
      cell: (r) => (
        <div>
          <p className="font-mono text-sm">{r.accession}</p>
          <p className="text-xs text-muted-foreground">{r.mutantLine}</p>
        </div>
      ),
    },
    {
      key: "quantity",
      header: "Qty",
      sortable: true,
      sortAccessor: (r) => r.quantity,
      cell: (r) => <span className="font-mono text-sm">{r.quantity}</span>,
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (r) => r.status,
      cell: (r) => <Badge variant={statusVariant(r.status)}>{r.status.replace("_", " ")}</Badge>,
    },
    {
      key: "requestedAt",
      header: "Requested",
      sortable: true,
      sortAccessor: (r) => r.requestedAt,
      cell: (r) => (
        <span className="text-sm text-muted-foreground">{r.requestedAt}</span>
      ),
    },
    {
      key: "trackingNumber",
      header: "Tracking",
      cell: (r) =>
        r.trackingNumber ? (
          <span className="font-mono text-xs">{r.trackingNumber}</span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (r) =>
        r.status === "pending" || r.status === "under_review" ? (
          <div className="flex items-center justify-end gap-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setActionTarget({ request: r, action: "approve" })}
            >
              <CheckCircle2 className="size-3.5" />
              Approve
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setActionTarget({ request: r, action: "deny" })}
            >
              <XCircle className="size-3.5" />
              Deny
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm">
            Details
          </Button>
        ),
    },
  ];

  const stockColumns: DataTableColumn<SeedStock>[] = [
    {
      key: "accession",
      header: "Accession",
      sortable: true,
      sortAccessor: (s) => s.accession,
      cell: (s) => <span className="font-mono text-sm">{s.accession}</span>,
    },
    {
      key: "mutantLine",
      header: "Mutant Line",
      sortable: true,
      sortAccessor: (s) => s.mutantLine,
      cell: (s) => <span className="text-sm">{s.mutantLine}</span>,
    },
    {
      key: "quantityAvailable",
      header: "Available",
      sortable: true,
      sortAccessor: (s) => s.quantityAvailable,
      cell: (s) => (
        <span className="font-mono text-sm">{s.quantityAvailable}</span>
      ),
    },
    {
      key: "availability",
      header: "Status",
      sortable: true,
      sortAccessor: (s) => s.availability,
      cell: (s) => (
        <Badge
          variant={
            s.availability === "available"
              ? "success"
              : s.availability === "limited"
                ? "warning"
                : "destructive"
          }
        >
          {s.availability}
        </Badge>
      ),
    },
    {
      key: "lastInventoryDate",
      header: "Last Inventory",
      cell: (s) => (
        <span className="text-sm text-muted-foreground">{s.lastInventoryDate}</span>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h2 className="font-serif text-2xl font-semibold">Seed Management</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage seed stock inventory and process germplasm requests.
        </p>
      </div>

      {/* Stats */}
      <div className="grid gap-4 sm:grid-cols-4">
        {[
          { label: "Pending Requests", value: reqData?.items.filter((r) => r.status === "pending").length ?? 0, icon: Package },
          { label: "Shipped", value: reqData?.items.filter((r) => r.status === "shipped").length ?? 0, icon: Truck },
          { label: "Total Stock", value: stockData?.total ?? 0, icon: Sprout },
          { label: "Low Stock", value: stockData?.items.filter((s) => s.availability === "limited").length ?? 0, icon: Package },
        ].map((s) => (
          <Card key={s.label}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                  {s.label}
                </p>
                <s.icon className="size-4 text-muted-foreground" />
              </div>
              <p className="mt-2 font-serif text-2xl font-semibold">{s.value}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 border-b border-border">
        {(["requests", "inventory"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`border-b-2 px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t === "requests" ? "Requests" : "Inventory"}
          </button>
        ))}
      </div>

      {tab === "requests" ? (
        <DataTable
          columns={reqColumns}
          data={reqData?.items ?? []}
          rowKey={(r) => r.id}
          loading={reqLoading}
          emptyTitle="No seed requests"
          emptyDescription="Pending seed requests will appear here."
        />
      ) : (
        <DataTable
          columns={stockColumns}
          data={stockData?.items ?? []}
          rowKey={(s) => s.id}
          loading={stockLoading}
          emptyTitle="No seed stock"
          emptyDescription="Add seed stock records to track inventory."
        />
      )}

      {actionTarget && (
        <ConfirmDialog
          open={Boolean(actionTarget)}
          onOpenChange={(open) => !open && setActionTarget(null)}
          title={actionTarget.action === "approve" ? "Approve Seed Request" : "Deny Seed Request"}
          description={
            actionTarget.action === "approve"
              ? `Approve the request from ${actionTarget.request.user} for ${actionTarget.request.quantity} seeds of ${actionTarget.request.accession}? An MTA will be generated.`
              : `Deny the seed request from ${actionTarget.request.user}? The requester will be notified by email.`
          }
          confirmLabel={actionTarget.action === "approve" ? "Approve" : "Deny"}
          severity={actionTarget.action === "approve" ? "default" : "destructive"}
          onConfirm={() =>
            actionMutation.mutate({
              requestId: actionTarget.request.id,
              action: actionTarget.action === "approve" ? "approved" : "denied",
            })
          }
          loading={actionMutation.isPending}
        />
      )}
    </div>
  );
}
