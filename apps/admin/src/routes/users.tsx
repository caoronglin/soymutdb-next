import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { UserPlus, Shield, Building2, Eye } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Button, Input, Badge, Card, CardContent, CardHeader, CardTitle, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";
import { ConfirmDialog } from "../components/confirm-dialog";

/** 10-role permission system. Synchronized with backend ``RoleName`` enum.
 *
 * Level mapping (matches ``_ROLE_LEVEL`` in core/security.py):
 *   viewer=0, researcher=1, curator=2, data_manager=3, track_manager=3,
 *   blast_manager=3, seed_manager=3, content_editor=3, auditor=4, administrator=5
 */
export const ROLES = [
  { id: "viewer", label: "Viewer", level: 0 },
  { id: "researcher", label: "Researcher", level: 1 },
  { id: "curator", label: "Curator", level: 2 },
  { id: "data_manager", label: "Data Manager", level: 3 },
  { id: "track_manager", label: "Track Manager", level: 3 },
  { id: "blast_manager", label: "BLAST Manager", level: 3 },
  { id: "seed_manager", label: "Seed Manager", level: 3 },
  { id: "content_editor", label: "Content Editor", level: 3 },
  { id: "auditor", label: "Auditor", level: 4 },
  { id: "administrator", label: "Administrator", level: 5 },
] as const;

export type RoleId = (typeof ROLES)[number]["id"];

interface AdminUser {
  id: string;
  name: string;
  email: string;
  role: RoleId;
  organization: string;
  status: "active" | "suspended" | "pending";
  lastLogin: string | null;
  createdAt: string;
}

interface RoleChangeAction {
  user: AdminUser;
  newRole: RoleId;
}

export default function UsersPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [roleChange, setRoleChange] = useState<RoleChangeAction | null>(null);

  const { data, isLoading } = useQuery<{ items: AdminUser[]; total: number }>({
    queryKey: ["admin-users", page, search, roleFilter],
    queryFn: () =>
      http.get("/admin/users", {
        params: { page, page_size: 20, search, role: roleFilter !== "all" ? roleFilter : undefined },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const roleMutation = useMutation({
    mutationFn: async (params: { userId: string; role: RoleId }) => {
      return http.patch(`/admin/users/${params.userId}/role`, {
        json: { role: params.role },
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-users"] });
      setRoleChange(null);
    },
  });

  const handleRoleConfirm = useCallback(() => {
    if (!roleChange) return;
    roleMutation.mutate({ userId: roleChange.user.id, role: roleChange.newRole });
  }, [roleChange, roleMutation]);

  const users = data?.items ?? [];
  const filtered = users;

  const columns: DataTableColumn<AdminUser>[] = [
    {
      key: "name",
      header: "User",
      sortable: true,
      sortAccessor: (u) => u.name,
      cell: (u) => (
        <div>
          <p className="font-medium">{u.name}</p>
          <p className="text-xs text-muted-foreground">{u.email}</p>
        </div>
      ),
    },
    {
      key: "role",
      header: "Role",
      sortable: true,
      sortAccessor: (u) => u.role,
      cell: (u) => {
        const role = ROLES.find((r) => r.id === u.role);
        return (
          <Badge variant={role && role.level >= 7 ? "default" : "secondary"}>
            {role?.label ?? u.role}
          </Badge>
        );
      },
    },
    {
      key: "organization",
      header: "Organization",
      sortable: true,
      sortAccessor: (u) => u.organization,
      cell: (u) => (
        <span className="text-sm">{u.organization || "—"}</span>
      ),
    },
    {
      key: "status",
      header: "Status",
      sortable: true,
      sortAccessor: (u) => u.status,
      cell: (u) => (
        <Badge variant={u.status === "active" ? "success" : u.status === "pending" ? "warning" : "destructive"}>
          {u.status}
        </Badge>
      ),
    },
    {
      key: "lastLogin",
      header: "Last Login",
      cell: (u) => (
        <span className="text-sm text-muted-foreground">
          {u.lastLogin ?? "Never"}
        </span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (u) => (
        <Select
          value={u.role}
          onValueChange={(value) =>
            setRoleChange({ user: u, newRole: value as RoleId })
          }
        >
          <SelectTrigger className="h-8 w-36" aria-label={`Change role for ${u.name}`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ROLES.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {r.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Users & Roles</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            10-role permission system. Role escalations require four-eyes approval.
          </p>
        </div>
        <Button>
          <UserPlus className="size-4" />
          Invite User
        </Button>
      </div>

      {/* Role overview cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Shield className="size-4 text-primary" />
              Role System
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">{ROLES.length}</p>
            <p className="text-xs text-muted-foreground">permission levels</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Building2 className="size-4 text-primary" />
              Organizations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">—</p>
            <p className="text-xs text-muted-foreground">registered</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <Eye className="size-4 text-primary" />
              Pending Approvals
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">
              {filtered.filter((u) => u.status === "pending").length}
            </p>
            <p className="text-xs text-muted-foreground">awaiting review</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm">
              <UserPlus className="size-4 text-primary" />
              Total Users
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">{data?.total ?? 0}</p>
            <p className="text-xs text-muted-foreground">registered</p>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search users..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <Select value={roleFilter} onValueChange={setRoleFilter}>
          <SelectTrigger className="h-9 w-40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Roles</SelectItem>
            {ROLES.map((r) => (
              <SelectItem key={r.id} value={r.id}>
                {r.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <DataTable
        columns={columns}
        data={filtered}
        rowKey={(u) => u.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle="No users found"
        emptyDescription="Invite users to get started."
      />

      {/* Role change confirmation (four-eyes approval) */}
      {roleChange && (
        <ConfirmDialog
          open={Boolean(roleChange)}
          onOpenChange={(open) => !open && setRoleChange(null)}
          title="Confirm Role Change"
          description={`Changing ${roleChange.user.name}'s role to "${ROLES.find((r) => r.id === roleChange.newRole)?.label}". Role escalations require four-eyes approval from another administrator.`}
          confirmLabel="Submit for Approval"
          severity="critical"
          confirmPhrase="APPROVE"
          onConfirm={handleRoleConfirm}
          loading={roleMutation.isPending}
        >
          <div className="rounded-lg border border-border bg-muted/30 p-3">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Current role:</span>
              <Badge variant="secondary">
                {ROLES.find((r) => r.id === roleChange.user.role)?.label}
              </Badge>
            </div>
            <div className="mt-2 flex items-center justify-between text-sm">
              <span className="text-muted-foreground">New role:</span>
              <Badge variant="default">
                {ROLES.find((r) => r.id === roleChange.newRole)?.label}
              </Badge>
            </div>
          </div>
        </ConfirmDialog>
      )}
    </div>
  );
}
