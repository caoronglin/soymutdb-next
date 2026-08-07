/**
 * Genes index route — server-side paginated gene list with filters.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import * as React from "react";
import { Search, ArrowRight } from "lucide-react";
import { Input, Select, SelectTrigger, SelectValue, SelectContent, SelectItem, PageHeader, FilterBar } from "@soymutdb/ui";
import { searchGenes } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../../components/data-table";
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

  const activeFilters = [search.q, search.chromosome, search.biotype].filter(Boolean).length;
  const reset = () => {
    setQ("");
    navigate({ to: "/genes", search: { ...search, q: "", chromosome: "", biotype: "", page: 1 } });
  };

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <PageHeader
          title={t("genes.title")}
          description={t("genes.subtitle")}
          breadcrumb={[{ label: t("nav.home"), href: "/" }, { label: t("genes.title") }]}
        />

        <FilterBar
          className="mt-8"
          columns={3}
          active={activeFilters > 0}
          onClearAll={reset}
          items={[
            {
              key: "q",
              label: t("genes.search"),
              active: search.q.length > 0,
              control: (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    navigate({ to: "/genes", search: { ...search, q: q.trim(), page: 1 } });
                  }}
                  role="search"
                >
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
                    <Input
                      type="search"
                      value={q}
                      onChange={(e) => setQ(e.target.value)}
                      placeholder={t("genes.searchPlaceholder")}
                      aria-label={t("genes.search")}
                      className="h-9 pl-9"
                    />
                  </div>
                </form>
              ),
            },
            {
              key: "chromosome",
              label: t("genes.chromosome"),
              active: search.chromosome.length > 0,
              control: (
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
              key: "biotype",
              label: t("genes.biotype"),
              active: search.biotype.length > 0,
              control: (
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

        <div className="mt-4">
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
    </FadeUp>
  );
}
