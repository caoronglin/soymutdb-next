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
import { searchGenes, type GeneSummary } from "@soymutdb/api-client";
import { FadeUp } from "../../components/route-motion";
import {
  SOYBEAN_CHROMOSOMES,
  formatPosition,
  compactGeneId,
  formatNumber,
} from "../../lib/format";

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
const PAGE_SIZE = 20;

interface SortState {
  sort_by: string;
  sort_dir: "asc" | "desc";
}

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
        page_size: PAGE_SIZE,
        sort_by: search.sort_by,
        sort_dir: search.sort_dir,
      }),
    placeholderData: (prev) => prev,
  });

  const data = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  const currentSort: SortState = { sort_by: search.sort_by, sort_dir: search.sort_dir };

  const columns: TableColumnsType<GeneSummary> = [
    {
      title: t("genes.geneId"),
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
          className="link-underline font-mono text-sm font-medium text-primary"
        >
          {compactGeneId(row.gene_id, 18)}
        </Link>
      ),
    },
    {
      title: t("genes.symbol"),
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
      title: t("genes.biotypeLabel"),
      dataIndex: "biotype",
      key: "biotype",
      render: (_, row) => <span className="font-mono text-xs">{row.biotype}</span>,
    },
    {
      title: t("genes.chromosomeLabel"),
      dataIndex: "chromosome",
      key: "chromosome",
      render: (_, row) => <span className="font-mono text-xs">{row.chromosome}</span>,
    },
    {
      title: t("genes.position"),
      dataIndex: "start_pos",
      key: "position",
      render: (_, row) => (
        <span className="font-mono text-xs text-muted-foreground">
          {formatPosition(row.start_pos)}–{formatPosition(row.end_pos)}
        </span>
      ),
    },
    {
      title: t("genes.variantCount"),
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
        <p className="eyebrow">{t("genes.title")}</p>
        <h1 className="mt-2 font-display text-4xl font-semibold tracking-tight">
          {t("genes.subtitle")}
        </h1>

        <Form
          layout="inline"
          className="mt-8 flex flex-wrap items-end gap-x-4 gap-y-4"
          onFinish={() => navigate({ to: "/genes", search: { ...search, q: q.trim(), page: 1 } })}
        >
          <Form.Item label={t("genes.search")} className="mb-0">
            <Input.Search
              data-testid="genes-search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("genes.searchPlaceholder")}
              aria-label={t("genes.search")}
              allowClear
              enterButton={false}
              style={{ width: 240 }}
            />
          </Form.Item>
          <Form.Item label={t("genes.chromosome")} className="mb-0">
            <Select
              value={search.chromosome || "all"}
              onChange={(v) =>
                navigate({ to: "/genes", search: { ...search, chromosome: v === "all" ? "" : v, page: 1 } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: t("genes.allChromosomes") },
                ...SOYBEAN_CHROMOSOMES.map((c) => ({ value: c, label: c })),
              ]}
            />
          </Form.Item>
          <Form.Item label={t("genes.biotype")} className="mb-0">
            <Select
              value={search.biotype || "all"}
              onChange={(v) =>
                navigate({ to: "/genes", search: { ...search, biotype: v === "all" ? "" : v, page: 1 } })
              }
              style={{ width: 170 }}
              options={[
                { value: "all", label: t("genes.allBiotype") },
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
                      {t("genes.noResults")}
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
