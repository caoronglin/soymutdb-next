import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Dna, Plus, FileText } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Button, Input, Badge, Card, CardContent, CardHeader, CardTitle } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";

interface Assembly {
  id: string;
  name: string;
  species: string;
  version: string;
  geneCount: number;
  chromosomeCount: number;
  totalLengthBp: number;
  isDefault: boolean;
  createdAt: string;
}

export default function AssembliesPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");

  const { data, isLoading } = useQuery<{ items: Assembly[]; total: number }>({
    queryKey: ["admin-assemblies", page, search],
    queryFn: () =>
      http.get("/admin/assemblies", {
        params: { page, page_size: 20, search },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const assemblies = data?.items ?? [];

  const columns: DataTableColumn<Assembly>[] = [
    {
      key: "name",
      header: "Assembly",
      sortable: true,
      sortAccessor: (a) => a.name,
      cell: (a) => (
        <div className="flex items-center gap-2">
          <Dna className="size-4 text-primary" />
          <div>
            <p className="font-medium">
              {a.name}
              {a.isDefault && (
                <Badge variant="success" className="ml-2">Default</Badge>
              )}
            </p>
            <p className="text-xs text-muted-foreground">
              {a.species} · v{a.version}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: "chromosomeCount",
      header: "Chromosomes",
      sortable: true,
      sortAccessor: (a) => a.chromosomeCount,
      cell: (a) => <span className="font-mono text-sm">{a.chromosomeCount}</span>,
    },
    {
      key: "geneCount",
      header: "Genes",
      sortable: true,
      sortAccessor: (a) => a.geneCount,
      cell: (a) => (
        <span className="font-mono text-sm">{a.geneCount.toLocaleString()}</span>
      ),
    },
    {
      key: "totalLengthBp",
      header: "Length (bp)",
      sortable: true,
      sortAccessor: (a) => a.totalLengthBp,
      cell: (a) => (
        <span className="font-mono text-sm">
          {a.totalLengthBp.toLocaleString()}
        </span>
      ),
    },
    {
      key: "createdAt",
      header: "Created",
      sortable: true,
      sortAccessor: (a) => a.createdAt,
      cell: (a) => (
        <span className="text-sm text-muted-foreground">{a.createdAt}</span>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: () => (
        <div className="flex items-center justify-end gap-1">
          <Button variant="ghost" size="sm">
            <FileText className="size-3.5" />
            Genes
          </Button>
          <Button variant="outline" size="sm">
            Edit
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-serif text-2xl font-semibold">Assemblies & Genes</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage reference genome assemblies and gene annotations.
          </p>
        </div>
        <Button>
          <Plus className="size-4" />
          New Assembly
        </Button>
      </div>

      {/* Summary cards */}
      <div className="grid gap-4 sm:grid-cols-3">
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Total Assemblies</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">{data?.total ?? 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Total Genes</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-serif text-2xl font-semibold">
              {assemblies.reduce((sum, a) => sum + a.geneCount, 0).toLocaleString()}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Total Length</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="font-mono text-2xl font-semibold">
              {(assemblies.reduce((sum, a) => sum + a.totalLengthBp, 0) / 1e9).toFixed(2)} Gb
            </p>
          </CardContent>
        </Card>
      </div>

      <Input
        placeholder="Search assemblies..."
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        className="max-w-xs"
      />

      <DataTable
        columns={columns}
        data={assemblies}
        rowKey={(a) => a.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle="No assemblies found"
        emptyDescription="Add a reference assembly to get started."
      />
    </div>
  );
}
