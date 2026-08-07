/**
 * Genes index route — server-side paginated gene list with filters.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Search, ArrowRight } from "lucide-react";
import { Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@soymutdb/ui";
import { searchGenes } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { FilterPanel } from "../../components/filter-panel";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES, formatPosition, compactGeneId } from "../../lib/format";

interface GeneRow {
  gene_id: string;
  symbol: string | null;
  name: string | null;
  biotype: string;
  chromosome: string;
  start_pos: number;
  end_pos: number;
  variant_count?: number;
  high_impact_variants?: number;
}

export const Route = createFileRoute("/genes/")({
  component: GenesComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    q: String(search.q ?? ""),
    chromosome: String(search.chromosome ?? ""),
    biotype: String(search.biotype ?? ""),
    page: Number(search.page ?? 1),
    sort_by: String(search.sort_by ?? "gene_id"),
    sort_dir: (search.sort_dir as "asc" | "desc") ?? "asc",
  }),
});

const BIOTYPES = ["protein_coding", "pseudogene", "tRNA", "rRNA", "miRNA", "lncRNA", "transposable_element"];

function GenesComponent() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const navigate = useNavigate();
  const [q, setQ] = React.useState(search.q);

  React.useEffect(() => setQ(search.q), [search.q]);

  const query = useQuery({
    queryKey: ["genes", search],
    queryFn: () =>
      searchGenes({
        q: search.q || undefined,
        chromosome: search.chromosome || undefined,
        biotype: search.biotype || undefined,
        page: search.page,
        page_size: 20,
        sort_by: search.sort_by,
        sort_dir: search.sort_dir,
      }),
    placeholderData: (prev) => prev,
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const totalPages = query.data?.total_pages ?? 1;

  const columns: DataTableColumn<GeneRow>[] = [
    {
      id: "gene_id",
      header: t("genes.geneId"),
      sortKey: "gene_id",
      frozen: true,
      cell: (row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          className="link-underline font-mono text-sm font-medium text-primary"
        >
          {compactGeneId(row.gene_id, 18)}
        </Link>
      ),
    },
    { id: "symbol", header: t("genes.symbol"), sortKey: "symbol", cell: (row) => row.symbol ?? "—" },
    { id: "biotype", header: t("genes.biotypeLabel"), cell: (row) => <span className="font-mono text-xs">{row.biotype}</span> },
    { id: "chromosome", header: t("genes.chromosomeLabel"), cell: (row) => <span className="font-mono text-xs">{row.chromosome}</span> },
    {
      id: "position",
      header: t("genes.position"),
      cell: (row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {formatPosition(row.start_pos)}–{formatPosition(row.end_pos)}
        </span>
      ),
    },
    { id: "variant_count", header: t("genes.variantCount"), sortKey: "variant_count", numeric: true, cell: (row) => row.variant_count?.toLocaleString() ?? "—" },
    {
      id: "actions",
      header: "",
      width: "48px",
      cell: (row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label={`View ${row.gene_id}`}
        >
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      ),
    },
  ];

  const activeFilters = [search.chromosome, search.biotype].filter(Boolean).length;

  return (
    <div className="container-prose section-rhythm">
      <FadeUp>
        <p className="eyebrow">{t("genes.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">{t("genes.subtitle")}</h1>
      </FadeUp>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          navigate({ to: "/genes", search: { ...search, q: q.trim(), page: 1 } });
        }}
        className="mt-10"
        role="search"
      >
        <div className="group relative">
          <Search className="pointer-events-none absolute left-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground transition-colors group-focus-within:text-primary" aria-hidden />
          <Input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={t("genes.searchPlaceholder")}
            aria-label={t("genes.search")}
            className="h-12 rounded-xl bg-card pl-12 shadow-sm transition-all hover:border-ring/40 focus-visible:shadow-[var(--shadow-glow)]"
          />
        </div>
      </form>

      <div className="mt-10 flex gap-6">
        <FilterPanel
          activeCount={activeFilters}
          onReset={() => navigate({ to: "/genes", search: { ...search, chromosome: "", biotype: "", page: 1 } })}
          groups={[
            {
              id: "chromosome",
              label: t("genes.chromosome"),
              children: (
                <Select
                  value={search.chromosome || "all"}
                  onValueChange={(v) =>
                    navigate({ to: "/genes", search: { ...search, chromosome: v === "all" ? "" : v, page: 1 } })
                  }
                >
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("genes.allChromosomes")}</SelectItem>
                    {SOYBEAN_CHROMOSOMES.map((c) => (
                      <SelectItem key={c} value={c}>{c}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ),
            },
            {
              id: "biotype",
              label: t("genes.biotype"),
              children: (
                <Select
                  value={search.biotype || "all"}
                  onValueChange={(v) =>
                    navigate({ to: "/genes", search: { ...search, biotype: v === "all" ? "" : v, page: 1 } })
                  }
                >
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("genes.allBiotype")}</SelectItem>
                    {BIOTYPES.map((b) => (
                      <SelectItem key={b} value={b}>{b}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ),
            },
          ]}
        />

        <div className="min-w-0 flex-1">
          <DataTable
            columns={columns}
            data={data}
            loading={query.isLoading}
            sort={{ key: search.sort_by, dir: search.sort_dir }}
            onSortChange={(s) =>
              navigate({
                to: "/genes",
                search: s ? { ...search, sort_by: s.key, sort_dir: s.dir, page: 1 } : { ...search, sort_by: "gene_id", sort_dir: "asc", page: 1 },
              })
            }
            emptyTitle={t("genes.noResults")}
            emptyDescription={t("common.noResults")}
            pagination={{
              page: search.page,
              totalPages,
              total,
              pageSize: 20,
              onPageChange: (page) => navigate({ to: "/genes", search: { ...search, page } }),
            }}
            ariaLabel="Gene search results"
          />
        </div>
      </div>
    </div>
  );
}
