/**
 * Genes index route — server-side paginated gene list with filters.
 *
 * AntD 5 migration (A1): DataTable → Table, FilterBar → inline Form,
 * PageHeader → Typography. TanStack Query data flow and URL search state
 * (q / chromosome / biotype / page / sort_by / sort_dir) unchanged.
 */
import { createFileRoute, Link, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { useSiteContent } from "../../lib/site-content-react";
import * as React from "react";
import { ArrowRightOutlined as ArrowRight, ReloadOutlined } from "@ant-design/icons";
import {
  Button,
  Empty,
  Form,
  Input,
  Select,
  Table,
  Typography,
  type TableColumnsType,
  type TableProps,
} from "@/lib/antd";
import { getAssemblies, getReleaseId, searchGenes, type GeneSummary } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import { queryKeys } from "../../lib/query-keys";
import { SITE_VARIANT } from "../../lib/site-variant";
import { assemblyOptionLabel, resolveAssemblyParam } from "../../lib/assembly-selection";
import {
  SOYBEAN_CHROMOSOMES,
  formatPosition,
  compactGeneId,
  formatNumber,
} from "../../lib/format";

export const Route = createFileRoute("/genes/")({
  component: GenesComponent,
  validateSearch: (search: Record<string, unknown>) => ({
    assembly: String(search.assembly ?? ""),
    q: String(search.q ?? ""),
    chromosome: String(search.chromosome ?? ""),
    biotype: String(search.biotype ?? ""),
    page: Number(search.page ?? 1),
    sort_by: String(search.sort_by ?? "gene_id"),
    sort_dir: (search.sort_dir as "asc" | "desc") ?? "asc",
  }),
});

const BIOTYPES = ["protein_coding", "pseudogene", "tRNA", "rRNA", "miRNA", "lncRNA", "transposable_element"];
const PAGE_SIZE = 20;

interface SortState {
  sort_by: string;
  sort_dir: "asc" | "desc";
}

function GenesComponent() {
  const { t } = useTranslation();
  const { get } = useSiteContent();
  const search = Route.useSearch();
  const navigate = useNavigate();
  const [q, setQ] = React.useState(search.q);

  React.useEffect(() => setQ(search.q), [search.q]);

  const releaseId = getReleaseId();
  const assembliesQuery = useQuery({
    queryKey: ["assemblies", releaseId, SITE_VARIANT],
    queryFn: getAssemblies,
    staleTime: 30 * 60 * 1000,
  });
  const assemblies = assembliesQuery.data ?? [];
  const defaultAssembly = assemblies.find((assembly) => assembly.is_default);
  const assemblyResolution = search.assembly
    ? resolveAssemblyParam(assemblies, search.assembly)
    : defaultAssembly
      ? { status: "resolved" as const, assembly: defaultAssembly, via: "id" as const }
      : { status: "absent" as const };
  const selectedAssembly = assemblyResolution.status === "resolved" ? assemblyResolution.assembly : undefined;
  const assemblyId = selectedAssembly ? String(selectedAssembly.id) : "";

  const query = useQuery({
    queryKey: queryKeys.genes.search({
      q: search.q || undefined,
      assemblyId: assemblyId || undefined,
      chromosome: search.chromosome || undefined,
      biotype: search.biotype || undefined,
      page: search.page,
      pageSize: PAGE_SIZE,
      sortBy: search.sort_by,
      sortDir: search.sort_dir,
      releaseId,
      siteVariant: SITE_VARIANT,
    }),
    queryFn: () =>
      searchGenes({
        q: search.q || undefined,
        assembly_id: assemblyId || undefined,
        chromosome: search.chromosome || undefined,
        biotype: search.biotype || undefined,
        page: search.page,
        page_size: PAGE_SIZE,
        sort_by: search.sort_by,
        sort_dir: search.sort_dir,
      }),
    enabled: Boolean(assemblyId),
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  const currentSort: SortState = { sort_by: search.sort_by, sort_dir: search.sort_dir };

  const columns: TableColumnsType<GeneSummary> = [
    {
      title: get("genes.geneId", t("genes.geneId")),
      dataIndex: "gene_id",
      key: "gene_id",
      sorter: true,
      sortOrder:
        currentSort.sort_by === "gene_id"
          ? currentSort.sort_dir === "asc"
            ? "ascend"
            : "descend"
          : null,
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          search={{ assembly: row.assembly_id ? String(row.assembly_id) : undefined }}
          className="link-underline font-mono text-sm font-medium text-primary"
        >
          {compactGeneId(row.gene_id, 18)}
        </Link>
      ),
    },
    {
      title: get("genes.symbol", t("genes.symbol")),
      dataIndex: "symbol",
      key: "symbol",
      sorter: true,
      sortOrder:
        currentSort.sort_by === "symbol"
          ? currentSort.sort_dir === "asc"
            ? "ascend"
            : "descend"
          : null,
      render: (_, row) => row.symbol ?? "—",
    },
    {
      title: get("genes.biotypeLabel", t("genes.biotypeLabel")),
      dataIndex: "biotype",
      key: "biotype",
      render: (_, row) => <span className="font-mono text-xs">{row.biotype}</span>,
    },
    {
      title: get("genes.chromosomeLabel", t("genes.chromosomeLabel")),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: get("genes.position", t("genes.position")),
      dataIndex: "start_pos",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {formatPosition(row.start_pos)}–{formatPosition(row.end_pos)}
        </span>
      ),
    },
    {
      title: get("genes.variantCount", t("genes.variantCount")),
      dataIndex: "variant_count",
      key: "variant_count",
      sorter: true,
      sortOrder:
        currentSort.sort_by === "variant_count"
          ? currentSort.sort_dir === "asc"
            ? "ascend"
            : "descend"
          : null,
      align: "right",
      render: (_, row) => row.variant_count?.toLocaleString() ?? "—",
    },
    {
      title: "",
      key: "actions",
      width: 48,
      render: (_, row) => (
        <Link
          to="/genes/$geneId"
          params={{ geneId: row.gene_id }}
          search={{ assembly: row.assembly_id ? String(row.assembly_id) : undefined }}
          className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label={`View ${row.gene_id}`}
        >
          <ArrowRight className="size-4" aria-hidden />
        </Link>
      ),
    },
  ];

  const handleTableChange: TableProps<GeneSummary>["onChange"] = (
    _pagination,
    _filters,
    sorter,
  ) => {
    const s = Array.isArray(sorter) ? sorter[0] : sorter;
    const next: SortState | null =
      s && s.order
        ? { sort_by: String(s.field), sort_dir: s.order === "ascend" ? "asc" : "desc" }
        : null;
    // Pagination-triggered onChange reports the unchanged sort — ignore it.
    if (
      next
        ? next.sort_by === currentSort.sort_by && next.sort_dir === currentSort.sort_dir
        : currentSort.sort_by === "gene_id" && currentSort.sort_dir === "asc"
    ) {
      return;
    }
    navigate({
      to: "/genes",
      search: next
        ? { ...search, ...next, page: 1 }
        : { ...search, sort_by: "gene_id", sort_dir: "asc", page: 1 },
    });
  };

  const activeFilters = [search.q, search.chromosome, search.biotype].filter(Boolean).length;
  const reset = () => {
    setQ("");
    navigate({ to: "/genes", search: { ...search, q: "", chromosome: "", biotype: "", page: 1 } });
  };

  return (
    <FadeUp>
      <div className="container-prose py-10 md:py-14">
        <p className="eyebrow">{get("genes.title", t("genes.title"))}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {get("genes.subtitle", t("genes.subtitle"))}
        </h1>

        <Form
          layout="inline"
          className="mt-8 flex flex-wrap items-center gap-x-4 gap-y-4"
          onFinish={() => navigate({ to: "/genes", search: { ...search, q: q.trim(), page: 1 } })}
        >
          <Form.Item label={get("genes.assemblyLabel", t("genes.assemblyLabel"))} className="mb-0">
            <Select
              value={selectedAssembly ? String(selectedAssembly.id) : undefined}
              onChange={(value) => navigate({ to: "/genes", search: { ...search, assembly: value, page: 1 } })}
              loading={assembliesQuery.isLoading}
              disabled={assembliesQuery.isError}
              placeholder={t("search.genes.assemblyPlaceholder")}
              style={{ width: 190 }}
              options={assemblies.map((assembly) => ({
                value: String(assembly.id),
                label: assemblyOptionLabel(assembly),
              }))}
            />
          </Form.Item>
          <Form.Item label={get("genes.search", t("genes.search"))} className="mb-0">
            <Input.Search
              data-testid="genes-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={get("genes.searchPlaceholder", t("genes.searchPlaceholder"))}
              aria-label={get("genes.search", t("genes.search"))}
              allowClear
              enterButton={false}
              style={{ width: "min(360px, 80vw)" }}
            />
          </Form.Item>
          <Form.Item label={get("genes.chromosome", t("genes.chromosome"))} className="mb-0">
            <Select
              value={search.chromosome || "all"}
              onChange={(v) =>
                navigate({ to: "/genes", search: { ...search, chromosome: v === "all" ? "" : v, page: 1 } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: get("genes.allChromosomes", t("genes.allChromosomes")) },
                ...SOYBEAN_CHROMOSOMES.map((c) => ({ value: c, label: c })),
              ]}
            />
          </Form.Item>
          <Form.Item label={get("genes.biotype", t("genes.biotype"))} className="mb-0">
            <Select
              value={search.biotype || "all"}
              onChange={(v) =>
                navigate({ to: "/genes", search: { ...search, biotype: v === "all" ? "" : v, page: 1 } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: get("genes.allBiotype", t("genes.allBiotype")) },
                ...BIOTYPES.map((b) => ({ value: b, label: b })),
              ]}
            />
          </Form.Item>
          <Form.Item className="mb-0">
            <Button icon={<ReloadOutlined />} onClick={reset} disabled={activeFilters === 0}>
              {t("common.clear")}
            </Button>
          </Form.Item>
        </Form>

        {assemblyResolution.status === "unknown" || assemblyResolution.status === "ambiguous" ? (
          <Empty
            className="mt-6"
            data-testid="genes-unknown-assembly"
            description={
              assemblyResolution.status === "ambiguous"
                ? `Assembly name matches several versions: ${assemblyResolution.matches.map(assemblyOptionLabel).join(", ")}. Select a version.`
                : "The requested assembly is unavailable; no gene query was sent."
            }
          />
        ) : null}

        <div className="mt-4" role="region" aria-label="Gene search results">
          <Table<GeneSummary>
            rowKey="gene_id"
            columns={columns}
            dataSource={data}
            loading={query.isLoading}
            onChange={handleTableChange}
            pagination={{
              current: search.page,
              pageSize: PAGE_SIZE,
              total,
              showSizeChanger: false,
              showTotal: (n, range) =>
                `${formatNumber(range[0])}–${formatNumber(range[1])} of ${formatNumber(n)}`,
              onChange: (page) => navigate({ to: "/genes", search: { ...search, page } }),
            }}
            locale={{
              emptyText: (
                <Empty
                  description={
                    <Typography.Text type="secondary">
                      {get("genes.noResults", t("genes.noResults"))}
                      <br />
                      <span className="text-xs">{t("common.noResults")}</span>
                    </Typography.Text>
                  }
                />
              ),
            }}
          />
        </div>
      </div>
    </FadeUp>
  );
}
