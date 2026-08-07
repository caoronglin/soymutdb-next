/**
 * Variants index route — advanced filter + cursor-based pagination.
 */
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Download } from "lucide-react";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem, Button, Badge, PageHeader, FilterBar } from "@soymutdb/ui";
import { searchVariants } from "@soymutdb/api-client";
import { DataTable, type DataTableColumn } from "../../components/data-table";
import { FadeUp } from "../../components/route-motion";
import { SOYBEAN_CHROMOSOMES, formatPosition } from "../../lib/format";

interface VariantRow {
  variant_id: string;
  chromosome: string;
  position: number;
  ref_allele: string;
  alt_allele: string;
  variant_type: string;
  impact?: string;
  gene_id?: string;
  gene_symbol?: string;
  consequence?: string;
}

export const Route = createFileRoute("/variants/")({
  component: VariantsComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    chromosome: String(search.chromosome ?? ""),
    variant_type: String(search.variant_type ?? ""),
    impact: String(search.impact ?? ""),
    page: Number(search.page ?? 1),
    sort_by: String(search.sort_by ?? "position"),
    sort_dir: (search.sort_dir as "asc" | "desc") ?? "asc",
  }),
});

const VARIANT_TYPES = ["SNP", "INS", "DEL", "MNV", "SV"];
const IMPACTS = ["HIGH", "MODERATE", "LOW", "MODIFIER"];

function VariantsComponent() {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const navigate = useNavigate();

  const query = useQuery({
    queryKey: ["variants", search],
    queryFn: () =>
      searchVariants({
        chromosome: search.chromosome || undefined,
        variant_type: search.variant_type ? [search.variant_type] : undefined,
        impact: search.impact ? [search.impact] : undefined,
        page: search.page,
        page_size: 25,
        sort_by: search.sort_by,
        sort_dir: search.sort_dir,
      }),
    placeholderData: (prev) => prev,
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const totalPages = query.data?.total_pages ?? 1;

  const columns: DataTableColumn<VariantRow>[] = [
    {
      id: "variant_id",
      header: "Variant ID",
      frozen: true,
      cell: (row) => <span className="font-mono text-xs">{row.variant_id.slice(0, 12)}…</span>,
    },
    { id: "chromosome", header: t("variants.chromosomeLabel"), cell: (row) => <span className="font-mono text-xs">{row.chromosome}</span> },
    { id: "position", header: t("variants.positionLabel"), sortKey: "position", numeric: true, cell: (row) => <span className="font-mono text-xs">{formatPosition(row.position)}</span> },
    { id: "ref_alt", header: "Ref→Alt", cell: (row) => <span className="font-mono text-xs">{row.ref_allele}→{row.alt_allele}</span> },
    { id: "variant_type", header: t("variants.variantTypeLabel"), cell: (row) => <Badge variant="outline" className="font-mono text-[10px]">{row.variant_type}</Badge> },
    {
      id: "impact",
      header: t("variants.impactLabel"),
      cell: (row) => row.impact ? <ImpactBadge impact={row.impact} /> : <span className="text-muted-foreground">—</span>,
    },
    { id: "gene_symbol", header: t("variants.geneSymbol"), cell: (row) => row.gene_symbol ? <span className="font-mono text-xs">{row.gene_symbol}</span> : <span className="text-muted-foreground">—</span> },
  ];

  const activeFilters = [search.chromosome, search.variant_type, search.impact].filter(Boolean).length;

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <PageHeader
          title={t("variants.title")}
          description={t("variants.subtitle")}
          breadcrumb={[{ label: t("nav.home"), href: "/" }, { label: t("variants.title") }]}
          actions={
            <Button variant="outline" size="sm">
              <Download className="size-4" aria-hidden />
              {t("variants.export")}
            </Button>
          }
        />

        <FilterBar
          className="mt-8"
          columns={3}
          active={activeFilters > 0}
          onClearAll={() => navigate({ to: "/variants", search: { chromosome: "", variant_type: "", impact: "", page: 1, sort_by: "position", sort_dir: "asc" } })}
          items={[
            {
              key: "chromosome",
              label: t("variants.chromosome"),
              active: search.chromosome.length > 0,
              control: (
                <Select
                  value={search.chromosome || "all"}
                  onValueChange={(v) => navigate({ to: "/variants", search: { ...search, chromosome: v === "all" ? "" : v, page: 1 } })}
                >
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("variants.allChromosomes")}</SelectItem>
                    {SOYBEAN_CHROMOSOMES.map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}
                  </SelectContent>
                </Select>
              ),
            },
            {
              key: "variant_type",
              label: t("variants.variantType"),
              active: search.variant_type.length > 0,
              control: (
                <Select
                  value={search.variant_type || "all"}
                  onValueChange={(v) => navigate({ to: "/variants", search: { ...search, variant_type: v === "all" ? "" : v, page: 1 } })}
                >
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("variants.allTypes")}</SelectItem>
                    {VARIANT_TYPES.map((v) => <SelectItem key={v} value={v}>{v}</SelectItem>)}
                  </SelectContent>
                </Select>
              ),
            },
            {
              key: "impact",
              label: t("variants.impact"),
              active: search.impact.length > 0,
              control: (
                <Select
                  value={search.impact || "all"}
                  onValueChange={(v) => navigate({ to: "/variants", search: { ...search, impact: v === "all" ? "" : v, page: 1 } })}
                >
                  <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">{t("variants.allImpacts")}</SelectItem>
                    {IMPACTS.map((i) => <SelectItem key={i} value={i}>{i}</SelectItem>)}
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
                to: "/variants",
                search: s ? { ...search, sort_by: s.key, sort_dir: s.dir, page: 1 } : { ...search, sort_by: "position", sort_dir: "asc", page: 1 },
              })
            }
            emptyTitle={t("variants.noResults")}
            emptyDescription={t("common.noResults")}
            pagination={{
              page: search.page,
              totalPages,
              total,
              pageSize: 25,
              onPageChange: (page) => navigate({ to: "/variants", search: { ...search, page } }),
            }}
            ariaLabel="Variant search results"
          />
        </div>
      </div>
    </FadeUp>
  );
}

function ImpactBadge({ impact }: { impact: string }) {
  const tone = impact === "HIGH" ? "high" : impact === "MODERATE" ? "moderate" : impact === "LOW" ? "low" : "modifier";
  const color = `var(--impact-${tone})`;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs">
      <span className="size-2 rounded-full" style={{ backgroundColor: color }} aria-hidden />
      <span className="font-mono">{impact}</span>
    </span>
  );
}
