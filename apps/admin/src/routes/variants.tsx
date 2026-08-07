import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { http } from "@soymutdb/api-client";
import { Button, Input, Badge, PageHeader } from "@soymutdb/ui";
import { DataTable, type DataTableColumn } from "../components/data-table";

interface AdminVariant {
  id: string;
  chromosome: string;
  position: number;
  ref: string;
  alt: string;
  variantType: string;
  impact: string | null;
  geneSymbol: string | null;
  mutantLineName: string;
  releaseName: string;
}

export default function VariantsPage() {
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [impactFilter, setImpactFilter] = useState("all");

  const { data, isLoading } = useQuery<{ items: AdminVariant[]; total: number }>({
    queryKey: ["admin-variants", page, search, impactFilter],
    queryFn: () =>
      http.get("/admin/variants", {
        params: {
          page,
          page_size: 20,
          search,
          impact: impactFilter !== "all" ? impactFilter : undefined,
        },
      }),
    placeholderData: { items: [], total: 0 },
  });

  const variants = data?.items ?? [];

  const impactVariant = (impact: string | null) => {
    if (!impact) return "outline" as const;
    switch (impact) {
      case "HIGH":
        return "destructive" as const;
      case "MODERATE":
        return "warning" as const;
      case "LOW":
        return "secondary" as const;
      default:
        return "outline" as const;
    }
  };

  const columns: DataTableColumn<AdminVariant>[] = [
    {
      key: "position",
      header: "Location",
      sortable: true,
      sortAccessor: (v) => `${v.chromosome}:${v.position}`,
      cell: (v) => (
        <span className="font-mono text-sm">
          {v.chromosome}:{v.position.toLocaleString()}
        </span>
      ),
    },
    {
      key: "change",
      header: "Change",
      cell: (v) => (
        <span className="font-mono text-sm">
          <span className="text-muted-foreground">{v.ref}</span>
          <span className="mx-1 text-muted-foreground">→</span>
          <span className="font-semibold">{v.alt}</span>
        </span>
      ),
    },
    {
      key: "variantType",
      header: "Type",
      sortable: true,
      sortAccessor: (v) => v.variantType,
      cell: (v) => <Badge variant="outline">{v.variantType}</Badge>,
    },
    {
      key: "impact",
      header: "Impact",
      sortable: true,
      sortAccessor: (v) => v.impact ?? "",
      cell: (v) =>
        v.impact ? (
          <Badge variant={impactVariant(v.impact)}>{v.impact}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      key: "geneSymbol",
      header: "Gene",
      sortable: true,
      sortAccessor: (v) => v.geneSymbol ?? "",
      cell: (v) => (
        <span className="font-mono text-sm">
          {v.geneSymbol ?? "—"}
        </span>
      ),
    },
    {
      key: "mutantLineName",
      header: "Mutant Line",
      cell: (v) => <span className="text-sm">{v.mutantLineName}</span>,
    },
    {
      key: "releaseName",
      header: "Release",
      cell: (v) => (
        <Badge variant="secondary">{v.releaseName}</Badge>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Variant Management"
        description="Browse and manage genomic variants across all releases."
        actions={
          <Button variant="outline">
            <Download className="size-4" />
            Export
          </Button>
        }
      />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <Input
          placeholder="Search by gene, position, or line..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-xs"
        />
        <div className="flex items-center gap-1">
          {["all", "HIGH", "MODERATE", "LOW", "MODIFIER"].map((imp) => (
            <Button
              key={imp}
              variant={impactFilter === imp ? "default" : "outline"}
              size="sm"
              onClick={() => setImpactFilter(imp)}
            >
              {imp === "all" ? "All" : imp}
            </Button>
          ))}
        </div>
        <Badge variant="secondary">
          {(data?.total ?? 0).toLocaleString()} total
        </Badge>
      </div>

      <DataTable
        columns={columns}
        data={variants}
        rowKey={(v) => v.id}
        loading={isLoading}
        page={page}
        pageSize={20}
        total={data?.total ?? 0}
        onPageChange={setPage}
        emptyTitle="No variants found"
        emptyDescription="Adjust your filters or import new variant data."
      />
    </div>
  );
}
